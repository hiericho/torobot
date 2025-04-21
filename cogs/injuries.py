# cogs/injuries.py
import discord
from discord import app_commands
from discord.ext import commands
# --- ADD THIS IMPORT ---
from typing import Dict, List, Tuple, Optional
# ----------------------
# --- Import from utils ---
from utils.injury_fetcher import InjuryReportFetcher # Import the new fetcher
from utils.team_mapper import find_espn_logo_code # Import the mapping helper
from utils.emoji_mapper import get_injury_emoji # Import the emoji helper
# -------------------------
from discord.ui import View, Button
import math
import logging
import traceback
import asyncio # For timeout handling with aiohttp
from datetime import datetime

logger = logging.getLogger(__name__)

# --- InjuryPaginator View ---
class InjuryPaginator(View):
    # Added type hints here too
    def __init__(self, injuries: List[Dict], team_name: str, team_logo: Optional[str], author_id: int, timeout: int = 120):
        super().__init__(timeout=timeout)
        self.injuries = injuries if injuries else [] # Ensure it's a list
        self.team_name = team_name
        self.team_logo = team_logo
        self.page = 0
        self.per_page = 5
        self.author_id = author_id
        # Ensure total_pages is at least 1, even if no injuries
        self.total_pages = math.ceil(len(self.injuries) / self.per_page) if self.injuries else 1
        self.update_view()

    def update_view(self):
        """Updates the embed and buttons based on the current page."""
        self.clear_items()
        # Previous Button
        prev_button = Button(label="⏮️ Previous", style=discord.ButtonStyle.secondary, custom_id="prev_page", disabled=(self.page == 0))
        prev_button.callback = self.go_to_previous
        self.add_item(prev_button)

        # Next Button
        next_button = Button(label="Next ⏭️", style=discord.ButtonStyle.secondary, custom_id="next_page", disabled=(self.page >= self.total_pages - 1))
        next_button.callback = self.go_to_next
        self.add_item(next_button)

    def get_embed(self) -> discord.Embed:
        """Creates the embed for the current page."""
        embed = discord.Embed(
            title=f"🩹 {self.team_name} Injury Report (Page {self.page+1}/{self.total_pages})",
            color=discord.Color.orange()
        )
        if self.team_logo:
            embed.set_thumbnail(url=self.team_logo)
        embed.set_footer(text="Source: ESPN API")

        if not self.injuries:
             embed.description = "No reported injuries found via ESPN API."
             return embed

        start_index = self.page * self.per_page
        end_index = start_index + self.per_page
        current_page_injuries = self.injuries[start_index:end_index]

        if not current_page_injuries:
             # This case means page number is out of sync, should ideally not happen
             embed.description = "No injuries on this page (data sync issue?)."
        else:
            for injury in current_page_injuries:
                # Use .get() for safety, provide defaults
                status = injury.get("status", "Unknown")
                emoji = get_injury_emoji(status) # Use helper
                player_name = injury.get("name", "Unknown Player")
                comment = injury.get("comment", "No details")
                embed.add_field(
                    name=f"{emoji} {player_name} - {status}",
                    value=comment[:1024],
                    inline=False
                )
        return embed

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.author_id:
            return True
        else:
            await interaction.response.send_message("Sorry, only the person who ran the command can change pages.", ephemeral=True)
            return False

    async def go_to_previous(self, interaction: discord.Interaction):
        if self.page > 0:
            self.page -= 1
            self.update_view()
            try:
                await interaction.response.edit_message(embed=self.get_embed(), view=self)
            except discord.NotFound:
                logger.warning("Failed to edit message for pagination (previous) - message likely deleted.")
            except Exception as e:
                logger.error(f"Error editing message for pagination (previous): {e}", exc_info=True)
        else:
             await interaction.response.defer() # Acknowledge interaction

    async def go_to_next(self, interaction: discord.Interaction):
         if self.page < self.total_pages - 1:
            self.page += 1
            self.update_view()
            try:
                await interaction.response.edit_message(embed=self.get_embed(), view=self)
            except discord.NotFound:
                 logger.warning("Failed to edit message for pagination (next) - message likely deleted.")
            except Exception as e:
                 logger.error(f"Error editing message for pagination (next): {e}", exc_info=True)
         else:
             await interaction.response.defer() # Acknowledge interaction


# --- Main Injuries Cog ---
class Injuries(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.injury_fetcher = InjuryReportFetcher() # Instantiate the fetcher
        self.all_injuries_cache: Optional[Dict[str, List[Dict]]] = None # Type hint cache
        self.cache_timestamp: Optional[datetime] = None # Use datetime for timestamp if needed

    async def cog_unload(self):
        await self.injury_fetcher.close_session()

    # Added type hints here
    async def get_all_injury_data(self) -> Tuple[Optional[Dict[str, List[Dict]]], Optional[str]]:
         """Gets all injury data, using a simple time-based cache."""
         # Use discord.utils.utcnow() for timezone-aware comparison if needed
         # Or just compare timestamps directly if using time.time()
         # For simplicity, let's skip precise timestamp logic for now unless needed
         # A simple check: if cache exists, use it for a short duration
         # More robust: Use datetime and check expiry

         # Basic cache check (no timestamp for now)
         if self.all_injuries_cache:
              logger.info("Using cached injury data (no expiry check).")
              return self.all_injuries_cache, None

         logger.info("Fetching fresh injury data from API.")
         data, error = await self.injury_fetcher.fetch_injuries()
         if data is not None: # Cache only on success
              self.all_injuries_cache = data
              # self.cache_timestamp = discord.utils.utcnow() # Add timestamp if implementing expiry
         return data, error

    # --- Autocomplete using API Team Names ---
    # Added type hints here
    async def team_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> List[app_commands.Choice[str]]:
        """Autocompletes using team names from the fetched API data."""
        choices: List[app_commands.Choice[str]] = [] # Type hint choices
        all_data, error = await self.get_all_injury_data()
        if error or not all_data:
             logger.warning(f"Cannot autocomplete teams: Injury data fetch failed or was empty. Error: {error}")
             return []

        api_team_names = list(all_data.keys())
        count = 0
        current_lower = current.lower()

        for name in sorted(api_team_names):
             if current_lower in name.lower():
                  choices.append(app_commands.Choice(name=name, value=name))
                  count += 1
                  if count >= 25: break

        return choices


    @app_commands.command(name="injury", description="Get the latest NBA injury report for a specific team.")
    @app_commands.describe(team="Enter team name (e.g., Los Angeles Lakers, Boston Celtics)")
    @app_commands.autocomplete(team=team_autocomplete)
    async def injury_slash(self, interaction: discord.Interaction, team: str):
        """Fetches and displays the ESPN injury report using API data."""
        # ... (defer logic remains the same) ...
        try:
            await interaction.response.defer(ephemeral=False)
        except Exception as defer_err:
             logger.error(f"Failed to defer interaction for /injury '{team}': {defer_err}", exc_info=True)
             return

        embed = None
        try:
            # ... (Fetch all data logic remains the same) ...
            all_injuries_data, error_msg = await self.get_all_injury_data()

            if error_msg or all_injuries_data is None:
                error_desc = error_msg or "Failed to retrieve injury data cache."
                embed = discord.Embed(title="Injury Report Error", description=error_desc, color=discord.Color.red())
                await interaction.followup.send(embed=embed, ephemeral=True)
                return

            # ... (Find team and logo code logic remains the same) ...
            api_team_names = list(all_injuries_data.keys())
            logo_code, canonical_team_name = find_espn_logo_code(team, api_team_names)

            if not canonical_team_name:
                await interaction.followup.send(f"❌ Team '{team}' not found in injury data. Please use autocomplete or check the name.", ephemeral=True)
                return

            # ... (Get injuries, logo, name logic remains the same) ...
            injuries = all_injuries_data.get(canonical_team_name, [])
            team_logo = f"https://a.espncdn.com/i/teamlogos/nba/500/{logo_code}.png" if logo_code else None
            team_name = canonical_team_name

            # ... (Create Embed or Paginator logic remains the same) ...
            if not injuries:
                 embed = discord.Embed(
                    title=f"✅ {team_name} Injury Report",
                    description="No reported injuries found via ESPN API.",
                    color=discord.Color.green()
                 )
                 if team_logo: embed.set_thumbnail(url=team_logo)
                 embed.set_footer(text="Source: ESPN API")
                 await interaction.followup.send(embed=embed)

            elif len(injuries) <= 5:
                embed = discord.Embed(
                    title=f"🩹 {team_name} Injury Report",
                    description=f"Current reported injuries ({len(injuries)} players):",
                    color=discord.Color.orange()
                )
                if team_logo: embed.set_thumbnail(url=team_logo)
                embed.set_footer(text="Source: ESPN API")
                for injury in injuries:
                    emoji = get_injury_emoji(injury.get("status", "Default"))
                    embed.add_field(
                        name=f"{emoji} {injury.get('name','?')} - {injury.get('status','?')}",
                        value=injury.get('comment','?')[:1024],
                        inline=False
                    )
                await interaction.followup.send(embed=embed)
            else:
                 logger.info(f"Using paginator for {team_name} injuries ({len(injuries)} found).")
                 view = InjuryPaginator(
                     injuries=injuries,
                     team_name=team_name,
                     team_logo=team_logo,
                     author_id=interaction.user.id
                 )
                 initial_embed = view.get_embed()
                 await interaction.followup.send(embed=initial_embed, view=view)

        # ... (Error handling remains the same) ...
        except Exception as e:
            logger.error(f"Unexpected error in /injury command for '{team}':", exc_info=True)
            error_embed = discord.Embed(title="❌ Command Error", description=f"An unexpected error occurred while processing the injury report for '{team}'.", color=discord.Color.red())
            try:
                if interaction.is_done(): await interaction.followup.send(embed=error_embed, ephemeral=True)
                else: await interaction.response.send_message(embed=error_embed, ephemeral=True)
            except Exception as send_e: logger.error(f"Failed to send error embed for /injury: {send_e}")


# --- Setup Function ---
async def setup(bot: commands.Bot):
    # ... (library checks remain the same) ...
    lib_error = False
    try:
        import aiohttp
        import bs4
    except ImportError:
        logger.error("Missing required libraries ('aiohttp', 'beautifulsoup4') for Injuries cog. Cog will not be loaded.")
        logger.error("Please install them: pip install aiohttp beautifulsoup4")
        lib_error = True
    if not hasattr(bot, 'helpers') or 'get_team_abbreviation' not in bot.helpers:
         logger.error("Bot instance missing 'helpers' dict or required team helpers. Injuries cog may fail.")
         # lib_error = True
    if lib_error:
         return

    await bot.add_cog(Injuries(bot))
    logger.info("Injuries Cog loaded.")