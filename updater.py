"""
QB Draft Contest - standings generator.

Reads drafts.json, pulls nflverse schedules + play-by-play, and writes
standings.json for index.html.

Scoring (from the league's Rules tab):
  * 1 pt per regular-season win the QB is credited with; a tie is half a
    win (0.5 pt).
  * Regular-season points are halved (rounded down to a whole number) if
    the QB's record is below .500, with ties counting as half a win.
  * 3 pts per playoff win (Super Bowl excluded); a first-round bye counts as
    a playoff win.
  * 5 pts for a Super Bowl win.
  * Goff rule: each game's result goes to whichever QB on that team threw
    the most official pass attempts. If tied, it goes to the starter.
  * Rulings: drafts.json can override who gets credit for a specific game
    (e.g. a rest day rather than an injury). Overrides appear in the audit.
  * Bench swaps: the outgoing QB scores weeks 1..to_week, the incoming QB
    scores from_week..end (including playoffs). Each is scored separately.
"""

import json
import math
from datetime import datetime, timezone
from pathlib import Path

import nflreadpy as nfl
import pandas as pd

ROOT = Path(__file__).parent
CONFIG_PATH = ROOT / "drafts.json"
OUTPUT_PATH = ROOT / "standings.json"

OPEN_END = 99  # default last week of a roster window


# --------------------------------------------------------------------------
# Per-game QB credit
# --------------------------------------------------------------------------
def credited_qbs(pbp: pd.DataFrame, rulings: list) -> pd.DataFrame:
    """One row per (game_id, posteam, passer): attempts, starter flag and
    whether that QB is credited with the team's result."""
    has_passer = pbp["passer_player_id"].notna()

    # Official pass attempts: completions, incompletions, interceptions.
    # Sacks and two-point tries are excluded; plays wiped out by penalty
    # are play_type "no_play" and carry no attempt flag.
    att = pbp[
        has_passer
        & (pbp["pass_attempt"] == 1)
        & (pbp["sack"] != 1)
        & (pbp["two_point_attempt"] != 1)
    ]
    counts = (
        att.groupby(["game_id", "week", "posteam", "passer_player_id"])
        .agg(attempts=("play_id", "size"), passer_name=("passer_player_name", "first"))
        .reset_index()
    )

    # Starter = QB on the team's first dropback with a named passer.
    starters = (
        pbp[has_passer]
        .sort_values(["game_id", "play_id"])
        .groupby(["game_id", "posteam"])["passer_player_id"]
        .first()
        .rename("starter_id")
        .reset_index()
    )
    counts = counts.merge(starters, on=["game_id", "posteam"], how="left")
    counts["is_starter"] = counts["passer_player_id"] == counts["starter_id"]

    # Most attempts wins; the starter breaks ties.
    counts = counts.sort_values(
        ["game_id", "posteam", "attempts", "is_starter"],
        ascending=[True, True, False, False],
    )
    counts["credited"] = ~counts.duplicated(["game_id", "posteam"])
    counts["ruling"] = None

    for r in rulings:
        mask = (counts.week == r["week"]) & (counts.posteam == r["team"])
        if not mask.any():
            raise ValueError(f"Ruling matches no game: {r}")
        game_id = counts.loc[mask, "game_id"].iat[0]
        if not (mask & (counts.passer_player_id == r["credit_id"])).any():
            # QB had no pass attempts (e.g. a one-snap start); add a row.
            counts = pd.concat([counts, pd.DataFrame([{
                "game_id": game_id, "week": r["week"], "posteam": r["team"],
                "passer_player_id": r["credit_id"], "attempts": 0,
                "passer_name": r.get("credit_name"), "is_starter": True,
            }])], ignore_index=True)
            mask = (counts.week == r["week"]) & (counts.posteam == r["team"])
        counts.loc[mask, "credited"] = counts.loc[mask, "passer_player_id"] == r["credit_id"]
        counts.loc[mask, "ruling"] = r["note"]
    return counts


def team_results(sched: pd.DataFrame) -> pd.DataFrame:
    """One row per completed game per team, with its result."""
    done = sched[sched["result"].notna()]
    rows = []
    for _, g in done.iterrows():
        for team, opp, pf, pa, home in (
            (g.home_team, g.away_team, g.home_score, g.away_score, True),
            (g.away_team, g.home_team, g.away_score, g.home_score, False),
        ):
            rows.append({
                "game_id": g.game_id, "week": int(g.week), "game_type": g.game_type,
                "date": str(g.gameday), "home": home,
                "team": team, "opponent": opp, "pf": int(pf), "pa": int(pa),
                "outcome": "W" if pf > pa else ("L" if pf < pa else "T"),
            })
    return pd.DataFrame(rows)


def bye_teams(sched: pd.DataFrame) -> set:
    """Teams that played a divisional-round game without a wild-card game."""
    wc = set(sched.loc[sched.game_type == "WC", ["home_team", "away_team"]].values.ravel())
    div = set(sched.loc[sched.game_type == "DIV", ["home_team", "away_team"]].values.ravel())
    return div - wc if wc else set()


def team_lookup(qb_id, pbp, fallback=None):
    """Return f(week) -> the team this QB was on, from his own pass plays."""
    seen = (pbp[pbp.passer_player_id == qb_id]
            .groupby("week")["posteam"].agg(lambda s: s.mode().iat[0])
            .sort_index())
    weeks, teams = list(seen.index), list(seen.values)

    def f(week):
        team = teams[0] if teams else fallback
        for w, t in zip(weeks, teams):
            if w <= week:
                team = t
        return team
    return f


# --------------------------------------------------------------------------
# Scoring
# --------------------------------------------------------------------------
def score_qb(entry, games, credit, byes, team_of, names):
    qb_id = entry["id"]
    lo, hi = entry.get("from_week", 1), entry.get("to_week", OPEN_END)

    by_game = credit.set_index(["game_id", "posteam"]).sort_index()
    stats = dict(wins=0, losses=0, ties=0, playoff_wins=0, sb_wins=0,
                 byes=0, missed_games=0, goff_rule=0)
    log = []

    for _, g in games[(games.week >= lo) & (games.week <= hi)].iterrows():
        if g.team != team_of(g.week):
            continue
        base = {"wk": g.week, "type": g.game_type, "opp": g.opponent,
                "gid": g.game_id, "date": g.date, "home": bool(g.home), "team": g.team}
        if not g.has_pbp:
            log.append({**base, "res": "pending"})
            continue
        base["score"] = f"{g.pf}-{g.pa}"
        key = (g.game_id, g.team)
        team_rows = by_game.loc[[key]] if key in by_game.index else by_game.iloc[0:0]
        mine = team_rows[team_rows.passer_player_id == qb_id]
        if mine.empty:
            if g.game_type == "REG":
                stats["missed_games"] += 1
            log.append({**base, "res": "DNP"})
            continue

        row = mine.iloc[0]
        rec = {**base, "att": int(row.attempts)}
        opp_key = (g.game_id, g.opponent)
        if opp_key in by_game.index:
            o = by_game.loc[[opp_key]]
            o = o[o.credited]
            if not o.empty:
                rec["opp_qb_id"] = o.iloc[0].passer_player_id
                rec["opp_qb"] = names.get(o.iloc[0].passer_player_id, o.iloc[0].passer_name)
                rec["opp_att"] = int(o.iloc[0].attempts)
        if isinstance(row.ruling, str):
            rec["ruling"] = row.ruling
        if not row.credited:
            other = team_rows[team_rows.credited].iloc[0]
            stats["goff_rule"] += 1
            rec.update(res="goff", outcome=g.outcome,
                       credited=names.get(other.passer_player_id, other.passer_name),
                       credited_att=int(other.attempts))
        else:
            rec["res"] = g.outcome
            tied = team_rows[(team_rows.passer_player_id != qb_id)
                             & (team_rows.attempts == row.attempts)]
            if not tied.empty and not isinstance(row.ruling, str):
                rec["tiebreak"] = names.get(tied.iloc[0].passer_player_id, tied.iloc[0].passer_name)
            if g.game_type == "REG":
                stats[{"W": "wins", "L": "losses", "T": "ties"}[g.outcome]] += 1
            elif g.outcome == "W":
                stats["sb_wins" if g.game_type == "SB" else "playoff_wins"] += 1
            # A bye goes to whoever is credited with the team's divisional game.
            if g.game_type == "DIV" and g.team in byes:
                stats["byes"] += 1
                rec["bye"] = True
        log.append(rec)

    gp = stats["wins"] + stats["losses"] + stats["ties"]
    win_pct = (stats["wins"] + 0.5 * stats["ties"]) / gp if gp else 0.0
    halved = gp > 0 and win_pct < 0.5
    # A tie is worth half a win (half a point). Halving rounds down to a
    # whole number, as the original rule does.
    reg_raw = stats["wins"] + 0.5 * stats["ties"]
    reg_points = math.floor(reg_raw / 2) if halved else reg_raw
    reg_points = int(reg_points) if float(reg_points).is_integer() else reg_points
    post_points = 3 * (stats["playoff_wins"] + stats["byes"]) + 5 * stats["sb_wins"]

    return {
        "name": entry["name"], "id": qb_id, "team": team_of(min(hi, 30)),
        "window": [lo, None if hi == OPEN_END else hi],
        **stats,
        "win_pct": round(win_pct, 3), "halved": halved,
        "reg_points": reg_points, "post_points": post_points,
        "points": reg_points + post_points,
        "subbed_out_after": entry.get("to_week"),
        "subbed_in_week": entry.get("from_week"),
        "games": log,
    }


def _rec(q):
    pts = f"{q['points']} pt" + ("" if q["points"] == 1 else "s")
    return f"{q['wins']}-{q['losses']}{'-' + str(q['ties']) if q['ties'] else ''}, {pts}"


def build_audit(managers_out):
    """Plain-language list of everything that moved a result away from the
    simple 'starter gets the W/L' reading, plus bench swaps and ties."""
    audit = []
    for m, md in managers_out.items():
        roster = md["roster"]
        outs = [q for q in roster if q["subbed_out_after"]]
        ins = [q for q in roster if q["subbed_in_week"]]
        for o, i in zip(outs, ins):
            audit.append({"kind": "swap", "manager": m, "text":
                f"{m} swapped {o['name']} for {i['name']} before Week {i['subbed_in_week']}. "
                f"{o['name']} scores Weeks 1–{o['subbed_out_after']} ({_rec(o)}); "
                f"{i['name']} scores Week {i['subbed_in_week']} onward, playoffs included ({_rec(i)})."})
        for q in roster:
            for g in q["games"]:
                wk = f"Week {g['wk']}" if g["type"] == "REG" else g["type"]
                if g["res"] == "goff":
                    audit.append({"kind": "goff", "manager": m, "text":
                        f"{wk} vs {g['opp']} ({g['score']}, {g['outcome']}): {g['credited']} threw "
                        f"{g['credited_att']} passes to {q['name']}'s {g['att']}, so the result "
                        f"goes to {g['credited']}." + (f" Ruling: {g['ruling']}" if g.get("ruling") else "")})
                elif g.get("ruling"):
                    audit.append({"kind": "ruling", "manager": m, "text":
                        f"{wk} vs {g['opp']} ({g['score']}): credited to {q['name']}. Ruling: {g['ruling']}"})
                if g.get("tiebreak"):
                    audit.append({"kind": "tiebreak", "manager": m, "text":
                        f"{wk} vs {g['opp']} ({g['score']}, {g['res']}): {q['name']} and {g['tiebreak']} "
                        f"each threw {g['att']} passes; the tie goes to the starter, {q['name']}."})
                if g["res"] == "T":
                    audit.append({"kind": "tie", "manager": m, "text":
                        f"{wk} vs {g['opp']} ({g['score']}): tie for {q['name']}, worth half a win "
                        f"(½ point, and half a win for the .500 check)."})
    return audit


def head_to_head(seasons, managers):
    """Every game where both managers had a credited QB on the field
    against each other, within each QB's roster window."""
    games = []
    for year, s in seasons.items():
        credited = {}  # game_id -> {manager: (qb, log entry)}
        for m in managers:
            for q in s["managers"][m]["roster"]:
                for g in q["games"]:
                    if g["res"] in ("W", "L", "T"):
                        credited.setdefault(g["gid"], {})[m] = (q, g)
        for gid, sides in credited.items():
            if len(sides) < 2:
                continue
            a, b = managers
            (qa, ga), (qb, gb) = sides[a], sides[b]
            assert ga["opp_qb_id"] == qb["id"] and gb["opp_qb_id"] == qa["id"], gid
            winner = {"W": a, "L": b, "T": None}[ga["res"]]
            home = a if ga["home"] else b
            games.append({
                "season": year, "wk": ga["wk"], "type": ga["type"], "date": ga["date"],
                "qbs": {a: qa["name"], b: qb["name"]},
                "ids": {a: qa["id"], b: qb["id"]},
                "teams": {a: gb["opp"], b: ga["opp"]},
                "score": {a: int(ga["score"].split("-")[0]), b: int(ga["score"].split("-")[1])},
                "home": home, "winner": winner,
            })
    games.sort(key=lambda g: (g["season"], g["date"], g["wk"]))
    return games


def build_season(year, cfg, managers, names):
    print(f"Season {year}: loading data…")
    sched = nfl.load_schedules([year]).to_pandas()
    pbp = nfl.load_pbp([year]).to_pandas()

    credit = credited_qbs(pbp, cfg.get("rulings", []))
    games = team_results(sched)
    games["has_pbp"] = games.game_id.isin(set(pbp.game_id))
    byes = bye_teams(sched)

    done_reg = sched[(sched.game_type == "REG") & sched.result.notna()]
    sb = sched[sched.game_type == "SB"]
    final = not sb.empty and sb.result.notna().all()

    managers_out = {}
    for m in managers:
        roster = [score_qb(e, games, credit, byes, team_lookup(e["id"], pbp), names)
                  for e in cfg["rosters"][m]]
        managers_out[m] = {"points": sum(q["points"] for q in roster), "roster": roster}

    return {
        "label": cfg.get("label", str(year)),
        "stakes": cfg.get("stakes"),
        "status": "final" if final else "in_progress",
        "through_week": int(done_reg.week.max()) if not done_reg.empty else 0,
        "pending_games": int((~games.has_pbp).sum() // 2),
        "bench": cfg.get("bench"),
        "managers": managers_out,
        "audit": build_audit(managers_out),
    }


def main():
    config = json.loads(CONFIG_PATH.read_text())
    managers = config["managers"]
    players = nfl.load_players().to_pandas()
    names = dict(zip(players.gsis_id, players.display_name))
    seasons = {y: build_season(int(y), cfg, managers, names)
               for y, cfg in sorted(config["seasons"].items())}

    lifetime = {m: sum(s["managers"][m]["points"] for s in seasons.values()) for m in managers}
    season_wins = {m: 0 for m in managers}
    for s in seasons.values():
        if s["status"] == "final":
            pts = {m: s["managers"][m]["points"] for m in managers}
            leaders = [m for m, p in pts.items() if p == max(pts.values())]
            if len(leaders) == 1:
                season_wins[leaders[0]] += 1

    result = {
        "head_to_head": head_to_head(seasons, managers),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="minutes"),
        "managers": managers,
        "lifetime_points": lifetime,
        "season_wins": season_wins,
        "seasons": seasons,
    }

    # Only rewrite when the standings changed, so the workflow doesn't
    # commit a new timestamp every run.
    if OUTPUT_PATH.exists():
        old = json.loads(OUTPUT_PATH.read_text())
        old.pop("generated_at", None)
        new = json.loads(json.dumps({k: v for k, v in result.items() if k != "generated_at"}, default=int))
        if old == new:
            print("No changes.")
            return
    OUTPUT_PATH.write_text(json.dumps(result, indent=1, default=int))
    print("Wrote standings.json: " + ", ".join(f"{m} {p}" for m, p in lifetime.items()))


if __name__ == "__main__":
    main()
