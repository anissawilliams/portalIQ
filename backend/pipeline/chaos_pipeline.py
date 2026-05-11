"""
chaos_pipeline.py — CFB Chaos Factor (Python port from R)
===========================================================
Ports the Williams & Mefford (2025) Chaos Factor pipeline from R/cfbfastR
to Python using the CFBD API.

Chaos = w1·WinProbVolatility + w2·LeadChangeCount + w3·ExplosivePlayDelta

Where:
  WinProbVolatility  = std dev of home_wp_after across all plays in a game
  LeadChangeCount    = number of times lead sign flips (±1) during the game
  ExplosivePlayDelta = max(team explosive plays) - min(team explosive plays)
    - Explosive rush: yards_gained >= 12
    - Explosive pass: yards_gained >= 16

Usage:
    python chaos_pipeline.py --years 2021 2022 2023 2024
    python chaos_pipeline.py --years 2024 --out ./data/cfb_data
"""

import os
import time
import argparse
import warnings
import urllib3
from pathlib import Path

import numpy as np
import pandas as pd
import cfbd
from cfbd import Configuration, ApiClient
from dotenv import load_dotenv

warnings.filterwarnings('ignore')
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

load_dotenv()

# =============================================================================
# CONFIG
# =============================================================================

CFBD_API_KEY = os.environ.get("CFBD_API_KEY", "")

# Chaos weights (from paper — can be tuned)
W1 = 0.5  # WinProbVolatility
W2 = 0.3  # LeadChangeCount
W3 = 0.2  # ExplosivePlayDelta

# Explosive play thresholds (standard football)
EXPLOSIVE_RUSH_YARDS = 12
EXPLOSIVE_PASS_YARDS = 16

# Power 5 conferences (paper filtered to these)
POWER5 = ['SEC', 'Big Ten', 'ACC', 'Big 12', 'Pac-12']

DELAY = 0.5  # seconds between API calls


def get_config():
    config = Configuration()
    config.api_key['Authorization'] = CFBD_API_KEY
    config.api_key_prefix['Authorization'] = 'Bearer'
    config.host = "https://api.collegefootballdata.com"
    config.access_token = CFBD_API_KEY
    config.verify_ssl = False
    return config


# =============================================================================
# STEP 1: COLLECT PLAY-BY-PLAY
# =============================================================================

def fetch_plays(api_client, year, week=None):
    """
    Fetch play-by-play for a given season (and optionally week).
    Returns a DataFrame with one row per play.
    """
    plays_api = cfbd.PlaysApi(api_client)

    all_plays = []
    weeks = [week] if week else range(1, 16)

    for wk in weeks:
        try:
            plays = plays_api.get_plays(year=year, week=wk, classification='fbs')
            for p in plays:
                all_plays.append({
                    'game_id': p.game_id,
                    'play_id': p.id,
                    'week': wk,
                    'season': year,
                    'home': p.home,
                    'away': p.away,
                    'offense': p.offense,
                    'defense': p.defense,
                    'offense_score': p.offense_score,
                    'defense_score': p.defense_score,
                    'home_wp': getattr(p, 'home_wp', None),
                    'play_type': p.play_type,
                    'yards_gained': getattr(p, 'yards_gained', None),
                    'offense_conference': getattr(p, 'offense_conference', None),
                    'defense_conference': getattr(p, 'defense_conference', None),
                    'play_number': getattr(p, 'play_number', None),
                })
            print(f"    Week {wk}: {len(plays)} plays")
            time.sleep(DELAY)
        except Exception as e:
            print(f"    Week {wk}: error — {e}")
            continue

    return pd.DataFrame(all_plays)


# =============================================================================
# STEP 2: STANDARDIZE PLAY ORDER
# =============================================================================

def standardize_play_order(df):
    """
    Replicates the R helper function for consistent play ordering.
    Uses play_number if available, otherwise ranks by play_id,
    falls back to row number within each game.
    """
    df = df.copy()

    def order_group(g):
        if g['play_number'].notna().all() and g['play_number'].nunique() == len(g):
            g['play_order'] = g['play_number'].rank(method='first').astype(int)
        elif g['play_id'].notna().any():
            g['play_order'] = g['play_id'].rank(method='first').astype(int)
        else:
            g['play_order'] = range(1, len(g) + 1)
        return g

    df = df.groupby('game_id', group_keys=False).apply(order_group)
    return df.sort_values(['game_id', 'play_order']).reset_index(drop=True)


# =============================================================================
# STEP 3: RECONSTRUCT SCOREBOARD
# =============================================================================

def reconstruct_scoreboard(df):
    """
    Converts possession-relative scores to per-team scores at each play.
    Replicates the long-to-wide pivot strategy from the paper.

    Returns df with columns: home_score, away_score, margin at each play.
    """
    df = df.copy()

    # For each play, offense has the ball — map scores to home/away
    # home_score = offense_score when offense == home, else defense_score
    df['home_score'] = np.where(
        df['offense'] == df['home'],
        df['offense_score'],
        df['defense_score']
    )
    df['away_score'] = np.where(
        df['offense'] == df['away'],
        df['offense_score'],
        df['defense_score']
    )

    # Forward-fill within each game to handle any gaps
    df = df.sort_values(['game_id', 'play_order'])
    df['home_score'] = df.groupby('game_id')['home_score'].ffill().fillna(0)
    df['away_score'] = df.groupby('game_id')['away_score'].ffill().fillna(0)
    df['margin'] = df['home_score'] - df['away_score']

    return df


# =============================================================================
# STEP 4A: LEAD CHANGE COUNT
# =============================================================================

def compute_lead_changes(df):
    """
    Counts the number of lead sign flips per game.
    lead_sign = +1 if home leads, -1 if away leads, 0 if tied.
    A lead change = transition from +1 to -1 or vice versa (ignores ties).
    """

    def lead_changes_for_game(g):
        g = g.sort_values('play_order')
        margin = g['margin'].values

        lead_sign = np.sign(margin)

        # Only count transitions between +1 and -1 (ignore 0)
        prev_nonzero = None
        changes = 0
        for s in lead_sign:
            if s == 0:
                continue
            if prev_nonzero is not None and s != prev_nonzero:
                changes += 1
            prev_nonzero = s

        return changes

    result = df.groupby('game_id').apply(lead_changes_for_game).reset_index()
    result.columns = ['game_id', 'lead_change_count']
    return result


# =============================================================================
# STEP 4B: EXPLOSIVE PLAY DIFFERENTIAL
# =============================================================================

def compute_explosive_plays(df):
    """
    Explosive play = rush >= 12 yards OR pass >= 16 yards.
    ExplosivePlayDelta = max(team explosive count) - min(team explosive count).
    """
    df = df.copy()
    yards = df['yards_gained'].fillna(0)
    ptype = df['play_type'].fillna('').str.lower()

    is_rush = ptype.str.contains('rush|run')
    is_pass = ptype.str.contains('pass|completion|incompletion|sack')

    df['is_explosive'] = (
            (is_rush & (yards >= EXPLOSIVE_RUSH_YARDS)) |
            (is_pass & (yards >= EXPLOSIVE_PASS_YARDS))
    ).astype(int)

    # Aggregate by game and offense team
    game_team = df.groupby(['game_id', 'offense'])['is_explosive'].sum().reset_index()
    game_team.columns = ['game_id', 'team', 'explosive_count']

    # Delta = max - min per game
    def explosive_delta(g):
        return g['explosive_count'].max() - g['explosive_count'].min()

    result = game_team.groupby('game_id').apply(explosive_delta).reset_index()
    result.columns = ['game_id', 'explosive_play_delta']
    return result


# =============================================================================
# STEP 4C: WIN PROBABILITY VOLATILITY
# =============================================================================

def compute_wp_volatility(df):
    """
    Win probability volatility = std dev of home_wp across all plays in a game.
    """
    result = (
        df[df['home_wp'].notna()]
        .groupby('game_id')['home_wp']
        .std()
        .reset_index()
    )
    result.columns = ['game_id', 'win_prob_volatility']
    return result


# =============================================================================
# STEP 5: CHAOS FACTOR
# =============================================================================

def compute_chaos_factor(lead_df, explosive_df, volatility_df, w1=W1, w2=W2, w3=W3):
    """
    Chaos = w1·WinProbVolatility + w2·LeadChangeCount + w3·ExplosivePlayDelta
    All components normalized to [0,1] before weighting.
    """
    chaos = lead_df.merge(explosive_df, on='game_id', how='outer')
    chaos = chaos.merge(volatility_df, on='game_id', how='outer')

    # Normalize each component to [0,1]
    for col in ['lead_change_count', 'explosive_play_delta', 'win_prob_volatility']:
        col_min = chaos[col].min()
        col_max = chaos[col].max()
        if col_max > col_min:
            chaos[f'{col}_norm'] = (chaos[col] - col_min) / (col_max - col_min)
        else:
            chaos[f'{col}_norm'] = 0.0

    chaos['chaos_factor'] = (
            w1 * chaos['win_prob_volatility_norm'] +
            w2 * chaos['lead_change_count_norm'] +
            w3 * chaos['explosive_play_delta_norm']
    )

    # Chaos tier labels
    p33 = chaos['chaos_factor'].quantile(0.33)
    p66 = chaos['chaos_factor'].quantile(0.66)
    chaos['chaos_tier'] = pd.cut(
        chaos['chaos_factor'],
        bins=[-np.inf, p33, p66, np.inf],
        labels=['Low', 'Medium', 'High']
    )

    return chaos


# =============================================================================
# STEP 6: TEAM-SEASON AGGREGATION
# =============================================================================

def aggregate_to_team_season(chaos_df, plays_df):
    """
    Rolls game-level chaos up to team-season level.
    Each team gets: avg_chaos, max_chaos, chaos_as_home, chaos_as_away,
    pct_high_chaos_games.
    """
    # Join home/away info back to chaos
    game_info = plays_df[['game_id', 'season', 'home', 'away']].drop_duplicates('game_id')
    chaos_with_info = chaos_df.merge(game_info, on='game_id', how='left')

    rows = []
    for _, row in chaos_with_info.iterrows():
        for team_type in ['home', 'away']:
            rows.append({
                'game_id': row['game_id'],
                'season': row['season'],
                'team': row[team_type],
                'is_home': team_type == 'home',
                'chaos_factor': row['chaos_factor'],
                'chaos_tier': str(row['chaos_tier']),
                'lead_change_count': row.get('lead_change_count', np.nan),
                'explosive_play_delta': row.get('explosive_play_delta', np.nan),
                'win_prob_volatility': row.get('win_prob_volatility', np.nan),
            })

    long_df = pd.DataFrame(rows)

    team_season = (
        long_df
        .groupby(['team', 'season'])
        .agg(
            games_played=('game_id', 'count'),
            avg_chaos=('chaos_factor', 'mean'),
            max_chaos=('chaos_factor', 'max'),
            std_chaos=('chaos_factor', 'std'),
            avg_lead_changes=('lead_change_count', 'mean'),
            avg_explosive_delta=('explosive_play_delta', 'mean'),
            avg_wp_volatility=('win_prob_volatility', 'mean'),
            pct_high_chaos=('chaos_tier', lambda x: (x == 'High').mean()),
        )
        .reset_index()
        .round(4)
    )

    return team_season


# =============================================================================
# MAIN PIPELINE
# =============================================================================

def run(years, out_dir='.', power5_only=True):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    config = get_config()
    all_plays = []
    all_chaos = []
    all_team_season = []

    print("=" * 60)
    print("CFB CHAOS FACTOR PIPELINE")
    print(f"Years: {years} | Power5 only: {power5_only}")
    print("=" * 60)

    with ApiClient(config) as api_client:
        for year in years:
            print(f"\n[{year}] Fetching play-by-play...")
            plays = fetch_plays(api_client, year)

            if plays.empty:
                print(f"  No plays found for {year}")
                continue

            print(f"  Total plays: {len(plays):,}")

            # Filter to Power 5 if requested
            if power5_only:
                mask = (
                        plays['offense_conference'].isin(POWER5) |
                        plays['defense_conference'].isin(POWER5)
                )
                plays = plays[mask]
                print(f"  After P5 filter: {len(plays):,} plays, "
                      f"{plays['game_id'].nunique()} games")

            # Pipeline steps
            print(f"  Standardizing play order...")
            plays = standardize_play_order(plays)

            print(f"  Reconstructing scoreboard...")
            plays = reconstruct_scoreboard(plays)

            print(f"  Computing features...")
            lead_df = compute_lead_changes(plays)
            explosive_df = compute_explosive_plays(plays)
            volatility_df = compute_wp_volatility(plays)

            print(f"  Computing Chaos Factor...")
            chaos = compute_chaos_factor(lead_df, explosive_df, volatility_df)
            chaos['season'] = year

            print(f"  Aggregating to team-season level...")
            team_season = aggregate_to_team_season(chaos, plays)

            # Save year-level files
            chaos.to_csv(out_dir / f'chaos_games_{year}.csv', index=False)
            team_season.to_csv(out_dir / f'chaos_team_season_{year}.csv', index=False)

            all_plays.append(plays)
            all_chaos.append(chaos)
            all_team_season.append(team_season)

            # Print top chaos games
            top = chaos.nlargest(5, 'chaos_factor')[
                ['game_id', 'chaos_factor', 'lead_change_count',
                 'explosive_play_delta', 'win_prob_volatility']
            ]
            print(f"\n  Top 5 chaos games {year}:")
            print(top.to_string(index=False))

    # Save combined files
    if all_chaos:
        pd.concat(all_chaos).to_csv(out_dir / 'chaos_games_all.csv', index=False)
        pd.concat(all_team_season).to_csv(out_dir / 'chaos_team_seasons.csv', index=False)

        print("\n" + "=" * 60)
        print("DONE")
        print(f"  chaos_games_all.csv      — game-level chaos scores")
        print(f"  chaos_team_seasons.csv   — team-season aggregates")
        print(f"  chaos_games_{{year}}.csv  — per-year game files")

    return pd.concat(all_team_season) if all_team_season else pd.DataFrame()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="CFB Chaos Factor Pipeline")
    parser.add_argument('--years', nargs='+', type=int,
                        default=[2021, 2022, 2023, 2024])
    parser.add_argument('--out', default='./data/cfb_data')
    parser.add_argument('--all-conferences', action='store_true',
                        help='Include non-Power 5 games')
    args = parser.parse_args()

    run(
        years=args.years,
        out_dir=args.out,
        power5_only=not args.all_conferences,
    )