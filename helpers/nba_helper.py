# helpers/nba_helper.py
import logging
from functools import lru_cache
import pandas as pd
from fuzzywuzzy import process, fuzz
from typing import List, Dict, Tuple, Optional, Any
import asyncio
import aiohttp
from bs4 import BeautifulSoup
import re # For B-Ref player code if needed, though simpler for now

# Import specific NBA API modules needed
from nba_api.stats.static import teams as nba_static_teams, players as nba_static_players
from nba_api.stats.endpoints import (
    commonplayerinfo,
    # playerprofilev2, # Replaced by playerdashboardbygeneralsplits for more direct stats
    leaguedashteamstats,
    scoreboardv2,
    leaguestandingsv3,
    teamgamelog,
    commonteamroster,
    leaguedashplayerstats,
    playerdashboardbygeneralsplits # Key endpoint for player stats
)

# Import constants using relative import
from .constants import (
    NBA_API_TIMEOUT,
    FUZZY_MATCH_THRESHOLD,
    PLAYER_HEADSHOT_URL_TEMPLATE, # Renamed for clarity
    ESPN_NBA_SCOREBOARD_URL # If used by any helper here, otherwise remove
    # Import other constants as needed
)

logger = logging.getLogger(__name__)

# --- Synchronous Static Data Fetching with Caching ---
@lru_cache(maxsize=1)
def get_all_nba_teams_cached() -> List[Dict[str, Any]]:
    """Cached synchronous fetch for all NBA teams static data."""
    logger.debug("SYNC: Fetching all NBA teams from API (stats.nba.com).")
    try:
        return nba_static_teams.get_teams()
    except Exception as e:
        logger.exception("SYNC: Failed to fetch NBA teams static list:", exc_info=False) # Less noise for common error
        return []

@lru_cache(maxsize=1)
def get_all_nba_players_cached(active_only: bool = True) -> List[Dict[str, Any]]:
    """Cached synchronous fetch for NBA players static data."""
    logger.debug(f"SYNC: Fetching {'active' if active_only else 'all'} NBA players from API (stats.nba.com).")
    try:
        return nba_static_players.get_active_players() if active_only else nba_static_players.get_players()
    except Exception as e:
        logger.exception(f"SYNC: Failed to fetch NBA players static list (active_only={active_only}):", exc_info=False)
        return []

# --- Synchronous ID/Name Finders (Leverage Cached Static Data) ---
@lru_cache(maxsize=1) # Cache the choices dictionary itself
def _get_team_fuzzy_choices() -> Dict[str, Dict[str, Any]]:
    """Builds a dictionary of team names/abbrs/ids for fuzzy matching."""
    all_teams = get_all_nba_teams_cached()
    choices = {}
    if not all_teams:
        return choices
    for t in all_teams:
        choices[t['full_name'].lower()] = t
        choices[t['abbreviation'].lower()] = t
        choices[t['nickname'].lower()] = t
        choices[str(t['id'])] = t # Allow matching by ID string
    return choices

def find_team_info_by_query(team_query: str) -> Optional[Dict[str, Any]]:
    """
    Finds NBA team static info by name, abbreviation, nickname, or ID string.
    Uses direct match first, then fuzzy matching.
    """
    if not team_query: return None
    team_query_lower = str(team_query).lower() # Ensure string for dict lookup
    
    choices = _get_team_fuzzy_choices()
    if not choices:
        logger.warning("Team fuzzy choices not available.")
        return None

    # Attempt direct match (abbreviation, nickname, full name lowercased, ID string)
    direct_match = choices.get(team_query_lower)
    if direct_match:
        logger.debug(f"Direct match for team query '{team_query}' -> '{direct_match['full_name']}'")
        return direct_match

    # Fuzzy match against the keys (which are various forms of team identifiers)
    # We pass only the keys for matching, then use the matched key to get the dict
    best_match_tuple = process.extractOne(
        team_query_lower, choices.keys(), # Match against the dictionary keys
        scorer=fuzz.token_set_ratio,
        score_cutoff=FUZZY_MATCH_THRESHOLD
    )

    if best_match_tuple:
        matched_key_str, score = best_match_tuple
        matched_team_info = choices[matched_key_str] # Get the dict using the matched key
        logger.info(f"Fuzzy match for team query '{team_query}' -> '{matched_key_str}' (Resolved to: {matched_team_info['full_name']}, Score: {score})")
        return matched_team_info
    
    logger.warning(f"No suitable team match found for query: '{team_query}'")
    return None

@lru_cache(maxsize=128) # Cache more individual player lookups
def find_player_info_by_name(player_query: str, active_only: bool = True) -> Optional[Dict[str, Any]]:
    """Finds the best player match using fuzzy matching on full names. Cached results."""
    if not player_query: return None
    
    all_players = get_all_nba_players_cached(active_only=active_only)
    if not all_players:
        return None

    # Create choices: { 'player full name lower': player_dict }
    choices = {p['full_name'].lower(): p for p in all_players if p.get('full_name')}
    if not choices: # No players with full names (should not happen)
        return None

    best_match_tuple = process.extractOne(
        player_query.lower(), choices.keys(), # Match against player name keys
        scorer=fuzz.token_set_ratio,
        score_cutoff=FUZZY_MATCH_THRESHOLD
    )

    if best_match_tuple:
        matched_name_key, score = best_match_tuple
        matched_player_info = choices[matched_name_key]
        logger.info(f"Fuzzy match for player query '{player_query}' -> '{matched_name_key}' (ID: {matched_player_info['id']}, Score: {score})")
        return matched_player_info
    
    logger.warning(f"No suitable player match found for query: '{player_query}'")
    return None

@lru_cache(maxsize=30) # Teams don't change IDs
def find_team_info_by_id(team_id: int) -> Optional[Dict[str, Any]]:
    """Finds team static data by ID. Cached."""
    all_teams = get_all_nba_teams_cached()
    for team_info in all_teams:
        if team_info['id'] == team_id:
            return team_info
    logger.warning(f"No team found for ID: {team_id}")
    return None

@lru_cache(maxsize=256) # Players don't change IDs often
def find_player_info_by_id(player_id: int, active_only: bool = True) -> Optional[Dict[str, Any]]:
    """Finds player static data by ID. Cached."""
    all_players = get_all_nba_players_cached(active_only=active_only)
    for player_info in all_players:
        if player_info['id'] == player_id:
            return player_info
    logger.warning(f"No player found for ID: {player_id} (active_only={active_only})")
    return None

# --- Asynchronous API Data Fetching Functions (Using nba_api with asyncio.to_thread) ---

async def fetch_team_season_stats(team_id: int, season: str, season_type: str = 'Regular Season') -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """
    Fetches detailed team season stats using LeagueDashTeamStats.
    Returns (stats_dict, None) or (None, error_message).
    """
    logger.info(f"ASYNC: Fetching team season stats for ID: {team_id}, Season: {season}, Type: {season_type}")
    if not isinstance(team_id, int):
        return None, "Invalid Team ID type provided."

    try:
        def _blocking_fetch():
            stats_endpoint = leaguedashteamstats.LeagueDashTeamStats(
                per_mode_detailed='PerGame',
                team_id_nullable=team_id,
                season=season,
                season_type_all_star=season_type, # e.g., 'Regular Season', 'Playoffs'
                timeout=NBA_API_TIMEOUT
            )
            data_frames = stats_endpoint.get_data_frames()
            if data_frames:
                return data_frames[0]
            return pd.DataFrame() # Return empty DF if no data

        stats_df = await asyncio.to_thread(_blocking_fetch)

        if stats_df is not None and not stats_df.empty:
            # The endpoint might return stats for all teams if team_id_nullable is not filtered by API
            # So, ensure we filter for the specific team if the API didn't.
            team_stats_df_filtered = stats_df[stats_df['TEAM_ID'] == team_id]
            if not team_stats_df_filtered.empty:
                stats_dict = team_stats_df_filtered.iloc[0].to_dict()
                # Calculate W_PCT if not present
                if 'W' in stats_dict and 'L' in stats_dict and stats_dict.get('W_PCT') is None: # Check for None explicitly
                    total_games = stats_dict['W'] + stats_dict['L']
                    stats_dict['W_PCT'] = (stats_dict['W'] / total_games) if total_games > 0 else 0.0
                logger.info(f"Successfully fetched stats for team ID {team_id}, Season {season}")
                return stats_dict, None
            else:
                logger.warning(f"LeagueDashTeamStats data found, but no specific entry for team ID {team_id} (Season: {season}).")
                return None, f"No stats entry found for team ID {team_id} in season {season} data."
        else:
            logger.warning(f"LeagueDashTeamStats returned no data for team ID {team_id} (Season: {season}).")
            return None, f"No stats data available for team ID {team_id} for season {season}."
    except Exception as e:
        logger.exception(f"ASYNC: Error fetching team stats for ID {team_id}, Season {season}:", exc_info=True)
        return None, f"API error fetching stats for team ID {team_id}."


async def fetch_player_bio_info(player_id: int) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """
    Fetches player bio using CommonPlayerInfo.
    Returns (bio_data, None) or (None, error_message).
    """
    logger.info(f"ASYNC: Fetching player bio for ID: {player_id}")
    if not isinstance(player_id, int):
        return None, "Invalid Player ID type."

    try:
        def _blocking_fetch():
            endpoint = commonplayerinfo.CommonPlayerInfo(player_id=player_id, timeout=NBA_API_TIMEOUT)
            data_frames = endpoint.common_player_info.get_data_frame() # This already returns the specific DF
            return data_frames

        info_df = await asyncio.to_thread(_blocking_fetch)

        if info_df is not None and not info_df.empty:
            bio_data = info_df.iloc[0].to_dict()
            # Augment common data
            bio_data['id'] = player_id
            bio_data['full_name'] = bio_data.get('DISPLAY_FIRST_LAST', f"Player ID {player_id}").strip()
            bio_data['headshot_url'] = PLAYER_HEADSHOT_URL_TEMPLATE.format(player_id=player_id)
            team_city = bio_data.get('TEAM_CITY', '')
            team_api_name = bio_data.get('TEAM_NAME', '')
            bio_data['team_full_name'] = f"{team_city} {team_api_name}".strip() if team_city or team_api_name else "N/A"
            # Ensure all expected keys are present, defaulting to "N/A"
            for key in ['TEAM_ABBREVIATION', 'POSITION', 'HEIGHT', 'WEIGHT', 'JERSEY',
                        'DRAFT_YEAR', 'DRAFT_ROUND', 'DRAFT_NUMBER', 'COUNTRY', 'BIRTHDATE']:
                bio_data.setdefault(key, "N/A")
            if bio_data['JERSEY'] != "N/A" and bio_data['JERSEY'] != '':
                bio_data['JERSEY'] = f"#{bio_data['JERSEY']}"


            logger.info(f"Successfully fetched bio for {bio_data['full_name']} (ID: {player_id})")
            return bio_data, None
        else:
            logger.warning(f"CommonPlayerInfo empty or None for Player ID {player_id}.")
            return None, f"Could not fetch detailed bio for Player ID {player_id}."
    except Exception as e:
        logger.exception(f"ASYNC: Error fetching CommonPlayerInfo for ID {player_id}:", exc_info=True)
        return None, f"API error fetching bio for Player ID {player_id}."


async def fetch_player_season_stats_dashboard(player_id: int, season: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """
    Fetches player PerGame (Base) and Advanced stats for a specific season using PlayerDashboardByGeneralSplits.
    Returns (combined_stats_dict, None) or (None, error_message).
    """
    logger.info(f"ASYNC: Fetching player dashboard stats for ID: {player_id}, Season: {season}")
    if not isinstance(player_id, int): return None, "Invalid Player ID type."
    if not season: return None, "Season parameter is required."

    combined_stats = {}
    error_messages = []

    try:
        def _blocking_dashboard_fetch(p_id, s, measure, per_mode, timeout):
            endpoint = playerdashboardbygeneralsplits.PlayerDashboardByGeneralSplits(
                player_id=p_id, season=s,
                measure_type_detailed_defense=measure, # 'Base' or 'Advanced'
                per_mode_detailed=per_mode, # 'PerGame'
                timeout=timeout
            )
            df = endpoint.overall_player_dashboard.get_data_frame()
            return df

        # Fetch Base Stats (PerGame)
        base_stats_df = await asyncio.to_thread(
            _blocking_dashboard_fetch, player_id, season, 'Base', 'PerGame', NBA_API_TIMEOUT
        )
        if base_stats_df is not None and not base_stats_df.empty:
            combined_stats.update(base_stats_df.iloc[0].to_dict())
        else:
            logger.warning(f"PlayerDashboard (Base) no stats for Player ID {player_id}, Season {season}.")
            error_messages.append(f"No traditional stats found for season {season}.")
            # Don't return yet, try to get advanced stats

        # Fetch Advanced Stats
        advanced_stats_df = await asyncio.to_thread(
            _blocking_dashboard_fetch, player_id, season, 'Advanced', 'PerGame', NBA_API_TIMEOUT
        )
        if advanced_stats_df is not None and not advanced_stats_df.empty:
            # Merge only specific advanced stats to avoid overwriting base stats with same column names
            adv_data = advanced_stats_df.iloc[0].to_dict()
            for key in ['EFG_PCT', 'TS_PCT', 'USG_PCT', 'PIE', 'NET_RATING', 'OFF_RATING', 'DEF_RATING', 'PACE']:
                if key in adv_data:
                    combined_stats[key] = adv_data[key]
        else:
            logger.warning(f"PlayerDashboard (Advanced) no stats for Player ID {player_id}, Season {season}.")
            # This might be normal if player doesn't qualify

        if not combined_stats: # If both base and advanced were empty
            final_error = " ".join(error_messages) or f"No stats data found for Player ID {player_id} in season {season}."
            return None, final_error
        
        logger.info(f"Successfully fetched dashboard stats for Player ID {player_id}, Season: {season}")
        return combined_stats, None # Success, even if only partial (e.g. base but no advanced)

    except Exception as e:
        logger.exception(f"ASYNC: Error fetching PlayerDashboard stats for ID {player_id}, Season {season}:", exc_info=True)
        return None, f"API error fetching player dashboard stats for Player ID {player_id}."


async def fetch_scoreboard_v2_data() -> Tuple[Optional[Dict[str, pd.DataFrame]], Optional[str]]:
    """Fetches today's scoreboard data using scoreboardv2."""
    logger.info("ASYNC: Fetching today's games (ScoreboardV2).")
    try:
        def _blocking_fetch():
            board = scoreboardv2.ScoreboardV2(timeout=NBA_API_TIMEOUT)
            return {
                "headers": board.game_header.get_data_frame(),
                "scores": board.line_score.get_data_frame(),
                "series": board.series_standings.get_data_frame()
                # Add other dataframes from scoreboardv2 if needed
            }
        
        data = await asyncio.to_thread(_blocking_fetch)
        
        # Basic validation that DFs were returned
        if data and data.get("headers") is not None: # Check one key DataFrame
            # Check if any headers were actually found (indicates games)
            if data["headers"].empty:
                 logger.info("ScoreboardV2 returned empty headers; likely no games today.")
                 # Return structure with empty DFs to indicate "no games" rather than error
                 return {"headers": pd.DataFrame(), "scores": pd.DataFrame(), "series": pd.DataFrame()}, None

            logger.info("Successfully fetched ScoreboardV2 data.")
            return data, None
        else:
            logger.warning("ScoreboardV2 did not return expected DataFrame structure.")
            return None, "API returned unexpected scoreboard data format."
            
    except Exception as e:
        logger.exception("ASYNC: Error fetching ScoreboardV2 data:", exc_info=True)
        return None, "API error fetching today's scoreboard."


async def fetch_league_standings_v3(season: str, season_type: str = 'Regular Season') -> Tuple[Optional[Dict[str, pd.DataFrame]], Optional[str]]:
    """
    Fetches season standings using LeagueStandingsV3.
    Returns {'East': east_df, 'West': west_df}, or (None, error_message).
    """
    logger.info(f"ASYNC: Fetching league standings for Season: {season}, Type: {season_type}")
    try:
        def _blocking_fetch():
            endpoint = leaguestandingsv3.LeagueStandingsV3(
                season=season,
                season_type=season_type,
                timeout=NBA_API_TIMEOUT
            )
            dataframes = endpoint.get_data_frames()
            if dataframes and isinstance(dataframes, list) and len(dataframes) > 0:
                return dataframes[0]
            return None

        standings_df = await asyncio.to_thread(_blocking_fetch)

        if standings_df is None or not isinstance(standings_df, pd.DataFrame) or standings_df.empty:
            logger.warning(f"LeagueStandingsV3 returned empty or invalid DataFrame for Season {season}, Type {season_type}.")
            return None, f"No standings data available for {season} ({season_type})."

        if 'Conference' not in standings_df.columns:
            logger.error("Standings DataFrame from LeagueStandingsV3 is missing 'Conference' column.")
            return None, "Standings data format error (missing Conference)."

        east_df = standings_df[standings_df['Conference'].str.lower() == 'east'].copy()
        west_df = standings_df[standings_df['Conference'].str.lower() == 'west'].copy()

        logger.info(f"Successfully fetched standings for {season}. East: {len(east_df)}, West: {len(west_df)}.")
        return {'East': east_df, 'West': west_df}, None

    except Exception as e:
        logger.exception(f"ASYNC: Error fetching league standings for Season {season}:", exc_info=True)
        return None, f"API error fetching league standings for {season}."


async def fetch_team_game_log(team_id: int, season: str, season_type: str = 'Regular Season', num_games: int = 5) -> Tuple[Optional[pd.DataFrame], Optional[str]]:
    """Fetches the game log for a team."""
    logger.info(f"ASYNC: Fetching game log (last {num_games}) for team ID: {team_id}, Season: {season}, Type: {season_type}")
    if not isinstance(team_id, int): return None, "Invalid Team ID."

    try:
        def _blocking_fetch():
            endpoint = teamgamelog.TeamGameLog(
                team_id=team_id,
                season=season,
                season_type_all_star=season_type,
                timeout=NBA_API_TIMEOUT
            )
            dataframes = endpoint.get_data_frames()
            if dataframes: return dataframes[0]
            return pd.DataFrame()

        log_df = await asyncio.to_thread(_blocking_fetch)

        if log_df is not None and not log_df.empty:
            logger.info(f"Successfully fetched game log for team ID {team_id}. Found {len(log_df)} games.")
            return log_df.head(num_games), None # API returns newest first
        else:
            logger.warning(f"TeamGameLog returned empty data for team ID {team_id}, Season {season}, Type {season_type}.")
            return None, f"No game log data found for team ID {team_id} for {season} ({season_type})."
    except Exception as e:
        logger.exception(f"ASYNC: Error fetching team game log for ID {team_id}:", exc_info=True)
        return None, f"API error fetching team game log for ID {team_id}."


async def fetch_team_roster_with_basic_stats(team_id: int, season: str) -> Tuple[Optional[List[Dict[str, Any]]], Optional[str]]:
    """
    Fetches team roster with basic player stats (PPG, EFF etc.) for a season using LeagueDashPlayerStats.
    Falls back to CommonTeamRoster for player names/IDs if LeagueDashPlayerStats fails.
    """
    logger.info(f"ASYNC: Fetching roster and player stats for team ID {team_id}, Season {season}")
    if not isinstance(team_id, int): return None, "Invalid Team ID."

    try:
        def _blocking_ldps_fetch():
            endpoint = leaguedashplayerstats.LeagueDashPlayerStats(
                team_id_nullable=team_id,
                season=season,
                per_mode_detailed='PerGame',
                season_type_all_star='Regular Season',
                timeout=NBA_API_TIMEOUT * 2 # Slightly longer for potentially larger dataset
            )
            dataframes = endpoint.get_data_frames()
            if dataframes: return dataframes[0]
            return pd.DataFrame()

        player_stats_df = await asyncio.to_thread(_blocking_ldps_fetch)

        if player_stats_df is not None and not player_stats_df.empty:
            logger.info(f"Fetched {len(player_stats_df)} players' stats via LeagueDashPlayerStats for team {team_id}, Season {season}.")
            relevant_cols = ['PLAYER_ID', 'PLAYER_NAME', 'TEAM_ABBREVIATION', 'GP', 'MIN', 'PTS', 'REB', 'AST', 'STL', 'BLK', 'TOV', 'FG_PCT', 'FG3_PCT', 'FT_PCT', 'PLUS_MINUS', 'EFF']
            existing_cols = [col for col in relevant_cols if col in player_stats_df.columns]
            roster_stats_df = player_stats_df[existing_cols].copy()

            sort_key = 'PTS' if 'PTS' in roster_stats_df.columns else ('EFF' if 'EFF' in roster_stats_df.columns else None)
            if sort_key:
                roster_stats_df.sort_values(by=sort_key, ascending=False, inplace=True)
            return roster_stats_df.to_dict('records'), None
        else:
            logger.warning(f"LeagueDashPlayerStats empty for team {team_id}, Season {season}. Falling back to CommonTeamRoster.")
            def _blocking_ctr_fetch():
                roster_endpoint = commonteamroster.CommonTeamRoster(team_id=team_id, season=season, timeout=NBA_API_TIMEOUT)
                dataframes = roster_endpoint.common_team_roster.get_data_frame()
                if dataframes is not None: return dataframes # common_team_roster specific DF
                return pd.DataFrame()

            roster_df_basic = await asyncio.to_thread(_blocking_ctr_fetch)
            if roster_df_basic is not None and not roster_df_basic.empty:
                logger.info(f"Fetched basic roster ({len(roster_df_basic)} players) via CommonTeamRoster for team {team_id}, Season {season}.")
                # Note: This only has basic info, not game stats like PPG.
                return roster_df_basic[['PLAYER_ID', 'PLAYER', 'POSITION', 'NICKNAME', 'HEIGHT', 'WEIGHT', 'NUM']].rename(
                    columns={'PLAYER': 'PLAYER_NAME', 'NUM': 'JERSEY'}
                ).to_dict('records'), "basic_info_only" # Signal that only basic info was returned
            else:
                logger.warning(f"All methods failed to fetch roster/player stats for team {team_id}, Season {season}.")
                return None, f"Could not fetch roster or player stats for team ID {team_id} for season {season}."

    except Exception as e:
        logger.exception(f"ASYNC: Error fetching team roster/stats for ID {team_id}, Season {season}:", exc_info=True)
        return None, f"API error fetching roster/stats for team ID {team_id}."


async def fetch_bref_advanced_player_stats(player_name: str, season_year_end: Optional[int] = None) -> Tuple[Optional[Dict[str, str]], Optional[str]]:
    """
    Fetches advanced stats (PER, WS, BPM) from Basketball-Reference for a player's latest or specified season.
    season_year_end: e.g., 2024 for the 2023-24 season. If None, tries latest.
    """
    logger.info(f"ASYNC BREF: Fetching advanced stats for '{player_name}'" + (f", Season ending {season_year_end}" if season_year_end else ", latest season"))
    
    # Simple B-Ref name to URL component logic (can be improved)
    name_parts = re.sub(r'[^\w\s]', '', player_name.lower()).split() # Remove punctuation, lowercase, split
    if len(name_parts) < 2:
        return None, "Player name for B-Ref must include at least first and last name."
    
    last_name_part = name_parts[-1][:5] # Last 5 chars of last name component
    first_name_part = name_parts[0][:2]  # First 2 chars of first name component
    
    # B-Ref often uses '01', '02' for players with similar URL components
    # For simplicity, we'll try '01'. Robust solution would try '02', '03' or use B-Ref search.
    player_url_id = f"{last_name_part}{first_name_part}01"
    url = f"https://www.basketball-reference.com/players/{last_name_part[0]}/{player_url_id}.html"
    
    stats = {}
    try:
        async with aiohttp.ClientSession() as session:
            logger.debug(f"ASYNC BREF: Requesting URL: {url}")
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as response: # Shorter timeout for scraping
                if response.status != 200:
                    logger.warning(f"ASYNC BREF: Player page not found on B-Ref (Status {response.status}): {player_name} ({url})")
                    return None, f"Player page not found on Basketball-Reference for '{player_name}' (Status: {response.status})."
                html = await response.text()

        soup = BeautifulSoup(html, "html.parser")
        
        # Find the 'Advanced' table. Sometimes it's within a comment if JS renders it.
        # Look for a div that might contain the table if it's commented out
        commented_out_div = soup.find('div', class_='table_container', id='div_advanced')
        adv_table_html = None
        if commented_out_div:
            comment = commented_out_div.find(string=lambda text: isinstance(text, BeautifulSoup.Comment))
            if comment:
                adv_table_html = BeautifulSoup(comment, 'html.parser').find("table", id="advanced")
        
        if not adv_table_html: # Fallback to direct find if not in comment
            adv_table_html = soup.find("table", id="advanced")

        if not adv_table_html or not hasattr(adv_table_html, 'tbody'):
            logger.warning(f"ASYNC BREF: Advanced stats table not found or no tbody for '{player_name}'.")
            return None, f"Advanced stats table not found on B-Ref page for '{player_name}'."

        # Determine which row to get (latest or specific season)
        target_row = None
        season_str_bref = f"{season_year_end-1}-{str(season_year_end)[-2:]}" if season_year_end else None

        for row in adv_table_html.tbody.find_all("tr"):
            if "thead" in row.get("class", []): continue # Skip header rows within tbody

            th_season = row.find("th", {"data-stat": "season"})
            if not th_season or not th_season.a: continue # Skip rows without a season link

            row_season_text = th_season.a.text.strip()

            if season_str_bref: # Specific season requested
                if row_season_text == season_str_bref:
                    target_row = row
                    break
            else: # Latest season (last row that is not a career total row)
                # B-Ref often has "Career" or "X seasons" as the last data-like row, skip those for "latest season"
                if "Career" not in th_season.text and "season" not in th_season.text.lower().split()[1:]: # crude check
                     target_row = row # Keep updating to get the last valid season row

        if not target_row:
            msg = f"Specified season {season_str_bref} not found." if season_str_bref else "No valid season data found in advanced table."
            logger.warning(f"ASYNC BREF: {msg} for '{player_name}'.")
            return None, f"{msg} for '{player_name}' on B-Ref."

        # Extract stats from the target row
        stats_to_extract = {"PER": "per", "TS%": "ts_pct", "USG%": "usg_pct", "WS": "ws", "BPM": "bpm"}
        extracted_stats = {}
        for stat_name, stat_key in stats_to_extract.items():
            cell = target_row.find("td", {"data-stat": stat_key})
            extracted_stats[stat_name] = cell.text.strip() if cell and cell.text.strip() != "" else "N/A"
        
        if not any(val != "N/A" for val in extracted_stats.values()): # If all are N/A
             return None, f"No advanced stats values found for '{player_name}' in the selected row on B-Ref."

        logger.info(f"ASYNC BREF: Successfully scraped advanced stats for '{player_name}': {extracted_stats}")
        return extracted_stats, None

    except asyncio.TimeoutError:
        logger.error(f"ASYNC BREF: Timeout fetching B-Ref page for '{player_name}'.")
        return None, f"Timeout connecting to Basketball-Reference for '{player_name}'."
    except Exception as e:
        logger.exception(f"ASYNC BREF: Error scraping B-Ref for '{player_name}':", exc_info=True)
        return None, f"Error scraping Basketball-Reference for '{player_name}'."