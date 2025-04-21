# helpers/nba_helper.py
import logging
from functools import lru_cache
import pandas as pd
from fuzzywuzzy import process, fuzz # Using token_set_ratio

# Import specific NBA API modules needed
from nba_api.stats.static import teams, players
from nba_api.stats.endpoints import (
    commonplayerinfo, playerprofilev2, leaguedashteamstats,
    scoreboardv2, leaguestandingsv3, teamgamelog, 
    commonteamroster, leaguedashplayerstats

)
# Import constants using relative import
from .constants import (
    NBA_API_TIMEOUT, FUZZY_MATCH_THRESHOLD, PLAYER_HEADSHOT_URL
    # Import other constants as needed by specific functions
)
import aiohttp
from bs4 import BeautifulSoup
import re
from nba_api.stats.endpoints import teamgamelog
from .constants import NBA_API_TIMEOUT
# DO NOT import embed_builder here

logger = logging.getLogger(__name__)

# --- Caching Wrappers ---
@lru_cache(maxsize=1)
def get_all_nba_teams() -> list:
    """Cached fetch for all NBA teams static data."""
    logger.debug("Fetching all NBA teams from API (stats.nba.com).")
    try:
        return teams.get_teams()
    except Exception as e:
        logger.exception("Failed to fetch NBA teams static list:", exc_info=e)
        return []

@lru_cache(maxsize=1)
def get_all_nba_players() -> list:
    """Cached fetch for active NBA players static data."""
    logger.debug("Fetching all active NBA players from API (stats.nba.com).")
    try:
        # Consider get_players() for all players if needed
        return players.get_active_players()
    except Exception as e:
        logger.exception("Failed to fetch NBA players static list:", exc_info=e)
        return []

# --- ID Finders with Fuzzy Matching (For nba_api data) ---
def find_team_by_name_or_abbr(team_query: str) -> dict | None:
    """Finds the nba_api team dict by name/abbr using fuzzy matching."""
    all_teams = get_all_nba_teams()
    if not all_teams:
        return None
    choices = {}
    for t in all_teams:
        choices[t['full_name'].lower()] = t
        choices[t['abbreviation'].lower()] = t
        choices[t['nickname'].lower()] = t
    best_match = process.extractOne(
        team_query.lower(), choices.keys(),
        scorer=fuzz.token_set_ratio, score_cutoff=FUZZY_MATCH_THRESHOLD
    )
    if best_match:
        matched_key, score = best_match
        logger.info(f"Fuzzy match for nba_api team '{team_query}' -> '{matched_key}' (Score: {score})")
        return choices[matched_key]
    logger.warning(f"Could not find nba_api team match for query: '{team_query}'")
    return None

def find_player(player_query: str) -> dict | None:
    """Finds the best active player match dict using fuzzy matching."""
    all_players = get_all_nba_players()
    if not all_players: return None
    choices = {p['full_name'].lower(): p for p in all_players}
    best_match = process.extractOne(
        player_query.lower(), choices.keys(),
        scorer=fuzz.token_set_ratio, score_cutoff=FUZZY_MATCH_THRESHOLD
    )
    if best_match:
        matched_key, score = best_match
        logger.info(f"Fuzzy match for player '{player_query}' -> '{matched_key}' (Score: {score})")
        return choices[matched_key]
    logger.warning(f"Could not find player match for query: '{player_query}'")
    return None

@lru_cache(maxsize=30)
def find_team_by_id(team_id: int) -> dict | None:
    """Finds team static data by ID (cached)."""
    all_teams = get_all_nba_teams()
    for team in all_teams:
        if team['id'] == team_id:
            return team
    return None

# --- API Data Fetching Functions (Using nba_api) ---

async def get_team_season_stats(team_id: int) -> dict | None:
    """Fetches detailed team season stats using nba_api (LeagueDashTeamStats)."""
    logger.info(f"Fetching nba_api team season stats for ID: {team_id}")
    if not isinstance(team_id, int):
        logger.error(f"Invalid team_id type for get_team_season_stats: {type(team_id)}")
        return {"error": "Internal: Invalid Team ID type."}
    try:
        stats_endpoint = leaguedashteamstats.LeagueDashTeamStats(
            per_mode_detailed='PerGame', team_id_nullable=team_id,
            season_type_all_star='Regular Season', timeout=NBA_API_TIMEOUT
        )
        stats_df = stats_endpoint.get_data_frames()[0]
        team_stats_df = stats_df[stats_df['TEAM_ID'] == team_id]
        if not team_stats_df.empty:
            stats_dict = team_stats_df.iloc[0].to_dict()
            if 'W' in stats_dict and 'L' in stats_dict and 'W_PCT' not in stats_dict:
                total_games = stats_dict['W'] + stats_dict['L']
                stats_dict['W_PCT'] = (stats_dict['W'] / total_games) if total_games > 0 else 0.0
            logger.info(f"Successfully fetched nba_api stats for team ID {team_id}")
            return stats_dict
        else:
            logger.warning(f"LeagueDashTeamStats returned no data for team ID {team_id}")
            return None
    except Exception as e:
        logger.exception(f"Error fetching nba_api team stats for ID {team_id}:", exc_info=e)
        return {"error": f"API error fetching stats (stats.nba.com) for team {team_id}."}

async def fetch_player_bio(player_name: str) -> dict:
    """Finds player and fetches bio using CommonPlayerInfo (nba_api)."""
    logger.info(f"Fetching nba_api player bio for: {player_name}")
    player_static_data = find_player(player_name)
    if not player_static_data: return {"error": f"Player '{player_name}' not found via stats.nba.com."}
    player_id = player_static_data['id']
    try:
        info_endpoint = commonplayerinfo.CommonPlayerInfo(player_id=player_id, timeout=NBA_API_TIMEOUT)
        info_df = info_endpoint.common_player_info.get_data_frame()
        if not info_df.empty:
            bio_data = info_df.iloc[0].to_dict()
            # Augment with necessary details
            bio_data['id'] = player_id
            bio_data['full_name'] = bio_data.get('DISPLAY_FIRST_LAST', player_static_data['full_name'])
            bio_data['headshot_url'] = PLAYER_HEADSHOT_URL.format(player_id=player_id)
            bio_data['team'] = f"{bio_data.get('TEAM_CITY', '')} {bio_data.get('TEAM_NAME', '')} ({bio_data.get('TEAM_ABBREVIATION', 'N/A')})".strip()
            bio_data['team_abbreviation'] = bio_data.get('TEAM_ABBREVIATION', 'N/A')
            bio_data['position'] = bio_data.get('POSITION', 'N/A')
            bio_data['height'] = bio_data.get('HEIGHT', 'N/A')
            bio_data['weight'] = bio_data.get('WEIGHT', 'N/A')
            bio_data['jersey_number'] = bio_data.get('JERSEY', 'N/A')
            bio_data['draft_year'] = bio_data.get('DRAFT_YEAR', 'N/A')
            bio_data['draft_round'] = bio_data.get('DRAFT_ROUND', 'N/A')
            bio_data['draft_number'] = bio_data.get('DRAFT_NUMBER', 'N/A')
            bio_data['country'] = bio_data.get('COUNTRY', 'N/A')
            logger.info(f"Successfully fetched bio for {bio_data['full_name']} ({player_id})")
            return bio_data
        else:
            logger.warning(f"CommonPlayerInfo (nba_api) empty for {player_id}.")
            return {"error": f"Could not fetch detailed bio for {player_static_data['full_name']}."}
    except Exception as e:
        logger.exception(f"Error fetching CommonPlayerInfo (nba_api) ID {player_id}:", exc_info=e)
        return {"error": f"API error fetching bio ({player_static_data.get('full_name','?')})"}

async def fetch_player_stats(player_id: int) -> dict:
    """Fetches player PerGame stats for latest regular season (nba_api)."""
    logger.info(f"Fetching player stats (nba_api) for ID: {player_id}")
    if not isinstance(player_id, int): return {"error": f"Internal: Invalid Player ID type."}
    try:
        profile_endpoint = playerprofilev2.PlayerProfileV2(player_id=player_id, per_mode36='PerGame', timeout=NBA_API_TIMEOUT)
        stats_df = profile_endpoint.season_totals_regular_season.get_data_frame()
        if not stats_df.empty:
            stats_dict = stats_df.iloc[-1].to_dict()
            logger.info(f"Successfully fetched nba_api stats for player ID {player_id}, Season: {stats_dict.get('SEASON_ID')}")
            return stats_dict
        else:
            logger.warning(f"PlayerProfileV2 (nba_api) no regular season stats for {player_id}")
            return {"error": "No regular season stats found via stats.nba.com."}
    except Exception as e:
        logger.exception(f"Error fetching PlayerProfileV2 (nba_api) for ID {player_id}:", exc_info=e)
        return {"error": f"API error fetching player stats (ID {player_id})."}
    
async def fetch_advanced_stats_bref(player_name: str) -> dict:
    """Fetches PER, WS, and BPM from Basketball-Reference for a player."""
    try:
        # Format player name to match Basketball-Reference URL pattern
        name_parts = player_name.lower().split()
        if len(name_parts) < 2:
            return {"error": "Player name must include first and last name."}
        first, last = name_parts[0], name_parts[1]
        player_code = f"{last[:5]}{first[:2]}01"

        url = f"https://www.basketball-reference.com/players/{last[0]}/{player_code}.html"

        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                if response.status != 200:
                    return {"error": f"Player page not found on Basketball-Reference: {player_name}"}
                html = await response.text()

        soup = BeautifulSoup(html, "html.parser")
        adv_table = soup.find("table", {"id": "advanced"})
        if not adv_table:
            return {"error": "Advanced stats table not found."}

        latest_row = adv_table.tbody.find_all("tr")[-1]
        if "class" in latest_row.attrs and "thead" in latest_row["class"]:
            latest_row = adv_table.tbody.find_all("tr")[-2]

        stats = {
            "PER": latest_row.find("td", {"data-stat": "per"}).text.strip(),
            "WS": latest_row.find("td", {"data-stat": "ws"}).text.strip(),
            "BPM": latest_row.find("td", {"data-stat": "bpm"}).text.strip(),
        }
        return stats
    except Exception as e:
        logger.exception("Failed to fetch advanced stats:", exc_info=e)
        return {"error": "Exception occurred while scraping Basketball-Reference."}

async def get_todays_games() -> dict | None:
    """Fetches today's scoreboard data (nba_api)."""
    logger.info("Fetching today's games (nba_api)")
    try:
        board = scoreboardv2.ScoreboardV2(timeout=NBA_API_TIMEOUT)
        # Get DataFrames, return None if empty
        headers_df = board.game_header.get_data_frame()
        scores_df = board.line_score.get_data_frame()
        series_df = board.series_standings.get_data_frame() # Optional playoff info
        return {
            "headers": headers_df if not headers_df.empty else None,
            "scores": scores_df if not scores_df.empty else None,
            "series": series_df if not series_df.empty else None
        }
    except Exception as e:
        logger.exception("Error fetching today's games scoreboard (nba_api):", exc_info=e)
        return None

# Assuming necessary imports are present:
import logging
import pandas as pd
from nba_api.stats.endpoints import leaguestandingsv3
# Assuming NBA_API_TIMEOUT is defined elsewhere (e.g., in constants)
# from helpers.constants import NBA_API_TIMEOUT

logger = logging.getLogger(__name__)

# --- Define constants if not imported ---
# Placeholder if constants not imported
NBA_API_TIMEOUT = 20
# ------------------------------------

async def get_season_standings() -> dict[str, pd.DataFrame] | None:
    """
    Fetches current regular season standings using nba_api's LeagueStandingsV3.

    Returns:
        A dictionary containing 'East' and 'West' DataFrames, or None on error/no data.
    """
    logger.info("Fetching current NBA season standings (nba_api)...")
    try:
        standings_endpoint = leaguestandingsv3.LeagueStandingsV3(
            season_type='Regular Season',
            timeout=NBA_API_TIMEOUT # Use the defined timeout
        )

        # --- Call get_data_frames() only ONCE ---
        dataframes = standings_endpoint.get_data_frames()

        # --- Validate the result ---
        # 1. Check if the result is a list and has at least one element
        if not dataframes or not isinstance(dataframes, list) or len(dataframes) == 0:
            logger.warning("LeagueStandingsV3 (nba_api) did not return a valid list of DataFrames.")
            return None

        # 2. Get the first DataFrame
        standings_df = dataframes[0]

        # 3. Check if it's actually a DataFrame and not empty
        if not isinstance(standings_df, pd.DataFrame) or standings_df.empty:
            logger.warning("LeagueStandingsV3 (nba_api) returned an empty or invalid DataFrame.")
            return None

        # --- Process the valid DataFrame ---
        # Ensure the 'Conference' column exists before filtering
        if 'Conference' not in standings_df.columns:
            logger.error("Standings DataFrame is missing the required 'Conference' column.")
            return None

        east_df = standings_df[standings_df['Conference'] == 'East'].copy()
        west_df = standings_df[standings_df['Conference'] == 'West'].copy()

        # Optional sorting (example: by Conference Rank)
        # east_df = east_df.sort_values(by='ConferenceRank')
        # west_df = west_df.sort_values(by='ConferenceRank')

        logger.info(f"Successfully fetched standings. East: {len(east_df)}, West: {len(west_df)} teams.")
        return {'East': east_df, 'West': west_df}

    except Exception as e:
        # Log the full exception details
        logger.exception("Error fetching league standings (nba_api):", exc_info=e)
        return None

async def get_team_game_log(team_id: int, num_games: int = 5) -> pd.DataFrame | None:
    """Fetches the game log for a team (last N games)."""
    logger.info(f"Fetching game log (last {num_games}) for team ID: {team_id}")
    if not isinstance(team_id, int):
        logger.error(f"Invalid team_id type for get_team_game_log: {type(team_id)}")
        return None # Return None on bad input

    try:
        # Fetch Regular Season games first
        log_endpoint = teamgamelog.TeamGameLog(
            team_id=team_id,
            season_type_all_star='Regular Season', # Prioritize regular season
            timeout=NBA_API_TIMEOUT
        )
        log_df = log_endpoint.get_data_frames()[0]

        # TODO: Optionally fetch Playoff games if Regular Season log is short?

        if not log_df.empty:
            # Games are typically ordered newest first in the API response
            logger.info(f"Successfully fetched game log for team ID {team_id}. Found {len(log_df)} games.")
            return log_df.head(num_games) # Return the most recent N games
        else:
            logger.warning(f"TeamGameLog returned empty data for team ID {team_id}")
            return None
    except Exception as e:
        logger.exception(f"Error fetching team game log for ID {team_id}:", exc_info=e)
        # Return None to indicate failure
        return None

# NEW Function to get roster and basic player stats
async def get_team_roster_and_player_stats(team_id: int, season: str) -> list | None:
    """
    Fetches team roster and basic player stats (like PPG, EFF) for a given season.

    Args:
        team_id: The ID of the team.
        season: The season string (e.g., "2023-24").

    Returns:
        A list of player dictionaries, each containing player info and key stats,
        sorted by a metric (e.g., PPG), or None on failure.
    """
    logger.info(f"Fetching roster and player stats for team ID {team_id}, season {season}")
    if not isinstance(team_id, int):
         logger.error("Invalid team_id type provided.")
         return None

    try:
        # Method 1: LeagueDashPlayerStats (often has common stats like PPG, EFF for all players)
        # This is usually more efficient than fetching player by player.
        player_stats_endpoint = leaguedashplayerstats.LeagueDashPlayerStats(
             team_id_nullable=team_id,
             season=season,
             per_mode_detailed='PerGame',
             season_type_all_star='Regular Season', # Adjust if needed
             timeout=NBA_API_TIMEOUT * 2 # Increase timeout slightly potentially
        )
        player_stats_df = player_stats_endpoint.get_data_frames()[0]

        if not player_stats_df.empty:
             logger.info(f"Fetched {len(player_stats_df)} players' stats via LeagueDashPlayerStats.")
             # Select relevant columns (adjust as needed based on the endpoint)
             relevant_cols = ['PLAYER_ID', 'PLAYER_NAME', 'TEAM_ABBREVIATION', 'GP', 'MIN', 'PTS', 'REB', 'AST', 'STL', 'BLK', 'EFF']
             # Filter DF for existing columns only
             existing_cols = [col for col in relevant_cols if col in player_stats_df.columns]
             roster_stats = player_stats_df[existing_cols].copy()

             # Sort by EFF or PTS to identify "stars" easily
             sort_key = 'PTS' if 'PTS' in roster_stats.columns else ('EFF' if 'EFF' in roster_stats.columns else None)
             if sort_key:
                  roster_stats.sort_values(by=sort_key, ascending=False, inplace=True)

             # Convert DataFrame to list of dictionaries
             return roster_stats.to_dict('records')

        # Method 2: Fallback using CommonTeamRoster (less efficient if stats needed for all)
        # This only gives basic player info, would require separate stats calls per player
        else:
            logger.warning("LeagueDashPlayerStats returned no data, trying CommonTeamRoster (basic info only).")
            roster_endpoint = commonteamroster.CommonTeamRoster(team_id=team_id, season=season, timeout=NBA_API_TIMEOUT)
            roster_df = roster_endpoint.common_team_roster.get_data_frame()
            if not roster_df.empty:
                logger.info(f"Fetched basic roster info for {len(roster_df)} players via CommonTeamRoster.")
                 # Return simplified data if only names/IDs needed
                return roster_df[['PLAYER_ID', 'PLAYER', 'POSITION']].rename(columns={'PLAYER':'PLAYER_NAME'}).to_dict('records')
            else:
                logger.warning(f"Failed to fetch roster/player stats for team {team_id} using both methods.")
                return None

    except Exception as e:
        logger.exception(f"Error fetching team roster/player stats for ID {team_id}:", exc_info=e)
        return None