# cogs/compare_teams.py
import discord
from discord.ext import commands
from discord import app_commands
import pandas as pd
import numpy as np
import logging
import traceback

# NBA API modules
from nba_api.stats.endpoints import teamdashboardbygeneralsplits

logger = logging.getLogger(__name__)

class CompareTeams(commands.Cog):
    """Cog for comparing statistics of two NBA teams."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.nba_data = bot.nba_data
        self.config = bot.config
        self.helpers = bot.helpers

    # --- Helper to fetch stats ---
    async def _fetch_team_season_stats(self, team_id: int, season: str) -> dict:
        """Fetches key season stats for a single team."""
        stats_dict = {
            "record": "N/A", "ppg": "N/A", "opp_ppg": "N/A", "net_rtg": "N/A",
            "fg_pct": "N/A", "fg3_pct": "N/A", "ft_pct": "N/A", "reb": "N/A",
            "ast": "N/A", "stl": "N/A", "blk": "N/A", "error": False
        }
        try:
            dashboard = teamdashboardbygeneralsplits.TeamDashboardByGeneralSplits(
                team_id=team_id,
                season=season,
                per_mode_detailed='PerGame',
                measure_type_detailed_defense='Base',
                timeout=15
            )
            # Using Overall dashboard for season stats
            overall_df = dashboard.overall_team_dashboard.get_data_frame()

            if not overall_df.empty:
                stats = overall_df.iloc[0]
                # Safely get stats and format them
                w = stats.get('W')
                l = stats.get('L')
                if pd.notna(w) and pd.notna(l):
                    stats_dict["record"] = f"{int(w)}-{int(l)}"

                pts = stats.get('PTS')
                if pd.notna(pts): stats_dict["ppg"] = f"{pts:.1f}"

                # Opponent PPG calculation
                opp_pts = stats.get('OPP_PTS')
                plus_minus = stats.get('PLUS_MINUS')
                if pd.notna(opp_pts):
                    stats_dict["opp_ppg"] = f"{opp_pts:.1f}"
                elif pd.notna(pts) and pd.notna(plus_minus):
                    opp_calc = pts - plus_minus
                    stats_dict["opp_ppg"] = f"{opp_calc:.1f}"

                if pd.notna(plus_minus):
                    stats_dict["net_rtg"] = f"{plus_minus:+.1f}" # Per Game

                fg_pct_val = stats.get('FG_PCT')
                if pd.notna(fg_pct_val): stats_dict["fg_pct"] = f"{fg_pct_val*100:.1f}%"

                fg3_pct_val = stats.get('FG3_PCT')
                if pd.notna(fg3_pct_val): stats_dict["fg3_pct"] = f"{fg3_pct_val*100:.1f}%"

                ft_pct_val = stats.get('FT_PCT')
                if pd.notna(ft_pct_val): stats_dict["ft_pct"] = f"{ft_pct_val*100:.1f}%"

                reb_val = stats.get('REB')
                if pd.notna(reb_val): stats_dict["reb"] = f"{reb_val:.1f}"

                ast_val = stats.get('AST')
                if pd.notna(ast_val): stats_dict["ast"] = f"{ast_val:.1f}"

                stl_val = stats.get('STL')
                if pd.notna(stl_val): stats_dict["stl"] = f"{stl_val:.1f}"

                blk_val = stats.get('BLK')
                if pd.notna(blk_val): stats_dict["blk"] = f"{blk_val:.1f}"

            else:
                logger.warning(f"Team Dashboard returned empty for {team_id}, S:{season}")
                stats_dict["error"] = True # Mark partial error

        except Exception as e:
            logger.error(f"API Error fetching team dashboard stats for {team_id}, S:{season}: {e}")
            stats_dict["error"] = True # Mark error

        return stats_dict


    # --- AUTOCOMPLETE (Copied/Adapted from TeamStats) ---
    async def team_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        choices = []
        combined_map = self.bot.nba_data.get('combined_map', {})
        if not combined_map: return []
        count = 0
        current_lower = current.lower()
        sorted_identifiers = sorted(combined_map.keys())
        # Prioritize startswith matches
        for identifier in sorted_identifiers:
            if identifier.startswith(current_lower):
                team_data = combined_map[identifier]
                choices.append(app_commands.Choice(name=team_data['full_name'], value=identifier))
                count += 1
                if count >= 25: break
        # Fill with contains matches
        if count < 25:
            for identifier in sorted_identifiers:
                if current_lower in identifier and not identifier.startswith(current_lower):
                    team_data = combined_map[identifier]
                    if not any(c.name == team_data['full_name'] for c in choices):
                        choices.append(app_commands.Choice(name=team_data['full_name'], value=identifier))
                        count += 1
                        if count >= 25: break
        return choices


    # --- Compare Command ---
    @app_commands.command(name='compare', description='Compares current season stats of two NBA teams.')
    @app_commands.describe(
        team1='The first team (name, nickname, or abbreviation)',
        team2='The second team (name, nickname, or abbreviation)'
    )
    @app_commands.autocomplete(team1=team_autocomplete, team2=team_autocomplete)
    async def compare_slash(self, interaction: discord.Interaction, team1: str, team2: str):
        """Displays a side-by-side comparison of two teams' season stats."""
        await interaction.response.defer(ephemeral=False)
        embed = None
        try:
            # --- Resolve Teams ---
            team1_id = self.helpers['get_team_id'](team1)
            team1_name = self.helpers['get_team_full_name'](team1)
            team1_abbr = self.helpers['get_team_abbreviation'](team1)
            team1_logo = self.helpers['get_team_logo_url'](team1)

            team2_id = self.helpers['get_team_id'](team2)
            team2_name = self.helpers['get_team_full_name'](team2)
            team2_abbr = self.helpers['get_team_abbreviation'](team2)
            # team2_logo = self.helpers['get_team_logo_url'](team2) # Can only use one thumbnail

            if not all([team1_id, team1_name, team1_abbr]):
                await interaction.followup.send(f"❗ Could not find the first team: '{team1}'.", ephemeral=True)
                return
            if not all([team2_id, team2_name, team2_abbr]):
                await interaction.followup.send(f"❗ Could not find the second team: '{team2}'.", ephemeral=True)
                return
            if team1_id == team2_id:
                await interaction.followup.send("❗ Please select two different teams to compare.", ephemeral=True)
                return

            current_season = self.config['CURRENT_SEASON']
            logger.info(f"Comparing teams: {team1_name} vs {team2_name} for season {current_season}")

            # --- Fetch Stats for Both Teams ---
            stats1 = await self._fetch_team_season_stats(team1_id, current_season)
            stats2 = await self._fetch_team_season_stats(team2_id, current_season)

            # --- Fetch Recent Form ---
            _, form1_str, _ = self.helpers['get_recent_form'](team1_id, current_season)
            _, form2_str, _ = self.helpers['get_recent_form'](team2_id, current_season)

            # --- Create Embed ---
            embed = discord.Embed(
                title=f"📊 Team Comparison: {team1_abbr} vs {team2_abbr}",
                description=f"Comparing key stats for the {current_season} season.",
                color=discord.Color.dark_purple()
            )
            # Use one logo as thumbnail
            if team1_logo:
                embed.set_thumbnail(url=team1_logo)

            # Build field values
            field1_value = (
                f"**Record:** {stats1['record']}\n"
                f"**PPG:** {stats1['ppg']}\n"
                f"**Opp PPG:** {stats1['opp_ppg']}\n"
                f"**NetRtg/Gm:** {stats1['net_rtg']}\n"
                f"**FG%:** {stats1['fg_pct']}\n"
                f"**3P%:** {stats1['fg3_pct']}\n"
                f"**FT%:** {stats1['ft_pct']}\n"
                f"**REB:** {stats1['reb']}\n"
                f"**AST:** {stats1['ast']}\n"
                f"**STL:** {stats1['stl']}\n"
                f"**BLK:** {stats1['blk']}\n"
                f"**Form (L5):** {form1_str}"
            )
            field2_value = (
                f"**Record:** {stats2['record']}\n"
                f"**PPG:** {stats2['ppg']}\n"
                f"**Opp PPG:** {stats2['opp_ppg']}\n"
                f"**NetRtg/Gm:** {stats2['net_rtg']}\n"
                f"**FG%:** {stats2['fg_pct']}\n"
                f"**3P%:** {stats2['fg3_pct']}\n"
                f"**FT%:** {stats2['ft_pct']}\n"
                f"**REB:** {stats2['reb']}\n"
                f"**AST:** {stats2['ast']}\n"
                f"**STL:** {stats2['stl']}\n"
                f"**BLK:** {stats2['blk']}\n"
                f"**Form (L5):** {form2_str}"
            )

            embed.add_field(name=f"🅰️ {team1_name} ({team1_abbr})", value=field1_value, inline=True)
            embed.add_field(name=f"🅱️ {team2_name} ({team2_abbr})", value=field2_value, inline=True)

            api_error = stats1['error'] or stats2['error']
            footer_text = f"Season: {current_season} | Data from NBA API"
            if api_error:
                footer_text += " | ⚠️ Some stats might be missing due to API errors."
            embed.set_footer(text=footer_text)

            await interaction.followup.send(embed=embed)

        except Exception as e:
            logger.error(f"Error in /compare command ({team1} vs {team2}):", exc_info=True)
            error_embed = discord.Embed(title="❌ Command Error", description="Failed to compare teams.", color=discord.Color.red())
            try:
                # Check if already responded before sending error
                if interaction.response.is_done():
                     await interaction.followup.send(embed=error_embed, ephemeral=True)
                else:
                     await interaction.response.send_message(embed=error_embed, ephemeral=True)
            except Exception as send_e:
                logger.error(f"Failed to send error embed for /compare: {send_e}")


async def setup(bot: commands.Bot):
    await bot.add_cog(CompareTeams(bot))
    logger.info("CompareTeams Cog loaded.")