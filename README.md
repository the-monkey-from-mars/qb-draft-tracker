# QB Draft Contest Tracker

Live standings for the TT13 vs Matt QB draft: https://the-monkey-from-mars.github.io/qb-draft-tracker/

## How it works

- `drafts.json` holds every season's rosters (and the current season's benches).
- `updater.py` pulls schedules and play-by-play from [nflverse](https://github.com/nflverse) via `nflreadpy`, scores every QB, and writes `standings.json`.
- `index.html` reads `standings.json`. No build step.
- `.github/workflows/update.yml` runs the updater Mon, Tue and Fri mornings and commits only when standings change. Run it any time from **Actions → Update QB Standings → Run workflow**.

## Scoring (mirrors the Rules tab of the original sheet)

| Item | Points |
| --- | --- |
| Regular-season win | 1 (halved, rounded down, if record is under .500) |
| Playoff win (not SB) | 3 |
| First-round bye | 3 (counts as a playoff win) |
| Super Bowl win | 5 |

**Goff rule:** each game goes to the QB on that team with the most official pass attempts (sacks and 2-pt tries excluded). A tie goes to the starter (first QB to drop back).

**Ties:** an NFL tie counts as half a win when checking the .500 line, and earns no points.

**Byes:** detected automatically (teams that skip the wild-card round) and credited to whoever is credited with that team's divisional-round game.

## Common edits

**New season:** copy the newest block in `drafts.json`, change the year key, label, stakes, rosters and bench. Nothing else changes.

**Bench swap (before Week 10):** on the outgoing QB add `"to_week": 9`; add the incoming QB with `"from_week": 10`:

```json
{"name": "Trevor Lawrence", "id": "00-0036971", "to_week": 9},
{"name": "Kyler Murray", "id": "00-0035228", "from_week": 10}
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
