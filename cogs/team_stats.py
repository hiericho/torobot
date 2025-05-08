# cogs/team_stats.py
import discord
from discord.ext import commands
from discord import app_commands, Interaction # Make sure Interaction is imported
import pandas as pd
import numpy as np # If used directly, otherwise can remove
import logging
from datetime import datetime
from typing import List, Optional, Dict, Any # Ensure these are here
import asyncio

# NBA API modules
from nba_api.stats.endpoints import leaguegamefinder, teamdashboardbygeneralsplits

logger = logging.getLogger(__name__)

# Import TYPE_CHECKING for conditional import for type hinting
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    # Assuming your bot.py is in the parent directory of 'cogs'
    # Adjust '..' if your bot.py is elsewhere (e.g., '...project_root.bot')
    # This import is ONLY for type checkers (like Mypy) and IDEs.
    # It will NOT run at runtime, preventing circular imports.
    from ..bot import NBAStatsBot


class TeamStats(commands.Cog):
    """Cog for NBA Team statistics and comparison commands."""

    # Use the imported (or string literal) type hint for your custom bot class
    def __init__(self, bot: 'NBAStatsBot'): # String literal is safest for runtime
        self.bot: 'NBAStatsBot' = bot
        # No self.helpers needed as per previous refactors
        # self.nba_data and self.config are accessed via self.bot

    # --- AUTOCOMPLETE ---
    async def team_autocomplete(
        self, interaction: Interaction, current: str
    ) -> List[app_commands.Choice[str]]:
        choices: List[app_commands.Choice[str]] = []
        # Access nba_data directly from the bot instance
        # Ensure self.bot exists and has nba_data
        if not hasattr(self.bot, 'nba_data') or not self.bot.nba_data:
            logger.warning("team_autocomplete: self.bot.nba_data not available.")
            return choices
            
        combined_map = self.bot.nba_data.get('combined_map', {})
        if not combined_map:
            return choices

        count = 0
        current_lower = current.lower()

        # Filter non-string/int keys and sort for somewhat predictable order
        # For 30 teams, sorting is fine. For much larger datasets, consider other indexing.
        valid_keys = [str(k) for k in combined_map.keys() if isinstance(k, (str, int))]
        
        # Prioritize 'startswith' matches on full name, then abbreviation, then nickname
        # This order can be adjusted based on preference.
        
        # Full Name Startswith
        for identifier_key in sorted(valid_keys): # Iterate over sorted valid keys
            team_data = combined_map.get(identifier_key)
            if team_data and team_data.get('full_name', '').lower().startswith(current_lower):
                choice_value = team_data.get('abbreviation', str(team_data.get('id', identifier_key))) # Prefer abbr or ID
                if not any(c.value == choice_value for c in choices): # Avoid duplicates by value
                    choices.append(app_commands.Choice(name=team_data['full_name'], value=choice_value))
                    count += 1
                    if count >= 25: break
        
        # Abbreviation Startswith (if still needed)
        if count < 25:
            for identifier_key in sorted(valid_keys):
                team_data = combined_map.get(identifier_key)
                if team_data and team_data.get('abbreviation', '').lower().startswith(current_lower):
                    choice_value = team_data.get('abbreviation')
                    if not any(c.value == choice_value for c in choices):
                        choices.append(app_commands.Choice(name=team_data['full_name'], value=choice_value))
                        count += 1
                        if count >= 25: break
        
        # Nickname Startswith (if still needed)
        if count < 25:
            for identifier_key in sorted(valid_keys):
                team_data = combined_map.get(identifier_key)
                if team_data and team_data.get('nickname', '').lower().startswith(current_lower):
                    choice_value = team_data.get('abbreviation', str(team_data.get('id', identifier_key)))
                    if not any(c.value == choice_value for c in choices):
                        choices.append(app_commands.Choice(name=team_data['full_name'], value=choice_value))
                        count += 1
                        if count >= 25: break

        # Fill with 'contains' matches on full name if still under limit
        if count < 25:
            for identifier_key in sorted(valid_keys):
                team_data = combined_map.get(identifier_key)
                if team_data and current_lower in team_data.get('full_name', '').lower():
                    choice_value = team_data.get('abbreviation', str(team_data.get('id', identifier_key)))
                    if not any(c.value == choice_value for c in choices): # Check by value to avoid duplicates
                        choices.append(app_commands.Choice(name=team_data['full_name'], value=choice_value))
                        count += 1
                        if count >= 25: break
                        
        return choices[:25] # Ensure not more than 25

    # --- ENHANCED Team Stats Command ---
    @app_commands.command(name='team', description='Shows detailed stats for a specific NBA team.')
    @app_commands.describe(team_identifier='Team name, nickname, abbreviation, or ID')
    @app_commands.autocomplete(team_identifier=team_autocomplete)
    async def team_stats_command(self, interaction: Interaction, team_identifier: str): # Renamed method
        """Displays detailed current season stats for the specified team."""
        await interaction.response.defer(ephemeral=False)
        logger.info(f"/team command invoked by {interaction.user.name} for: '{team_identifier}'")

        try:
            # --- Resolve Team using bot's helper methods ---
            # These methods are assumed to be defined in your NBAStatsBot class in bot.py
            team_id = self.bot._get_team_id(team_identifier)
            team_full_name = self.bot._get_team_full_name(team_identifier)
            team_logo_url = self.bot._get_team_logo_url(team_identifier)
            current_season = self.bot.config.get('CURRENT_SEASON')

            if not current_season:
                logger.error("Missing CURRENT_SEASON in bot configuration for /team command.")
                await interaction.followup.send("❗ Bot configuration error: Season information is missing.", ephemeral=True)
                return

            if not team_id or not team_full_name:
                await interaction.followup.send(f"❗ Could not find team: '{team_identifier}'. Please use autocomplete or check the name/abbreviation.", ephemeral=True)
                return

            logger.info(f"Fetching detailed stats for team: {team_full_name} (ID: {team_id}) for season {current_season}")

            # --- Initialize Stat Variables ---
            record, ppg, opp_ppg, reb, ast, stl, blk = ("N/A",) * 7
            off_rtg, def_rtg, net_rtg, pace = ("N/A",) * 4
            efg_pct, ts_pct, tov_ratio, ast_ratio, reb_pct = ("N/A",) * 5
            api_error_occurred = False
            api_timeout = self.bot.config.get("API_TIMEOUT_SECONDS", 20)

            # --- Fetch Stats (Base and Advanced) ---
            # IMPORTANT: teamdashboardbygeneralsplits is a SYNCHRONOUS (blocking) call from nba-api
            # It should be run in a thread to avoid blocking the bot's event loop.
            def _blocking_fetch_dashboards(t_id, c_season, timeout_val):
                base_data, adv_data = None, None
                base_err, adv_err = None, None
                try:
                    base_dash = teamdashboardbygeneralsplits.TeamDashboardByGeneralSplits(
                        team_id=t_id, season=c_season, per_mode_detailed='PerGame',
                        measure_type_detailed_defense='Base', timeout=timeout_val
                    )
                    base_data = base_dash.overall_team_dashboard.get_data_frame()
                except Exception as e_base:
                    base_err = e_base
                
                try:
                    adv_dash = teamdashboardbygeneralsplits.TeamDashboardByGeneralSplits(
                        team_id=t_id, season=c_season, per_mode_detailed='Per100Possessions',
                        measure_type_detailed_defense='Advanced', timeout=timeout_val
                    )
                    adv_data = adv_dash.overall_team_dashboard.get_data_frame()
                except Exception as e_adv:
                    adv_err = e_adv
                return base_data, adv_data, base_err, adv_err

            base_df, adv_df, base_api_err, adv_api_err = await asyncio.to_thread(
                _blocking_fetch_dashboards, team_id, current_season, api_timeout
            )

            if base_api_err:
                logger.error(f"API Error fetching Base team dashboard for {team_id}: {base_api_err}", exc_info=True)
                api_error_occurred = True
            if adv_api_err:
                logger.error(f"API Error fetching Advanced team dashboard for {team_id}: {adv_api_err}", exc_info=True)
                api_error_occurred = True


            # Process Base Stats
            if base_df is not None and not base_df.empty:
                base_s = base_df.iloc[0]
                w, l = base_s.get('W'), base_s.get('L')
                if pd.notna(w) and pd.notna(l): record = f"{int(w)}-{int(l)}"
                if pd.notna(base_s.get('PTS')): ppg = f"{base_s.get('PTS'):.1f}"
                if pd.notna(base_s.get('REB')): reb = f"{base_s.get('REB'):.1f}"
                if pd.notna(base_s.get('AST')): ast = f"{base_s.get('AST'):.1f}"
                if pd.notna(base_s.get('STL')): stl = f"{base_s.get('STL'):.1f}"
                if pd.notna(base_s.get('BLK')): blk = f"{base_s.get('BLK'):.1f}"
                if pd.notna(base_s.get('OPP_PTS')): # OPP_PTS sometimes in Base, sometimes needs Opponent dashboard
                    opp_ppg = f"{base_s.get('OPP_PTS'):.1f}"
                elif pd.notna(base_s.get('PTS')) and pd.notna(base_s.get('PLUS_MINUS')):
                    opp_ppg = f"{base_s.get('PTS') - base_s.get('PLUS_MINUS'):.1f}"
            elif not base_api_err: # No error, but empty df
                logger.warning(f"Base dashboard (PerGame) empty for {team_full_name}, S:{current_season}")
                api_error_occurred = True # Treat empty essential data as an issue

            # Process Advanced Stats
            if adv_df is not None and not adv_df.empty:
                adv_s = adv_df.iloc[0]
                if pd.notna(adv_s.get('OFF_RATING')): off_rtg = f"{adv_s.get('OFF_RATING'):.1f}"
                if pd.notna(adv_s.get('DEF_RATING')): def_rtg = f"{adv_s.get('DEF_RATING'):.1f}"
                if pd.notna(adv_s.get('NET_RATING')): net_rtg = f"{adv_s.get('NET_RATING'):+.1f}"
                if pd.notna(adv_s.get('PACE')): pace = f"{adv_s.get('PACE'):.1f}"
                if pd.notna(adv_s.get('EFG_PCT')): efg_pct = f"{adv_s.get('EFG_PCT')*100:.1f}%"
                if pd.notna(adv_s.get('TS_PCT')): ts_pct = f"{adv_s.get('TS_PCT')*100:.1f}%"
                if pd.notna(adv_s.get('AST_RATIO')): ast_ratio = f"{adv_s.get('AST_RATIO'):.1f}"
                # TM_TOV_PCT is often preferred for team TOV % from Advanced dashboard
                if pd.notna(adv_s.get('TM_TOV_PCT')): tov_ratio = f"{adv_s.get('TM_TOV_PCT')*100:.1f}%" 
                elif pd.notna(adv_s.get('TOV_RATIO')): tov_ratio = f"{adv_s.get('TOV_RATIO'):.1f}" # Fallback
                if pd.notna(adv_s.get('REB_PCT')): reb_pct = f"{adv_s.get('REB_PCT')*100:.1f}%"
            elif not adv_api_err:
                logger.warning(f"Advanced dashboard (Per100Poss) empty for {team_full_name}, S:{current_season}")
                # Not setting api_error_occurred = True for advanced, as it might be less critical or player DNPQ

            # --- Fetch recent form ---
            # Assuming self.bot._get_recent_form is blocking, wrap it
            form_win_pct, recent_form_str, form_season = await asyncio.to_thread(
                self.bot._get_recent_form, team_id, current_season # Pass season explicitly
            )

            # --- Create Embed ---
            embed_color = discord.Color.blue() # Or use team specific color if you have mapping
            embed = discord.Embed(
                title=f"{team_full_name} ({record})",
                description=f"**Season:** {current_season}",
                color=embed_color
            )
            if team_logo_url:
                embed.set_thumbnail(url=team_logo_url)

            separator = " | "
            embed.add_field(name="📈 Offense / Defense", value=(
                f"PPG: **`{ppg}`**{separator}Opp PPG: **`{opp_ppg}`**\n"
                f"Off Rtg: **`{off_rtg}`**{separator}Def Rtg: **`{def_rtg}`**{separator}Net Rtg: **`{net_rtg}`**"
            ), inline=False)

            embed.add_field(name="🏀 Core Stats & Pace", value=(
                f"REB: **`{reb}`**{separator}AST: **`{ast}`**\n"
                f"STL: **`{stl}`**{separator}BLK: **`{blk}`**{separator}Pace: **`{pace}`**"
            ), inline=False)

            embed.add_field(name="🎯 Efficiency & Ratios", value=(
                f"eFG%: **`{efg_pct}`**{separator}TS%: **`{ts_pct}`**\n"
                f"AST Ratio: **`{ast_ratio}`**{separator}TOV%: **`{tov_ratio}`**{separator}REB%: **`{reb_pct}`**"
            ), inline=False)

            embed.add_field(name=f"📅 Recent Form (L5 - {form_season})", value=f"{recent_form_str}", inline=False)

            footer_text = "PPG/REB/AST/STL/BLK: PerGame. Ratings/Pace: Per100. Percentages: %"
            if api_error_occurred:
                footer_text += " | ⚠️ Some stats may be missing due to API issues."
            embed.set_footer(text=footer_text)
            embed.timestamp = discord.utils.utcnow() # Add timestamp


            await interaction.followup.send(embed=embed)

        except Exception as e:
            logger.error(f"General error in /team command for '{team_identifier}': {e}", exc_info=True)
            # Assuming you have a shared error embed builder or create one locally
            err_embed = discord.Embed(
                title="❌ Command Error",
                description=f"An unexpected error occurred while fetching stats for '{team_identifier}'. Please try again later.",
                color=discord.Color.red()
            )
            try:
                # interaction might be done if defer() failed or error happened before defer
                if interaction.response.is_done():
                     await interaction.followup.send(embed=err_embed, ephemeral=True)
                else: # Should be rare if defer() is first line
                     await interaction.response.send_message(embed=err_embed, ephemeral=True)
            except discord.HTTPException as send_e:
                logger.error(f"Failed to send error embed for /team command: {send_e}")


    # --- Versus Command ---
    @app_commands.command(name='versus', description='H2H stats & prediction for Away @ Home.')
    @app_commands.describe(
        away_team='Visiting team (name, nickname, abbreviation, or ID)',
        home_team='Home team (name, nickname, abbreviation, or ID)'
    )
    @app_commands.autocomplete(away_team=team_autocomplete, home_team=team_autocomplete)
    async def versus_command(self, interaction: Interaction, away_team: str, home_team: str): # Renamed method
        await interaction.response.defer(ephemeral=False)
        logger.info(f"/versus command invoked by {interaction.user.name}: {away_team} @ {home_team}")

        try:
            # --- Config Access ---
            current_season = self.bot.config.get('CURRENT_SEASON')
            previous_season = self.bot.config.get('PREVIOUS_SEASON')
            weight_current = self.bot.config.get('WEIGHT_CURRENT', 0.7)
            weight_previous = self.bot.config.get('WEIGHT_PREVIOUS', 0.3)
            default_avg_ppg = self.bot.config.get('DEFAULT_AVG_PPG', 112.0)
            api_timeout = self.bot.config.get("API_TIMEOUT_SECONDS", 20)

            if not all([current_season, previous_season]):
                logger.error("Missing season configuration for /versus command.")
                await interaction.followup.send("❗ Bot configuration error: Season data missing.", ephemeral=True)
                return

            # --- Team Resolution (Using bot's internal methods) ---
            away_id = self.bot._get_team_id(away_team)
            home_id = self.bot._get_team_id(home_team)
            
            # Fetch full names and abbreviations after confirming IDs
            away_full, home_full, away_abbr, home_abbr = "N/A", "N/A", "N/A", "N/A"
            if away_id:
                away_full = self.bot._get_team_full_name(str(away_id)) or away_team # Fallback to input
                away_abbr = self.bot._get_team_abbreviation(str(away_id)) or "AWAY"
            if home_id:
                home_full = self.bot._get_team_full_name(str(home_id)) or home_team
                home_abbr = self.bot._get_team_abbreviation(str(home_id)) or "HOME"

            if not away_id or not home_id:
                missing_team = away_team if not away_id else home_team
                await interaction.followup.send(f"❗ Invalid team identifier provided for '{missing_team}'. Please use autocomplete.", ephemeral=True)
                return
            if away_id == home_id:
                await interaction.followup.send("❗ Teams must be different for comparison.", ephemeral=True)
                return

            logger.info(f"Processing Versus: {away_abbr}({away_id}) vs {home_abbr}({home_id})")

            # --- Data Fetching (H2H) ---
            # leaguegamefinder is a SYNCHRONOUS call.
            h2h_dfs, api_error_occurred_h2h = [], False
            seasons_to_check = [s for s in [current_season, previous_season] if s] # Filter out None seasons

            def _blocking_fetch_h2h(vs_id, t_id, season_str, timeout_val):
                try:
                    finder = leaguegamefinder.LeagueGameFinder(
                        vs_team_id_nullable=vs_id,
                        team_id_nullable=t_id,
                        season_nullable=season_str,
                        season_type_nullable='Regular Season', # Consider 'Playoffs' option
                        timeout=timeout_val
                    )
                    df = finder.get_data_frames()
                    return df[0] if df else pd.DataFrame(), None
                except Exception as e:
                    return pd.DataFrame(), e

            for season_val in seasons_to_check:
                games_df_season, h2h_err = await asyncio.to_thread(
                    _blocking_fetch_h2h, away_id, home_id, season_val, api_timeout
                )
                if h2h_err:
                    logger.error(f"API Error fetching H2H ({home_abbr} vs {away_abbr}) S:{season_val}: {h2h_err}", exc_info=True)
                    api_error_occurred_h2h = True
                if not games_df_season.empty:
                    games_df_season['API_SEASON'] = season_val
                    h2h_dfs.append(games_df_season)
            
            # --- Fetch Form & PPG (using bot's blocking helpers with asyncio.to_thread) ---
            away_recent_wl_pct, away_recent_form_str, form_season_away = await asyncio.to_thread(
                self.bot._get_recent_form, away_id # Will default to current season if not specified
            )
            home_recent_wl_pct, home_recent_form_str, form_season_home = await asyncio.to_thread(
                self.bot._get_recent_form, home_id
            )

            away_ppg_curr = await asyncio.to_thread(self.bot._get_season_ppg, away_id, current_season)
            away_ppg_prev = await asyncio.to_thread(self.bot._get_season_ppg, away_id, previous_season)
            home_ppg_curr = await asyncio.to_thread(self.bot._get_season_ppg, home_id, current_season)
            home_ppg_prev = await asyncio.to_thread(self.bot._get_season_ppg, home_id, previous_season)

            # --- H2H Analysis (largely similar to your previous logic, ensure robustness) ---
            combined_h2h_df = pd.DataFrame()
            if h2h_dfs:
                try:
                    combined_h2h_df = pd.concat(h2h_dfs, ignore_index=True)
                    if 'WL' in combined_h2h_df.columns: # Ensure WL column exists before filtering
                        combined_h2h_df = combined_h2h_df[combined_h2h_df['WL'].notna()].copy()
                except Exception as concat_e:
                    logger.error(f"Error concatenating H2H DataFrames: {concat_e}")
                    api_error_occurred_h2h = True

            home_h2h_w, away_h2h_w, total_h2h_g = 0, 0, 0
            home_h2h_wp, away_h2h_wp = 0.0, 0.0
            home_avg_pts_s, away_avg_pts_s = "N/A", "N/A"
            home_road_ws, away_road_ws = "N/A", "N/A" # Win % when playing this opponent on the road
            h2h_foot_str = f"No H2H data ({'/'.join(seasons_to_check) if seasons_to_check else 'N/A'})."

            if not combined_h2h_df.empty and 'WL' in combined_h2h_df.columns: # Check WL exists
                total_h2h_g = len(combined_h2h_df)
                if total_h2h_g > 0:
                    home_h2h_w = len(combined_h2h_df[combined_h2h_df['WL'] == 'W'])
                    away_h2h_w = total_h2h_g - home_h2h_w
                    home_h2h_wp = round((home_h2h_w / total_h2h_g) * 100, 1)
                    away_h2h_wp = round((away_h2h_w / total_h2h_g) * 100, 1)

                    if 'PTS' in combined_h2h_df.columns and pd.api.types.is_numeric_dtype(combined_h2h_df['PTS']):
                        home_avg_val = combined_h2h_df['PTS'].mean()
                        home_avg_pts_s = f"{home_avg_val:.1f}" if pd.notna(home_avg_val) else "N/A"
                        if 'PLUS_MINUS' in combined_h2h_df.columns and pd.api.types.is_numeric_dtype(combined_h2h_df['PLUS_MINUS']):
                            away_avg_val = (combined_h2h_df['PTS'] - combined_h2h_df['PLUS_MINUS']).mean()
                            away_avg_pts_s = f"{away_avg_val:.1f}" if pd.notna(away_avg_val) else "N/A"
                    h2h_foot_str = f"{total_h2h_g} H2H games ({'/'.join(seasons_to_check)})."
                    
                    # Road Win % based on MATCHUP (as discussed before)
                    if 'MATCHUP' in combined_h2h_df.columns:
                        # Away team (away_abbr) winning AT home team's (home_abbr) arena
                        # Games where home_abbr is "vs. away_abbr" -> WL for home_abbr is 'L'
                        games_home_is_home = combined_h2h_df[combined_h2h_df['MATCHUP'].str.fullmatch(f"{home_abbr} vs. {away_abbr}", case=False, na=False)]
                        if not games_home_is_home.empty:
                            away_wins_there = games_home_is_home[games_home_is_home['WL'] == 'L'].shape[0]
                            away_road_ws = f"{(away_wins_there / len(games_home_is_home)) * 100:.1f}%"

                        # Home team (home_abbr) winning AT away team's (away_abbr) arena
                        # Games where home_abbr is "@ away_abbr" -> WL for home_abbr is 'W'
                        games_home_is_away = combined_h2h_df[combined_h2h_df['MATCHUP'].str.fullmatch(f"{home_abbr} @ {away_abbr}", case=False, na=False)]
                        if not games_home_is_away.empty:
                            home_wins_there = games_home_is_away[games_home_is_away['WL'] == 'W'].shape[0]
                            home_road_ws = f"{(home_wins_there / len(games_home_is_away)) * 100:.1f}%"


            # --- Predicted Score Calculation (largely same, ensure weights are from self.bot.config) ---
            def calculate_weighted_ppg(ppg_c, ppg_p, team_log_abbr: str):
                ppg_c_n = float(ppg_c) if isinstance(ppg_c, (int, float, np.number)) and pd.notna(ppg_c) else None
                ppg_p_n = float(ppg_p) if isinstance(ppg_p, (int, float, np.number)) and pd.notna(ppg_p) else None
                w_curr = self.bot.config.get('WEIGHT_CURRENT', 0.7) # Get from bot.config
                w_prev = self.bot.config.get('WEIGHT_PREVIOUS', 0.3)
                def_ppg = self.bot.config.get('DEFAULT_AVG_PPG', 112.0)

                if ppg_c_n and ppg_p_n: return (ppg_c_n * w_curr) + (ppg_p_n * w_prev)
                elif ppg_c_n: return ppg_c_n
                elif ppg_p_n: return ppg_p_n
                else:
                    logger.warning(f"({team_log_abbr}) No valid PPG. Using default: {def_ppg}.")
                    return def_ppg

            away_w_ppg = calculate_weighted_ppg(away_ppg_curr, away_ppg_prev, away_abbr)
            home_w_ppg = calculate_weighted_ppg(home_ppg_curr, home_ppg_prev, home_abbr)

            h2h_adj = (home_h2h_wp - away_h2h_wp) * 0.05 # Small H2H adjustment
            pred_away_raw = away_w_ppg - h2h_adj
            pred_home_raw = home_w_ppg + h2h_adj
            min_s = 70
            pred_s_away = f"{max(min_s, pred_away_raw):.1f}"
            pred_s_home = f"{max(min_s, pred_home_raw):.1f}"
            pred_s_total = f"{(max(min_s, pred_away_raw) + max(min_s, pred_home_raw)):.1f}"

            # --- Win Probability Prediction (Simplified Model - review carefully) ---
            H2H_PROB_W = 0.60; FORM_PROB_W = 0.40; PROB_THRESHOLD = 2.0
            home_h2h_f = home_h2h_wp / 100.0
            # away_h2h_f = away_h2h_wp / 100.0 # This is away's win % in H2H, so home's loss % is 1 - this
            
            home_form_f = home_recent_wl_pct if isinstance(home_recent_wl_pct, float) else 0.5
            away_form_f = away_recent_wl_pct if isinstance(away_recent_wl_pct, float) else 0.5

            # Strength relative to opponent in H2H and form
            home_str = (home_h2h_f * H2H_PROB_W) + (home_form_f * FORM_PROB_W)
            # Away strength: (their H2H win * weight) + (their form * weight)
            # For probability, we need to compare home_str vs (1 - home_str equivalent for away)
            # Let's use direct strength comparison and normalize
            away_str_raw = ((1-home_h2h_f) * H2H_PROB_W) + (away_form_f * FORM_PROB_W) # (1-home_h2h_f) is away's implied H2H win rate vs home

            total_metric_score = home_str + away_str_raw # Sum of individual strength scores
            home_wp, away_wp = 50.0, 50.0
            winner_pred = "N/A"

            if total_metric_score > 0.001:
                home_wp = round((home_str / total_metric_score) * 100, 1)
                away_wp = round(100.0 - home_wp, 1)
                if abs(home_wp - away_wp) < PROB_THRESHOLD: winner_pred = "Too Close"
                elif home_wp > away_wp: winner_pred = home_abbr
                else: winner_pred = away_abbr
            else: winner_pred = "Too Close (No Data)"

            # --- Embed Creation (largely same, ensure variables are correct) ---
            embed_vs = discord.Embed(
                title=f"⚔️ {away_abbr} @ {home_abbr} — H2H & Prediction",
                description=f"Analysis based on {current_season} & {previous_season} regular season data.",
                color=discord.Color.dark_orange() # Or from constants
            )
            embed_vs.timestamp = discord.utils.utcnow()

            form_s_away_disp = f"(S:{form_season_away})" if form_season_away != "N/A" else ""
            form_s_home_disp = f"(S:{form_season_home})" if form_season_home != "N/A" else ""
            
            # Use consistent H2H variable names
            embed_vs.add_field(name=f"✈️ {away_abbr} ({away_full})", value=(
                f"📈 **Form (L5)**: {away_recent_form_str} `{away_form_f*100:.0f}%` {form_s_away_disp}\n"
                f"🏆 **H2H Wins**: `{away_h2h_w}`\n📊 **H2H Win%**: `{away_h2h_wp}%`\n"
                f"🎯 **Avg H2H PTS**: `{away_avg_pts_s}`\n🛣️ **Win% @{home_abbr}**: `{away_road_ws}`"
            ), inline=True)
            embed_vs.add_field(name=f"🏠 {home_abbr} ({home_full})", value=(
                f"📈 **Form (L5)**: {home_recent_form_str} `{home_form_f*100:.0f}%` {form_s_home_disp}\n"
                f"🏆 **H2H Wins**: `{home_h2h_w}`\n📊 **H2H Win%**: `{home_h2h_wp}%`\n"
                f"🎯 **Avg H2H PTS**: `{home_avg_pts_s}`\n🛣️ **Win% @{away_abbr}**: `{home_road_ws}`"
            ), inline=True)

            embed_vs.add_field(name="--- Predictions ---", value="\u200b", inline=False)
            embed_vs.add_field(name="🔢 Predicted Score", value=f"**`{pred_s_away} - {pred_s_home}`**", inline=True)
            embed_vs.add_field(name="📈 Predicted Total", value=f"**`{pred_s_total}`**", inline=True)
            if winner_pred == "Too Close" or winner_pred == "Too Close (No Data)":
                embed_vs.add_field(name="🔮 Predicted Winner", value=f"⚖️ {winner_pred}", inline=True)
            elif winner_pred != "N/A":
                embed_vs.add_field(name="🔮 Predicted Winner", value=f"**{winner_pred}**", inline=True)

            # Basis for win probability (which form season was used for this calc)
            # The form season used for probability is implicitly the one from _get_recent_form
            # You might want to specify which season's H2H data is weighted more if that's part of the model
            win_prob_form_season = form_season_home if form_season_home != "N/A" else current_season # Example
            embed_vs.add_field(name=f"📊 Win Probability (Form basis S:{win_prob_form_season})",
                               value=f"`{away_abbr}: {away_wp}%` | `{home_abbr}: {home_wp}%`", inline=False)

            embed_vs.set_footer(text=h2h_foot_str)
            if api_error_occurred_h2h: # Use the specific flag for H2H API errors
                embed_vs.description += "\n⚠️ *Note: Some H2H API data might be missing, affecting historical results.*"

            await interaction.followup.send(embed=embed_vs)

        except Exception as e:
            logger.error(f"General error in /versus command ({away_team} vs {home_team}): {e}", exc_info=True)
            # Assuming error_embed builder
            err_embed_vs = discord.Embed(title="❌ Command Error", description="An unexpected error occurred during versus comparison.", color=discord.Color.red())
            await interaction.followup.send(embed=err_embed_vs, ephemeral=True)


# --- Setup Function ---
async def setup(bot: 'NBAStatsBot'): # Use string literal for type hint
    # Check for necessary bot attributes (config, nba_data) and methods
    required_attrs = ['config', 'nba_data']
    missing_attrs = [attr for attr in required_attrs if not hasattr(bot, attr)]
    if missing_attrs:
        logger.error(f"TeamStats Cog: Bot instance missing required attributes: {', '.join(missing_attrs)}. Cog not loaded.")
        return

    required_bot_methods = [
        '_get_team_id', '_get_team_full_name', '_get_team_logo_url',
        '_get_recent_form', '_get_team_abbreviation', '_get_season_ppg'
    ]
    missing_methods = [method for method in required_bot_methods if not hasattr(bot, method)]
    if missing_methods:
        logger.error(f"TeamStats Cog: Bot instance missing required methods: {', '.join(missing_methods)}. Cog not loaded.")
        return

    await bot.add_cog(TeamStats(bot))
    logger.info("TeamStats Cog loaded successfully.")