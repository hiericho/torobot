# bot.py
# Core Python modules
import platform
from datetime import datetime
import os
import asyncio
import traceback
import logging
import json # Import json for logging raw data
# Third-party libraries
import discord
from discord.ext import commands
from discord import app_commands
import pandas as pd
import numpy as np
import pytz
from dotenv import load_dotenv

# NBA API modules
from nba_api.stats.static import teams, players
from nba_api.stats.endpoints import (
    teamgamelog,
    leaguegamefinder,
    TeamYearByYearStats,
    commonteamroster,
    commonplayerinfo,  # For player details
    playerprofilev2,   # For player stats
    teamdashboardbygeneralsplits # For team stats
)
from nba_api.live.nba.endpoints import scoreboard as live_scoreboard

# --- SETUP LOGGING ---
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s:%(levelname)s:%(name)s: %(message)s') # Set level to DEBUG to see the new log
logger = logging.getLogger(__name__)
# Reduce library noise (optional)
logging.getLogger('discord').setLevel(logging.INFO) # Keep discord logs cleaner usually
logging.getLogger('nba_api').setLevel(logging.INFO) # Or WARNING

# --- LOAD ENVIRONMENT VARIABLES ---
load_dotenv()
BOT_TOKEN = os.getenv('DISCORD_TOKEN')

# --- BOT INITIALIZATION ---
intents = discord.Intents.default()
# intents.message_content = True # Uncomment if you need message content later

# --- Create a custom Bot class ---
class NBAStatsBot(commands.Bot):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # --- CONFIGURATION (Stage 1: Define without PREVIOUS_SEASON) ---
        self.config = {
            "CURRENT_SEASON": self._get_current_season_year(), # Define this first
            "WEIGHT_CURRENT": 0.70,
            "WEIGHT_PREVIOUS": 0.30,
            "DEFAULT_AVG_PPG": 112.0,
            "NBA_LOGO_URL": "https://cdn.nba.com/logos/nba/nba-logoman-75-word_white.svg",
            "PLAYER_HEADSHOT_URL": "https://cdn.nba.com/headshots/nba/latest/1040x760/{player_id}.png", # Added
            "TEAM_LOGO_URL": "https://cdn.nba.com/logos/nba/{team_id}/primary/L/logo.svg"
            # PREVIOUS_SEASON will be added in Stage 2
        }

        # --- CONFIGURATION (Stage 2: Add PREVIOUS_SEASON) ---
        # Now self.config exists, calculate and add PREVIOUS_SEASON
        self.config["PREVIOUS_SEASON"] = self._get_previous_season_year()
        logger.info(f"Determined Seasons: Current={self.config.get('CURRENT_SEASON', 'N/A')}, Previous={self.config.get('PREVIOUS_SEASON', 'N/A')}")


        # --- NBA DATA LOADING ---
        self.nba_data = self._load_nba_data()
        self.player_data = self._load_player_data()

        # --- HELPER FUNCTIONS ---
        # Assign helpers after all config and data is loaded
        self.helpers = {
            "get_team_abbreviation": self._get_team_abbreviation,
            "get_team_id": self._get_team_id,
            "get_team_full_name": self._get_team_full_name,
            "get_todays_nba_games": self._get_todays_nba_games, # This helper includes the debug log now
            "convert_to_epoch": self._convert_to_epoch,
            "get_recent_form": self._get_recent_form,
            "get_season_ppg": self._get_season_ppg,
            "find_player": self._find_player,
            "get_player_headshot_url": self._get_player_headshot_url, # Added
            "get_team_logo_url": self._get_team_logo_url,
        }

    def _get_current_season_year(self):
        """Determines the current NBA season string (e.g., 2024-25)."""
        now = datetime.now()
        # NBA season typically starts around October
        current_year = now.year if now.month >= 10 else now.year - 1
        return f"{current_year}-{str(current_year + 1)[-2:]}"

    # This helper now accesses the existing self.config['CURRENT_SEASON']
    def _get_previous_season_year(self):
        """Determines the previous NBA season string based on current."""
        try:
            current_season_str = self.config['CURRENT_SEASON']
            current_season_start_year = int(current_season_str.split('-')[0])
            prev_year = current_season_start_year - 1
            return f"{prev_year}-{str(current_season_start_year)[-2:]}"
        except (ValueError, IndexError, TypeError, KeyError) as e:
            logger.error(f"Could not parse current season from self.config to determine previous season ({e}). Defaulting.")
            now = datetime.now()
            current_year = now.year if now.month >= 10 else now.year - 1
            prev_default_year = current_year - 1
            return f"{prev_default_year}-{str(current_year)[-2:]}"


    def _load_nba_data(self):
        """Fetches and prepares NBA team data."""
        nba_data = {}
        try:
            nba_teams_list = teams.get_teams()
            if isinstance(nba_teams_list, list) and nba_teams_list:
                nba_data['teams_list'] = nba_teams_list
                nba_data['team_id_map'] = {str(team['id']): team for team in nba_teams_list}
                nba_data['team_abbr_map'] = {team['abbreviation'].lower(): team for team in nba_teams_list}
                nba_data['team_full_name_map'] = {team['full_name'].lower(): team for team in nba_teams_list}
                nba_data['team_nickname_map'] = {team['nickname'].lower(): team for team in nba_teams_list}
                combined_map = {}
                for team in nba_teams_list:
                    combined_map[team['full_name'].lower()] = team
                    combined_map[team['nickname'].lower()] = team
                    combined_map[team['abbreviation'].lower()] = team
                nba_data['combined_map'] = combined_map
                logger.info(f"Successfully loaded data for {len(nba_teams_list)} NBA teams.")
            else:
                logger.error("NBA teams data is empty or not a list.")
                nba_data = self._initialize_empty_nba_data()
        except Exception as e:
            logger.critical(f"Fatal Error: Could not fetch NBA teams list: {e}", exc_info=True)
            nba_data = self._initialize_empty_nba_data()
        return nba_data

    def _initialize_empty_nba_data(self):
        """Returns a dictionary with empty NBA team data structures."""
        return {'teams_list': [], 'team_id_map': {}, 'team_abbr_map': {}, 'team_full_name_map': {}, 'team_nickname_map': {}, 'combined_map': {}}

    def _load_player_data(self):
        """Fetches basic active player data for autocomplete."""
        player_dict = {}
        try:
            active_players = players.get_active_players()
            if isinstance(active_players, list) and active_players:
                 player_dict = {p['full_name'].lower(): p for p in active_players}
                 logger.info(f"Successfully loaded data for {len(active_players)} active players.")
            else: logger.error("Active players data is empty or not a list.")
        except Exception as e: logger.error(f"Could not fetch active player list: {e}", exc_info=True)
        return player_dict

    # --- HELPER METHOD IMPLEMENTATIONS ---
    def _get_team_data_by_identifier(self, identifier):
        identifier_lower = str(identifier).lower()
        return self.nba_data.get('combined_map', {}).get(identifier_lower)

    def _get_team_abbreviation(self, identifier):
        team_data = self._get_team_data_by_identifier(identifier)
        return team_data['abbreviation'] if team_data else None

    def _get_team_id(self, identifier):
        team_data = self._get_team_data_by_identifier(identifier)
        return team_data['id'] if team_data else None

    def _get_team_full_name(self, identifier):
        team_data = self._get_team_data_by_identifier(identifier)
        return team_data['full_name'] if team_data else None

    def _get_team_logo_url(self, identifier):
         team_id = self._get_team_id(identifier)
         return self.config.get('TEAM_LOGO_URL', '').format(team_id=team_id) if team_id and self.config.get('TEAM_LOGO_URL') else None

    def _get_player_headshot_url(self, player_id):
        if not player_id: return None
        try:
            int(player_id) # Validate it's an ID
            url_template = self.config.get('PLAYER_HEADSHOT_URL')
            return url_template.format(player_id=player_id) if url_template else None
        except (ValueError, KeyError, TypeError): logger.error(f"Could not format player headshot URL for ID: {player_id}"); return None

    def _find_player(self, name_query):
        query_lower = name_query.lower()
        player_info = self.player_data.get(query_lower) # Check preload
        if player_info: return player_info
        if name_query.isdigit(): # Check ID
             for p_info in self.player_data.values():
                  if p_info.get('id') == int(name_query): return p_info
        logger.info(f"Player '{name_query}' not in preload, querying API...")
        try:
            found_players = players.find_players_by_full_name(name_query)
            if found_players: logger.info(f"API found players for '{name_query}'"); return found_players[0]
            else: logger.warning(f"API found no players matching '{name_query}'.")
        except Exception as e: logger.error(f"API error finding player '{name_query}': {e}", exc_info=True)
        return None

    # --- MODIFIED HELPER WITH DEBUG LOGGING ---
    def _get_todays_nba_games(self):
        """Fetches live scoreboard data and logs a sample."""
        try:
            logger.debug("Fetching live scoreboard data...")
            board = live_scoreboard.ScoreBoard(timeout=15) # Added timeout
            response_data = board.get_dict()
            
            # --- TEMPORARY DEBUG LOG ---
            # Log the raw structure of the first 2 games (if they exist)
            games_sample = response_data.get('scoreboard', {}).get('games', [])[:2]
            logger.debug(f"RAW SCOREBOARD DATA (SAMPLE):\n{json.dumps(games_sample, indent=2)}")
            # --------------------------

            # Return the full list of games
            games = response_data.get('scoreboard', {}).get('games', [])
            return games
        except Exception as e:
            logger.error(f"Error fetching today's games from live scoreboard: {e}", exc_info=True)
            return None
    # --- END OF MODIFIED HELPER ---

    def _convert_to_epoch(self, date_time_str):
        try:
            dt_obj = datetime.strptime(date_time_str, "%Y-%m-%dT%H:%M:%SZ")
            # Make timezone aware (UTC) before getting timestamp
            dt_obj = dt_obj.replace(tzinfo=pytz.utc)
            return int(dt_obj.timestamp())
        except (ValueError, TypeError) as e: logger.warning(f"Error converting time string '{date_time_str}': {e}"); return None
        except Exception as e: logger.error(f"Error converting time: {e}", exc_info=True); return None

    def _get_recent_form(self, team_id, season=None):
        if not team_id: return 0.0, "N/A", "N/A" # Handle missing team_id
        if season is None: season = self.config.get('CURRENT_SEASON')
        if not season: logger.error("Season missing for get_recent_form."); return 0.0, "N/A", "N/A"

        seasons_to_try = [season]
        prev_season = self.config.get('PREVIOUS_SEASON')
        if season == self.config.get('CURRENT_SEASON') and prev_season and prev_season != season: seasons_to_try.append(prev_season)

        for s in seasons_to_try:
            try:
                team_log_df = teamgamelog.TeamGameLog(team_id=team_id, season=s, timeout=15).get_data_frames()[0] # Increased timeout
                if not team_log_df.empty:
                    last_5 = team_log_df.sort_values(by='GAME_DATE', ascending=False).head(5)
                    last_5_wl = last_5['WL'].dropna()
                    if not last_5_wl.empty:
                        wins = (last_5_wl == 'W').sum()
                        form_str = ''.join(['✅' if wl == 'W' else '❌' for wl in last_5_wl])
                        win_pct = wins / len(last_5_wl)
                        logger.info(f"Found form for {team_id} in {s}")
                        return win_pct, form_str, s
            except IndexError: logger.info(f"IndexError (no DF) fetching form for {team_id}, S:{s}")
            except Exception as e: logger.error(f"Error fetching form for {team_id} season {s}: {e}", exc_info=True)
        logger.warning(f"Could not fetch recent form for team ID {team_id}"); return 0.0, "N/A", "N/A"

    def _get_season_ppg(self, team_id, season):
        if not team_id: return None
        if not season: logger.error("Season missing for get_season_ppg."); return None
        try:
            stats_df = TeamYearByYearStats(team_id=team_id, per_mode_simple='PerGame', timeout=15).get_data_frames()[0]
            season_stats = stats_df[stats_df['YEAR'] == season]
            if not season_stats.empty:
                ppg = season_stats.iloc[0]['PTS']
                if pd.notna(ppg): logger.info(f"Found PPG {ppg:.1f} for {team_id} S:{season}"); return float(ppg)
                else: logger.warning(f"PPG is NaN for {team_id} S:{season}")
            else: logger.info(f"No row found for {team_id} S:{season} in TeamYearByYearStats")
        except IndexError: logger.warning(f"IndexError (no DF) fetching PPG for {team_id} S:{season}")
        except Exception as e: logger.error(f"Error fetching PPG for {team_id} season {season}: {e}", exc_info=True)
        logger.warning(f"Could not fetch PPG for team ID {team_id} season {season}"); return None

    # --- Bot Setup and Events ---
    async def load_extensions(self):
        cogs_dir = os.path.join(os.path.dirname(__file__), 'cogs')
        if not os.path.exists(cogs_dir): logger.warning("Cogs directory not found."); return
        cog_files = ['general.py', 'schedule.py', 'team_stats.py', 'player_stats.py', 'injuries.py', 'compare_teams.py', 'season.py']
        loaded_cogs_count = 0
        for filename in cog_files:
            filepath = os.path.join(cogs_dir, filename)
            if os.path.exists(filepath) and filename.endswith('.py') and not filename.startswith('_'):
                cog_name = f'cogs.{filename[:-3]}'
                try:
                    if cog_name not in self.extensions: await self.load_extension(cog_name); logger.info(f'Loaded cog: {cog_name}')
                    else: logger.info(f'Cog already loaded: {cog_name}')
                    loaded_cogs_count += 1
                except commands.ExtensionError as e: logger.error(f'Failed to load extension {cog_name}.', exc_info=True)
            else: logger.warning(f"Cog file not found or invalid: {filename}")
        logger.info(f"--- Finished loading/verifying {loaded_cogs_count} cog(s) ---")

    async def setup_hook(self):
        logger.info("--- Running setup_hook ---")
        await self.load_extensions()
        if self.application_id:
            logger.info(f"Application ID: {self.application_id}. Syncing commands...")
            try: synced = await self.tree.sync(); logger.info(f"Synced {len(synced)} app command(s) globally.")
            except discord.HTTPException as e: logger.error(f"HTTPException sync: {e.status} {e.text}", exc_info=True)
            except Exception as e: logger.error(f"Error syncing commands: {e}", exc_info=True)
        else: logger.error("Cannot sync commands - Application ID not set.")
        logger.info("--- setup_hook finished ---")

    async def on_ready(self):
        """Event triggered when the bot is fully ready."""
        if not self.user: # Should not happen if logged in, but safety check
            logger.error("on_ready triggered but bot.user is None!")
            return

        logger.info(f'Logged in as {self.user.name} ({self.user.id})')
        current_season = self.config.get('CURRENT_SEASON', 'N/A')
        prev_season = self.config.get('PREVIOUS_SEASON', 'N/A')
        logger.info(f"Using NBA Seasons: Current={current_season}, Previous={prev_season}")
        logger.info(f"discord.py Version: {discord.__version__}")
        logger.info(f"Python Version: {platform.python_version()}")
        logger.info(f"System: {platform.system()} {platform.release()} ({os.name})")
        logger.info('------ Bot is ready and online! ------')

        # --- Set Streaming Presence ---
        try:
            cmd = self.tree.get_command('today') # Use '/today' or '/commands' or another relevant command
            cmd_name = cmd.name if cmd else 'stats' # Fallback command name for status
            stream_name = f"NBA Games | /{cmd_name}"
            stream_url = self.config.get("DEFAULT_STREAMING_URL", "https://www.twitch.tv/nba") # Use config or fallback

            activity = discord.Streaming(name=stream_name, url=stream_url)
            await self.change_presence(status=discord.Status.online, activity=activity)
            logger.info(f"Presence set to: Streaming '{stream_name}'")
        except Exception as e:
            logger.error(f"Failed to set streaming presence: {e}", exc_info=True)
            # Fallback to simpler presence if streaming setup fails
            try:
                 activity = discord.Game(name="NBA Stats")
                 await self.change_presence(status=discord.Status.online, activity=activity)
                 logger.info("Set fallback 'Playing' presence.")
            except Exception as fallback_e:
                 logger.error(f"Failed to set fallback presence: {fallback_e}")

# Instantiate the custom bot
bot = NBAStatsBot(command_prefix='/', intents=intents, help_command=None)

# --- MAIN EXECUTION ---
async def main():
    if not BOT_TOKEN: logger.critical("FATAL ERROR: DISCORD_TOKEN not found."); return
    try: logger.info("Attempting bot login..."); await bot.start(BOT_TOKEN)
    except discord.LoginFailure: logger.critical("FATAL ERROR: Invalid Discord Token.")
    except discord.PrivilegedIntentsRequired: logger.critical("FATAL ERROR: Privileged Intents missing.")
    except Exception as e: logger.critical(f"Bot run error: {e}", exc_info=True)

if __name__ == "__main__":
    try:
        if os.name == 'nt': asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        asyncio.run(main())
    except KeyboardInterrupt: logger.info("Bot shut down manually.")
    except Exception as e: logger.critical(f"Critical error in main block: {e}", exc_info=True)