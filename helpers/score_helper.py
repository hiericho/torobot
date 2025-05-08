# score_helper.py
import os
import time
import pandas as pd
import numpy as np
from colorama import init, Fore, Style # For internal logging
from collections import Counter # Used by some functions
import traceback # For detailed error logging

# --- ML Imports ---
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestRegressor, GradientBoostingRegressor
from sklearn.metrics import mean_absolute_error
from sklearn.preprocessing import StandardScaler
from sklearn.impute import SimpleImputer

# --- XGBoost Import ---
try:
    import xgboost as xgb
    XGB_AVAILABLE = True
except ImportError:
    XGB_AVAILABLE = False

# --- NBA_API Imports (for feature data) ---
try:
    from nba_api.stats.static import teams
    from nba_api.stats.endpoints import teamgamelog
    NBA_API_AVAILABLE = True
except ImportError:
    NBA_API_AVAILABLE = False

# --- Configuration for ML and Feature Data ---
HISTORICAL_DATA_CSV = 'data/historical_nba_data.csv'
NBA_API_SEASON = "2024-25" # Make sure this season has data if you're testing now
NBA_API_SEASON_TYPE = "Regular Season"
NBA_API_ROLLING_WINDOW = 10
NBA_API_DELAY = 0.7

FEATURE_COLS = [
    'Away_AST_Roll10_PreGame', 'Away_BLK_Roll10_PreGame', 'Away_DREB_Roll10_PreGame', 'Away_FG3A_Roll10_PreGame', 'Away_FG3M_Roll10_PreGame', 'Away_FG3_PCT_Roll10_PreGame', 'Away_FGA_Roll10_PreGame', 'Away_FGM_Roll10_PreGame', 'Away_FG_PCT_Roll10_PreGame', 'Away_FTA_Roll10_PreGame', 'Away_FTM_Roll10_PreGame', 'Away_FT_PCT_Roll10_PreGame', 'Away_OREB_Roll10_PreGame', 'Away_PF_Roll10_PreGame', 'Away_PTS_Roll10_PreGame', 'Away_REB_Roll10_PreGame', 'Away_STL_Roll10_PreGame', 'Away_TOV_Roll10_PreGame',
    'Home_AST_Roll10_PreGame', 'Home_BLK_Roll10_PreGame', 'Home_DREB_Roll10_PreGame', 'Home_FG3A_Roll10_PreGame', 'Home_FG3M_Roll10_PreGame', 'Home_FG3_PCT_Roll10_PreGame', 'Home_FGA_Roll10_PreGame', 'Home_FGM_Roll10_PreGame', 'Home_FG_PCT_Roll10_PreGame', 'Home_FTA_Roll10_PreGame', 'Home_FTM_Roll10_PreGame', 'Home_FT_PCT_Roll10_PreGame', 'Home_OREB_Roll10_PreGame', 'Home_PF_Roll10_PreGame', 'Home_PTS_Roll10_PreGame', 'Home_REB_Roll10_PreGame', 'Home_STL_Roll10_PreGame', 'Home_TOV_Roll10_PreGame',
    'Diff_AST_Roll10_PreGame', 'Diff_BLK_Roll10_PreGame', 'Diff_DREB_Roll10_PreGame', 'Diff_FG3A_Roll10_PreGame', 'Diff_FG3M_Roll10_PreGame', 'Diff_FG3_PCT_Roll10_PreGame', 'Diff_FGA_Roll10_PreGame', 'Diff_FGM_Roll10_PreGame', 'Diff_FG_PCT_Roll10_PreGame', 'Diff_FTA_Roll10_PreGame', 'Diff_FTM_Roll10_PreGame', 'Diff_FT_PCT_Roll10_PreGame', 'Diff_OREB_Roll10_PreGame', 'Diff_PF_Roll10_PreGame', 'Diff_PTS_Roll10_PreGame', 'Diff_REB_Roll10_PreGame', 'Diff_STL_Roll10_PreGame', 'Diff_TOV_Roll10_PreGame',
]
TARGET_HOME_SCORE = 'Home_Team_Score'
TARGET_AWAY_SCORE = 'Away_Team_Score'

models_store = {
    "imputer": None, "scaler": None, "trained_models": {}, "evaluation": {},
    "feature_names": list(FEATURE_COLS), "nba_teams_lu": {},
    "best_model_name": None, "models_ready": False
}

COLOR_NEUTRAL=Style.RESET_ALL; COLOR_ERROR=Fore.RED; COLOR_HEADER=Fore.BLUE+Style.BRIGHT;
COLOR_INFO=Fore.LIGHTBLACK_EX; COLOR_METRIC=Fore.LIGHTMAGENTA_EX; COLOR_YELLOW=Fore.YELLOW;
COLOR_GREEN=Fore.GREEN; COLOR_RESET=Style.RESET_ALL
init(autoreset=True)

TEAM_NAME_MAP = {
    "LA Clippers": "Los Angeles Clippers", "LAC": "Los Angeles Clippers",
    "LAL": "Los Angeles Lakers", "NY Knicks": "New York Knicks", "NYK": "New York Knicks",
    "GS Warriors": "Golden State Warriors", "GSW": "Golden State Warriors",
    "Okla City Thunder": "Oklahoma City Thunder", "OKC": "Oklahoma City Thunder",
}

def load_and_prep_historical_data(filepath=HISTORICAL_DATA_CSV):
    print(f"{COLOR_NEUTRAL}Helper: Loading historical data from {filepath}...")
    try:
        df = pd.read_csv(filepath, low_memory=False)
        print(f"{COLOR_INFO}Helper: Loaded {len(df)} games.")
    except FileNotFoundError:
        print(f"{COLOR_ERROR}Helper: Historical data file not found at {filepath}")
        return None, None, None
    except Exception as e:
        print(f"{COLOR_ERROR}Helper: Error loading CSV: {e}")
        return None, None, None

    initial_feature_names = list(FEATURE_COLS) # Start with the defined list
    cols_to_keep_initially = initial_feature_names + [TARGET_HOME_SCORE, TARGET_AWAY_SCORE]
    
    actual_cols_present = [col for col in cols_to_keep_initially if col in df.columns]
    missing_essential_targets = [col for col in [TARGET_HOME_SCORE, TARGET_AWAY_SCORE] if col not in df.columns]
    if missing_essential_targets:
        print(f"{COLOR_ERROR}Helper: CSV missing essential target columns: {missing_essential_targets}")
        return None, None, None

    # Filter to only columns present in the CSV
    df_ml = df[actual_cols_present].copy()
    
    # Features that are actually in the CSV and also in our initial list
    usable_feature_names = [col for col in initial_feature_names if col in df_ml.columns]
    if not usable_feature_names:
        print(f"{COLOR_ERROR}Helper: No usable feature columns found in CSV from the expected list.")
        return None, None, None
    
    models_store['feature_names'] = usable_feature_names # Store the features we will actually use

    print(f"{COLOR_NEUTRAL}Helper: Preprocessing historical data with {len(usable_feature_names)} features...")
    for col in usable_feature_names:
        df_ml[col] = pd.to_numeric(df_ml[col], errors='coerce')

    df_ml.replace([np.inf, -np.inf], np.nan, inplace=True)
    initial_rows = len(df_ml)
    df_ml.dropna(subset=[TARGET_HOME_SCORE, TARGET_AWAY_SCORE], inplace=True)
    if len(df_ml) < initial_rows:
        print(f"{COLOR_INFO}Helper: Dropped {initial_rows - len(df_ml)} rows w/ missing targets.")
    if df_ml.empty:
        print(f"{COLOR_ERROR}Helper: No data remaining after dropping rows with missing targets.")
        return None, None, None

    X = df_ml[models_store['feature_names']] # Use the confirmed usable features
    y_home = df_ml[TARGET_HOME_SCORE]
    y_away = df_ml[TARGET_AWAY_SCORE]

    cols_all_nan = X.columns[X.isna().all()].tolist()
    if cols_all_nan:
        print(f"{COLOR_YELLOW}Helper: Warning - Dropping all-NaN features: {cols_all_nan}")
        X = X.drop(columns=cols_all_nan)
        models_store['feature_names'] = X.columns.tolist() # CRITICAL: Update feature names
        if not models_store['feature_names']:
            print(f"{COLOR_ERROR}Helper: No valid features left after dropping all-NaN columns.")
            return None, None, None
    
    if X.empty: # Check if X became empty after dropping all-NaN columns
        print(f"{COLOR_ERROR}Helper: Feature set X is empty after processing.")
        return None, None, None

    print(f"{COLOR_NEUTRAL}Helper: Imputing missing features (mean) for {len(models_store['feature_names'])} features...")
    imputer = SimpleImputer(strategy='mean')
    X_imputed = imputer.fit_transform(X)
    X = pd.DataFrame(X_imputed, columns=models_store['feature_names'])
    models_store['imputer'] = imputer

    print(f"{COLOR_NEUTRAL}Helper: Applying StandardScaler...")
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)
    X = pd.DataFrame(X_scaled, columns=models_store['feature_names'])
    models_store['scaler'] = scaler

    print(f"{COLOR_NEUTRAL}Helper: Preprocessing complete: {len(X)} games ({len(models_store['feature_names'])} features).")
    return X, y_home, y_away

def train_all_models(X, y_home, y_away):
    print(f"{COLOR_NEUTRAL}Helper: Splitting data for training...")
    try:
        X_train, X_test, y_home_train, y_home_test, y_away_train, y_away_test = train_test_split(
            X, y_home, y_away, test_size=0.2, random_state=42 # X already has the correct feature_names
        )
        print(f"{COLOR_INFO}Helper: Train size: {len(X_train)}, Test size: {len(X_test)}")
    except Exception as e:
        print(f"{COLOR_ERROR}Helper: Error splitting data: {e}")
        return False

    models_to_train_config = {
        "RF": {
            'home': RandomForestRegressor(n_estimators=100, random_state=42, n_jobs=-1, max_depth=20, min_samples_leaf=10),
            'away': RandomForestRegressor(n_estimators=100, random_state=42, n_jobs=-1, max_depth=20, min_samples_leaf=10)},
        "GB": {
            'home': GradientBoostingRegressor(n_estimators=100, learning_rate=0.1, max_depth=5, random_state=42, subsample=0.7),
            'away': GradientBoostingRegressor(n_estimators=100, learning_rate=0.1, max_depth=5, random_state=42, subsample=0.7)}}
    if XGB_AVAILABLE:
        models_to_train_config["XGB"] = {
             'home': xgb.XGBRegressor(objective='reg:squarederror', n_estimators=200, learning_rate=0.05,max_depth=5, subsample=0.7, colsample_bytree=0.7, random_state=42,n_jobs=-1, early_stopping_rounds=10),
             'away': xgb.XGBRegressor(objective='reg:squarederror', n_estimators=200, learning_rate=0.05,max_depth=5, subsample=0.7, colsample_bytree=0.7, random_state=42,n_jobs=-1, early_stopping_rounds=10)}

    overall_success = True
    models_store['trained_models'].clear()
    models_store['evaluation'].clear()

    for model_name, model_pair_config in models_to_train_config.items():
        print(f"\n--- Helper: Training {model_name} Models ---")
        try:
            home_model = model_pair_config['home']; away_model = model_pair_config['away']
            print(f"{COLOR_NEUTRAL}Helper: Fitting {model_name} Home...")
            eval_set_home = [(X_test, y_home_test)] if model_name == "XGB" and XGB_AVAILABLE else None
            if eval_set_home: home_model.fit(X_train, y_home_train, eval_set=eval_set_home, verbose=False)
            else: home_model.fit(X_train, y_home_train)

            print(f"{COLOR_NEUTRAL}Helper: Fitting {model_name} Away...")
            eval_set_away = [(X_test, y_away_test)] if model_name == "XGB" and XGB_AVAILABLE else None
            if eval_set_away: away_model.fit(X_train, y_away_train, eval_set=eval_set_away, verbose=False)
            else: away_model.fit(X_train, y_away_train)

            models_store['trained_models'][model_name] = {'home': home_model, 'away': away_model}
            print(f"{COLOR_NEUTRAL}Helper: Evaluating {model_name}...")
            home_preds = home_model.predict(X_test); away_preds = away_model.predict(X_test)
            home_mae = mean_absolute_error(y_home_test, home_preds)
            away_mae = mean_absolute_error(y_away_test, away_preds)
            avg_mae = (home_mae + away_mae) / 2
            models_store['evaluation'][model_name] = {'home_mae': home_mae, 'away_mae': away_mae, 'average_mae': avg_mae}
            print(f"{COLOR_METRIC}Helper: Eval Complete ({model_name}): Avg MAE: {avg_mae:.2f} pts")
        except Exception as e:
            print(f"{COLOR_ERROR}Helper: Error training/evaluating {model_name}: {e}"); traceback.print_exc()
            overall_success = False; models_store['trained_models'][model_name] = None; models_store['evaluation'][model_name] = None

    print(f"\n{COLOR_NEUTRAL}Helper: Finished training all models.")
    best_model_name_found = None; min_mae = float('inf')
    for model_name, eval_results in models_store['evaluation'].items():
        if eval_results and eval_results.get('average_mae') is not None:
            if eval_results['average_mae'] < min_mae:
                min_mae = eval_results['average_mae']; best_model_name_found = model_name
    if best_model_name_found:
        print(f"{COLOR_GREEN}Helper: Best model: {best_model_name_found} (Avg MAE: {min_mae:.2f}){COLOR_RESET}")
        models_store['best_model_name'] = best_model_name_found
    else:
        print(f"{COLOR_YELLOW}Helper: Warning - Could not determine best model.{COLOR_RESET}")
        models_store['best_model_name'] = None; overall_success = False

    models_store['models_ready'] = (overall_success and models_store['best_model_name'] is not None and
                                    bool(models_store['trained_models'].get(models_store['best_model_name'])) and
                                    models_store['imputer'] is not None and models_store['scaler'] is not None)
    return models_store['models_ready']

def initialize_nba_teams():
    if not NBA_API_AVAILABLE:
        print(f"{COLOR_YELLOW}Helper: NBA_API not available, cannot initialize teams.")
        models_store['nba_teams_lu'] = {}; return False
    print(f"{COLOR_NEUTRAL}Helper: Initializing NBA team lookup...")
    try:
        nba_teams_list = teams.get_teams()
        temp_lu = {team[k].lower(): team['id'] for team in nba_teams_list for k in ['full_name', 'nickname', 'abbreviation'] if team.get(k)}
        for odds_name, nba_api_standard_name in TEAM_NAME_MAP.items():
            if odds_name.lower() not in temp_lu:
                nba_api_id = temp_lu.get(nba_api_standard_name.lower())
                if nba_api_id: temp_lu[odds_name.lower()] = nba_api_id
        models_store['nba_teams_lu'] = temp_lu
        print(f"{COLOR_INFO}Helper: NBA team lookup initialized with {len(models_store['nba_teams_lu'])} entries.")
        return True
    except Exception as e:
        print(f"{COLOR_ERROR}Helper: Failed to fetch NBA teams: {e}"); models_store['nba_teams_lu'] = {}; return False

def get_team_id_from_odds_name(odds_api_team_name):
    if not models_store['nba_teams_lu']: return None
    name_lower = odds_api_team_name.lower()
    team_id = models_store['nba_teams_lu'].get(name_lower)
    if team_id: return team_id
    mapped_standard_name = TEAM_NAME_MAP.get(odds_api_team_name)
    if mapped_standard_name:
        team_id = models_store['nba_teams_lu'].get(mapped_standard_name.lower())
        if team_id: return team_id
    parts = odds_api_team_name.split()
    if len(parts) > 1:
        nickname_lower = parts[-1].lower()
        team_id = models_store['nba_teams_lu'].get(nickname_lower)
        if team_id: return team_id
    return None

def get_last_n_games_for_team(team_id, n=None):
    if n is None: n = NBA_API_ROLLING_WINDOW + 5
    if not NBA_API_AVAILABLE or team_id is None: return pd.DataFrame() # Return empty DF
    try:
        log = teamgamelog.TeamGameLog(team_id=team_id, season=NBA_API_SEASON, season_type_all_star=NBA_API_SEASON_TYPE)
        df = log.get_data_frames()[0]; time.sleep(NBA_API_DELAY)
    except Exception as e:
        print(f"{COLOR_ERROR}Helper: NBA_API Log Error (T{team_id}, S:{NBA_API_SEASON}, ST:{NBA_API_SEASON_TYPE}): {e}"); return pd.DataFrame()
    if df.empty: return pd.DataFrame()
    try:
        df['GAME_DATE'] = pd.to_datetime(df['GAME_DATE'], format='%b %d, %Y', errors='coerce')
        df.dropna(subset=['GAME_DATE'], inplace=True)
    except Exception as date_e:
        print(f"{COLOR_YELLOW}Helper: Date parsing error for T{team_id}: {date_e}")
    if df.empty: return pd.DataFrame()
    return df.sort_values('GAME_DATE', ascending=False).head(n)

def calculate_live_rolling_stats_for_log(game_log_df):
    n_roll = NBA_API_ROLLING_WINDOW
    # Base stat categories that we calculate from game logs
    # These are the keys that will be in the returned dictionary.
    expected_output_base_keys = [
        'PTS_Roll10', 'AST_Roll10', 'BLK_Roll10', 'DREB_Roll10',
        'FG3A_Roll10', 'FG3M_Roll10', 'FG3_PCT_Roll10',
        'FGA_Roll10', 'FGM_Roll10', 'FG_PCT_Roll10',
        'FTA_Roll10', 'FTM_Roll10', 'FT_PCT_Roll10',
        'OREB_Roll10', 'PF_Roll10', 'REB_Roll10', 'STL_Roll10', 'TOV_Roll10'
    ]
    live_stats = {key: np.nan for key in expected_output_base_keys} # Initialize with NaNs

    if game_log_df is None or game_log_df.empty or len(game_log_df) < 1:
        return live_stats

    # Columns needed from the log to calculate all expected_output_base_keys
    required_cols_from_log = ['PTS', 'AST', 'BLK', 'DREB', 'FG3A', 'FG3M', 'FGA', 'FGM', 'FTA', 'FTM', 'OREB', 'PF', 'REB', 'STL', 'TOV']
    missing_cols = [c for c in required_cols_from_log if c not in game_log_df.columns]
    if missing_cols:
        print(f"{COLOR_ERROR}Helper: Game log missing required columns for stats: {missing_cols}")
        return live_stats

    df = game_log_df.sort_values('GAME_DATE', ascending=True).copy()
    for col in required_cols_from_log:
        df[col] = pd.to_numeric(df[col], errors='coerce')

    # Calculate rolling means for stats that are direct averages
    mean_stat_bases = ['PTS', 'AST', 'BLK', 'DREB', 'OREB', 'PF', 'REB', 'STL', 'TOV']
    if all(col in df.columns for col in mean_stat_bases):
        rolling_means = df[mean_stat_bases].rolling(window=n_roll, closed='left', min_periods=1).mean()
        if not rolling_means.empty:
            last_row_means = rolling_means.iloc[-1]
            for col_base in mean_stat_bases:
                live_stats[f'{col_base}_Roll10'] = last_row_means.get(col_base, np.nan)

    # Calculate rolling sums for made/attempted stats, then derive percentages
    sum_stat_bases = ['FG3A', 'FG3M', 'FGA', 'FGM', 'FTA', 'FTM']
    if all(col in df.columns for col in sum_stat_bases):
        rolling_sums = df[sum_stat_bases].rolling(window=n_roll, closed='left', min_periods=1).sum()
        if not rolling_sums.empty:
            last_row_sums = rolling_sums.iloc[-1]
            for col_base in sum_stat_bases: # Store sums like FGM_Roll10 if they are features
                live_stats[f'{col_base}_Roll10'] = last_row_sums.get(col_base, np.nan)
            
            # Derive percentages
            s_fg3m = live_stats.get('FG3M_Roll10', np.nan); s_fg3a = live_stats.get('FG3A_Roll10', np.nan)
            s_fgm  = live_stats.get('FGM_Roll10', np.nan);  s_fga  = live_stats.get('FGA_Roll10', np.nan)
            s_ftm  = live_stats.get('FTM_Roll10', np.nan);  s_fta  = live_stats.get('FTA_Roll10', np.nan)

            live_stats['FG3_PCT_Roll10'] = (s_fg3m / s_fg3a) if pd.notna(s_fg3a) and pd.notna(s_fg3m) and s_fg3a > 0 else 0.0
            live_stats['FG_PCT_Roll10']  = (s_fgm / s_fga) if pd.notna(s_fga) and pd.notna(s_fgm) and s_fga > 0 else 0.0
            live_stats['FT_PCT_Roll10']  = (s_ftm / s_fta) if pd.notna(s_fta) and pd.notna(s_ftm) and s_fta > 0 else 0.0
            
    return live_stats


def prepare_live_features_from_stats(home_stats, away_stats):
    if home_stats is None or away_stats is None:
        print(f"{COLOR_YELLOW}Helper: Cannot prepare features: missing home or away stats (None).")
        return pd.DataFrame([[np.nan] * len(models_store['feature_names'])], columns=models_store['feature_names'])

    live_features_dict = {}
    current_model_feature_names = models_store['feature_names']

    # Populate Home_ features
    for stat_key_suffix, value in home_stats.items(): # e.g., stat_key_suffix is 'PTS_Roll10'
        feature_name = f"Home_{stat_key_suffix}_PreGame" # e.g., 'Home_PTS_Roll10_PreGame'
        if feature_name in current_model_feature_names: # Check against actual model features
            live_features_dict[feature_name] = value

    # Populate Away_ features
    for stat_key_suffix, value in away_stats.items():
        feature_name = f"Away_{stat_key_suffix}_PreGame"
        if feature_name in current_model_feature_names:
            live_features_dict[feature_name] = value

    # Populate Diff_ features
    # Assumes home_stats and away_stats have the same keys (e.g., 'PTS_Roll10', 'AST_Roll10')
    # Iterate over the keys from one of them (e.g. home_stats) that are expected base stats
    base_stat_keys_for_diff = home_stats.keys() # These are like 'PTS_Roll10'
    for stat_key_suffix in base_stat_keys_for_diff:
        feature_name = f"Diff_{stat_key_suffix}_PreGame"
        if feature_name in current_model_feature_names:
            home_val = home_stats.get(stat_key_suffix, np.nan)
            away_val = away_stats.get(stat_key_suffix, np.nan) # Get corresponding away stat
            diff_val = np.nan
            if pd.notna(home_val) and pd.notna(away_val):
                try: diff_val = home_val - away_val
                except TypeError: pass # Keep diff_val as np.nan
            live_features_dict[feature_name] = diff_val
    
    # Debugging print (optional, remove after fixing)
    # print(f"DEBUG Helper prepare_live_features: live_features_dict keys: {sorted(live_features_dict.keys())}")
    # missing_in_dict = [f for f in current_model_feature_names if f not in live_features_dict]
    # if missing_in_dict:
    #     print(f"DEBUG Helper prepare_live_features: Features MISSING from live_features_dict (will be NaN): {missing_in_dict}")

    ordered_live_features = {col: live_features_dict.get(col, np.nan) for col in current_model_feature_names}
    feature_vector_df = pd.DataFrame([ordered_live_features], columns=current_model_feature_names)

    if models_store['imputer'] is None or models_store['scaler'] is None:
        print(f"{COLOR_ERROR}Helper: Imputer or Scaler not available. Cannot preprocess live features.")
        return None
    try:
        imputed_vector = models_store['imputer'].transform(feature_vector_df)
        imputed_df = pd.DataFrame(imputed_vector, columns=current_model_feature_names)
        scaled_vector = models_store['scaler'].transform(imputed_df)
        final_feature_vector_df = pd.DataFrame(scaled_vector, columns=current_model_feature_names)
        if final_feature_vector_df.isnull().values.any():
            print(f"{COLOR_YELLOW}Helper: Warning - NaNs detected in final feature vector after scaling.")
        return final_feature_vector_df
    except Exception as e:
        print(f"{COLOR_ERROR}Helper: Error applying imputer/scaler to live features: {e}"); traceback.print_exc()
        return None

def predict_scores_with_model(feature_vector_df, model_name_key):
    if feature_vector_df is None or feature_vector_df.empty:
        print(f"{COLOR_ERROR}Helper: Prediction aborted: feature_vector_df is None or empty.")
        return None, None
    if model_name_key not in models_store['trained_models'] or models_store['trained_models'][model_name_key] is None:
        print(f"{COLOR_ERROR}Helper: Model '{model_name_key}' not found or not trained.")
        return None, None
    model_pair = models_store['trained_models'][model_name_key]
    home_model = model_pair.get('home'); away_model = model_pair.get('away')
    if home_model is None or away_model is None:
        print(f"{COLOR_ERROR}Helper: Home or away sub-model for '{model_name_key}' is None.")
        return None, None
    try:
        if feature_vector_df.isnull().values.any():
            print(f"{COLOR_YELLOW}Helper: NaNs present in feature vector for model '{model_name_key}'. Prediction may be affected.")
        # Ensure feature_vector_df has columns in the same order as training (should be handled by prepare_live_features)
        # X_predict_df = feature_vector_df[models_store['feature_names']] # Redundant if prepare_live_features is correct

        pred_home = home_model.predict(feature_vector_df)[0]
        pred_away = away_model.predict(feature_vector_df)[0]
        return round(float(pred_home)), round(float(pred_away))
    except Exception as e:
        print(f"{COLOR_ERROR}Helper: Error during '{model_name_key}' prediction: {e}"); traceback.print_exc()
        print(f"{COLOR_INFO}Helper: Input feature vector for prediction:\n{feature_vector_df.to_string()}")
        return None, None