# cogs/team_stats.py
import discord
from discord.ext import commands
from discord import app_commands
import pandas as pd
import numpy as np
import logging
from datetime import datetime
# NBA API modules
from nba_api.stats.endpoints import leaguegamefinder, teamdashboardbygeneralsplits
logger = logging.getLogger(__name__)
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from ..bot import NBAStatsBot # Adjust path as needed

class TeamStats(commands.Cog):
    
    def __init__(self, bot: 'NBAStatsBot'): # Or NBAStatsBot if import works
        self.bot: 'NBAStatsBot' = bot       # Or NBAStatsBot

    # --- AUTOCOMPLETE ---
    async def team_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        choices = []
        # Access nba_data directly from the bot instance
        combined_map = self.bot.nba_data.get('combined_map', {})
        if not combined_map:
            return []

        count = 0
        current_lower = current.lower()

        # Ensure keys are strings for consistent processing
        # Sort identifiers to have a somewhat predictable order, though this can be slow for large maps
        # For very large maps, more advanced searching/indexing might be needed, but for 30 teams, this is fine.
        sorted_identifiers = sorted([str(k) for k in combined_map.keys() if isinstance(k, (str, int))]) # Filter non-string/int keys

        # Prioritize 'startswith' matches
        for identifier_key in sorted_identifiers:
            # Autocomplete value is often the original key (e.g., 'LAL', 'Los Angeles Lakers')
            # Name shown to user is the full name.
            team_data = combined_map.get(identifier_key)
            if team_data and team_data.get('full_name', '').lower().startswith(current_lower):
                # Use the original identifier_key (which could be abbr, nickname, or full_name lowercased from combined_map keys)
                # as the value, but show the proper full_name.
                choice_value = team_data.get('abbreviation', identifier_key) # Prefer abbreviation or ID as value
                choices.append(app_commands.Choice(name=team_data['full_name'], value=str(choice_value)))
                count += 1
                if count >= 25: break
            elif team_data and team_data.get('abbreviation', '').lower().startswith(current_lower):
                choice_value = team_data.get('abbreviation')
                choices.append(app_commands.Choice(name=team_data['full_name'], value=str(choice_value)))
                count += 1
                if count >= 25: break
            elif team_data and team_data.get('nickname', '').lower().startswith(current_lower):
                choice_value = team_data.get('abbreviation', identifier_key) # Fallback to key if no abbr
                choices.append(app_commands.Choice(name=team_data['full_name'], value=str(choice_value)))
                count += 1
                if count >= 25: break


        # Fill with 'contains' matches if still under limit
        if count < 25:
            for identifier_key in sorted_identifiers:
                team_data = combined_map.get(identifier_key)
                full_name_lower = team_data.get('full_name', '').lower()
                # Check if already added to avoid duplicates
                if team_data and current_lower in full_name_lower and \
                   not any(c.name == team_data['full_name'] for c in choices):
                    choice_value = team_data.get('abbreviation', identifier_key)
                    choices.append(app_commands.Choice(name=team_data['full_name'], value=str(choice_value)))
                    count += 1
                    if count >= 25: break
        return choices[:25] # Ensure not more than 25

    # --- ENHANCED Team Stats Command ---
    @app_commands.command(name='team', description='Shows detailed stats for a specific NBA team.')
    @app_commands.describe(team_identifier='The team (name, nickname, or abbreviation)')
    @app_commands.autocomplete(team_identifier=team_autocomplete)
    async def team_slash(self, interaction: discord.Interaction, team_identifier: str):
        """Displays detailed current season stats for the specified team."""
        await interaction.response.defer(ephemeral=False)

        try:
            # --- Resolve Team using bot's helper methods ---
            team_id = self.bot._get_team_id(team_identifier) # Use direct method call
            team_full_name = self.bot._get_team_full_name(team_identifier)
            team_logo_url = self.bot._get_team_logo_url(team_identifier)
            current_season = self.bot.config.get('CURRENT_SEASON')

            if not all([current_season]): # Ensure critical config is present
                logger.error("Missing CURRENT_SEASON in bot configuration for /team command.")
                await interaction.followup.send("❗ Bot configuration error: Season not set.", ephemeral=True)
                return

            if not team_id or not team_full_name:
                await interaction.followup.send(f"❗ Could not find team: '{team_identifier}'. Use autocomplete or check the name/abbreviation.", ephemeral=True)
                return

            logger.info(f"Fetching detailed stats for team: {team_full_name} (ID: {team_id}) for {current_season}")

            # --- Fetch Stats (Base and Advanced) ---
            record = "N/A"
            ppg, opp_ppg, reb, ast, stl, blk = ("N/A",) * 6
            off_rtg, def_rtg, net_rtg = ("N/A",) * 3
            pace, efg_pct, ts_pct, tov_ratio, ast_ratio, reb_pct = ("N/A",) * 6
            api_error_occurred = False
            api_timeout = self.bot.config.get("API_TIMEOUT_SECONDS", 20)

            try:
                # Fetch Base Stats (Per Game)
                base_dashboard = teamdashboardbygeneralsplits.TeamDashboardByGeneralSplits(
                    team_id=team_id, season=current_season, per_mode_detailed='PerGame',
                    measure_type_detailed_defense='Base', timeout=api_timeout
                )
                base_df = base_dashboard.overall_team_dashboard.get_data_frame()

                if not base_df.empty:
                    base_stats = base_df.iloc[0]
                    w, l = base_stats.get('W'), base_stats.get('L')
                    if pd.notna(w) and pd.notna(l): record = f"{int(w)}-{int(l)}"
                    if pd.notna(base_stats.get('PTS')): ppg = f"{base_stats.get('PTS'):.1f}"
                    if pd.notna(base_stats.get('REB')): reb = f"{base_stats.get('REB'):.1f}"
                    if pd.notna(base_stats.get('AST')): ast = f"{base_stats.get('AST'):.1f}"
                    if pd.notna(base_stats.get('STL')): stl = f"{base_stats.get('STL'):.1f}"
                    if pd.notna(base_stats.get('BLK')): blk = f"{base_stats.get('BLK'):.1f}"

                    # OPP_PTS might not always be directly available for 'Base' measure_type
                    # It's usually in 'Opponent' measure_type or can be calculated if PLUS_MINUS is present
                    if pd.notna(base_stats.get('OPP_PTS')):
                        opp_ppg = f"{base_stats.get('OPP_PTS'):.1f}"
                    elif pd.notna(base_stats.get('PTS')) and pd.notna(base_stats.get('PLUS_MINUS')):
                        opp_ppg = f"{base_stats.get('PTS') - base_stats.get('PLUS_MINUS'):.1f}"
                    else: # Try fetching opponent dashboard if primary OPP_PTS is missing
                        try:
                            opp_dashboard = teamdashboardbygeneralsplits.TeamDashboardByGeneralSplits(
                                team_id=team_id, season=current_season, per_mode_detailed='PerGame',
                                measure_type_detailed_defense='Opponent', timeout=api_timeout # Fetch Opponent stats
                            )
                            opp_df = opp_dashboard.overall_team_dashboard.get_data_frame()
                            if not opp_df.empty and pd.notna(opp_df.iloc[0].get('PTS')):
                                opp_ppg = f"{opp_df.iloc[0].get('PTS'):.1f}"
                        except Exception as opp_e:
                            logger.warning(f"Could not fetch opponent dashboard for OPP_PTS for {team_id}: {opp_e}")
                else:
                    logger.warning(f"Base dashboard (PerGame) empty for {team_id}, season {current_season}")
                    api_error_occurred = True

                # Fetch Advanced Stats
                adv_dashboard = teamdashboardbygeneralsplits.TeamDashboardByGeneralSplits(
                    team_id=team_id, season=current_season, # Default PerMode is PerGame for Advanced, but often Per100 is desired
                    per_mode_detailed='Per100Possessions', # Explicitly Per100Poss for ratings
                    measure_type_detailed_defense='Advanced', timeout=api_timeout
                )
                adv_df = adv_dashboard.overall_team_dashboard.get_data_frame()

                if not adv_df.empty:
                    adv_stats = adv_df.iloc[0]
                    if pd.notna(adv_stats.get('OFF_RATING')): off_rtg = f"{adv_stats.get('OFF_RATING'):.1f}"
                    if pd.notna(adv_stats.get('DEF_RATING')): def_rtg = f"{adv_stats.get('DEF_RATING'):.1f}"
                    if pd.notna(adv_stats.get('NET_RATING')): net_rtg = f"{adv_stats.get('NET_RATING'):+.1f}" # Keep sign
                    if pd.notna(adv_stats.get('PACE')): pace = f"{adv_stats.get('PACE'):.1f}"
                    if pd.notna(adv_stats.get('EFG_PCT')): efg_pct = f"{adv_stats.get('EFG_PCT')*100:.1f}%"
                    if pd.notna(adv_stats.get('TS_PCT')): ts_pct = f"{adv_stats.get('TS_PCT')*100:.1f}%"
                    if pd.notna(adv_stats.get('AST_RATIO')): ast_ratio = f"{adv_stats.get('AST_RATIO'):.1f}" # This is AST_RATIO from advanced
                    if pd.notna(adv_stats.get('TM_TOV_PCT')): tov_ratio = f"{adv_stats.get('TM_TOV_PCT')*100:.1f}%" # TM_TOV_PCT often used for team TOV%
                    elif pd.notna(adv_stats.get('TOV_RATIO')): tov_ratio = f"{adv_stats.get('TOV_RATIO'):.1f}" # Fallback if TM_TOV_PCT not there
                    if pd.notna(adv_stats.get('REB_PCT')): reb_pct = f"{adv_stats.get('REB_PCT')*100:.1f}%"
                else:
                    logger.warning(f"Advanced dashboard (Per100Poss) empty for {team_id}, season {current_season}")
                    api_error_occurred = True

            except Exception as e:
                logger.error(f"API Error fetching team dashboard stats for {team_full_name} (ID: {team_id}): {e}", exc_info=True)
                api_error_occurred = True # Mark that an error occurred

            # --- Fetch recent form ---
            _, recent_form_str, _ = self.bot._get_recent_form(team_id, current_season) # Pass season explicitly

            # --- Create Embed ---
            embed_color = discord.Color.dark_blue() # Consider team-specific colors if available
            embed = discord.Embed(
                title=f"{team_full_name} ({record})",
                description=f"**Season:** {current_season}",
                color=embed_color
            )
            if team_logo_url:
                embed.set_thumbnail(url=team_logo_url)

            separator = " | "
            off_def_value = (
                f"PPG: **`{ppg}`**{separator}Opp PPG: **`{opp_ppg}`**\n"
                f"Off Rtg: **`{off_rtg}`**{separator}Def Rtg: **`{def_rtg}`**{separator}Net Rtg: **`{net_rtg}`**"
            )
            embed.add_field(name="📈 Offense / Defense", value=off_def_value, inline=False)

            core_pace_value = (
                f"REB: **`{reb}`**{separator}AST: **`{ast}`**\n"
                f"STL: **`{stl}`**{separator}BLK: **`{blk}`**{separator}Pace: **`{pace}`**"
            )
            embed.add_field(name="🏀 Core & Pace", value=core_pace_value, inline=False) # Changed to False for better spacing

            eff_ratio_value = (
                f"eFG%: **`{efg_pct}`**{separator}TS%: **`{ts_pct}`**\n"
                f"AST Ratio: **`{ast_ratio}`**{separator}TOV%: **`{tov_ratio}`**{separator}REB%: **`{reb_pct}`**"
            )
            embed.add_field(name="🎯 Efficiency & Ratios", value=eff_ratio_value, inline=False) # Changed to False

            embed.add_field(name=f"📅 Recent Form (L5 - {current_season})", value=f"{recent_form_str}", inline=False)

            footer_text = "PPG/REB/AST/STL/BLK: PerGame. Ratings/Pace: Per100. Percentages: %"
            if api_error_occurred:
                 footer_text += " | ⚠️ Some stats may be missing due to API issues."
            embed.set_footer(text=footer_text)
            timestamp = datetime.utcnow()
            embed.timestamp = timestamp


            await interaction.followup.send(embed=embed)

        except Exception as e:
            logger.error(f"Error in /team command for '{team_identifier}': {e}", exc_info=True)
            error_embed = discord.Embed(
                title="❌ Command Error",
                description=f"An unexpected error occurred while fetching stats for '{team_identifier}'. Please try again later.",
                color=discord.Color.red()
            )
            try:
                if interaction.is_done():
                    await interaction.followup.send(embed=error_embed, ephemeral=True)
                else: # Should not happen if deferred
                    await interaction.response.send_message(embed=error_embed, ephemeral=True)
            except discord.HTTPException as send_e:
                logger.error(f"Failed to send error embed for /team command: {send_e}")

    # --- Versus Command ---
    @app_commands.command(name='versus', description=f'H2H stats & prediction for Away @ Home.')
    @app_commands.describe(
        away_team='The visiting team (name, nickname, or abbreviation)',
        home_team='The home team (name, nickname, or abbreviation)'
    )
    @app_commands.autocomplete(away_team=team_autocomplete, home_team=team_autocomplete)
    async def versus_slash(self, interaction: discord.Interaction, away_team: str, home_team: str):
        """Compares two NBA teams using multi-season data, designating home/away."""
        await interaction.response.defer(ephemeral=False)
        # start_time = datetime.now() # For performance measurement if needed

        try:
            # Config access
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

            # Team Resolution
            away_full = self.bot._get_team_full_name(away_team)
            home_full = self.bot._get_team_full_name(home_team)
            away_id = self.bot._get_team_id(away_team)
            home_id = self.bot._get_team_id(home_team)
            away_abbr = self.bot._get_team_abbreviation(away_team)
            home_abbr = self.bot._get_team_abbreviation(home_team)

            if not all([away_full, home_full, away_id, home_id, away_abbr, home_abbr]):
                await interaction.followup.send("❗ Invalid team identifier(s) provided. Please use autocomplete or check names.", ephemeral=True)
                return
            if away_id == home_id:
                 await interaction.followup.send("❗ Teams must be different for comparison.", ephemeral=True)
                 return

            logger.info(f"Processing Versus: Away={away_abbr}({away_id}) vs Home={home_abbr}({home_id})")

            # Data Fetching (H2H)
            h2h_dfs, api_error_occurred = [], False
            seasons_to_check = [current_season, previous_season]
            for season in seasons_to_check:
                if not season: continue # Skip if a season string is None/empty
                try:
                    gamefinder = leaguegamefinder.LeagueGameFinder(
                        vs_team_id_nullable=away_id,
                        team_id_nullable=home_id,
                        season_nullable=season,
                        season_type_nullable='Regular Season', # Consider adding 'Playoffs' or making it an option
                        timeout=api_timeout
                    )
                    games_df_season = gamefinder.get_data_frames()[0]
                    if not games_df_season.empty:
                        games_df_season['API_SEASON'] = season # Tag season for later
                        h2h_dfs.append(games_df_season)
                except Exception as api_e:
                    logger.error(f"API Error fetching H2H ({home_abbr} vs {away_abbr}) Season {season}: {api_e}", exc_info=True)
                    api_error_occurred = True

            # Fetch Form & PPG using bot's helper methods
            away_recent_wl_pct, away_recent_form_str, form_season_away = self.bot._get_recent_form(away_id) # Uses current by default
            home_recent_wl_pct, home_recent_form_str, form_season_home = self.bot._get_recent_form(home_id) # Uses current by default

            away_ppg_curr = self.bot._get_season_ppg(away_id, current_season)
            away_ppg_prev = self.bot._get_season_ppg(away_id, previous_season)
            home_ppg_curr = self.bot._get_season_ppg(home_id, current_season)
            home_ppg_prev = self.bot._get_season_ppg(home_id, previous_season)

            # H2H Analysis
            combined_h2h_df = pd.DataFrame()
            if h2h_dfs:
                try:
                    combined_h2h_df = pd.concat(h2h_dfs, ignore_index=True)
                    combined_h2h_df = combined_h2h_df[combined_h2h_df['WL'].notna()].copy() # Ensure WL is not NaN
                except Exception as concat_e:
                    logger.error(f"Error concatenating H2H DataFrames: {concat_e}")
                    api_error_occurred = True # Treat as an API/data issue

            home_h2h_wins, away_h2h_wins, total_h2h_games = 0, 0, 0
            home_h2h_win_pct, away_h2h_win_pct = 0.0, 0.0
            home_avg_pts_str, away_avg_pts_str = "N/A", "N/A"
            home_road_win_str, away_road_win_str = "N/A", "N/A" # Win % when playing this opponent on the road
            h2h_footer = f"No H2H data found for {current_season}/{previous_season}."

            if not combined_h2h_df.empty:
                total_h2h_games = len(combined_h2h_df)
                if total_h2h_games > 0:
                    # Home team's perspective (game logs are from home_id's view vs. away_id)
                    home_h2h_wins = len(combined_h2h_df[combined_h2h_df['WL'] == 'W'])
                    away_h2h_wins = total_h2h_games - home_h2h_wins
                    home_h2h_win_pct = round((home_h2h_wins / total_h2h_games) * 100, 1)
                    away_h2h_win_pct = round((away_h2h_wins / total_h2h_games) * 100, 1)

                    # Calculate average points in H2H games
                    if 'PTS' in combined_h2h_df.columns and pd.api.types.is_numeric_dtype(combined_h2h_df['PTS']):
                        home_avg_pts_val = combined_h2h_df['PTS'].mean() # Home team's points
                        home_avg_pts_str = f"{home_avg_pts_val:.1f}" if pd.notna(home_avg_pts_val) else "N/A"

                        if 'PLUS_MINUS' in combined_h2h_df.columns and pd.api.types.is_numeric_dtype(combined_h2h_df['PLUS_MINUS']):
                            # Away_PTS = Home_PTS - PLUS_MINUS
                            away_avg_pts_val = (combined_h2h_df['PTS'] - combined_h2h_df['PLUS_MINUS']).mean()
                            away_avg_pts_str = f"{away_avg_pts_val:.1f}" if pd.notna(away_avg_pts_val) else "N/A"
                        else:
                            logger.warning("PLUS_MINUS column missing or not numeric for H2H opponent points calculation.")
                    else:
                        logger.warning("PTS column missing or not numeric for H2H points calculation.")

                    h2h_footer = f"{total_h2h_games} H2H games analyzed ({current_season}/{previous_season})."

                    # Road Win %: This logic is a bit tricky with how LeagueGameFinder returns data for `team_id` vs `vs_team_id`.
                    # The current `combined_h2h_df` is from `home_id`'s perspective against `away_id`.
                    # So, a 'W' in `combined_h2h_df` means `home_id` won that H2H game.
                    # `away_road_win_str`: Away team (away_id) winning AT home_id's arena. This is `away_h2h_wins`.
                    # `home_road_win_str`: Home team (home_id) winning AT away_id's arena. This requires a separate query or careful parsing.
                    # For simplicity, we'll use overall H2H for now, as true "road win % vs this specific opponent" is more complex.
                    # This part of your original code was complex and might need re-evaluation for accuracy
                    # based on how `leaguegamefinder` structures results when `team_id` and `vs_team_id` are both specified.
                    # If `MATCHUP` is like "LAC vs. LAL", then 'LAL' is the `vs_team_id`.
                    # If `MATCHUP` is like "LAL @ LAC", then 'LAL' is the `team_id`.
                    # The current query is `team_id_nullable=home_id, vs_team_id_nullable=away_id`.
                    # So, `MATCHUP` should be like `HOME_ABBR vs. AWAY_ABBR` or `HOME_ABBR @ AWAY_ABBR`
                    # This means games are always from `home_id`'s schedule.
                    # `WL` is for `home_id`.
                    if 'MATCHUP' in combined_h2h_df.columns:
                        # Games where `home_id` was playing `away_id` (irrespective of location, filtered by vs_team_id)
                        # To get "Away team's win % when playing at Home team's arena":
                        # This would be `away_id` winning when `MATCHUP` shows `home_abbr vs. away_abbr`.
                        # `WL` is for `home_id`. So if `home_id` LOST (`WL == 'L'`), `away_id` WON.
                        games_home_team_is_home = combined_h2h_df[combined_h2h_df['MATCHUP'].str.startswith(f"{home_abbr} vs.", na=False)]
                        if not games_home_team_is_home.empty:
                            away_wins_at_home_arena = games_home_team_is_home[games_home_team_is_home['WL'] == 'L'].shape[0]
                            away_road_win_str = f"{(away_wins_at_home_arena / len(games_home_team_is_home)) * 100:.1f}%"

                        # To get "Home team's win % when playing at Away team's arena":
                        # This means `home_id` won when `MATCHUP` shows `home_abbr @ away_abbr`.
                        games_home_team_is_away = combined_h2h_df[combined_h2h_df['MATCHUP'].str.startswith(f"{home_abbr} @", na=False)]
                        if not games_home_team_is_away.empty:
                            home_wins_at_away_arena = games_home_team_is_away[games_home_team_is_away['WL'] == 'W'].shape[0]
                            home_road_win_str = f"{(home_wins_at_away_arena / len(games_home_team_is_away)) * 100:.1f}%"


            # Predicted Score Calculation
            def calculate_weighted_ppg(ppg_c, ppg_p, team_abbr_log: str):
                ppg_c_num = float(ppg_c) if isinstance(ppg_c, (int, float, np.number)) and pd.notna(ppg_c) else None
                ppg_p_num = float(ppg_p) if isinstance(ppg_p, (int, float, np.number)) and pd.notna(ppg_p) else None

                if ppg_c_num and ppg_p_num:
                    return (ppg_c_num * weight_current) + (ppg_p_num * weight_previous)
                elif ppg_c_num: # Only current season available
                    return ppg_c_num
                elif ppg_p_num: # Only previous season available
                    return ppg_p_num
                else:
                    logger.warning(f"({team_abbr_log}) No valid PPG data for prediction. Using default: {default_avg_ppg}.")
                    return default_avg_ppg

            away_w_ppg = calculate_weighted_ppg(away_ppg_curr, away_ppg_prev, away_abbr)
            home_w_ppg = calculate_weighted_ppg(home_ppg_curr, home_ppg_prev, home_abbr)

            # Score adjustment based on H2H win percentages (simple model)
            h2h_diff_factor = (home_h2h_win_pct - away_h2h_win_pct) * 0.05 # Small adjustment
            pred_score_away_raw = away_w_ppg - h2h_diff_factor
            pred_score_home_raw = home_w_ppg + h2h_diff_factor

            # Ensure scores are somewhat realistic (e.g., not below a certain threshold)
            min_score = 70
            pred_score_away = f"{max(min_score, pred_score_away_raw):.1f}"
            pred_score_home = f"{max(min_score, pred_score_home_raw):.1f}"
            pred_total = f"{ (max(min_score, pred_score_away_raw) + max(min_score, pred_score_home_raw)):.1f}"


            # Win Probability Prediction (Simplified Model)
            # Weights for H2H performance and recent form
            H2H_WEIGHT_PROB = 0.60
            FORM_WEIGHT_PROB = 0.40

            # Use H2H win percentage for the current prediction basis (e.g., current season if available)
            # This was `form_season_basis` in your code. Let's simplify to overall H2H for now.
            # Or, stick to single_season_h2h for more recency if preferred.
            home_h2h_factor = home_h2h_win_pct / 100.0  # Overall H2H win % for home team
            away_h2h_factor = away_h2h_win_pct / 100.0  # Overall H2H win % for away team

            home_form_factor = home_recent_wl_pct if isinstance(home_recent_wl_pct, float) else 0.5
            away_form_factor = away_recent_wl_pct if isinstance(away_recent_wl_pct, float) else 0.5

            home_strength = (home_h2h_factor * H2H_WEIGHT_PROB) + (home_form_factor * FORM_WEIGHT_PROB)
            away_strength = (away_h2h_factor * H2H_WEIGHT_PROB) + (away_form_factor * FORM_WEIGHT_PROB) # Note: away_h2h_factor is their H2H win rate.

            total_strength = home_strength + (1 - away_form_factor * FORM_WEIGHT_PROB - away_h2h_factor * H2H_WEIGHT_PROB ) # This logic for total_strength needs care
            # A simpler way:
            # The probability is relative. If home_strength is higher, home has higher prob.
            # Normalize:
            total_score_metric = home_strength + away_strength # Sum of individual strength scores
            home_win_prob, away_win_prob = 50.0, 50.0
            pred_winner = "N/A"

            if total_score_metric > 0.001: # Avoid division by zero
                home_win_prob = round((home_strength / total_score_metric) * 100, 1)
                away_win_prob = round(100.0 - home_win_prob, 1) # Ensure it sums to 100

                # Determine predicted winner
                prob_threshold = 2.0 # If difference is less than this, "Too Close"
                if abs(home_win_prob - away_win_prob) < prob_threshold:
                    pred_winner = "Too Close"
                elif home_win_prob > away_win_prob:
                    pred_winner = home_abbr
                else:
                    pred_winner = away_abbr
            else: # If both strengths are zero (e.g., no data)
                pred_winner = "Too Close (No Data)"


            # Embed Creation
            embed_color = discord.Color.dark_orange()
            embed = discord.Embed(
                title=f"⚔️ {away_abbr} @ {home_abbr} — H2H & Prediction",
                description=f"Analysis based on {current_season} & {previous_season} regular season data.",
                color=embed_color
            )
            timestamp = datetime.utcnow()
            embed.timestamp = timestamp


            form_season_display_away = f"(S:{form_season_away})" if form_season_away != "N/A" else ""
            form_season_display_home = f"(S:{form_season_home})" if form_season_home != "N/A" else ""

            embed.add_field(
                name=f"✈️ {away_abbr} ({away_full})",
                value=(
                    f"📈 **Form (L5)**: {away_recent_form_str} `{away_form_factor*100:.0f}%` {form_season_display_away}\n"
                    f"🏆 **H2H Wins**: `{away_h2h_wins}`\n"
                    f"📊 **H2H Win%**: `{away_h2h_win_pct}%`\n"
                    f"🎯 **Avg H2H PTS**: `{away_avg_pts_str}`\n"
                    f"🛣️ **Win% @{home_abbr}**: `{away_road_win_str}`" # Away team's win % when playing at the home team's arena
                ),
                inline=True
            )
            embed.add_field(
                name=f"🏠 {home_abbr} ({home_full})",
                value=(
                    f"📈 **Form (L5)**: {home_recent_form_str} `{home_form_factor*100:.0f}%` {form_season_display_home}\n"
                    f"🏆 **H2H Wins**: `{home_h2h_wins}`\n"
                    f"📊 **H2H Win%**: `{home_h2h_win_pct}%`\n"
                    f"🎯 **Avg H2H PTS**: `{home_avg_pts_str}`\n"
                    f"🛣️ **Win% @{away_abbr}**: `{home_road_win_str}`" # Home team's win % when playing at the away team's arena
                ),
                inline=True
            )

            embed.add_field(name="--- Predictions ---", value="\u200b", inline=False) # Separator

            embed.add_field(name="🔢 Predicted Score", value=f"**`{pred_score_away} - {pred_score_home}`**", inline=True)
            embed.add_field(name="📈 Predicted Total", value=f"**`{pred_total}`**", inline=True)

            if pred_winner == "Too Close" or pred_winner == "Too Close (No Data)":
                embed.add_field(name="🔮 Predicted Winner", value=f"⚖️ {pred_winner}", inline=True)
            elif pred_winner != "N/A":
                embed.add_field(name="🔮 Predicted Winner", value=f"**{pred_winner}**", inline=True)
            else: # Should not happen if logic is correct
                embed.add_field(name="🔮 Predicted Winner", value="`Error`", inline=True)


            # Basis for win probability (which H2H data was primarily used)
            # win_prob_basis_note = f" (H2H from {current_season}/{previous_season})"
            embed.add_field(
                name=f"📊 Win Probability", # {win_prob_basis_note}
                value=f"`{away_abbr}: {away_win_prob}%` | `{home_abbr}: {home_win_prob}%`",
                inline=False
            )

            embed.set_footer(text=h2h_footer)
            if api_error_occurred:
                embed.description += "\n⚠️ *Note: Some API data might be missing or incomplete, affecting results.*"

            await interaction.followup.send(embed=embed)

        except Exception as e:
            logger.error(f"Critical error in /versus command: {e}", exc_info=True)
            error_embed = discord.Embed(
                title="❌ Command Error",
                description="An unexpected error occurred while processing the versus comparison. Please try again later.",
                color=discord.Color.red()
            )
            try:
                if interaction.is_done():
                    await interaction.followup.send(embed=error_embed, ephemeral=True)
                else:
                    await interaction.response.send_message(embed=error_embed, ephemeral=True) # Should be rare
            except discord.HTTPException as send_e:
                logger.error(f"Failed to send error embed for /versus command: {send_e}")


async def setup(bot: NBAStatsBot): # Use your specific Bot class for type hinting
    # Check if the bot instance has the necessary methods directly, instead of a 'helpers' dict
    # These methods are defined in your NBAStatsBot class starting with an underscore
    required_bot_methods = [
        '_get_team_id', '_get_team_full_name', '_get_team_logo_url',
        '_get_recent_form', '_get_team_abbreviation', '_get_season_ppg'
    ]
    missing_methods = [method_name for method_name in required_bot_methods if not hasattr(bot, method_name)]

    if missing_methods:
        logger.error(f"TeamStats Cog cannot be loaded. Bot instance is missing required methods: {', '.join(missing_methods)}")
        return
    if not hasattr(bot, 'config') or not hasattr(bot, 'nba_data'):
        logger.error("TeamStats Cog cannot be loaded. Bot instance is missing 'config' or 'nba_data' attributes.")
        return

    await bot.add_cog(TeamStats(bot))
    logger.info("TeamStats Cog loaded successfully.")

# Ensure your bot class is imported if it's in a different file for type hinting
# from ..bot import NBAStatsBot # If bot.py is one level up
# Or, if in the same directory and bot.py defines NBAStatsBot:
# from bot import NBAStatsBot # This might cause circular import issues if bot.py imports cogs.
# A common practice is to use forward references with strings for type hints if direct import is problematic:
# def __init__(self, bot: 'NBAStatsBot'):
# async def setup(bot: 'NBAStatsBot'):
# For this example, I'll assume NBAStatsBot is globally available or imported correctly.
# To avoid circular imports, often the bot class definition is kept separate or hints are strings.
# For now, I've used NBAStatsBot directly assuming it's resolvable in your project structure.
# If NBAStatsBot is defined in bot.py in the root, and cogs are in a cogs/ folder:
# You might need: from ..main_bot_file import NBAStatsBot (adjust main_bot_file)
# Or just use commands.Bot and then cast/assume methods exist.
# Using `bot: commands.Bot` in __init__ and setup, then `self.bot: NBAStatsBot` after assignment is also an option.