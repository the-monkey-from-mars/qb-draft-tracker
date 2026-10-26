# QB Draft Contest Tracker

Live standings for the TT13 vs Matt QB draft: https://the-monkey-from-mars.github.io/qb-draft-tracker/

## How it works

- `drafts.json` holds every season's rosters (and the current season's benches).
- `updater.py` pulls schedules and play-by-play from [nflverse](https://github.com/nflverse) via `nflreadpy`, scores every QB, and writes `standings.json`.
- `index.html` reads `standings.json`. No build step.
- `.github/workflows/update.yml` runs the updater every morning from September through February and commits only when standings change.

### How updating works

The site is static: GitHub Pages serves `index.html` and `standings.json`, and the page just reads the JSON. Scores change only when the workflow regenerates `standings.json` and commits it; Pages then redeploys within a minute or two.

- **Automatic:** daily at 11:23 UTC in-season. nflverse refreshes play-by-play overnight, so Sunday's games appear Monday morning.
- **On demand:** the "Run an update now" link on the page opens the workflow; click **Run workflow** (needs repo write access, so it only works for the owner). Takes about 3 minutes.
- **Open tabs** re-check `standings.json` when you switch back to them.

## Scoring (mirrors the Rules tab of the original sheet)

| Item | Points |
| --- | --- |
| Regular-season win | 1 (halved, rounded down, if record is under .500) |
| Regular-season tie | 0.5 |
| Playoff win (not SB) | 3 |
| First-round bye | 3 (counts as a playoff win) |
| Super Bowl win | 5 |

**Goff rule:** each game goes to the QB on that team with the most official pass attempts (sacks and 2-pt tries excluded). A tie goes to the starter (first QB to drop back).

**Ties:** an NFL tie is half a win: it earns 0.5 points and counts as half a win when checking the .500 line. If the QB is under .500, his regular-season points (ties included) are halved and rounded down to a whole number.

**Goff rule scope:** applies to every game (injury, rest or benching alike), not only injuries.

**Head-to-head:** a game counts when a TT13 QB and a Matt QB faced each other, both were on their manager's roster that week (bench-swap windows respected), and both were credited with the result under the Goff rule. Playoffs are included. A QB who played for both managers is listed under each, with only that stint's games. Built in `updater.py` (`head_to_head`) and stored in `standings.json`.

**Game details:** hovering (or tapping, on phones) a W/L/T square shows the date, final score, attempts and opposing QB.

**Audit:** each season's page lists every bench swap, every Goff-rule game (with both QBs' attempts), every attempts tie settled by the starter rule, every NFL tie and every ruling.

**Byes:** detected automatically (teams that skip the wild-card round) and credited to whoever is credited with that team's divisional-round game.

## Common edits

**New season:** copy the newest block in `drafts.json`, change the year key, label, stakes, rosters and bench. Nothing else changes.

**Bench swap (before Week 10):** on the outgoing QB add `"to_week": 9`; add the incoming QB with `"from_week": 10`:

```json
{"name": "Trevor Lawrence", "id": "00-0036971", "to_week": 9},
{"name": "Kyler Murray", "id": "00-0035228", "from_week": 10}
```

**Commissioner ruling (override who gets a game):** add a `rulings` list to the season. The QB doesn't need to have thrown a pass. Every ruling is shown under Scoring notes on the page.

```json
"rulings": [
  {"week": 18, "team": "HOU", "credit_id": "00-0039163", "credit_name": "C.J. Stroud",
   "note": "Rested for the playoffs, not injured, so the starter keeps the win."}
]
```

**Finding a player id:**

```python
import nflreadpy as nfl
p = nfl.load_players().to_pandas()
print(p[p.display_name.str.contains("Shough")][["gsis_id", "display_name", "position"]])
```

Players are matched by id, not name, because the source data sometimes spells the same QB two ways (for example `A.Rodgers` and `Aa.Rodgers`).

## Running locally

```powershell
pip install -r requirements.txt
python updater.py
python -m http.server 8000   # then open http://localhost:8000
```

## Keep the schedule alive

GitHub turns off scheduled workflows after 60 days with no repo activity, which happens every offseason. Each September, open **Actions → Update QB Standings** and click **Enable workflow** if it shows as disabled.
