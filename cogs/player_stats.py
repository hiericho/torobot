# cogs/player_stats.py
import discord
from discord.ext import commands
from discord import app_commands, Interaction
import pandas as pd
# import numpy as np # Not strictly needed as pd.isna covers np.nan
import logging
import asyncio

from typing import List, Optional, Dict, Any

# NBA API modules
from nba_api.stats.static import players as nba_static_players
from nba_api.stats.endpoints import (
    commonplayerinfo,
    playerdashboardbygeneralsplits
)

# Import TYPE_CHECKING for conditional import for type hinting
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    # Assuming bot.py is one level up from the cogs directory
    from ..bot import NBAStatsBot

logger = logging.getLogger(__name__)

API_TIMEOUT_SECONDS = 20 # Default timeout for API calls in this cog

# --- Stat Formatting Utility ---
def _format_player_stat(stat_key: str, value: Any) -> str:
    """Formats a single stat value for display."""
    # A common convention for percentage stats from nba-api often end in _PCT
    is_percentage = stat_key.upper().endswith('_PCT')

    if value is None or pd.isna(value): # Handles None, np.nan, pd.NA
        return "N/A"
    
    # Handle common non-numeric "empty" string markers often found in data
    if isinstance(value, str) and (value.strip() == "" or value.strip() == "-"):
        return "N/A"

    try:
        if is_percentage:
            num_val = float(value)
            return f"{num_val * 100:.1f}%" # Standard percentage format
        
        num_val = float(value) # Attempt to convert to float for consistent numeric handling
        
        # Determine precision based on typical stat representation
        if stat_key.upper() in ['GP']: # Games Played should be integer
            return str(int(num_val))
        if num_val.is_integer(): # Other whole numbers
             return str(int(num_val))
        elif stat_key.upper() == 'PLUS_MINUS':
            return f"{num_val:+.1f}" # Ensure sign for plus/minus
        else: # Default for most per-game averages
            return f"{num_val:.1f}"
            
    except (ValueError, TypeError):
        # If conversion fails, it might be a non-numeric string (e.g., "Inactive")
        logger.warning(f"Could not format stat '{stat_key}' with value '{value}' (type: {type(value)}) as a number. Returning as string.")
        return str(value) # Fallback: return original value as string

class PlayerStats(commands.Cog):
    """Cog for NBA Player statistics commands."""

    def __init__(self, bot: 'NBAStatsBot'):
        self.bot: 'NBAStatsBot' = bot

    async def player_autocomplete(
        self, interaction: Interaction, current: str
    ) -> List[app_commands.Choice[str]]:
        choices: List[app_commands.Choice[str]] = []
        if not current or len(current) < 2: return choices
        
        count = 0
        current_lower = current.lower()

        if hasattr(self.bot, 'player_data') and self.bot.player_data:
            player_data_cache = self.bot.player_data
            sorted_cache_items = sorted(player_data_cache.items(), key=lambda item: item[1].get('full_name', '') if isinstance(item[1], dict) else '')

            for name_key_lower, player_info in sorted_cache_items:
                if isinstance(player_info, dict): # Ensure player_info is a dict
                    full_name = player_info.get('full_name', '')
                    # Match against full name or if the key itself matches (e.g. ID string)
                    if name_key_lower.startswith(current_lower) or full_name.lower().startswith(current_lower):
                        player_id_val = player_info.get('id')
                        if player_id_val is not None and not any(c.value == str(player_id_val) for c in choices):
                            choices.append(app_commands.Choice(name=full_name or 'Unknown Player', value=str(player_id_val)))
                            count += 1
                            if count >= 25: break
            if count < 25:
                for name_key_lower, player_info in sorted_cache_items:
                    if isinstance(player_info, dict):
                        full_name = player_info.get('full_name', '')
                        if (current_lower in name_key_lower or current_lower in full_name.lower()) and \
                           not (name_key_lower.startswith(current_lower) or full_name.lower().startswith(current_lower)):
                            player_id_val = player_info.get('id')
                            if player_id_val is not None and not any(c.value == str(player_id_val) for c in choices):
                                choices.append(app_commands.Choice(name=full_name or 'Unknown Player', value=str(player_id_val)))
                                count += 1
                                if count >= 25: break
        else:
            logger.warning("Player autocomplete: self.bot.player_data not available.")

        if count < 5 and len(current) >= 3:
            logger.info(f"Player autocomplete: Cache results low ({count}), trying API for '{current}'")
            try:
                api_found_players = await asyncio.to_thread(nba_static_players.find_players_by_full_name, current)
                if api_found_players:
                    for player_api_data in api_found_players:
                        player_id_api = player_api_data.get('id')
                        player_name_api = player_api_data.get('full_name')
                        if player_id_api is not None and player_name_api and \
                           not any(c.value == str(player_id_api) for c in choices):
                            choices.append(app_commands.Choice(name=player_name_api, value=str(player_id_api)))
                            count += 1
                            if count >= 25: break
            except Exception as e:
                logger.warning(f"Player autocomplete API error for '{current}': {e}")
        
        # Ensure choices are unique by value, then sort by name
        final_choices_dict = {choice.value: choice for choice in choices}
        final_choices = sorted(list(final_choices_dict.values()), key=lambda c: c.name)
        
        logger.debug(f"Player autocomplete for '{current}' returning {len(final_choices)} choices.")
        return final_choices[:25]

    @app_commands.command(name='player', description='Shows detailed stats for a specific NBA player.')
    @app_commands.describe(player_identifier='Start typing player name or enter Player ID')
    @app_commands.autocomplete(player_identifier=player_autocomplete)
    async def player_stats_command(self, interaction: Interaction, player_identifier: str):
        logger.info(f"/player command invoked by {interaction.user.name} (ID: {interaction.user.id}) with input: '{player_identifier}'")
        await interaction.response.defer(ephemeral=False)

        player_id: Optional[int] = None
        resolved_player_name_for_error = player_identifier

        try:
            player_id = int(player_identifier)
            logger.debug(f"Input '{player_identifier}' successfully parsed as Player ID: {player_id}")
        except ValueError:
            logger.debug(f"Input '{player_identifier}' is not a direct ID, attempting name lookup via self.bot._find_player.")
            try:
                # self.bot._find_player is assumed to be a sync method in bot.py
                # If it involves API calls, it should be run in a thread too.
                # For now, assuming it's primarily cache-based or its internal API calls are handled.
                player_info_dict = self.bot._find_player(player_identifier)
                if player_info_dict and 'id' in player_info_dict:
                    player_id = player_info_dict['id']
                    resolved_player_name_for_error = player_info_dict.get('full_name', player_identifier)
                else:
                    logger.warning(f"Could not resolve '{player_identifier}' using self.bot._find_player.")
            except Exception as find_err:
                logger.error(f"Error during self.bot._find_player call for '{player_identifier}': {find_err}", exc_info=True)
        
        if not player_id:
            await interaction.followup.send(f"❗ Player '{resolved_player_name_for_error}' not found.", ephemeral=True)
            return

        current_season = self.bot.config.get('CURRENT_SEASON')
        if not current_season:
            logger.error("CURRENT_SEASON not found in bot.config for /player command.")
            await interaction.followup.send("Bot configuration error: Current season is not set.", ephemeral=True)
            return

        # Initialize Stat Variables
        player_name_bio, team_name_bio, team_abbr_bio, position_bio, height_bio, weight_bio, jersey_bio = ("N/A",) * 7
        gp, mpg, ppg, rpg, apg, spg, bpg, tov, plus_minus = ("N/A",) * 9
        fg_pct, fg3_pct, ft_pct, efg_pct, ts_pct, usg_pct = ("N/A",) * 6
        api_error_occurred_flag = False

        # --- Helper functions for blocking API calls ---
        def _blocking_fetch_common_player_info(p_id_val, timeout_val):
            try:
                endpoint = commonplayerinfo.CommonPlayerInfo(player_id=p_id_val, timeout=timeout_val)
                return endpoint.common_player_info.get_data_frame(), None
            except Exception as e: return None, e

        def _blocking_fetch_player_dashboard(p_id_val, season_str_val, measure_type_val, per_mode_str_val, timeout_val):
            try:
                endpoint = playerdashboardbygeneralsplits.PlayerDashboardByGeneralSplits(
                    player_id=p_id_val, season=season_str_val,
                    measure_type_detailed=measure_type_val, # CORRECTED PARAMETER
                    per_mode_detailed=per_mode_str_val,     # CORRECTED PARAMETER
                    season_type_playoffs='Regular Season',  # Ensure this is what you want (matches signature)
                    timeout=timeout_val
                )
                return endpoint.overall_player_dashboard.get_data_frame(), None
            except Exception as e: return None, e
        
        try:
            # Fetch Common Player Info (Bio Details)
            logger.debug(f"Fetching CommonPlayerInfo for Player ID: {player_id}")
            player_info_df, cpi_err = await asyncio.to_thread(
                _blocking_fetch_common_player_info, player_id, API_TIMEOUT_SECONDS
            )
            if cpi_err:
                logger.error(f"API Error CommonPlayerInfo (ID {player_id}): {cpi_err}", exc_info=True)
                api_error_occurred_flag = True
                # Try to get name from static cache if bio failed, as name is crucial for display
                static_p_info_fallback = await asyncio.to_thread(player_id) # from nba_helper, if available
                if static_p_info_fallback and static_p_info_fallback.get('full_name'):
                    player_name_bio = static_p_info_fallback['full_name']
                else:
                    player_name_bio = f"Player ID {player_id}" # Last resort
            elif player_info_df is not None and not player_info_df.empty:
                p_info = player_info_df.iloc[0]
                player_name_bio = f"{p_info.get('FIRST_NAME', '')} {p_info.get('LAST_NAME', '')}".strip() or f"Player ID {player_id}"
                team_city_val = p_info.get('TEAM_CITY', '')
                team_n_val = p_info.get('TEAM_NAME', '')
                team_name_bio = f"{team_city_val} {team_n_val}".strip() if team_city_val or team_n_val else "N/A"
                team_abbr_bio = p_info.get('TEAM_ABBREVIATION', 'N/A') if pd.notna(p_info.get('TEAM_ABBREVIATION')) else "N/A"
                position_bio = p_info.get('POSITION', 'N/A') if pd.notna(p_info.get('POSITION')) else "N/A"
                height_bio = p_info.get('HEIGHT', 'N/A') if pd.notna(p_info.get('HEIGHT')) else "N/A"
                weight_val = p_info.get('WEIGHT')
                weight_bio = str(weight_val) if pd.notna(weight_val) else "N/A"
                jersey_num_val = p_info.get('JERSEY')
                jersey_bio = f"#{jersey_num_val}" if pd.notna(jersey_num_val) and str(jersey_num_val).strip() else "N/A"
            else:
                logger.warning(f"CommonPlayerInfo DF empty/None for Player ID: {player_id}")
                static_p_info_fallback = await asyncio.to_thread(player_id)
                if static_p_info_fallback and static_p_info_fallback.get('full_name'):
                    player_name_bio = static_p_info_fallback['full_name']
                else:
                    player_name_bio = f"Player ID {player_id}"
                    api_error_occurred_flag = True

            # Fetch Base Stats
            logger.debug(f"Fetching PlayerDashboard (Base) for Player ID: {player_id}, S: {current_season}")
            base_stats_df, base_err = await asyncio.to_thread(
                _blocking_fetch_player_dashboard, player_id, current_season, 'Base', 'PerGame', API_TIMEOUT_SECONDS
            )
            if base_err:
                logger.error(f"API Error PlayerDashboard (Base) (ID {player_id}): {base_err}", exc_info=True)
                api_error_occurred_flag = True
            elif base_stats_df is not None and not base_stats_df.empty:
                logger.debug(f"Base Stats DF (Player ID {player_id}, S:{current_season}):\n{base_stats_df.head().to_string(index=False)}")
                s_row = base_stats_df.iloc[0]
                gp = _format_player_stat('GP', s_row.get('GP'))
                mpg = _format_player_stat('MIN', s_row.get('MIN'))
                ppg = _format_player_stat('PTS', s_row.get('PTS'))
                rpg = _format_player_stat('REB', s_row.get('REB'))
                apg = _format_player_stat('AST', s_row.get('AST'))
                spg = _format_player_stat('STL', s_row.get('STL'))
                bpg = _format_player_stat('BLK', s_row.get('BLK'))
                tov = _format_player_stat('TOV', s_row.get('TOV'))
                plus_minus = _format_player_stat('PLUS_MINUS', s_row.get('PLUS_MINUS'))
                fg_pct = _format_player_stat('FG_PCT', s_row.get('FG_PCT'))
                fg3_pct = _format_player_stat('FG3_PCT', s_row.get('FG3_PCT'))
                ft_pct = _format_player_stat('FT_PCT', s_row.get('FT_PCT'))
            else:
                logger.warning(f"Base PlayerDashboard empty for ID {player_id}, S:{current_season} (No API error reported).")

            # Fetch Advanced Stats
            logger.debug(f"Fetching PlayerDashboard (Advanced) for Player ID: {player_id}, S: {current_season}")
            adv_stats_df, adv_err = await asyncio.to_thread(
                _blocking_fetch_player_dashboard, player_id, current_season, 'Advanced', 'PerGame', API_TIMEOUT_SECONDS
            )
            if adv_err:
                logger.error(f"API Error PlayerDashboard (Advanced) (ID {player_id}): {adv_err}", exc_info=True)
                api_error_occurred_flag = True
            elif adv_stats_df is not None and not adv_stats_df.empty:
                logger.debug(f"Advanced Stats DF (Player ID {player_id}, S:{current_season}):\n{adv_stats_df.head().to_string(index=False)}")
                adv_row = adv_stats_df.iloc[0]
                efg_pct = _format_player_stat('EFG_PCT', adv_row.get('EFG_PCT'))
                ts_pct = _format_player_stat('TS_PCT', adv_row.get('TS_PCT'))
                usg_pct = _format_player_stat('USG_PCT', adv_row.get('USG_PCT'))
            else:
                logger.warning(f"Advanced PlayerDashboard empty for ID {player_id}, S:{current_season} (No API error reported).")
            
            # --- Create Embed ---
            logger.debug(f"Creating embed for Player ID: {player_id} (Display Name: '{player_name_bio}')")
            
            embed_title = player_name_bio
            if jersey_bio != "N/A" and jersey_bio: embed_title = f"{jersey_bio} {embed_title}"

            desc_parts_list = []
            if team_name_bio != "N/A": desc_parts_list.append(f"**{team_name_bio}** ({team_abbr_bio if team_abbr_bio != 'N/A' else '?'})")
            if position_bio != "N/A" and position_bio: desc_parts_list.append(position_bio)
            if height_bio != "N/A" and height_bio: desc_parts_list.append(height_bio)
            if weight_bio != "N/A" and weight_bio: desc_parts_list.append(f"{weight_bio} lbs")
            
            final_desc_str = " | ".join(filter(None, desc_parts_list)) or "Bio details unavailable."

            player_profile_embed = discord.Embed(
                title=f"🏀 {embed_title.strip()}", description=final_desc_str,
                color=discord.Color.gold() # Or from constants/team color
            )

            player_headshot_url = self.bot._get_player_headshot_url(player_id) # Assumed synchronous
            if player_headshot_url: player_profile_embed.set_thumbnail(url=player_headshot_url)

            stat_field_separator = " | "
            player_profile_embed.add_field(name=f"📊 Per Game Stats ({current_season})", value=(
                f"PPG: **`{ppg}`**{stat_field_separator}RPG: **`{rpg}`**{stat_field_separator}APG: **`{apg}`**\n"
                f"SPG: **`{spg}`**{stat_field_separator}BPG: **`{bpg}`**{stat_field_separator}TOV: **`{tov}`**"
            ), inline=False)

            player_profile_embed.add_field(name="🎯 Shooting Efficiency", value=(
                f"FG%: **`{fg_pct}`**{stat_field_separator}3P%: **`{fg3_pct}`**{stat_field_separator}FT%: **`{ft_pct}`**\n"
                f"eFG%: **`{efg_pct}`**{stat_field_separator}TS%: **`{ts_pct}`**"
            ), inline=False)

            player_profile_embed.add_field(name="⚙️ Usage & Impact", value=(
                f"GP: **`{gp}`**{stat_field_separator}MPG: **`{mpg}`**\n"
                f"USG%: **`{usg_pct}`**{stat_field_separator}Season +/-: **`{plus_minus}`**"
            ), inline=False)

            footer_final_text = f"Data for {current_season} via NBA API (stats.nba.com)"
            if api_error_occurred_flag:
                footer_final_text += " | ⚠️ Some data might be missing or incomplete."
            player_profile_embed.set_footer(text=footer_final_text)
            player_profile_embed.timestamp = discord.utils.utcnow()

            logger.info(f"Successfully prepared embed for Player ID {player_id}. Sending response.")
            await interaction.followup.send(embed=player_profile_embed)

        except Exception as e:
            logger.error(f"General error in /player command processing for input '{player_identifier}' (ID: {player_id}): {e}", exc_info=True)
            err_msg_user = f"An unexpected error occurred while fetching stats for '{resolved_player_name_for_error}'."
            if api_error_occurred_flag: err_msg_user += " There may have been issues retrieving some data from the API."
            
            critical_error_embed = discord.Embed(title="❌ Command Execution Error", description=err_msg_user, color=discord.Color.red())
            try: await interaction.followup.send(embed=critical_error_embed, ephemeral=True)
            except discord.HTTPException as send_final_err: logger.error(f"Failed to send final error embed for /player: {send_final_err}")

async def setup(bot: 'NBAStatsBot'):
    required_attrs = ['config', 'player_data']
    missing_attrs = [attr for attr in required_attrs if not hasattr(bot, attr)]
    if missing_attrs:
        logger.error(f"PlayerStats Cog: Bot instance missing attributes: {', '.join(missing_attrs)}. Not loading.")
        return

    required_methods = ['_find_player', '_get_player_headshot_url']
    missing_bot_methods = [m for m in required_methods if not hasattr(bot, m) or not callable(getattr(bot, m))]
    if missing_bot_methods:
        logger.error(f"PlayerStats Cog: Bot instance missing callable methods: {', '.join(missing_bot_methods)}. Not loading.")
        return

    await bot.add_cog(PlayerStats(bot))
    logger.info("PlayerStats Cog loaded successfully.")