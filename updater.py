"""
QB Draft Contest - standings generator.

Reads drafts.json, pulls nflverse schedules + play-by-play, and writes
standings.json for index.html.

Scoring (from the league's Rules tab):
  * 1 pt per regular-season win the QB is credited with.
  * Regular-season points are halved (rounded down) if the QB's record is
    below .500.
  * 3 pts per playoff win (Super Bowl excluded); a first-round bye counts as
    a playoff win.
  * 5 pts for a Super Bowl win.
  * "Goff rule": each game's result goes to whichever QB on that team threw
    the most pass attempts. If tied, it goes to the starter.
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

FIRST_WEEK, LAST_WEEK = 1, 99  # open-ended default window


# --------------------------------------------------------------------------
# Per-game QB credit
# --------------------------------------------------------------------------
def credited_qbs(pbp: pd.DataFrame) -> pd.DataFrame:
    """One row per (game_id, posteam): passer ids, attempts, and the QB
    credited with the result under the Goff rule."""
    has_passer = pbp["passer_player_id"].notna()

    # Official pass attempts: completions, incompletions, interceptions.
    # Sacks and two-point tries are excluded; plays wiped out by penalty
    # are already play_type == "no_play" and have no attempt flag.
    att = pbp[
        has_passer
        & (pbp["pass_attempt"] == 1)
        & (pbp["sack"] != 1)
        & (pbp["two_point_attempt"] != 1)
    ]
    counts = (
        att.groupby(["game_id", "posteam", "passer_player_id"])
        .size()
        .rename("attempts")
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
    return counts


def team_results(sched: pd.DataFrame) -> pd.DataFrame:
    """One row per completed game per team, with its result."""
    done = sched[sched["result"].notna()].copy()
    rows = []
    for _, g in done.iterrows():
        for team, opp, pf, pa, home in (
            (g.home_team, g.away_team, g.home_score, g.away_score, True),
            (g.away_team, g.home_team, g.away_score, g.home_score, False),
        ):
            rows.append({
                "game_id": g.game_id,
                "week": int(g.week),
                "game_type": g.game_type,
                "team": team,
                "opponent": opp,
                "home": home,
                "pf": int(pf),
                "pa": int(pa),
                "outcome": "W" if pf > pa else ("L" if pf < pa else "T"),
            })
    return pd.DataFrame(rows)


def bye_teams(sched: pd.DataFrame) -> set:
    """Teams that played a divisional-round game without a wild-card game."""
    wc = set(sched.loc[sched.game_type == "WC", ["home_team", "away_team"]].values.ravel())
    div = set(sched.loc[sched.game_type == "DIV", ["home_team", "away_team"]].values.ravel())
    return div - wc if wc else set()


# --------------------------------------------------------------------------
# Scoring
# --------------------------------------------------------------------------
def score_qb(entry, games, credit, byes, team_by_week):
    qb_id = entry["id"]
    lo = entry.get("from_week", FIRST_WEEK)
    hi = entry.get("to_week", LAST_WEEK)

    mine = credit[credit.passer_player_id == qb_id].set_index(["game_id", "posteam"])
    stats = {"wins": 0, "losses": 0, "ties": 0, "playoff_wins": 0, "sb_wins": 0,
             "byes": 0, "missed_games": 0, "goff_rule": 0}
    log = []

    for _, g in games[(games.week >= lo) & (games.week <= hi)].iterrows():
        key = (g.game_id, g.team)
        team = team_by_week(g.week)
        if g.team != team:
            continue
        if not g.has_pbp:
            log.append({"wk": g.week, "type": g.game_type, "opp": g.opponent,
                        "res": "pending"})
            continue
        if key not in mine.index:
            if g.game_type == "REG":
                stats["missed_games"] += 1
            log.append({"wk": g.week, "type": g.game_type, "opp": g.opponent,
                        "res": "DNP", "score": f"{g.pf}-{g.pa}"})
            continue

        row = mine.loc[key]
        rec = {"wk": g.week, "type": g.game_type, "opp": g.opponent,
               "score": f"{g.pf}-{g.pa}", "att": int(row.attempts)}
        if not row.credited:
            stats["goff_rule"] += 1
            rec["res"] = "goff"
        else:
            rec["res"] = g.outcome
            if g.game_type == "REG":
                stats[{"W": "wins", "L": "losses", "T": "ties"}[g.outcome]] += 1
            elif g.outcome == "W":
                stats["sb_wins" if g.game_type == "SB" else "playoff_wins"] += 1
            # A bye is credited to whoever is credited with the team's
            # divisional-round game.
            if g.game_type == "DIV" and g.team in byes:
                stats["byes"] += 1
                rec["bye"] = True
        log.append(rec)

    gp = stats["wins"] + stats["losses"] + stats["ties"]
    win_pct = (stats["wins"] + 0.5 * stats["ties"]) / gp if gp else 0.0
    halved = gp > 0 and win_pct < 0.5
    reg_points = math.floor(stats["wins"] / 2) if halved else stats["wins"]
    post_points = 3 * (stats["playoff_wins"] + stats["byes"]) + 5 * stats["sb_wins"]

    return {
        "name": entry["name"],
        "id": qb_id,
        "team": team_by_week(hi if hi < LAST_WEEK else 99),
        "window": [lo, hi if hi < LAST_WEEK else None],
        **stats,
        "win_pct": round(win_pct, 3),
        "halved": halved,
        "reg_points": reg_points,
        "post_points": post_points,
        "points": reg_points + post_points,
        "subbed_out_after": entry.get("to_week"),
        "subbed_in_week": entry.get("from_week"),
        "games": log,
    }


def team_lookup(qb_id, pbp):
    """Return f(week) -> the team this QB was on, from his own pass plays."""
    seen = (pbp[pbp.passer_player_id == qb_id]
            .groupby("week")["posteam"].agg(lambda s: s.mode().iat[0])
            .sort_index())
    if seen.empty:
        return lambda week: None
    weeks, teams = list(seen.index), list(seen.values)

    def f(week):
        team = teams[0]
        for w, t in zip(weeks, teams):
            if w <= week:
                team = t
        return team
    return f


def build_season(year, cfg, managers):
    print(f"Season {year}: loading data…")
    sched = nfl.load_schedules([year]).to_pandas()
    pbp = nfl.load_pbp([year]).to_pandas()

    credit = credited_qbs(pbp)
    games = team_results(sched)
    games["has_pbp"] = games.game_id.isin(set(pbp.game_id))
    byes = bye_teams(sched)

    reg = sched[sched.game_type == "REG"]
    done_reg = reg[reg.result.notna()]
    season_over = (sched.game_type == "SB").any() and sched.loc[sched.game_type == "SB", "result"].notna().all()

    out = {
        "label": cfg.get("label", str(year)),
        "stakes": cfg.get("stakes"),
        "status": "final" if season_over else "in_progress",
        "through_week": int(done_reg.week.max()) if not done_reg.empty else 0,
        "pending_games": int((~games.has_pbp).sum() // 2),
        "bench": cfg.get("bench"),
        "managers": {},
    }
    for m in managers:
        roster = [score_qb(e, games, credit, byes, team_lookup(e["id"], pbp))
                  for e in cfg["rosters"][m]]
        out["managers"][m] = {
            "points": sum(q["points"] for q in roster),
            "roster": roster,
        }
    return out


def main():
    config = json.loads(CONFIG_PATH.read_text())
    managers = config["managers"]
    seasons = {}
    for year, cfg in sorted(config["seasons"].items()):
        seasons[year] = build_season(int(year), cfg, managers)

    lifetime = {m: sum(s["managers"][m]["points"] for s in seasons.values()) for m in managers}
    season_wins = {m: 0 for m in managers}
    for s in seasons.values():
        if s["status"] != "final":
            continue
        pts = {m: s["managers"][m]["points"] for m in managers}
        top = max(pts.values())
        leaders = [m for m, p in pts.items() if p == top]
        if len(leaders) == 1:
            season_wins[leaders[0]] += 1

    result = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="minutes"),
        "managers": managers,
        "lifetime_points": lifetime,
        "season_wins": season_wins,
        "seasons": seasons,
    }

    # Only touch the file if the standings themselves changed, so the
    # workflow doesn't commit a new timestamp every run.
    if OUTPUT_PATH.exists():
        old = json.loads(OUTPUT_PATH.read_text())
        old.pop("generated_at", None)
        new = dict(result)
        new.pop("generated_at")
        if old == json.loads(json.dumps(new)):
            print("No changes.")
            return
    OUTPUT_PATH.write_text(json.dumps(result, indent=1, default=int))
    print(f"Wrote {OUTPUT_PATH.name}: " + ", ".join(f"{m} {p}" for m, p in lifetime.items()))


if __name__ == "__main__":
    main()
