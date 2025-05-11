# /home/hiericho/torobot2/cogs/type_season.py

import discord
from discord import app_commands, Interaction
from discord.ext import commands
import pandas as pd
import numpy as np
import asyncio
import logging
from typing import List, Optional, Tuple, Dict, Any

# NBA_API imports
from nba_api.stats.static import teams as nba_static_teams
from nba_api.stats.endpoints import leaguegamefinder, leaguedashteamstats
from requests.exceptions import ReadTimeout, ConnectionError

# Use your bot's main logger or a specific one for this cog
# logger = logging.getLogger('discord') # This is the general discord.py logger
logger = logging.getLogger(__name__) # More specific to this file

# --- Helper to format season string (e.g., 2023 -> 2023-24) ---
def format_season_id(year_start: int) -> str:
    """Converts a starting year of a season to the NBA API season format (e.g., 2023 -> 2023-24)."""
    return f"{year_start}-{str(year_start+1)[-2:]}"

# --- Autocomplete function (uses real team data) ---
async def team_autocomplete(interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
    """Autocompletes team names for command arguments using live team data."""
    choices = []
    # Access the bot instance via interaction.client
    bot_instance = interaction.client

    if not hasattr(bot_instance, 'all_nba_teams_data') or not bot_instance.all_nba_teams_data:
        logger.info("Autocomplete: NBA team data not found on bot, attempting to fetch...")
        try:
            # This is a blocking call, run in a thread
            all_teams_data = await asyncio.to_thread(nba_static_teams.get_teams)
            # Cache it on the client for subsequent autocompletes in this session
            bot_instance.all_nba_teams_data = all_teams_data
            logger.info(f"Autocomplete: Successfully fetched and cached {len(all_teams_data)} NBA teams.")
        except Exception as e:
            logger.error(f"Autocomplete: Failed to fetch teams: {e}", exc_info=True)
            bot_instance.all_nba_teams_data = [] # Ensure it's an empty list on failure
            return [] # Return empty choices if fetch fails

    all_teams_data_cache = getattr(bot_instance, 'all_nba_teams_data', [])

    if current:
        for team in all_teams_data_cache:
            if (current.lower() in team['full_name'].lower() or
                current.lower() in team['abbreviation'].lower() or
                current.lower() in team['nickname'].lower() or
                current.lower() in team['city'].lower()):
                choices.append(app_commands.Choice(name=f"{team['full_name']} ({team['abbreviation']})", value=str(team['id'])))
                if len(choices) >= 25: break # Optimization: stop if we already have 25 matches
    else: # Show some initial choices if input is empty
        for i, team in enumerate(all_teams_data_cache):
            if i >= 25: break # Discord limits to 25 choices
            choices.append(app_commands.Choice(name=f"{team['full_name']} ({team['abbreviation']})", value=str(team['id'])))
    
    return choices[:25] # Ensure max 25 choices are returned


class TypeCog(commands.Cog, name="typeseason"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.api_timeout = self.bot.config.get("API_TIMEOUT_SECONDS", 20)
        
        # Team data will be loaded by team_autocomplete on first use if not present.
        # Or, you can load it in main.py's setup_hook and pass it to the cog or set it on bot.
        if not hasattr(self.bot, 'all_nba_teams_data'):
            self.bot.all_nba_teams_data = [] # Initialize as empty list
            logger.info("TypeCog initialized. NBA team data will be fetched on first autocomplete request if needed.")
        else:
            logger.info("TypeCog initialized. NBA team data already present on bot.")

    # --- Team Data Helper Methods ---
    def _get_team_info(self, team_identifier: str) -> Optional[Dict[str, Any]]:
        """Retrieves team info dictionary by ID, abbreviation, name, or nickname."""
        # Ensure data is available; autocomplete should have populated it if commands are used.
        if not hasattr(self.bot, 'all_nba_teams_data') or not self.bot.all_nba_teams_data:
            logger.warning("Team data not loaded on bot. Cannot get team info. Autocomplete might not have run yet or failed.")
            # Optionally, try a synchronous fetch here as a last resort, though not ideal in a command.
            # For now, we'll rely on autocomplete or a setup_hook load.
            return None
            
        try:
            team_id_int = int(team_identifier)
            for team in self.bot.all_nba_teams_data:
                if team['id'] == team_id_int:
                    return team
        except ValueError: # team_identifier is not an ID string
            pass

        for team in self.bot.all_nba_teams_data:
            if (team_identifier.lower() == team['abbreviation'].lower() or
                team_identifier.lower() == team['full_name'].lower() or
                team_identifier.lower() == team['nickname'].lower() or
                team_identifier.lower() == team['city'].lower()):
                return team
        logger.debug(f"Team identifier '{team_identifier}' not found in cached team data.")
        return None

    def _get_team_id(self, team_identifier: str) -> Optional[int]:
        team_info = self._get_team_info(team_identifier)
        return team_info['id'] if team_info else None

    def _get_team_full_name(self, team_id_or_identifier: str) -> Optional[str]:
        team_info = self._get_team_info(team_id_or_identifier) 
        return team_info['full_name'] if team_info else None

    def _get_team_abbreviation(self, team_id_or_identifier: str) -> Optional[str]:
        team_info = self._get_team_info(team_id_or_identifier)
        return team_info['abbreviation'] if team_info else None

    # --- Real Data Fetching Helper Methods ---
    async def _get_recent_form(self, team_id: int, num_games: int = 5) -> Tuple[Optional[float], str, Optional[str]]:
        """
        Fetches recent form (W/L string and win percentage) for a team.
        Returns: (win_pct, form_string, season_of_last_game)
        """
        try:
            finder = leaguegamefinder.LeagueGameFinder(
                team_id_nullable=team_id,
                season_type_nullable="Regular Season",
                timeout=self.api_timeout
            )
            games_df_list = await asyncio.to_thread(finder.get_data_frames)
            games_df = games_df_list[0] if games_df_list and not games_df_list[0].empty else pd.DataFrame()
            
            if games_df.empty:
                finder_playoffs = leaguegamefinder.LeagueGameFinder(
                    team_id_nullable=team_id,
                    season_type_nullable="Playoffs",
                    timeout=self.api_timeout
                )
                games_df_playoffs_list = await asyncio.to_thread(finder_playoffs.get_data_frames)
                games_df = games_df_playoffs_list[0] if games_df_playoffs_list and not games_df_playoffs_list[0].empty else pd.DataFrame()
                
                if games_df.empty:
                    logger.warning(f"No recent games found for team ID {team_id} for form calculation.")
                    return 0.0, "N/A", "N/A"

            all_games = games_df
            all_games['GAME_DATE'] = pd.to_datetime(all_games['GAME_DATE'])
            all_games_with_wl = all_games.dropna(subset=['WL'])
            recent_games = all_games_with_wl.sort_values(by='GAME_DATE', ascending=False).head(num_games)

            if recent_games.empty:
                return 0.0, "N/A", "N/A"

            form_list = recent_games['WL'].tolist()
            form_string = " ".join(form_list) # Consider "W L W W L" format or "✅❌✅✅❌"
            wins = form_list.count('W')
            win_pct = wins / len(form_list) if form_list else 0.0
            
            last_game_season_raw = recent_games.iloc[0]['SEASON_ID'] if 'SEASON_ID' in recent_games.columns and not recent_games.empty else "N/A"
            last_game_season = last_game_season_raw
            if isinstance(last_game_season_raw, str) and len(last_game_season_raw) == 5 and last_game_season_raw.startswith('2'):
                 last_game_season = format_season_id(int(last_game_season_raw[1:]))

            return round(win_pct, 3), form_string, last_game_season
        except (ReadTimeout, ConnectionError) as e:
            logger.error(f"API timeout/connection error fetching recent form for team ID {team_id}: {e}")
            return 0.0, "API Error", "N/A"
        except Exception as e:
            logger.error(f"Error fetching recent form for team ID {team_id}: {e}", exc_info=True)
            return 0.0, "Error", "N/A"

    async def _get_season_ppg(self, team_id: int, season: str, season_type_for_ppg: str = "Regular Season") -> Optional[float]:
        """Fetches average Points Per Game for a team in a specific season and type."""
        try:
            if not isinstance(season, str) or '-' not in season:
                logger.warning(f"Invalid season format for PPG: {season}. Expected YYYY-YY.")
                return self.bot.config.get('DEFAULT_AVG_PPG', 112.0)

            team_stats = leaguedashteamstats.LeagueDashTeamStats(
                team_id_nullable=team_id,
                season=season,
                season_type_all_star=season_type_for_ppg,
                timeout=self.api_timeout,
            )
            stats_df_list = await asyncio.to_thread(team_stats.get_data_frames)

            if not stats_df_list or stats_df_list[0].empty:
                logger.warning(f"No {season_type_for_ppg} stats found for team ID {team_id} in season {season}.")
                return None 

            stats_df = stats_df_list[0]
            if 'PTS' in stats_df.columns and 'GP' in stats_df.columns and pd.notna(stats_df['GP'].iloc[0]) and stats_df['GP'].iloc[0] > 0:
                ppg = stats_df['PTS'].iloc[0] / stats_df['GP'].iloc[0]
                return round(ppg, 1)
            elif 'PPG' in stats_df.columns and pd.notna(stats_df['PPG'].iloc[0]):
                 return round(stats_df['PPG'].iloc[0], 1)
            else:
                logger.warning(f"PPG or PTS/GP columns not found/valid for team ID {team_id}, season {season}, type {season_type_for_ppg}.")
                return None
        except (ReadTimeout, ConnectionError) as e:
            logger.error(f"API timeout/connection error fetching PPG for team {team_id}, season {season}: {e}")
            return None
        except Exception as e:
            logger.error(f"Error fetching PPG for team ID {team_id}, season {season}: {e}", exc_info=True)
            return None

    # --- Main Command ---
    @app_commands.command(name='typeseason', description='H2H stats & prediction for Away @ Home, by season type.')
    @app_commands.describe(
        away_team='Visiting team (name, nickname, abbreviation, or ID)',
        home_team='Home team (name, nickname, abbreviation, or ID)',
        typeseason='Filter H2H games by type (default: Regular Season).'
    )
    @app_commands.choices(typeseason=[
        app_commands.Choice(name="Regular Season", value="Regular Season"),
        app_commands.Choice(name="Playoffs", value="Playoffs"),
        app_commands.Choice(name="Pre-Season", value="Pre Season"),
        app_commands.Choice(name="Play-In Tournament", value="PlayIn"), # API value for play-in
        app_commands.Choice(name="All-Star Game", value="All Star"), # API value for All-Star
    ])
    @app_commands.autocomplete(away_team=team_autocomplete, home_team=team_autocomplete)
    async def typeseason_command(self, interaction: Interaction, away_team: str, home_team: str,
                                 # typeseason is the parameter name, so it's fine here
                                 typeseason: Optional[app_commands.Choice[str]] = None): 
        
        await interaction.response.defer(ephemeral=False)

        selected_typeseason_choice = typeseason if typeseason else app_commands.Choice(name="Regular Season", value="Regular Season")
        selected_typeseason_value = selected_typeseason_choice.value
        selected_typeseason_name = selected_typeseason_choice.name


        logger.info(f"/{interaction.command.name} invoked by {interaction.user.name}: {away_team} @ {home_team} (TypeSeason: {selected_typeseason_name})")

        try:
            current_season = self.bot.config.get('CURRENT_SEASON')
            previous_season = self.bot.config.get('PREVIOUS_SEASON')

            if not all([current_season, previous_season]):
                logger.error(f"Missing season configuration for /{interaction.command.name} command.")
                await interaction.followup.send("❗ Bot configuration error: Season data missing.", ephemeral=True)
                return

            away_id = self._get_team_id(away_team)
            home_id = self._get_team_id(home_team)
            
            # Fetch names and abbreviations AFTER IDs are confirmed
            if not away_id or not home_id:
                missing_team_input = away_team if not away_id else home_team
                logger.warning(f"Invalid team identifier. Away input: '{away_team}', Home input: '{home_team}'. Resolved Away ID: {away_id}, Home ID: {home_id}")
                await interaction.followup.send(f"❗ Could not identify team: '{missing_team_input}'. Please use autocomplete or a valid Team ID/Name/Abbreviation.", ephemeral=True)
                return

            away_full_name = self._get_team_full_name(str(away_id)) or away_team
            home_full_name = self._get_team_full_name(str(home_id)) or home_team
            away_abbr = self._get_team_abbreviation(str(away_id)) or "AWAY"
            home_abbr = self._get_team_abbreviation(str(home_id)) or "HOME"

            if away_id == home_id:
                await interaction.followup.send("❗ Teams must be different for comparison.", ephemeral=True)
                return

            logger.info(f"Processing {interaction.command.name}: {away_abbr}({away_id}) vs {home_abbr}({home_id}) for {selected_typeseason_name}")

            h2h_dfs, api_error_occurred_h2h = [], False
            seasons_to_check = [s for s in [current_season, previous_season] if s]

            # This local helper function is fine for asyncio.to_thread
            def _blocking_fetch_h2h_api(vs_team_id_param, team_id_main_param, season_str_param, season_type_str_param, timeout_val_param):
                try:
                    finder = leaguegamefinder.LeagueGameFinder(
                        vs_team_id_nullable=vs_team_id_param,
                        team_id_nullable=team_id_main_param,
                        season_nullable=season_str_param,
                        season_type_nullable=season_type_str_param, # API uses 'season_type_nullable'
                        timeout=timeout_val_param
                    )
                    df_list = finder.get_data_frames()
                    return df_list[0] if df_list and not df_list[0].empty else pd.DataFrame(), None
                except (ReadTimeout, ConnectionError) as e_api:
                    logger.error(f"API Timeout/Connection Error in _blocking_fetch_h2h (vs:{vs_team_id_param}, t:{team_id_main_param}, s:{season_str_param}, type:{season_type_str_param}): {e_api}")
                    return pd.DataFrame(), e_api # Return the error object
                except Exception as e_gen:
                    logger.error(f"General API Error in _blocking_fetch_h2h (vs:{vs_team_id_param}, t:{team_id_main_param}, s:{season_str_param}, type:{season_type_str_param}): {e_gen}", exc_info=True)
                    return pd.DataFrame(), e_gen # Return the error object


            for season_val in seasons_to_check:
                # Correctly pass the API parameter name 'season_type_nullable'
                games_df_season, h2h_err = await asyncio.to_thread(
                    _blocking_fetch_h2h_api, away_id, home_id, season_val, selected_typeseason_value, self.api_timeout
                )
                if h2h_err: # Check if an error object was returned
                    logger.error(f"API Error fetching H2H ({home_abbr} vs {away_abbr}) S:{season_val} TypeSeason:{selected_typeseason_name}: {h2h_err}", exc_info=isinstance(h2h_err, Exception))
                    api_error_occurred_h2h = True # Mark that an API error happened
                if not games_df_season.empty:
                    games_df_season['API_SEASON'] = season_val
                    h2h_dfs.append(games_df_season)
            
            # ... (rest of your data processing and embed creation logic remains the same) ...
            # Ensure that from here on, you handle the case where one of the _get_season_ppg calls might return None
            # and that calculate_weighted_ppg can handle None inputs robustly.

            away_recent_wl_pct, away_recent_form_str, form_season_away = await self._get_recent_form(away_id)
            home_recent_wl_pct, home_recent_form_str, form_season_home = await self._get_recent_form(home_id)

            ppg_season_type_for_model = "Regular Season" # For overall team strength
            away_ppg_curr = await self._get_season_ppg(away_id, current_season, ppg_season_type_for_model)
            away_ppg_prev = await self._get_season_ppg(away_id, previous_season, ppg_season_type_for_model)
            home_ppg_curr = await self._get_season_ppg(home_id, current_season, ppg_season_type_for_model)
            home_ppg_prev = await self._get_season_ppg(home_id, previous_season, ppg_season_type_for_model)

            combined_h2h_df = pd.DataFrame()
            if h2h_dfs:
                try:
                    combined_h2h_df = pd.concat(h2h_dfs, ignore_index=True)
                    if 'WL' in combined_h2h_df.columns:
                        combined_h2h_df = combined_h2h_df[combined_h2h_df['WL'].notna()].copy()
                    if 'TEAM_ABBREVIATION' in combined_h2h_df.columns:
                         combined_h2h_df = combined_h2h_df[combined_h2h_df['TEAM_ABBREVIATION'] == home_abbr].copy()
                except Exception as concat_e:
                    logger.error(f"Error concatenating or filtering H2H DataFrames: {concat_e}", exc_info=True)
                    combined_h2h_df = pd.DataFrame() # Ensure it's empty on error

            home_h2h_w, away_h2h_w, total_h2h_g = 0, 0, 0
            home_h2h_wp, away_h2h_wp = 0.0, 0.0
            home_avg_pts_s, away_avg_pts_s = "N/A", "N/A"
            home_road_ws, away_road_ws = "N/A", "N/A"
            
            h2h_footer_typeseason_name = selected_typeseason_name
            if selected_typeseason_value == "All Star": # All Star is the API value
                h2h_footer_typeseason_name = "All-Star participation"
            h2h_foot_str = f"No {h2h_footer_typeseason_name} H2H data ({'/'.join(seasons_to_check) if seasons_to_check else 'N/A'})."

            if not combined_h2h_df.empty and 'WL' in combined_h2h_df.columns:
                total_h2h_g_initial = len(combined_h2h_df)
                home_h2h_w = len(combined_h2h_df[combined_h2h_df['WL'] == 'W'])
                away_h2h_w = len(combined_h2h_df[combined_h2h_df['WL'] == 'L'])
                total_h2h_g = home_h2h_w + away_h2h_w

                if total_h2h_g > 0:
                    home_h2h_wp = round((home_h2h_w / total_h2h_g) * 100, 1)
                    away_h2h_wp = round((away_h2h_w / total_h2h_g) * 100, 1)

                    if 'PTS' in combined_h2h_df.columns and pd.api.types.is_numeric_dtype(combined_h2h_df['PTS']):
                        home_avg_val = combined_h2h_df['PTS'].mean()
                        home_avg_pts_s = f"{home_avg_val:.1f}" if pd.notna(home_avg_val) else "N/A"
                        if 'PLUS_MINUS' in combined_h2h_df.columns and pd.api.types.is_numeric_dtype(combined_h2h_df['PLUS_MINUS']):
                            # Ensure PLUS_MINUS is numeric before subtraction
                            combined_h2h_df['PLUS_MINUS'] = pd.to_numeric(combined_h2h_df['PLUS_MINUS'], errors='coerce')
                            combined_h2h_df['AWAY_PTS_CALC'] = combined_h2h_df['PTS'] - combined_h2h_df['PLUS_MINUS']
                            away_avg_val = combined_h2h_df['AWAY_PTS_CALC'].mean()
                            away_avg_pts_s = f"{away_avg_val:.1f}" if pd.notna(away_avg_val) else "N/A"
                    
                    h2h_foot_str = f"{total_h2h_g} {h2h_footer_typeseason_name} H2H games ({'/'.join(seasons_to_check)})."
                    if total_h2h_g != total_h2h_g_initial:
                        h2h_foot_str += f" (filtered from {total_h2h_g_initial} records)"

                    if 'MATCHUP' in combined_h2h_df.columns:
                        games_home_vs_away = combined_h2h_df[
                            combined_h2h_df['MATCHUP'].str.contains(f"vs\\. {away_abbr}", case=False, na=False, regex=True) # Escaped '.' for regex
                        ]
                        if not games_home_vs_away.empty:
                            away_wins_there = games_home_vs_away[games_home_vs_away['WL'] == 'L'].shape[0]
                            away_road_ws = f"{(away_wins_there / len(games_home_vs_away)) * 100:.1f}%" if len(games_home_vs_away) > 0 else "0.0%"

                        games_home_at_away = combined_h2h_df[
                            combined_h2h_df['MATCHUP'].str.contains(f"@ {away_abbr}", case=False, na=False)
                        ]
                        if not games_home_at_away.empty:
                            home_wins_there = games_home_at_away[games_home_at_away['WL'] == 'W'].shape[0]
                            home_road_ws = f"{(home_wins_there / len(games_home_at_away)) * 100:.1f}%" if len(games_home_at_away) > 0 else "0.0%"
            
            def calculate_weighted_ppg(ppg_c, ppg_p, team_log_abbr: str):
                ppg_c_n = float(ppg_c) if isinstance(ppg_c, (int, float, np.number)) and pd.notna(ppg_c) else None
                ppg_p_n = float(ppg_p) if isinstance(ppg_p, (int, float, np.number)) and pd.notna(ppg_p) else None
                w_curr = self.bot.config.get('WEIGHT_CURRENT', 0.7)
                w_prev = self.bot.config.get('WEIGHT_PREVIOUS', 0.3)
                def_ppg = self.bot.config.get('DEFAULT_AVG_PPG', 112.0)

                if ppg_c_n is not None and ppg_p_n is not None: return (ppg_c_n * w_curr) + (ppg_p_n * w_prev)
                elif ppg_c_n is not None: return ppg_c_n
                elif ppg_p_n is not None: return ppg_p_n
                else:
                    logger.warning(f"({team_log_abbr}) No valid PPG from _get_season_ppg for model. Using default: {def_ppg}.")
                    return def_ppg

            away_w_ppg = calculate_weighted_ppg(away_ppg_curr, away_ppg_prev, away_abbr)
            home_w_ppg = calculate_weighted_ppg(home_ppg_curr, home_ppg_prev, home_abbr)

            h2h_adj = (home_h2h_wp - away_h2h_wp) * 0.05 
            pred_away_raw = away_w_ppg - h2h_adj
            pred_home_raw = home_w_ppg + h2h_adj
            min_s = 70
            pred_s_away = f"{max(min_s, pred_away_raw):.1f}"
            pred_s_home = f"{max(min_s, pred_home_raw):.1f}"
            pred_s_total = f"{(max(min_s, pred_away_raw) + max(min_s, pred_home_raw)):.1f}"

            H2H_PROB_W = self.bot.config.get('H2H_PROB_WEIGHT', 0.60)
            FORM_PROB_W = self.bot.config.get('FORM_PROB_WEIGHT', 0.40)
            PROB_THRESHOLD = self.bot.config.get('PROB_CLOSE_THRESHOLD', 2.0)

            home_h2h_f = home_h2h_wp / 100.0 if total_h2h_g > 0 else 0.5
            home_form_f = home_recent_wl_pct if isinstance(home_recent_wl_pct, float) and pd.notna(home_recent_wl_pct) else 0.5
            away_form_f = away_recent_wl_pct if isinstance(away_recent_wl_pct, float) and pd.notna(away_recent_wl_pct) else 0.5
            home_str_metric = (home_h2h_f * H2H_PROB_W) + (home_form_f * FORM_PROB_W) # Renamed from home_str to avoid conflict
            
            away_h2h_f = (1.0 - home_h2h_f) if total_h2h_g > 0 else 0.5 # This assumes H2H is zero-sum for win %
            away_str_metric_raw = (away_h2h_f * H2H_PROB_W) + (away_form_f * FORM_PROB_W) # Renamed
            
            total_metric_score = home_str_metric + away_str_metric_raw
            home_wp, away_wp = 50.0, 50.0
            winner_pred = "N/A"

            if total_metric_score > 0.001: # Avoid division by zero
                home_wp = round((home_str_metric / total_metric_score) * 100, 1)
                away_wp = round(100.0 - home_wp, 1) # Ensure it sums to 100
                if abs(home_wp - away_wp) < PROB_THRESHOLD: winner_pred = "Too Close"
                elif home_wp > away_wp: winner_pred = home_abbr
                else: winner_pred = away_abbr
            else: # Fallback if total_metric_score is too low (e.g. all inputs were 0.5 for H2H and form)
                winner_pred = "Too Close (Low Data)" if total_h2h_g == 0 and (home_form_f == 0.5 and away_form_f == 0.5) else "Too Close (Calc Issue)"
            
            embed_title = f"⚔️ {away_abbr} @ {home_abbr} — {selected_typeseason_name} H2H & Prediction"
            if selected_typeseason_value == "All Star":
                embed_title = f"🌟 {away_full_name} vs {home_full_name} — Player All-Star Game Participation"

            embed_description = (
                f"Analysis based on {selected_typeseason_name} H2H from {current_season} & {previous_season} seasons.\n"
                f"Overall stats (PPG from '{ppg_season_type_for_model}', Form from recent games) are used for prediction model."
            )
            if selected_typeseason_value == "All Star":
                embed_description = (
                    f"Showing games where players from {away_full_name} and {home_full_name} may have participated in "
                    f"All-Star events during {current_season} & {previous_season} seasons.\n"
                    f"Franchise H2H predictions are not applicable for All-Star games."
                )

            embed_vs = discord.Embed(
                title=embed_title,
                description=embed_description,
                color=self.bot.config.get('EMBED_COLOR_VERSUS', discord.Color.dark_orange())
            )
            embed_vs.timestamp = discord.utils.utcnow()

            form_s_away_disp = f"(S:{form_season_away})" if form_season_away not in ["N/A", None, ''] else ""
            form_s_home_disp = f"(S:{form_season_home})" if form_season_home not in ["N/A", None, ''] else ""
            
            typeseason_short = "".join([word[0] for word in selected_typeseason_name.split() if word[0].isupper()])
            if not typeseason_short or len(typeseason_short) > 3:
                 typeseason_short = selected_typeseason_name.split(" ")[0][:3].upper() # Max 3 chars

            embed_vs.add_field(name=f"✈️ {away_abbr} ({away_full_name})", value=(
                f"📈 **Form (L5)**: {away_recent_form_str} `{away_form_f*100:.0f}%` {form_s_away_disp}\n"
                f"🏆 **H2H Wins ({typeseason_short})**: `{away_h2h_w}`\n"
                f"📊 **H2H Win% ({typeseason_short})**: `{away_h2h_wp}%`\n"
                f"🎯 **Avg H2H PTS ({typeseason_short})**: `{away_avg_pts_s}`\n"
                f"🛣️ **Win% @{home_abbr} ({typeseason_short})**: `{away_road_ws}`"
            ), inline=True)
            embed_vs.add_field(name=f"🏠 {home_abbr} ({home_full_name})", value=(
                f"📈 **Form (L5)**: {home_recent_form_str} `{home_form_f*100:.0f}%` {form_s_home_disp}\n"
                f"🏆 **H2H Wins ({typeseason_short})**: `{home_h2h_w}`\n"
                f"📊 **H2H Win% ({typeseason_short})**: `{home_h2h_wp}%`\n"
                f"🎯 **Avg H2H PTS ({typeseason_short})**: `{home_avg_pts_s}`\n"
                f"🛣️ **Win% @{away_abbr} ({typeseason_short})**: `{home_road_ws}`"
            ), inline=True)

            if selected_typeseason_value != "All Star":
                embed_vs.add_field(name="--- Predictions ---", value="\u200b", inline=False)
                embed_vs.add_field(name="🔢 Predicted Score", value=f"**`{pred_s_away} - {pred_s_home}`**", inline=True)
                embed_vs.add_field(name="📈 Predicted Total", value=f"**`{pred_s_total}`**", inline=True)
                winner_display_name = winner_pred
                if winner_pred == home_abbr: winner_display_name = home_full_name
                elif winner_pred == away_abbr: winner_display_name = away_full_name

                if "Too Close" in winner_pred or "Low Data" in winner_pred or "Calc Issue" in winner_pred:
                    embed_vs.add_field(name="🔮 Predicted Winner", value=f"⚖️ {winner_pred}", inline=True)
                elif winner_pred != "N/A":
                    embed_vs.add_field(name="🔮 Predicted Winner", value=f"**{winner_display_name}**", inline=True)

                win_prob_form_season = form_season_home if form_season_home not in ["N/A", None, ''] else current_season
                embed_vs.add_field(name=f"📊 Win Probability (Form S:{win_prob_form_season}, H2H {typeseason_short})",
                                   value=f"`{away_abbr}: {away_wp}%` | `{home_abbr}: {home_wp}%`", inline=False)
            else:
                embed_vs.add_field(name="--- All-Star Game Data ---", 
                                   value="Direct H2H predictions are not applicable for All-Star franchise matchups. "
                                         "Stats reflect player participation if any H2H games are found.", 
                                   inline=False)

            embed_vs.set_footer(text=h2h_foot_str)
            if api_error_occurred_h2h:
                current_desc = embed_vs.description or ""
                embed_vs.description = current_desc.strip() + f"\n⚠️ *Note: Some {selected_typeseason_name} H2H API data might be missing or incomplete due to API errors.*"

            await interaction.followup.send(embed=embed_vs)

        except Exception as e:
            logger.error(f"General error in /{interaction.command.name} command ({away_team} vs {home_team}, TypeSeason: {selected_typeseason_name}): {e}", exc_info=True)
            # Assuming you have a consistent error embed helper, or a default one
            # from your main bot file, you can call it like:
            # from helpers.embed_builder import error_embed as bot_error_embed # if it's there
            # err_embed_vs = bot_error_embed(description="An unexpected error occurred. Please try again later.", title="Command Error")
            # For now, a simple fallback:
            err_embed_vs = discord.Embed(title="❌ Command Error", description="An unexpected error occurred while processing your request. The developers have been notified.", color=discord.Color.red())
            try:
                await interaction.followup.send(embed=err_embed_vs, ephemeral=True)
            except discord.NotFound: # Interaction might have expired
                logger.warning(f"Could not send error followup for /{interaction.command.name}, interaction likely expired.")
            except Exception as followup_e:
                logger.error(f"Error sending error followup for /{interaction.command.name}: {followup_e}", exc_info=True)


async def setup(bot: commands.Bot):
    # Ensure bot.config exists and has necessary keys
    if not hasattr(bot, 'config'):
        logger.warning("Bot 'config' not found during TypeCog setup. Using default config values for TypeCog.")
        bot.config = {} # Initialize if totally missing

    # Set defaults for keys specifically used by this cog if they are missing
    default_typecog_config = {
        'CURRENT_SEASON': '2023-24', 
        'PREVIOUS_SEASON': '2022-23',
        'WEIGHT_CURRENT': 0.7,
        'WEIGHT_PREVIOUS': 0.3,
        'DEFAULT_AVG_PPG': 112.0,
        'API_TIMEOUT_SECONDS': 20,
        'H2H_PROB_WEIGHT': 0.60,
        'FORM_PROB_WEIGHT': 0.40,
        'PROB_CLOSE_THRESHOLD': 2.0,
        'EMBED_COLOR_VERSUS': 0xfab100 
    }
    for key, value in default_typecog_config.items():
        bot.config.setdefault(key, value)
    
    # Convert color to discord.Color object if it's an int
    if isinstance(bot.config.get('EMBED_COLOR_VERSUS'), int):
        bot.config['EMBED_COLOR_VERSUS'] = discord.Color(bot.config['EMBED_COLOR_VERSUS'])

    # Alternative way to load initial team data (in main.py's setup_hook)
    # This is more robust than doing it in cog init or first autocomplete.
    # if not hasattr(bot, 'all_nba_teams_data') or not bot.all_nba_teams_data:
    #     logger.info("Setup: Fetching initial NBA team data for the bot...")
    #     try:
    #         bot.all_nba_teams_data = await asyncio.to_thread(nba_static_teams.get_teams)
    #         logger.info(f"Setup: Successfully fetched {len(bot.all_nba_teams_data)} NBA teams.")
    #     except Exception as e:
    #         logger.error(f"Setup: Failed to fetch initial NBA teams: {e}", exc_info=True)
    #         bot.all_nba_teams_data = []

    await bot.add_cog(TypeCog(bot))
    logger.info("Cog 'TypeCog' (typeseason command) loaded successfully.")