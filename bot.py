# bot.py
# Core Python modules
import platform
from datetime import datetime, timezone # Standard library timezone
import os
import asyncio
import logging
import json # For logging raw data

# Third-party libraries
import discord
from discord.ext import commands
import pandas as pd
# import numpy as np # Not directly used in this file
import pytz # Still used for specific timezone needs if API gives non-UTC aware times
from dotenv import load_dotenv

# NBA API modules
from nba_api.stats.static import teams, players
from nba_api.stats.static import players as nba_static_players
from nba_api.stats.endpoints import (
    teamgamelog,
    leaguegamefinder,
    TeamYearByYearStats,
    commonteamroster,
    commonplayerinfo,
    playerprofilev2, # Consider if still needed or if PlayerDashboard covers all
    teamdashboardbygeneralsplits
)
from nba_api.live.nba.endpoints import scoreboard as live_scoreboard

# --- SETUP LOGGING ---
# Do this ONCE at the top
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s:%(levelname)s:%(name)s: %(message)s')
logger = logging.getLogger(__name__) # Get the logger for this module
# Reduce library noise
logging.getLogger('discord').setLevel(logging.INFO)
logging.getLogger('nba_api').setLevel(logging.INFO)

# --- UTILITY FUNCTIONS FOR SEASON CALCULATION ---
# These can be top-level functions or static methods if preferred
def _calculate_current_season_year() -> str:
    """Determines the current NBA season string (e.g., 2023-24)."""
    now = datetime.now()
    current_year = now.year if now.month >= 10 else now.year - 1
    return f"{current_year}-{str(current_year + 1)[-2:]}"

def _calculate_previous_season_year(current_season_str: str) -> str:
    """Determines the previous NBA season string based on the current season."""
    try:
        current_season_start_year = int(current_season_str.split('-')[0])
        prev_year = current_season_start_year - 1
        return f"{prev_year}-{str(current_season_start_year)[-2:]}"
    except (ValueError, IndexError, TypeError) as e:
        logger.error(
            f"Could not parse current season '{current_season_str}' to determine previous season: {e}. Defaulting."
        )
        now = datetime.now()
        current_year = now.year if now.month >= 10 else now.year - 1
        prev_default_year = current_year - 1
        return f"{prev_default_year}-{str(current_year)[-2:]}"

# --- NBAStatsBot Class DEFINITION ---
class NBAStatsBot(commands.Bot):
    def __init__(self, command_prefix, intents, **kwargs): # Added command_prefix and intents to signature
        super().__init__(command_prefix=command_prefix, intents=intents, **kwargs) # Pass them to super

        current_season = _calculate_current_season_year()
        previous_season = _calculate_previous_season_year(current_season)

        self.config = {
            "CURRENT_SEASON": current_season,
            "PREVIOUS_SEASON": previous_season,
            "WEIGHT_CURRENT": 0.70,
            "WEIGHT_PREVIOUS": 0.30,
            "DEFAULT_AVG_PPG": 112.0,
            "NBA_LOGO_URL": "https://cdn.nba.com/logos/nba/nba-logoman-75-word_white.svg",
            "PLAYER_HEADSHOT_URL_TEMPLATE": "https://cdn.nba.com/headshots/nba/latest/1040x760/{player_id}.png",
            "TEAM_LOGO_URL_TEMPLATE": "https://cdn.nba.com/logos/nba/{team_id}/primary/L/logo.svg",
            "DEFAULT_STREAMING_URL": "https://www.twitch.tv/nba",
            "API_DATETIME_FORMAT": "%Y-%m-%dT%H:%M:%SZ",
            "API_TIMEOUT_SECONDS": 20,
        }
        logger.info(f"Determined Seasons: Current={self.config['CURRENT_SEASON']}, Previous={self.config['PREVIOUS_SEASON']}")

        # Blocking calls for initial data load.
        # Consider asyncio.to_thread if startup is slow, but for now this is fine in __init__.
        self.nba_data: dict = self._load_nba_data()
        self.player_data: dict = self._load_player_data()
        # Ensure helper methods are defined within this class or correctly referenced if static/external

    # --- DATA LOADING METHODS (Blocking, called during __init__) ---
    def _load_nba_data(self) -> dict:
        """Fetches and prepares NBA team data."""
        nba_data = self._initialize_empty_nba_data()
        try:
            # This is a blocking synchronous call from nba_api
            nba_teams_list = teams.get_teams()
            if isinstance(nba_teams_list, list) and nba_teams_list:
                nba_data['teams_list'] = nba_teams_list
                # Create a combined map for easier lookup
                combined_map = {}
                for team in nba_teams_list:
                    combined_map[str(team['id'])] = team
                    combined_map[team['full_name'].lower()] = team
                    combined_map[team['nickname'].lower()] = team
                    combined_map[team['abbreviation'].lower()] = team
                nba_data['combined_map'] = combined_map
                logger.info(f"Successfully loaded data for {len(nba_teams_list)} NBA teams.")
            else:
                logger.error("NBA teams data from API is empty or not a list.")
        except Exception as e:
            logger.critical(f"Fatal Error: Could not fetch NBA teams list: {e}", exc_info=True)
        return nba_data

    def _initialize_empty_nba_data(self) -> dict:
        return {'teams_list': [], 'combined_map': {}}

    def _load_player_data(self) -> dict:
        """Fetches basic active player data."""
        player_dict = {}
        try:
            # This is a blocking synchronous call
            active_players = players.get_active_players()
            if isinstance(active_players, list) and active_players:
                for p in active_players:
                    if p.get('full_name'): # Ensure full_name exists
                        player_dict[p['full_name'].lower()] = p
                    player_dict[str(p['id'])] = p # Allow lookup by ID string
                logger.info(f"Successfully loaded data for {len(active_players)} active players.")
            else:
                logger.error("Active players data from API is empty or not a list.")
        except Exception as e:
            logger.error(f"Could not fetch active player list: {e}", exc_info=True)
        return player_dict

    # --- INTERNAL HELPER METHODS (used by cogs via self.bot._method_name) ---
    def _get_team_data_by_identifier(self, identifier: str | int) -> dict | None:
        identifier_lower = str(identifier).lower()
        return self.nba_data.get('combined_map', {}).get(identifier_lower)

    def _get_team_abbreviation(self, identifier: str | int) -> str | None:
        team_data = self._get_team_data_by_identifier(identifier)
        return team_data['abbreviation'] if team_data else None

    def _get_team_id(self, identifier: str | int) -> int | None:
        team_data = self._get_team_data_by_identifier(identifier)
        return team_data['id'] if team_data else None

    def _get_team_full_name(self, identifier: str | int) -> str | None:
        team_data = self._get_team_data_by_identifier(identifier)
        return team_data['full_name'] if team_data else None

    def _get_team_logo_url(self, identifier: str | int) -> str | None:
        team_id = self._get_team_id(identifier)
        logo_url_template = self.config.get('TEAM_LOGO_URL_TEMPLATE')
        return logo_url_template.format(team_id=team_id) if team_id and logo_url_template else None

    def _get_player_headshot_url(self, player_id: int | str) -> str | None:
        if not player_id: return None
        try:
            player_id_str = str(player_id)
            url_template = self.config.get('PLAYER_HEADSHOT_URL_TEMPLATE')
            return url_template.format(player_id=player_id_str) if url_template else None
        except (KeyError, TypeError) as e:
            logger.error(f"Could not format player headshot URL for ID: {player_id}: {e}")
            return None

    def _find_player(self, name_query: str) -> dict | None:
        """Finds a player by name (preloaded cache first) or ID, then queries API if not found."""
        query_lower = name_query.lower()

        player_info = self.player_data.get(query_lower) # Check full name (lower)
        if player_info: return player_info
        if name_query.isdigit(): # Check if query is an ID (string)
            player_info_by_id = self.player_data.get(name_query)
            if player_info_by_id: return player_info_by_id
        
        # If not in cache, query API (this is a blocking call, use in cog with asyncio.to_thread)
        # For direct use in bot._find_player, it remains blocking if called from sync context.
        # Cogs should use: player_info = await asyncio.to_thread(self.bot._find_player, query)
        logger.info(f"Player '{name_query}' not in preload, querying API (blocking call)...")
        try:
            # nba_static_players.find_players_by_full_name is synchronous
            found_api_players = nba_static_players.find_players_by_full_name(name_query)
            if found_api_players:
                logger.info(f"API found players for '{name_query}'. Returning first match.")
                # Optionally add to self.player_data cache here if desired
                # self.player_data[found_api_players[0]['full_name'].lower()] = found_api_players[0]
                # self.player_data[str(found_api_players[0]['id'])] = found_api_players[0]
                return found_api_players[0]
            else:
                logger.warning(f"API found no players matching '{name_query}'.")
        except Exception as e:
            logger.error(f"API error in _find_player for '{name_query}': {e}", exc_info=True)
        return None

    # Add other internal helper methods like _get_todays_nba_games, _convert_to_epoch,
    # _get_recent_form, _get_season_ppg here.
    # Ensure they use self.config for timeouts, etc.
    # And if they make blocking API calls (like nba-api endpoints), cogs should call them via asyncio.to_thread.
    def _get_todays_nba_games(self) -> list | None: # This uses nba_api.live which might be async-friendly or need to_thread
        """Fetches live scoreboard data."""
        try:
            logger.debug("Fetching live scoreboard data...")
            # live_scoreboard.ScoreBoard might be blocking or have its own async mechanisms.
            # If it's blocking:
            # In a cog: games = await asyncio.to_thread(self.bot._get_todays_nba_games)
            # For direct call here (less ideal if called from async context without to_thread):
            board = live_scoreboard.ScoreBoard(timeout=self.config.get("API_TIMEOUT_SECONDS"))
            response_data = board.get_dict()
            games = response_data.get('scoreboard', {}).get('games', [])
            logger.debug(f"Fetched {len(games)} games from live scoreboard.")
            return games
        except Exception as e:
            logger.error(f"Error fetching today's games from live scoreboard: {e}", exc_info=True)
            return None

    def _convert_to_epoch(self, date_time_str: str) -> int | None:
        if not date_time_str: return None
        try:
            api_format = self.config.get("API_DATETIME_FORMAT", "%Y-%m-%dT%H:%M:%SZ")
            dt_obj_naive = datetime.strptime(date_time_str, api_format)
            dt_obj_utc = dt_obj_naive.replace(tzinfo=timezone.utc)
            return int(dt_obj_utc.timestamp())
        except (ValueError, TypeError) as e:
            logger.warning(f"Error converting time string '{date_time_str}' to epoch: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error converting time string '{date_time_str}' to epoch: {e}", exc_info=True)
            return None

    def _get_recent_form(self, team_id: int, season: str | None = None) -> tuple[float, str, str]:
        # This method involves blocking API calls (teamgamelog)
        # Cogs should call: await asyncio.to_thread(self.bot._get_recent_form, team_id, season)
        if not team_id: return 0.0, "N/A", "N/A"
        effective_season = season if season is not None else self.config.get('CURRENT_SEASON')
        # ... (rest of your _get_recent_form logic) ...
        # Make sure to use self.config.get("API_TIMEOUT_SECONDS") in teamgamelog call
        # Simplified example of one call, ensure all are wrapped in try-except
        try:
            log = teamgamelog.TeamGameLog(
                team_id=team_id, season=effective_season,
                timeout=self.config.get("API_TIMEOUT_SECONDS")
            )
            team_log_df = log.get_data_frames()[0]
            # ... (process df) ...
            # Placeholder return
            if not team_log_df.empty:
                last_5 = team_log_df.sort_values(by='GAME_DATE', ascending=False).head(5)
                last_5_wl = last_5['WL'].dropna()
                if not last_5_wl.empty:
                    wins = (last_5_wl == 'W').sum()
                    form_str = ''.join(['✅' if wl == 'W' else '❌' for wl in last_5_wl])
                    win_pct = wins / len(last_5_wl)
                    return win_pct, form_str, effective_season
        except Exception as e:
             logger.error(f"Error in _get_recent_form for team {team_id}, S:{effective_season}: {e}")
        return 0.0, "N/A", "N/A" # Fallback

    def _get_season_ppg(self, team_id: int, season: str) -> float | None:
        # This method involves blocking API calls (TeamYearByYearStats)
        # Cogs should call: await asyncio.to_thread(self.bot._get_season_ppg, team_id, season)
        if not team_id or not season: return None
        # ... (rest of your _get_season_ppg logic) ...
        # Make sure to use self.config.get("API_TIMEOUT_SECONDS")
        try:
            stats = TeamYearByYearStats(
                team_id=team_id, per_mode_simple='PerGame',
                timeout=self.config.get("API_TIMEOUT_SECONDS")
            )
            stats_df = stats.get_data_frames()[0]
            season_stats_row = stats_df[stats_df['YEAR'] == season]
            if not season_stats_row.empty:
                ppg_val = season_stats_row.iloc[0]['PTS']
                if pd.notna(ppg_val): return float(ppg_val)
        except Exception as e:
            logger.error(f"Error in _get_season_ppg for team {team_id}, S:{season}: {e}")
        return None


    # --- Bot Setup and Events ---
    async def load_extensions(self):
        cogs_dir = os.path.join(os.path.dirname(__file__), 'cogs')
        if not os.path.isdir(cogs_dir):
            logger.warning(f"Cogs directory '{cogs_dir}' not found. No cogs will be loaded.")
            return
        cog_files_to_load = [ # Explicit list is safer
            'general.py', 'schedule.py', 'team_stats.py',
            'player_stats.py', 'injuries.py', 'compare_teams.py', 
            'season.py', 'ml_cog.py', 'type_season.py',
            'ping.py'
        ]
        loaded_cogs_count = 0
        for filename in cog_files_to_load:
            cog_module_name = f'cogs.{filename[:-3]}'
            try:
                if cog_module_name not in self.extensions:
                    await self.load_extension(cog_module_name)
                    logger.info(f'Successfully loaded cog: {cog_module_name}')
                else:
                    logger.info(f'Cog already loaded: {cog_module_name}')
                loaded_cogs_count += 1
            except commands.ExtensionError as e: # Catch specific discord.py extension errors
                logger.error(f'Failed to load extension {cog_module_name}.', exc_info=True)
            except Exception as e: # Catch any other error during loading
                logger.error(f'Unexpected error loading extension {cog_module_name}.', exc_info=True)
        logger.info(f"--- Finished loading/verifying {loaded_cogs_count} cog(s) ---")

    async def setup_hook(self):
        logger.info("--- Running setup_hook ---")
        await self.load_extensions()
        if self.application_id:
            logger.info(f"Application ID: {self.application_id}. Syncing app commands...")
            try:
                synced = await self.tree.sync() # Sync globally
                # For testing: guild = discord.Object(id=YOUR_TEST_GUILD_ID); await self.tree.sync(guild=guild)
                logger.info(f"Synced {len(synced)} application command(s) globally.")
            except discord.HTTPException as e:
                logger.error(f"HTTPException during command sync: {e.status} {e.text}", exc_info=True)
            except discord.Forbidden: # Important for checking bot scopes
                 logger.error("Forbidden: Bot may lack 'applications.commands' scope or required permissions to sync commands.", exc_info=True)
            except Exception as e:
                logger.error(f"Error syncing commands: {e}", exc_info=True)
        else:
            logger.warning("Cannot sync commands - Application ID not available at setup_hook.")
        logger.info("--- setup_hook finished ---")

    async def on_ready(self):
        if not self.user:
            logger.error("on_ready event triggered, but bot.user is None!")
            return

        logger.info(f'Logged in as {self.user.name} (ID: {self.user.id})')
        logger.info(f"discord.py Version: {discord.__version__}, Python: {platform.python_version()}")
        logger.info(f"System: {platform.system()} {platform.release()}")
        logger.info('------ Bot is ready and online! ------')

        try:
            target_command_name = self.config.get("PRESENCE_COMMAND_NAME", 'today')
            app_command = self.tree.get_command(target_command_name)
            status_command_name = app_command.name if app_command else "stats"
            stream_name = f"NBA Games | /{status_command_name}"
            stream_url = self.config.get("DEFAULT_STREAMING_URL", "https://www.twitch.tv/nba")
            activity = discord.Streaming(name=stream_name, url=stream_url)
            await self.change_presence(status=discord.Status.online, activity=activity)
            logger.info(f"Presence set to: Streaming '{stream_name}'")
        except Exception as e:
            logger.error(f"Failed to set streaming presence: {e}", exc_info=True)
            try:
                fallback_activity = discord.Game(name="NBA Stats | /commands")
                await self.change_presence(status=discord.Status.online, activity=fallback_activity)
                logger.info("Set fallback 'Playing' presence.")
            except Exception as fallback_e:
                logger.error(f"Failed to set fallback presence: {fallback_e}")

# --- ENV VAR LOADING & BOT INTENTS (Define AFTER NBAStatsBot class) ---
load_dotenv()
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')

# Debugging token load
print(f".env file loaded by load_dotenv(): {load_dotenv()}") # Will re-call, but ok for debug
print(f"Raw DISCORD_TOKEN from os.getenv: '{DISCORD_TOKEN}'")
if DISCORD_TOKEN:
    print(f"Token length: {len(DISCORD_TOKEN)}")
else:
    print("ERROR: DISCORD_TOKEN not found or is empty after os.getenv!")

# Setup Intents
intents = discord.Intents.default()
intents.message_content = True # If you need to read message content for prefix commands etc.
# intents.members = True      # If you need server members intent
# intents.presences = True   # If you need presence intent

# --- BOT INSTANTIATION (AFTER class definition and intent/token setup) ---
# Provide a default command_prefix, even if primarily using slash commands.
# help_command=None is good if you have a custom /commands or help via slash.
bot = NBAStatsBot(
    command_prefix=commands.when_mentioned_or('/'), # Sensible default
    intents=intents,
    help_command=None # Disable default help for custom /commands
)

# --- MAIN EXECUTION ---
async def main():
    if not DISCORD_TOKEN: # Check token again before trying to start
        logger.critical("FATAL ERROR: DISCORD_TOKEN is not set. Bot cannot start.")
        return

    try:
        logger.info("Attempting bot login and start...")
        await bot.start(DISCORD_TOKEN)
    except discord.LoginFailure:
        logger.critical("FATAL ERROR: Invalid Discord Token. Please regenerate the token in the Discord Developer Portal and update your .env file.")
    except discord.PrivilegedIntentsRequired:
        logger.critical(
            "FATAL ERROR: Privileged Intents (e.g., Message Content, Server Members, Presence) "
            "are required but not enabled in the Discord Developer Portal AND/OR in the bot's 'intents' object. "
            "Please check both."
        )
    except Exception as e:
        logger.critical(f"An unexpected critical error occurred during bot startup or runtime: {e}", exc_info=True)

if __name__ == "__main__":
    if os.name == 'nt': # For Windows compatibility
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot shutdown initiated by KeyboardInterrupt (Ctrl+C).")
    except Exception as e:
        logger.critical(f"Critical error in __main__ execution block: {e}", exc_info=True)
    finally:
        logger.info("Bot process terminated.")