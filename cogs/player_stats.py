import discord
from discord.ext import commands
from discord import app_commands
import pandas as pd
import logging
import asyncio

# No need for traceback import if not explicitly used
from typing import List, Optional
# import math # pd.notna is generally preferred for pandas data

# NBA API modules
from nba_api.stats.static import players # For autocomplete fallback
from nba_api.stats.endpoints import (
    commonplayerinfo,
    # playerprofilev2, # Can be an alternative, but PlayerDashboard is often more direct for splits
    playerdashboardbygeneralsplits # More versatile for per-game and advanced
)
from ..bot import NBAStatsBot

logger = logging.getLogger(__name__)

# Define a reasonable timeout for API calls within this cog
API_TIMEOUT = 20 # seconds

class PlayerStats(commands.Cog):
    """Cog for NBA Player statistics commands."""

    def __init__(self, bot: 'NBAStatsBot'): # Use string literal for your bot class
        self.bot: 'NBAStatsBot' = bot
        # No self.helpers needed, access bot methods directly

    async def player_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        """Provides autocomplete suggestions for active NBA players."""
        choices: List[app_commands.Choice[str]] = []
        if not current or len(current) < 2: # Require at least 2 chars for autocomplete
            return choices

        count = 0
        current_lower = current.lower()
        # Access player_data directly from the bot instance
        player_data_cache = self.bot.player_data # player_data is on the bot instance

        # Search preloaded cache
        if player_data_cache:
            # Prioritize names starting with current string
            for name_key_lower, player_info in player_data_cache.items():
                if name_key_lower.startswith(current_lower):
                    player_name = player_info.get('full_name', 'Unknown Player')
                    player_id = player_info.get('id')
                    if player_id is not None and not any(c.value == str(player_id) for c in choices):
                        choices.append(app_commands.Choice(name=player_name, value=str(player_id)))
                        count += 1
                        if count >= 25: break
            # Then search for names containing current string
            if count < 25:
                for name_key_lower, player_info in player_data_cache.items():
                    if current_lower in name_key_lower and not name_key_lower.startswith(current_lower):
                        player_name = player_info.get('full_name', 'Unknown Player')
                        player_id = player_info.get('id')
                        if player_id is not None and not any(c.value == str(player_id) for c in choices):
                            choices.append(app_commands.Choice(name=player_name, value=str(player_id)))
                            count += 1
                            if count >= 25: break
        else:
            logger.warning("Player autocomplete: self.bot.player_data is empty or not found.")


        # Fallback API search if not enough results from cache and current query is reasonably long
        if count < 5 and len(current) >= 3: # Only hit API if few results and decent query length
            logger.info(f"Player autocomplete: Cache results low ({count}), trying API for '{current}'")
            try:
                # This is a blocking call, consider asyncio.to_thread if it becomes slow
                api_found_players = await asyncio.to_thread(players.find_players_by_full_name, current)
                # api_found_players = players.find_players_by_full_name(current) # Original blocking call
                if api_found_players:
                    for player in api_found_players:
                        player_id = player.get('id')
                        player_name = player.get('full_name')
                        # Ensure player_id is valid and not already in choices
                        if player_id is not None and player_name and \
                           not any(c.value == str(player_id) for c in choices):
                            choices.append(app_commands.Choice(name=player_name, value=str(player_id)))
                            count += 1
                            if count >= 25: break
            except Exception as e:
                logger.error(f"Player autocomplete API error for '{current}': {e}", exc_info=False) # exc_info=False for less noise on common API issues

        # Sort final choices by name for better UX
        try:
            choices.sort(key=lambda c: c.name)
        except Exception as sort_e:
            logger.error(f"Error sorting autocomplete choices for '{current}': {sort_e}")

        logger.debug(f"Player autocomplete for '{current}' returning {len(choices)} choices.")
        return choices[:25] # Ensure limit

    @app_commands.command(name='player', description='Shows detailed stats for a specific NBA player.')
    @app_commands.describe(player_identifier='Start typing player name or enter Player ID')
    @app_commands.autocomplete(player_identifier=player_autocomplete)
    async def player_stats_command(self, interaction: discord.Interaction, player_identifier: str):
        """Displays detailed current season stats for the specified player."""
        logger.info(f"/player command invoked with: '{player_identifier}' by {interaction.user.name}")
        await interaction.response.defer(ephemeral=False)

        player_id: Optional[int] = None
        try:
            player_id = int(player_identifier)
            logger.debug(f"Interpreted '{player_identifier}' as player ID: {player_id}")
        except ValueError:
            logger.debug(f"'{player_identifier}' is not an ID, looking up player.")
            # Use the bot's _find_player method
            player_info_dict = self.bot._find_player(player_identifier)
            if player_info_dict and 'id' in player_info_dict:
                player_id = player_info_dict['id']
                logger.info(f"Resolved player '{player_identifier}' to ID: {player_id} (Name: {player_info_dict.get('full_name')})")
            else:
                logger.warning(f"Could not resolve '{player_identifier}' to a player ID.")

        if not player_id:
            await interaction.followup.send(
                f"❗ Player '{player_identifier}' not found. Please use the autocomplete suggestions or provide a valid Player ID.",
                ephemeral=True
            )
            return

        current_season = self.bot.config.get('CURRENT_SEASON')
        if not current_season:
            logger.error("CURRENT_SEASON not found in bot config for /player command.")
            await interaction.followup.send("Bot configuration error: Current season not set.", ephemeral=True)
            return

        # --- Initialize Stat Variables ---
        player_name, team_name, team_abbr, position, height, weight, jersey = ("N/A",) * 7
        gp, mpg, ppg, rpg, apg, spg, bpg, tov, plus_minus = ("N/A",) * 9
        fg_pct, fg3_pct, ft_pct, efg_pct, ts_pct, usg_pct = ("N/A",) * 6
        api_error_occurred = False

        try:
            # --- Fetch Common Player Info (Bio Details) ---
            logger.debug(f"Fetching CommonPlayerInfo for Player ID: {player_id}")
            try:
                cpi_endpoint = commonplayerinfo.CommonPlayerInfo(player_id=player_id, timeout=API_TIMEOUT)
                player_info_df = cpi_endpoint.common_player_info.get_data_frame()

                if not player_info_df.empty:
                    p_info = player_info_df.iloc[0]
                    player_name = f"{p_info.get('FIRST_NAME', '')} {p_info.get('LAST_NAME', '')}".strip() or "Unknown Player"
                    team_city = p_info.get('TEAM_CITY', '')
                    team_n = p_info.get('TEAM_NAME', '')
                    team_name = f"{team_city} {team_n}".strip() if team_city or team_n else "N/A"
                    team_abbr = p_info.get('TEAM_ABBREVIATION', 'N/A') if pd.notna(p_info.get('TEAM_ABBREVIATION')) else "N/A"
                    position = p_info.get('POSITION', 'N/A') if pd.notna(p_info.get('POSITION')) else "N/A"
                    height = p_info.get('HEIGHT', 'N/A') if pd.notna(p_info.get('HEIGHT')) else "N/A"
                    weight = str(p_info.get('WEIGHT', 'N/A')) if pd.notna(p_info.get('WEIGHT')) else "N/A" # Weight can be int
                    jersey_num = p_info.get('JERSEY')
                    jersey = f"#{jersey_num}" if pd.notna(jersey_num) and jersey_num != '' else "N/A"
                else:
                    logger.warning(f"CommonPlayerInfo DataFrame is empty for Player ID: {player_id}.")
                    api_error_occurred = True
            except Exception as e:
                logger.error(f"API Error fetching CommonPlayerInfo for Player ID {player_id}: {e}", exc_info=True)
                api_error_occurred = True

            # --- Fetch Per Game and Advanced Stats using PlayerDashboardByGeneralSplits ---
            # This endpoint can provide both base (per game) and advanced stats for a season.
            logger.debug(f"Fetching PlayerDashboardByGeneralSplits (Base & Advanced) for Player ID: {player_id}, Season: {current_season}")
            try:
                # Base Stats (PerGame)
                base_dashboard = playerdashboardbygeneralsplits.PlayerDashboardByGeneralSplits(
                    player_id=player_id, season=current_season,
                    measure_type_detailed_defense='Base', # For traditional stats
                    per_mode_detailed='PerGame',
                    timeout=API_TIMEOUT
                )
                base_stats_df = base_dashboard.overall_player_dashboard.get_data_frame()
                if not base_stats_df.empty:
                    s = base_stats_df.iloc[0]
                    if pd.notna(s.get('GP')): gp = str(int(s.get('GP')))
                    if pd.notna(s.get('MIN')): mpg = f"{s.get('MIN'):.1f}"
                    if pd.notna(s.get('PTS')): ppg = f"{s.get('PTS'):.1f}"
                    if pd.notna(s.get('REB')): rpg = f"{s.get('REB'):.1f}"
                    if pd.notna(s.get('AST')): apg = f"{s.get('AST'):.1f}"
                    if pd.notna(s.get('STL')): spg = f"{s.get('STL'):.1f}"
                    if pd.notna(s.get('BLK')): bpg = f"{s.get('BLK'):.1f}"
                    if pd.notna(s.get('TOV')): tov = f"{s.get('TOV'):.1f}" # Turnovers Per Game
                    if pd.notna(s.get('PLUS_MINUS')): plus_minus = f"{s.get('PLUS_MINUS'):+.1f}" # Total +/- for season from this view
                    if pd.notna(s.get('FG_PCT')): fg_pct = f"{s.get('FG_PCT')*100:.1f}%"
                    if pd.notna(s.get('FG3_PCT')): fg3_pct = f"{s.get('FG3_PCT')*100:.1f}%"
                    if pd.notna(s.get('FT_PCT')): ft_pct = f"{s.get('FT_PCT')*100:.1f}%"
                else:
                    logger.warning(f"Base stats dashboard empty for Player ID {player_id}, Season {current_season}")
                    # api_error_occurred = True # Don't flag if just no stats, might be DNP

                # Advanced Stats
                adv_dashboard = playerdashboardbygeneralsplits.PlayerDashboardByGeneralSplits(
                    player_id=player_id, season=current_season,
                    measure_type_detailed_defense='Advanced', # For eFG%, TS%, USG%
                    per_mode_detailed='PerGame', # Advanced stats are often rates, PerGame or Per100 apply
                    timeout=API_TIMEOUT
                )
                adv_stats_df = adv_dashboard.overall_player_dashboard.get_data_frame()
                if not adv_stats_df.empty:
                    adv = adv_stats_df.iloc[0]
                    if pd.notna(adv.get('EFG_PCT')): efg_pct = f"{adv.get('EFG_PCT')*100:.1f}%"
                    if pd.notna(adv.get('TS_PCT')): ts_pct = f"{adv.get('TS_PCT')*100:.1f}%"
                    if pd.notna(adv.get('USG_PCT')): usg_pct = f"{adv.get('USG_PCT')*100:.1f}%" # Usage Percentage
                else:
                    logger.warning(f"Advanced stats dashboard empty for Player ID {player_id}, Season {current_season}")

            except Exception as e:
                logger.error(f"API Error fetching PlayerDashboard stats for Player ID {player_id}: {e}", exc_info=True)
                api_error_occurred = True


            # --- Create Embed ---
            logger.debug(f"Creating embed for Player ID: {player_id} (Name: {player_name})")

            # Fallback for player_name if CommonPlayerInfo failed but ID is valid
            if player_name in ["N/A", "Unknown Player", ""]:
                cached_player_info = self.bot.player_data.get(str(player_id)) # Check cache by ID
                if cached_player_info and cached_player_info.get('full_name'):
                    player_name = cached_player_info['full_name']
                else: # Last resort, could query static players again if really needed
                    player_name = f"Player ID {player_id}"


            embed_color = discord.Color.dark_purple() # Example color
            title_str = f"{player_name}"
            if jersey != "N/A": title_str = f"{jersey} {title_str}"

            description_parts = [
                f"**{team_name}** ({team_abbr})" if team_name != "N/A" else None,
                position if position != "N/A" else None,
                height if height != "N/A" else None,
                f"{weight} lbs" if weight != "N/A" else None
            ]
            description_str = " | ".join(filter(None, description_parts))
            if not description_str: description_str = "Bio details not available."


            embed = discord.Embed(
                title=f"🏀 {title_str}",
                description=description_str,
                color=embed_color
            )

            # Get and set player headshot
            headshot_url = self.bot._get_player_headshot_url(player_id)
            if headshot_url:
                embed.set_thumbnail(url=headshot_url)
            else:
                logger.warning(f"Could not retrieve headshot URL for Player ID: {player_id}")

            separator = " | "
            # Field 1: Core Per Game Stats
            core_stats_value = (
                f"PPG: **`{ppg}`**{separator}RPG: **`{rpg}`**{separator}APG: **`{apg}`**\n"
                f"SPG: **`{spg}`**{separator}BPG: **`{bpg}`**{separator}TOV: **`{tov}`**"
            )
            embed.add_field(name=f"📊 Per Game Avg ({current_season})", value=core_stats_value, inline=False)

            # Field 2: Shooting Efficiency
            shooting_value = (
                f"FG%: **`{fg_pct}`**{separator}3P%: **`{fg3_pct}`**{separator}FT%: **`{ft_pct}`**\n"
                f"eFG%: **`{efg_pct}`**{separator}TS%: **`{ts_pct}`**"
            )
            embed.add_field(name="🎯 Shooting", value=shooting_value, inline=False)

            # Field 3: Context & Impact
            context_value = (
                f"GP: **`{gp}`**{separator}MPG: **`{mpg}`**\n"
                f"USG%: **`{usg_pct}`**{separator}Season +/-: **`{plus_minus}`**" # Plus/Minus is total for the season from this dashboard view
            )
            embed.add_field(name="⚙️ Usage & Impact", value=context_value, inline=False)

            footer_text = f"Data for {current_season} via NBA API"
            if api_error_occurred:
                footer_text += " | ⚠️ Some information might be missing due to API issues."
            embed.set_footer(text=footer_text)
            embed.timestamp = discord.utils.utcnow() # Add timestamp


            logger.info(f"Successfully prepared embed for Player ID {player_id}. Sending response.")
            await interaction.followup.send(embed=embed)

        except Exception as e:
            logger.error(f"Unexpected critical error in /player command for Player ID '{player_id or player_identifier}':", exc_info=True)
            error_message = f"An unexpected error occurred while fetching stats for '{player_identifier}'."
            if api_error_occurred:
                error_message += " There were also issues retrieving some data from the API."

            err_embed = discord.Embed(title="❌ Command Error", description=error_message, color=discord.Color.red())
            try:
                await interaction.followup.send(embed=err_embed, ephemeral=True)
            except discord.HTTPException as send_e:
                logger.error(f"Failed to send error embed for /player command after main exception: {send_e}")

async def setup(bot: 'NBAStatsBot'): # Use string literal for your bot class
    # Check for direct bot attributes/methods instead of 'helpers' dict
    required_bot_methods = ['_find_player', '_get_player_headshot_url']
    missing_methods = [method for method in required_bot_methods if not hasattr(bot, method)]
    if missing_methods:
        logger.error(f"PlayerStats Cog: Bot instance missing required methods: {', '.join(missing_methods)}. Cog not loaded.")
        return
    if not hasattr(bot, 'player_data') or not hasattr(bot, 'config'):
        logger.error("PlayerStats Cog: Bot instance missing 'player_data' or 'config' attributes. Cog not loaded.")
        return

    await bot.add_cog(PlayerStats(bot))
    logger.info("PlayerStats Cog loaded successfully.")