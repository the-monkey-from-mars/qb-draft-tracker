import nfl_data_py as nfl
import pandas as pd
import json
import math

# --- 1. LIFETIME CONTEST CONFIGURATION ---
SEASONS = [2021, 2022, 2023, 2024, 2025]

draft_history = {
    2025: {
        "P.Mahomes": {"manager": "TT13"},
        "L.Jackson": {"manager": "TT13"},
        "J.Burrow": {"manager": "TT13"},
        "K.Murray": {"manager": "TT13"},
        "J.Herbert": {"manager": "TT13"},
        "C.Stroud": {"manager": "TT13"},
        "J.Love": {"manager": "TT13"},
        "B.Purdy": {"manager": "TT13", "active_weeks": range(1, 10)},
        "S.Darnold": {"manager": "TT13", "active_weeks": range(10, 25), "byes": 1},
        
        "M.Stafford": {"manager": "Matt"},
        "J.Allen": {"manager": "Matt"},
        "J.Goff": {"manager": "Matt"},
        "J.Daniels": {"manager": "Matt"},
        "D.Maye": {"manager": "Matt"},
        "J.Hurts": {"manager": "Matt"},
        "B.Mayfield": {"manager": "Matt"},
        "B.Nix": {"manager": "Matt", "byes": 1},
    },
    2024: {
        "P.Mahomes": {"manager": "TT13", "byes": 1},
        "L.Jackson": {"manager": "TT13"},
        "J.Burrow": {"manager": "TT13"},
        "T.Lawrence": {"manager": "TT13", "active_weeks": range(1, 10)},
        "K.Murray": {"manager": "TT13", "active_weeks": range(10, 25)},
        "A.Rodgers": {"manager": "TT13"},
        "C.Stroud": {"manager": "TT13"},
        "C.Williams": {"manager": "TT13"},
        "B.Purdy": {"manager": "TT13"},
        
        "M.Stafford": {"manager": "Matt"},
        "J.Allen": {"manager": "Matt"},
        "J.Goff": {"manager": "Matt", "byes": 1},
        "K.Cousins": {"manager": "Matt"},
        "T.Tagovailoa": {"manager": "Matt"},
        "J.Hurts": {"manager": "Matt"},
        "J.Love": {"manager": "Matt"},
        "J.Herbert": {"manager": "Matt"},
    },
    2023: {
        "P.Mahomes": {"manager": "TT13"},
        "L.Jackson": {"manager": "TT13", "byes": 1},
        "J.Burrow": {"manager": "TT13"},
        "T.Lawrence": {"manager": "TT13"},
        "A.Rodgers": {"manager": "TT13"},
        "B.Young": {"manager": "TT13"},
        "D.Prescott": {"manager": "TT13"},
        "B.Purdy": {"manager": "TT13", "byes": 1},

        "R.Wilson": {"manager": "Matt"},
        "J.Allen": {"manager": "Matt"},
        "J.Goff": {"manager": "Matt"},
        "K.Cousins": {"manager": "Matt"},
        "D.Carr": {"manager": "Matt"},
        "J.Hurts": {"manager": "Matt"},
        "K.Pickett": {"manager": "Matt"},
        "J.Herbert": {"manager": "Matt"},
    },
    2022: {
        "P.Mahomes": {"manager": "TT13", "byes": 1},
        "L.Jackson": {"manager": "TT13"},
        "J.Burrow": {"manager": "TT13"},
        "T.Lawrence": {"manager": "TT13"},
        "A.Rodgers": {"manager": "TT13"},
        "M.Stafford": {"manager": "TT13"},
        "D.Prescott": {"manager": "TT13"},
        "T.Brady": {"manager": "TT13"},

        "R.Wilson": {"manager": "Matt"},
        "J.Allen": {"manager": "Matt"},
        "K.Murray": {"manager": "Matt"},
        "K.Cousins": {"manager": "Matt"},
        "D.Carr": {"manager": "Matt"},
        "J.Hurts": {"manager": "Matt", "byes": 1},
        "M.Jones": {"manager": "Matt"},
        "J.Herbert": {"manager": "Matt"},
    },
    2021: {
        "P.Mahomes": {"manager": "TT13"},
        "L.Jackson": {"manager": "TT13"},
        "J.Burrow": {"manager": "TT13"},
        "T.Lawrence": {"manager": "TT13"},
        "A.Rodgers": {"manager": "TT13", "byes": 1},
        "M.Stafford": {"manager": "TT13"},
        "B.Mayfield": {"manager": "TT13"},
        "T.Brady": {"manager": "TT13"},

        "R.Wilson": {"manager": "Matt"},
        "J.Allen": {"manager": "Matt"},
        "K.Murray": {"manager": "Matt"},
        "T.Tagovailoa": {"manager": "Matt"},
        "R.Tannehill": {"manager": "Matt", "byes": 1},
        "J.Hurts": {"manager": "Matt"},
        "M.Jones": {"manager": "Matt"},
        "J.Herbert": {"manager": "Matt"},
    }
}

def generate_standings():
    scoreboard = {
        "Matt": {"lifetime_points": 0, "seasons": {}},
        "TT13": {"lifetime_points": 0, "seasons": {}}
    }

    for year in SEASONS:
        print(f"Fetching {year} NFL Data...")
        schedules = nfl.import_schedules([year])
        pbp = nfl.import_pbp_data([year])
        
        drafts = draft_history[year]
        completed_games = schedules[schedules['result'].notna()]
        player_stats = {}
        pass_plays = pbp[pbp['play_type'] == 'pass'].copy()
        
        for qb_name, qb_info in drafts.items():
            qb_passes = pass_plays[pass_plays['passer_player_name'] == qb_name]
            primary_team = qb_passes['posteam'].mode()[0] if not qb_passes.empty else None
            
            # Detect substitution flags based on active weeks
            active_weeks = qb_info.get("active_weeks", range(1, 25))
            
            player_stats[qb_name] = {
                "manager": qb_info["manager"], 
                "team": primary_team,
                "wins": 0, "losses": 0, 
                "playoff_wins": 0, "sb_wins": 0,
                "byes": qb_info.get("byes", 0),
                "missed_games": 0, 
                "goff_rule": 0,
                "subbed_out": active_weeks == range(1, 10),
                "subbed_in": active_weeks == range(10, 25)
            }
            
        for _, game in completed_games.iterrows():
            game_id = game['game_id']
            game_week = game['week']
            home_team = game['home_team']
            away_team = game['away_team']
            home_won = game['home_score'] > game['away_score']
            is_playoff = game['game_type'] != 'REG'
            is_sb = game['game_type'] == 'SB'
            
            game_passes = pass_plays[pass_plays['game_id'] == game_id]
            
            for qb_name, qb_info in drafts.items():
                primary_team = player_stats[qb_name]["team"]
                if not primary_team:
                    continue 
                    
                if home_team == primary_team or away_team == primary_team:
                    active_weeks = qb_info.get("active_weeks", range(1, 25)) 
                    if game_week not in active_weeks:
                        continue
                        
                    team_passes = game_passes[game_passes['posteam'] == primary_team]
                    passer_counts = team_passes['passer_player_name'].value_counts()
                    
                    drafted_attempts = passer_counts.get(qb_name, 0)
                    backups = passer_counts.drop(qb_name, errors='ignore')
                    max_backup_attempts = backups.max() if not backups.empty else 0
                    
                    if drafted_attempts == 0:
                        player_stats[qb_name]["missed_games"] += 1
                    elif drafted_attempts >= max_backup_attempts:
                        won_game = (home_won and home_team == primary_team) or (not home_won and away_team == primary_team)
                        
                        # FIX: Nested correctly so ONLY the winner gets playoff/SB points
                        if won_game:
                            if is_sb:
                                player_stats[qb_name]["sb_wins"] += 1
                            elif is_playoff:
                                player_stats[qb_name]["playoff_wins"] += 1
                            else:
                                player_stats[qb_name]["wins"] += 1
                        else:
                            if not is_playoff and not is_sb:
                                player_stats[qb_name]["losses"] += 1
                    else:
                        player_stats[qb_name]["goff_rule"] += 1

        scoreboard["Matt"]["seasons"][year] = {"roster": [], "year_points": 0}
        scoreboard["TT13"]["seasons"][year] = {"roster": [], "year_points": 0}

        for qb, stats in player_stats.items():
            wins = stats["wins"]
            losses = stats["losses"]
            total_games = wins + losses
            win_pct = (wins / total_games) if total_games > 0 else 0
            
            halved = win_pct < 0.500
            reg_points = math.floor(wins / 2) if halved else wins
            
            playoff_pts = stats["playoff_wins"] * 3
            bye_pts = stats["byes"] * 3
            sb_pts = stats["sb_wins"] * 5
            
            total_points = reg_points + playoff_pts + bye_pts + sb_pts
            manager = stats["manager"]
            
            scoreboard[manager]["seasons"][year]["roster"].append({
                "name": qb,
                "wins": wins,
                "losses": losses,
                "win_pct": round(win_pct, 3),
                "halved": halved,
                "reg_points": reg_points,
                "playoff_wins": stats["playoff_wins"],
                "sb_wins": stats["sb_wins"],
                "byes": stats["byes"],
                "missed_games": stats["missed_games"],
                "goff_rule": stats["goff_rule"], 
                "subbed_out": stats["subbed_out"],
                "subbed_in": stats["subbed_in"],
                "points": total_points
            })
            scoreboard[manager]["seasons"][year]["year_points"] += total_points
            scoreboard[manager]["lifetime_points"] += total_points

    with open('standings.json', 'w') as f:
        json.dump(scoreboard, f, indent=4)
    print("All seasons successfully updated to standings.json!")

if __name__ == "__main__":
    generate_standings()