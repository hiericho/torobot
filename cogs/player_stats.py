# cogs/player_stats.py
import discord
from discord.ext import commands
from discord import app_commands
import pandas as pd
import logging
import traceback
# Need typing for hints if used elsewhere
from typing import List, Optional, Dict
import math # For checking NaN

# NBA API modules
from nba_api.stats.static import players # For autocomplete fallback
# We need more endpoints for detailed stats
from nba_api.stats.endpoints import commonplayerinfo, playerprofilev2, playerdashboardbygeneralsplits

logger = logging.getLogger(__name__)

# Define a reasonable timeout for API calls within this cog
API_TIMEOUT = 20 # seconds

class PlayerStats(commands.Cog):
    """Cog for NBA Player statistics commands."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Access shared data/config stored on the bot instance using getattr for safety
        self.nba_data = getattr(bot, 'nba_data', {})
        self.player_data = getattr(bot, 'player_data', {})
        self.config = getattr(bot, 'config', {})
        self.helpers = getattr(bot, 'helpers', {})


    # --- AUTOCOMPLETE (Code from previous version) ---
    async def player_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        """Provides autocomplete suggestions for active NBA players."""
        choices: List[app_commands.Choice[str]] = []
        if not current: return choices

        count = 0
        current_lower = current.lower()
        player_data_local = getattr(self, 'player_data', {})
        if not player_data_local: logger.warning("Autocomplete: self.player_data empty.")

        # Search preload
        for name_lower, player_info in player_data_local.items():
            if current_lower in name_lower:
                 player_name = player_info.get('full_name', '?')
                 player_id = player_info.get('id')
                 if player_id is not None:
                      choices.append(app_commands.Choice(name=player_name, value=str(player_id)))
                      count += 1
                      if count >= 25: break

        # Fallback API search
        if player_data_local and count < 5 and len(current) >= 3:
            logger.info(f"Autocomplete: Preload count low ({count}), trying API for '{current}'")
            try:
                api_players = players.find_players_by_full_name(current)
                if api_players:
                    for player in api_players:
                         player_id = player.get('id'); player_name = player.get('full_name')
                         if player_id is not None and player_name and \
                            not any(c.value == str(player_id) for c in choices):
                              choices.append(app_commands.Choice(name=player_name, value=str(player_id)))
                              count += 1
                              if count >= 25: break
            except Exception as e: logger.error(f"Player autocomplete API error: {e}", exc_info=True)

        try: choices.sort(key=lambda c: c.name)
        except Exception as sort_e: logger.error(f"Error sorting autocomplete choices: {sort_e}")
        logger.debug(f"Player autocomplete returning {len(choices)} choices for '{current}'.")
        return choices[:25]


    # --- ENHANCED PLAYER STATS COMMAND ---
    @app_commands.command(name='player', description='Shows detailed stats for a specific NBA player.')
    @app_commands.describe(player='Start typing the player name...')
    @app_commands.autocomplete(player=player_autocomplete)
    async def player_slash(self, interaction: discord.Interaction, player: str):
        """Displays detailed current season stats for the specified player."""
        logger.info(f"Received /player command for input: '{player}' from {interaction.user}")
        try:
            await interaction.response.defer(ephemeral=False)
            logger.debug(f"Deferred interaction for /player '{player}'")
        except Exception as defer_err:
            logger.error(f"CRITICAL: Failed to defer interaction for /player '{player}': {defer_err}", exc_info=True)
            return

        embed = None
        try:
            player_id = None
            # --- Player ID Resolution ---
            logger.debug(f"Attempting to resolve player ID for '{player}'")
            try:
                player_id = int(player)
                logger.debug(f"Input '{player}' is integer ID: {player_id}")
            except ValueError:
                logger.warning(f"Input '{player}' not an ID, attempting lookup via helper.")
                find_player_helper = self.helpers.get('find_player')
                if find_player_helper:
                    player_dict = find_player_helper(player)
                    if player_dict and 'id' in player_dict:
                        player_id = player_dict['id']; logger.info(f"Resolved '{player}' to ID: {player_id}")
                    else: logger.warning(f"Helper find_player returned no result/ID for '{player}'.")
                else: logger.error("Helper 'find_player' not found.")

            if not player_id:
                await interaction.followup.send(f"❗ Could not find player: '{player}'. Use autocomplete.", ephemeral=True); return

            logger.info(f"Fetching info and stats for player ID: {player_id}")
            current_season = self.config.get('CURRENT_SEASON', 'N/A')

            # --- Initialize Stat Variables ---
            player_name = "N/A"; team_name = "N/A"; team_abbr = "N/A"; position = "N/A"
            height = "N/A"; weight = "N/A"; jersey = "N/A"
            ppg, rpg, apg, spg, bpg, tov, mpg, gp, plus_minus = ("N/A",) * 9
            fg_pct, fg3_pct, ft_pct, efg_pct, ts_pct, usg_pct = ("N/A",) * 6
            api_error_flag = False # Flag for partial errors

            # --- Fetch Common Player Info (Bio Details) ---
            logger.debug(f"Fetching CommonPlayerInfo for {player_id}")
            try:
                 info = commonplayerinfo.CommonPlayerInfo(player_id=player_id, timeout=API_TIMEOUT)
                 p_info_df = info.common_player_info.get_data_frame()
                 if not p_info_df.empty:
                      p = p_info_df.iloc[0]
                      first = p.get('FIRST_NAME', ''); last = p.get('LAST_NAME', '')
                      player_name = f"{first} {last}".strip() or "Unknown Player"
                      city = p.get('TEAM_CITY', ''); team_n = p.get('TEAM_NAME', '')
                      team_name = f"{city} {team_n}".strip() or "N/A"
                      team_abbr = p.get('TEAM_ABBREVIATION') if pd.notna(p.get('TEAM_ABBREVIATION')) else "N/A"
                      position = p.get('POSITION') if pd.notna(p.get('POSITION')) else "N/A"
                      height = p.get('HEIGHT') if pd.notna(p.get('HEIGHT')) else "N/A"
                      weight = p.get('WEIGHT') if pd.notna(p.get('WEIGHT')) else "N/A"
                      jersey = f"#{p.get('JERSEY')}" if pd.notna(p.get('JERSEY')) else "N/A"
                 else: logger.warning(f"CommonPlayerInfo empty for {player_id}"); api_error_flag = True
            except Exception as e: logger.error(f"API Error CommonPlayerInfo: {e}", exc_info=True); api_error_flag = True

            # --- Fetch Per Game Stats (PlayerProfileV2) ---
            logger.debug(f"Fetching PlayerProfileV2 (PerGame) for {player_id}, season {current_season}")
            try:
                 profile = playerprofilev2.PlayerProfileV2(player_id=player_id, per_mode36='PerGame', timeout=API_TIMEOUT)
                 season_totals_df = profile.season_totals_regular_season.get_data_frame()
                 cs_stats_df = season_totals_df[season_totals_df['SEASON_ID'] == current_season]
                 if not cs_stats_df.empty:
                      s = cs_stats_df.iloc[0]
                      if pd.notna(s.get('GP')): gp = str(int(s.get('GP'))) # Games Played
                      if pd.notna(s.get('MIN')): mpg = f"{s.get('MIN'):.1f}" # Minutes
                      if pd.notna(s.get('PTS')): ppg = f"{s.get('PTS'):.1f}" # Points
                      if pd.notna(s.get('REB')): rpg = f"{s.get('REB'):.1f}" # Rebounds
                      if pd.notna(s.get('AST')): apg = f"{s.get('AST'):.1f}" # Assists
                      if pd.notna(s.get('STL')): spg = f"{s.get('STL'):.1f}" # Steals
                      if pd.notna(s.get('BLK')): bpg = f"{s.get('BLK'):.1f}" # Blocks
                      if pd.notna(s.get('TOV')): tov = f"{s.get('TOV'):.1f}" # Turnovers
                      if pd.notna(s.get('PLUS_MINUS')): plus_minus = f"{s.get('PLUS_MINUS'):+.1f}" # +/- per game
                      if pd.notna(s.get('FG_PCT')): fg_pct = f"{s.get('FG_PCT')*100:.1f}%"
                      if pd.notna(s.get('FG3_PCT')): fg3_pct = f"{s.get('FG3_PCT')*100:.1f}%"
                      if pd.notna(s.get('FT_PCT')): ft_pct = f"{s.get('FT_PCT')*100:.1f}%"
                 else:
                      logger.info(f"No PerGame stats found via PlayerProfileV2 for {player_id} in {current_season}")
                      # Keep stats as "N/A" if no row found
            except Exception as e: logger.error(f"API Error PlayerProfileV2: {e}", exc_info=True); api_error_flag = True

            # --- Fetch Advanced Stats (PlayerDashboard) ---
            logger.debug(f"Fetching PlayerDashboard (Advanced) for {player_id}, season {current_season}")
            try:
                 dashboard = playerdashboardbygeneralsplits.PlayerDashboardByGeneralSplits(
                      player_id=player_id,
                      season=current_season,
                      measure_type_detailed_defense='Advanced', # For TS%, USG%
                      per_mode_detailed='PerGame', # Or Per100 if needed, PerGame often has the rates too
                      timeout=API_TIMEOUT
                 )
                 adv_df = dashboard.overall_player_dashboard.get_data_frame()
                 if not adv_df.empty:
                      adv = adv_df.iloc[0]
                      if pd.notna(adv.get('EFG_PCT')): efg_pct = f"{adv.get('EFG_PCT')*100:.1f}%"
                      if pd.notna(adv.get('TS_PCT')): ts_pct = f"{adv.get('TS_PCT')*100:.1f}%"
                      if pd.notna(adv.get('USG_PCT')): usg_pct = f"{adv.get('USG_PCT')*100:.1f}%"
                 else:
                      logger.warning(f"Advanced dashboard empty for {player_id}, season {current_season}")
                      # Don't set api_error_flag here, maybe player didn't qualify for adv stats

            except Exception as e: logger.error(f"API Error PlayerDashboard: {e}", exc_info=True); api_error_flag = True


            # --- Create Pretty Embed ---
            logger.debug(f"Creating embed for player {player_id} ({player_name})")
            # Attempt to get player name from helper if needed
            if player_name in ["N/A", "Unknown Player"]:
                 find_player_helper = self.helpers.get('find_player')
                 if find_player_helper:
                     player_dict_h = find_player_helper(str(player_id))
                     if player_dict_h and player_dict_h.get('full_name'): player_name = player_dict_h['full_name']

            embed_color = discord.Color.dark_gold() # Example color
            embed = discord.Embed(
                title=f"🏀 {jersey} {player_name}", # Jersey # in title
                description=f"**{team_name}** ({team_abbr}) | {position} | {height} | {weight}", # Bio in description
                color=embed_color
            )

            # Get and set the thumbnail (Headshot)
            headshot_url_helper = self.helpers.get('get_player_headshot_url')
            if headshot_url_helper:
                headshot_url = headshot_url_helper(player_id)
                if headshot_url: embed.set_thumbnail(url=headshot_url)
                else: logger.warning(f"Could not get headshot URL for player {player_id}")
            else: logger.error("Helper 'get_player_headshot_url' not found.")

            # --- Fields with Emojis and Compact Layout ---
            separator = " | " # Separator for inline stats

            # Field 1: Core Per Game Stats
            core_stats_value = (
                f"📈 PPG: **`{ppg}`**{separator}"
                f" rebounds RPG: **`{rpg}`**{separator}"
                f"🤝 APG: **`{apg}`**\n"
                f"✋ SPG: **`{spg}`**{separator}"
                f"🚫 BPG: **`{bpg}`**{separator}"
                f" Turnover TOV: **`{tov}`**"
            )
            embed.add_field(name=f"📊 Per Game Averages ({current_season})", value=core_stats_value, inline=False)

            # Field 2: Shooting Efficiency
            shooting_value = (
                f" FG%: **`{fg_pct}`**{separator}"
                f" 3P%: **`{fg3_pct}`**\n"
                f" FT%: **`{ft_pct}`**{separator}"
                f" TS%: **`{ts_pct}`**"
                 # eFG% can be added if desired: f"eFG%: **`{efg_pct}`**"
            )
            embed.add_field(name="🎯 Shooting Efficiency", value=shooting_value, inline=True)

            # Field 3: Context & Impact
            context_value = (
                f"🎮 GP: **`{gp}`**{separator}"
                f"⏱️ MPG: **`{mpg}`**\n"
                f"📊 USG%: **`{usg_pct}`**{separator}"
                f" +/-: **`{plus_minus}`**"
            )
            embed.add_field(name="⚙️ Context / Impact", value=context_value, inline=True)


            # --- Footer ---
            footer_text = "Data via NBA API"
            if api_error_flag: footer_text += " | ⚠️ Some info/stats might be missing."
            embed.set_footer(text=footer_text)

            # --- Send the final response ---
            logger.info(f"Sending final response for /player '{player}' (ID: {player_id})")
            await interaction.followup.send(embed=embed)
            logger.debug(f"Successfully sent response for /player '{player}'")

        except Exception as e:
            logger.error(f"Unexpected error in /player command execution for input '{player}':", exc_info=True)
            try:
                error_embed = discord.Embed(title="❌ Command Error", description=f"An unexpected error occurred processing stats for '{player}'.", color=discord.Color.red())
                if interaction.is_done(): await interaction.followup.send(embed=error_embed, ephemeral=True)
                else: await interaction.response.send_message(embed=error_embed, ephemeral=True)
            except Exception as send_e: logger.error(f"Failed to send error embed for /player after main exception: {send_e}")


async def setup(bot: commands.Bot):
    # Checks remain the same
    if not hasattr(bot, 'player_data'): logger.error("Bot missing 'player_data'. PlayerStats cog requires preloaded data."); # return
    if not hasattr(bot, 'helpers') or not all(k in bot.helpers for k in ['find_player', 'get_player_headshot_url']): logger.error("Bot missing 'helpers' dict or required player helpers. PlayerStats cog may fail."); # return
    await bot.add_cog(PlayerStats(bot))
    logger.info("PlayerStats Cog loaded.")