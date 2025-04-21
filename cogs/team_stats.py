# cogs/team_stats.py
import discord
from discord.ext import commands
from discord import app_commands
import pandas as pd
import numpy as np
import logging
import traceback
from datetime import datetime
# NBA API modules
from nba_api.stats.endpoints import leaguegamefinder, teamdashboardbygeneralsplits

logger = logging.getLogger(__name__)

class TeamStats(commands.Cog):
    """Cog for NBA Team statistics and comparison commands."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Ensure attributes exist, provide defaults
        self.nba_data = getattr(bot, 'nba_data', {})
        self.config = getattr(bot, 'config', {})
        self.helpers = getattr(bot, 'helpers', {})

    # --- AUTOCOMPLETE (No Changes Needed) ---
    async def team_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        choices = []
        combined_map = self.nba_data.get('combined_map', {})
        if not combined_map: return []
        count = 0
        current_lower = current.lower()
        # Ensure keys are strings before sorting
        sorted_identifiers = sorted([str(k) for k in combined_map.keys()])
        # Prioritize startswith matches
        for identifier in sorted_identifiers:
            if identifier.startswith(current_lower):
                team_data = combined_map.get(identifier) # Use .get for safety
                if team_data and team_data.get('full_name'):
                    choices.append(app_commands.Choice(name=team_data['full_name'], value=identifier))
                    count += 1
                    if count >= 25: break
                else:
                     logger.warning(f"Team data missing or incomplete for identifier '{identifier}' during autocomplete.")
        # Fill with contains matches
        if count < 25:
            for identifier in sorted_identifiers:
                if current_lower in identifier and not identifier.startswith(current_lower):
                    team_data = combined_map.get(identifier)
                    if team_data and team_data.get('full_name') and \
                       not any(c.name == team_data['full_name'] for c in choices):
                        choices.append(app_commands.Choice(name=team_data['full_name'], value=identifier))
                        count += 1
                        if count >= 25: break
                    elif not team_data or not team_data.get('full_name'):
                         logger.warning(f"Team data missing or incomplete for contains match '{identifier}' during autocomplete.")
        return choices

    # --- ENHANCED Team Stats Command ---
    @app_commands.command(name='team', description='Shows detailed stats for a specific NBA team.')
    @app_commands.describe(team_identifier='The team (name, nickname, or abbreviation)')
    @app_commands.autocomplete(team_identifier=team_autocomplete)
    async def team_slash(self, interaction: discord.Interaction, team_identifier: str):
        """Displays detailed current season stats for the specified team."""
        await interaction.response.defer(ephemeral=False)
        embed = None # Initialize embed
        try:
            # --- Resolve Team ---
            get_id = self.helpers.get('get_team_id')
            get_name = self.helpers.get('get_team_full_name')
            get_logo = self.helpers.get('get_team_logo_url')
            get_form = self.helpers.get('get_recent_form')

            if not all([get_id, get_name, get_logo, get_form]):
                 logger.error("Missing required helper functions for /team command.")
                 await interaction.followup.send("❗ Bot configuration error: Missing helper functions.", ephemeral=True)
                 return

            team_id = get_id(team_identifier)
            team_full_name = get_name(team_identifier)
            team_logo_url = get_logo(team_identifier)
            current_season = self.config.get('CURRENT_SEASON', 'N/A')

            if not team_id or not team_full_name:
                await interaction.followup.send(f"❗ Could not find team: '{team_identifier}'. Use autocomplete or check name.", ephemeral=True)
                return

            logger.info(f"Fetching detailed stats for team: {team_full_name} (ID: {team_id}) for {current_season}")

            # --- Fetch Stats (Base and Advanced) ---
            record = "N/A"
            # Basic Stats
            ppg, opp_ppg, reb, ast, stl, blk = ("N/A",) * 6
            # Advanced Stats
            off_rtg, def_rtg, net_rtg = ("N/A",) * 3
            pace, efg_pct, ts_pct, tov_ratio, ast_ratio, reb_pct = ("N/A",) * 6
            api_error = False

            try:
                # Fetch Base Stats (Per Game)
                base_dashboard = teamdashboardbygeneralsplits.TeamDashboardByGeneralSplits(
                    team_id=team_id, season=current_season, per_mode_detailed='PerGame',
                    measure_type_detailed_defense='Base', timeout=20
                )
                base_df = base_dashboard.overall_team_dashboard.get_data_frame()

                if not base_df.empty:
                    base_stats = base_df.iloc[0]
                    w = base_stats.get('W'); l = base_stats.get('L')
                    if pd.notna(w) and pd.notna(l): record = f"{int(w)}-{int(l)}"
                    if pd.notna(base_stats.get('PTS')): ppg = f"{base_stats.get('PTS'):.1f}"
                    if pd.notna(base_stats.get('REB')): reb = f"{base_stats.get('REB'):.1f}"
                    if pd.notna(base_stats.get('AST')): ast = f"{base_stats.get('AST'):.1f}"
                    if pd.notna(base_stats.get('STL')): stl = f"{base_stats.get('STL'):.1f}"
                    if pd.notna(base_stats.get('BLK')): blk = f"{base_stats.get('BLK'):.1f}"
                    if pd.notna(base_stats.get('OPP_PTS')): opp_ppg = f"{base_stats.get('OPP_PTS'):.1f}"
                    elif pd.notna(base_stats.get('PTS')) and pd.notna(base_stats.get('PLUS_MINUS')):
                         opp_ppg = f"{base_stats.get('PTS') - base_stats.get('PLUS_MINUS'):.1f}"
                else:
                    logger.warning(f"Base dashboard empty for {team_id}, season {current_season}")
                    api_error = True

                # Fetch Advanced Stats (Per 100 Possessions usually)
                adv_dashboard = teamdashboardbygeneralsplits.TeamDashboardByGeneralSplits(
                    team_id=team_id, season=current_season, per_mode_detailed='Per100Possessions',
                    measure_type_detailed_defense='Advanced', timeout=20
                )
                adv_df = adv_dashboard.overall_team_dashboard.get_data_frame()

                if not adv_df.empty:
                    adv_stats = adv_df.iloc[0]
                    if pd.notna(adv_stats.get('OFF_RATING')): off_rtg = f"{adv_stats.get('OFF_RATING'):.1f}"
                    if pd.notna(adv_stats.get('DEF_RATING')): def_rtg = f"{adv_stats.get('DEF_RATING'):.1f}"
                    if pd.notna(adv_stats.get('NET_RATING')): net_rtg = f"{adv_stats.get('NET_RATING'):+.1f}" # Add sign
                    if pd.notna(adv_stats.get('PACE')): pace = f"{adv_stats.get('PACE'):.1f}"
                    if pd.notna(adv_stats.get('EFG_PCT')): efg_pct = f"{adv_stats.get('EFG_PCT')*100:.1f}%"
                    if pd.notna(adv_stats.get('TS_PCT')): ts_pct = f"{adv_stats.get('TS_PCT')*100:.1f}%"
                    if pd.notna(adv_stats.get('AST_RATIO')): ast_ratio = f"{adv_stats.get('AST_RATIO'):.1f}"
                    if pd.notna(adv_stats.get('TOV_RATIO')): tov_ratio = f"{adv_stats.get('TOV_RATIO'):.1f}" # Lower is better
                    if pd.notna(adv_stats.get('REB_PCT')): reb_pct = f"{adv_stats.get('REB_PCT')*100:.1f}%"
                else:
                    logger.warning(f"Advanced dashboard empty for {team_id}, season {current_season}")
                    api_error = True

            except Exception as e:
                logger.error(f"API Error fetching team dashboard stats for {team_id}: {e}", exc_info=True)
                api_error = True

            # --- Fetch recent form ---
            _, recent_form_str, _ = get_form(team_id)

            # --- Create PRETTIER Embed ---
            embed_color = discord.Color.dark_blue() # Or Color.random(), or lookup team color
            embed = discord.Embed(
                title=f"{team_full_name} ({record})", # Record in title
                description=f"**Season:** {current_season}",
                color=embed_color
            )
            if team_logo_url:
                embed.set_thumbnail(url=team_logo_url)

            # --- Field Grouping - More Compact ---
            # Using \u200b (zero-width space) as a separator for visual spacing if needed
            separator = " | " #" \u200b • \u200b "

            # Group 1: Offense/Defense Focus
            off_def_value = (
                f" PPG: **`{ppg}`** {separator}"
                f" Opp PPG: **`{opp_ppg}`**\n"
                f" Off Rtg: **`{off_rtg}`** {separator}"
                f" Def Rtg: **`{def_rtg}`** {separator}"
                f" Net Rtg: **`{net_rtg}`**"
            )
            embed.add_field(name="📈 Offense / Defense", value=off_def_value, inline=False)

            # Group 2: Core Stats & Pace
            core_pace_value = (
                f"REB: **`{reb}`**{separator}"
                f"AST: **`{ast}`**{separator}"
                f"STL: **`{stl}`**{separator}"
                f"BLK: **`{blk}`**\n"
                f"Pace: **`{pace}`**"
            )
            embed.add_field(name="🏀 Core Stats & Pace", value=core_pace_value, inline=True)

            # Group 3: Efficiency & Ratios
            eff_ratio_value = (
                f" eFG%: **`{efg_pct}`** {separator}"
                f" TS%: **`{ts_pct}`**\n"
                f" AST%: **`{ast_ratio}`** {separator}" # Renamed for clarity
                f" TOV%: **`{tov_ratio}`** {separator}" # Renamed for clarity
                f" REB%: **`{reb_pct}`**"
            )
            embed.add_field(name="🎯 Efficiency & Ratios", value=eff_ratio_value, inline=True)

            # Group 4: Recent Form (Maybe keep non-inline?)
            embed.add_field(name="📅 Recent Form (L5)", value=f"{recent_form_str}", inline=False)


            # --- Footer ---
            footer_text = "PPG/REB/AST/STL/BLK = Per Game | Ratings/Pace = Per 100 | Ratios = %"
            if api_error:
                 footer_text += " | ⚠️ Some stats may be missing due to API errors."
            embed.set_footer(text=footer_text)

            await interaction.followup.send(embed=embed)

        except Exception as e:
            logger.error(f"Error in /team command for '{team_identifier}':", exc_info=True)
            error_embed = discord.Embed(title="❌ Command Error", description=f"Failed to get stats for team '{team_identifier}'.", color=discord.Color.red())
            try:
                 if interaction.is_done():
                      await interaction.followup.send(embed=error_embed, ephemeral=True)
                 else:
                      await interaction.response.send_message(embed=error_embed, ephemeral=True)
            except Exception as send_e:
                 logger.error(f"Failed to send error embed for /team: {send_e}")


    # --- Versus Command (UNCHANGED) ---
    @app_commands.command(name='versus', description=f'H2H stats & prediction for Away @ Home.')
    @app_commands.describe(
        away_team='The visiting team (name, nickname, or abbreviation)',
        home_team='The home team (name, nickname, or abbreviation)'
    )
    @app_commands.autocomplete(away_team=team_autocomplete, home_team=team_autocomplete)
    async def versus_slash(self, interaction: discord.Interaction, away_team: str, home_team: str):
        """Compares two NBA teams using multi-season data, designating home/away."""
        # ... (versus command code remains exactly the same as previous full version) ...
        await interaction.response.defer(ephemeral=False)
        start_time = datetime.now()
        try:
            # Team Resolution
            away_full = self.helpers.get('get_team_full_name')(away_team)
            home_full = self.helpers.get('get_team_full_name')(home_team)
            away_id = self.helpers.get('get_team_id')(away_team)
            home_id = self.helpers.get('get_team_id')(home_team)
            away_abbr = self.helpers.get('get_team_abbreviation')(away_team)
            home_abbr = self.helpers.get('get_team_abbreviation')(home_team)
            if not all([away_full, home_full, away_id, home_id, away_abbr, home_abbr]):
                await interaction.followup.send("❗ Invalid team identifier(s) provided.", ephemeral=True); return
            if away_id == home_id:
                 await interaction.followup.send("❗ Teams must be different.", ephemeral=True); return
            logger.info(f"Processing Versus: Away={away_abbr}({away_id}) vs Home={home_abbr}({home_id})")

            # Data Fetching (H2H)
            h2h_dfs, api_error_occurred = [], False
            seasons_to_check = [self.config['CURRENT_SEASON'], self.config['PREVIOUS_SEASON']]
            for season in seasons_to_check:
                try:
                    gamefinder = leaguegamefinder.LeagueGameFinder(vs_team_id_nullable=away_id, team_id_nullable=home_id, season_nullable=season, season_type_nullable='Regular Season', timeout=15)
                    games_df_season = gamefinder.get_data_frames()[0]
                    if not games_df_season.empty: games_df_season['API_SEASON'] = season; h2h_dfs.append(games_df_season)
                except Exception as api_e: logger.error(f"API Error fetching H2H ({home_abbr} vs {away_abbr}) S{season}: {api_e}"); api_error_occurred = True

            # Fetch Form & PPG
            away_recent_wl_pct, away_recent_form_str, form_season_away = self.helpers['get_recent_form'](away_id)
            home_recent_wl_pct, home_recent_form_str, form_season_home = self.helpers['get_recent_form'](home_id)
            away_ppg_curr = self.helpers['get_season_ppg'](away_id, self.config['CURRENT_SEASON'])
            away_ppg_prev = self.helpers['get_season_ppg'](away_id, self.config['PREVIOUS_SEASON'])
            home_ppg_curr = self.helpers['get_season_ppg'](home_id, self.config['CURRENT_SEASON'])
            home_ppg_prev = self.helpers['get_season_ppg'](home_id, self.config['PREVIOUS_SEASON'])

            # H2H Analysis
            combined_h2h_df = pd.DataFrame()
            if h2h_dfs:
                try: combined_h2h_df = pd.concat(h2h_dfs, ignore_index=True); combined_h2h_df = combined_h2h_df[combined_h2h_df['WL'].notna()].copy()
                except Exception as concat_e: logger.error(f"Error concatenating H2H DFs: {concat_e}")
            home_h2h_wins, away_h2h_wins, total_h2h_games = 0, 0, 0
            home_h2h_win_pct, away_h2h_win_pct = 0.0, 0.0
            home_avg_pts, away_avg_pts = "N/A", "N/A"; home_road_win_str, away_road_win_str = "N/A", "N/A"
            h2h_footer = f"No H2H data found ({'/'.join(seasons_to_check)})."
            if not combined_h2h_df.empty:
                total_h2h_games = len(combined_h2h_df)
                if total_h2h_games > 0:
                    home_h2h_wins = len(combined_h2h_df[combined_h2h_df['WL'] == 'W']); away_h2h_wins = total_h2h_games - home_h2h_wins
                    home_h2h_win_pct = round((home_h2h_wins / total_h2h_games) * 100, 1); away_h2h_win_pct = round((away_h2h_wins / total_h2h_games) * 100, 1)
                    if 'PTS' in combined_h2h_df.columns and pd.api.types.is_numeric_dtype(combined_h2h_df['PTS']):
                         home_avg_pts_val = np.nanmean(combined_h2h_df['PTS']); home_avg_pts = round(home_avg_pts_val, 1) if pd.notna(home_avg_pts_val) else "N/A"
                         if 'PLUS_MINUS' in combined_h2h_df.columns and pd.api.types.is_numeric_dtype(combined_h2h_df['PLUS_MINUS']) and home_avg_pts != "N/A":
                              valid_pts = combined_h2h_df[['PTS', 'PLUS_MINUS']].dropna()
                              if not valid_pts.empty: opp_pts_val = np.nanmean(valid_pts['PTS'] - valid_pts['PLUS_MINUS']); away_avg_pts = round(opp_pts_val, 1) if pd.notna(opp_pts_val) else "N/A"
                    h2h_footer = f"{total_h2h_games} H2H games analyzed ({'/'.join(seasons_to_check)})."
                    if 'MATCHUP' in combined_h2h_df.columns:
                        try:
                            away_games_at_home = combined_h2h_df[combined_h2h_df['MATCHUP'].str.contains(f"{home_abbr} vs. {away_abbr}", na=False)]
                            away_road_win_str = f"{round((away_games_at_home[away_games_at_home['WL'] == 'L'].shape[0] / len(away_games_at_home)) * 100, 1)}%" if not away_games_at_home.empty else "0.0%"
                            home_games_at_away = combined_h2h_df[combined_h2h_df['MATCHUP'].str.contains(f"{home_abbr} @ {away_abbr}", na=False)]
                            home_road_win_str = f"{round((home_games_at_away[home_games_at_away['WL'] == 'W'].shape[0] / len(home_games_at_away)) * 100, 1)}%" if not home_games_at_away.empty else "0.0%"
                        except Exception as road_err: logger.error(f"Error calc road win rates: {road_err}")

            # Predicted Score Calculation
            def calculate_weighted_ppg(ppg_c, ppg_p, team_a):
                 ppg_c_num = float(ppg_c) if isinstance(ppg_c, (int, float, np.number)) and pd.notna(ppg_c) else None; ppg_p_num = float(ppg_p) if isinstance(ppg_p, (int, float, np.number)) and pd.notna(ppg_p) else None
                 w_curr, w_prev, default = self.config.get('WEIGHT_CURRENT', 0.7), self.config.get('WEIGHT_PREVIOUS', 0.3), self.config.get('DEFAULT_AVG_PPG', 112.0)
                 if ppg_c_num and ppg_p_num: return (ppg_c_num * w_curr) + (ppg_p_num * w_prev)
                 elif ppg_c_num: return ppg_c_num; 
                 elif ppg_p_num: return ppg_p_num; 
                 elif ppg_c_num is None:
                     return default
                 else: logger.warning(f"({team_a}) No valid PPG for prediction. Using default."); 
                 return default
            away_w_ppg = calculate_weighted_ppg(away_ppg_curr, away_ppg_prev, away_abbr); home_w_ppg = calculate_weighted_ppg(home_ppg_curr, home_ppg_prev, home_abbr)
            score_adj = (home_h2h_win_pct - away_h2h_win_pct) * 0.05 if isinstance(home_h2h_win_pct, (float, int)) and isinstance(away_h2h_win_pct, (float, int)) else 0.0
            pred_score_away, pred_score_home, pred_total = "N/A", "N/A", "N/A"
            if isinstance(away_w_ppg, (float, int)) and isinstance(home_w_ppg, (float, int)):
                pred_h = max(70, home_w_ppg + score_adj); pred_a = max(70, away_w_ppg - score_adj)
                pred_score_home = round(pred_h, 1); pred_score_away = round(pred_a, 1); pred_total = round(pred_h + pred_a, 1)

            # Win Prob Prediction
            form_season_basis = form_season_home if form_season_home != "N/A" else self.config['CURRENT_SEASON']
            single_season_h2h = combined_h2h_df[combined_h2h_df['API_SEASON'] == form_season_basis] if not combined_h2h_df.empty and 'API_SEASON' in combined_h2h_df.columns else pd.DataFrame()
            home_h2h_single_pct = (len(single_season_h2h[single_season_h2h['WL'] == 'W']) / len(single_season_h2h) * 100) if not single_season_h2h.empty and len(single_season_h2h) > 0 else 0.0
            h2h_w_prob, form_w_prob = 0.6, 0.4
            home_f_pct = home_recent_wl_pct if isinstance(home_recent_wl_pct, float) else 0.5; away_f_pct = away_recent_wl_pct if isinstance(away_recent_wl_pct, float) else 0.5
            home_factor = (home_h2h_single_pct / 100 * h2h_w_prob) + (home_f_pct * form_w_prob); away_factor = ((100 - home_h2h_single_pct) / 100 * h2h_w_prob) + (away_f_pct * form_w_prob)
            total_factor = home_factor + away_factor; home_win_prob, away_win_prob = 50.0, 50.0; pred_winner = "N/A"
            if total_factor > 0.001:
                home_win_prob = round((home_factor / total_factor) * 100, 1); away_win_prob = round(100 - home_win_prob, 1)
                if abs(home_win_prob - away_win_prob) < 2.0: pred_winner = "Too Close"
                elif home_win_prob > away_win_prob: pred_winner = home_abbr; 
                else: pred_winner = away_abbr
            else: pred_winner = "Too Close"

            # Embed Creation
            embed = discord.Embed(title=f"⚔️ {away_abbr} @ {home_abbr} — H2H Analysis & Prediction", description=f"Comparison based on {self.config['CURRENT_SEASON']} & {self.config['PREVIOUS_SEASON']} data.", color=discord.Color.dark_orange())
            embed.add_field(name=f"✈️ {away_abbr} ({away_full})", value=f"📈 **Form (L5)**: {away_recent_form_str} `({away_f_pct*100:.0f}%)` `(S:{form_season_away})`\n🏆 **H2H Wins**: `{away_h2h_wins}`\n📊 **H2H Win%**: `{away_h2h_win_pct}%`\n🎯 **Avg H2H PTS**: `{away_avg_pts}`\n🛣️ **Win% @{home_abbr}**: `{away_road_win_str}`", inline=True)
            embed.add_field(name=f"🏠 {home_abbr} ({home_full})", value=f"📈 **Form (L5)**: {home_recent_form_str} `({home_f_pct*100:.0f}%)` `(S:{form_season_home})`\n🏆 **H2H Wins**: `{home_h2h_wins}`\n📊 **H2H Win%**: `{home_h2h_win_pct}%`\n🎯 **Avg H2H PTS**: `{home_avg_pts}`\n🛣️ **Win% @{away_abbr}**: `{home_road_win_str}`", inline=True)
            embed.add_field(name="--- Predictions ---", value="\u200b", inline=False)
            embed.add_field(name="🔢 Predicted Score", value=f"**`{pred_score_away} - {pred_score_home}`**", inline=True); embed.add_field(name="📈 Predicted Total", value=f"**`{pred_total}`**", inline=True)
            if pred_winner == "Too Close": embed.add_field(name="🔮 Winner", value="⚖️ Too Close", inline=True)
            elif pred_winner != "N/A": embed.add_field(name="🔮 Winner", value=f"**{pred_winner}**", inline=True); 
            else: embed.add_field(name="\u200b", value="\u200b", inline=True)
            embed.add_field(name=f"📊 Win Probability (Basis S:{form_season_basis})", value=f"`✈️{away_abbr}: {away_win_prob}%` | `🏠{home_abbr}: {home_win_prob}%`", inline=False)
            embed.set_footer(text=h2h_footer);
            if api_error_occurred: embed.description += "\n⚠️ *Note: Some API data might be missing.*"
            await interaction.followup.send(embed=embed)

        except Exception as e:
            logger.error(f"Error in /versus command:", exc_info=True); error_embed = discord.Embed(title="❌ Command Error", description="Failed to process versus comparison.", color=discord.Color.red())
            try:
                 if interaction.is_done(): await interaction.followup.send(embed=error_embed, ephemeral=True)
                 else: await interaction.response.send_message(embed=error_embed, ephemeral=True)
            except Exception as send_e: logger.error(f"Failed to send error for /versus: {send_e}")


async def setup(bot: commands.Bot):
    required_helpers = ['get_team_id', 'get_team_full_name', 'get_team_logo_url', 'get_recent_form', 'get_team_abbreviation', 'get_season_ppg']
    if not hasattr(bot, 'helpers') or not all(h in bot.helpers for h in required_helpers):
         logger.error(f"TeamStats Cog missing required helpers: {required_helpers}. Cog not loaded.")
         return
    await bot.add_cog(TeamStats(bot))
    logger.info("TeamStats Cog loaded.")