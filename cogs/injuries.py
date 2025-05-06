import discord
from discord import app_commands
from discord.ext import commands
from typing import Dict, List, Tuple, Optional
from discord.ui import View, Button
import math
import logging
# import traceback # Not explicitly used
import asyncio
from datetime import datetime, timedelta # Added timedelta for cache expiry

# --- Import from utils ---
from utils.injury_fetcher import InjuryReportFetcher
from utils.team_mapper import find_espn_logo_code # Assuming this maps to ESPN's team concept
from utils.emoji_mapper import get_injury_emoji
# from helpers.constants import ESPN_LOGO_BASE_URL # Example if you have this constant

logger = logging.getLogger(__name__)

# --- Constants for this Cog ---
INJURY_CACHE_DURATION_MINUTES = 10 # Cache injury data for 10 minutes
ESPN_LOGO_BASE_URL = "https://a.espncdn.com/i/teamlogos/nba/500/{logo_code}.png" # Centralize URL

# --- InjuryPaginator View ---
class InjuryPaginator(View):
    def __init__(self, injuries: List[Dict], team_name: str, team_logo: Optional[str], author_id: int, timeout: int = 180): # Increased timeout slightly
        super().__init__(timeout=timeout)
        self.injuries: List[Dict] = injuries if injuries else []
        self.team_name: str = team_name
        self.team_logo: Optional[str] = team_logo
        self.page: int = 0
        self.per_page: int = 5 # Max 5 injuries per page for readability
        self.author_id: int = author_id
        self.total_pages: int = math.ceil(len(self.injuries) / self.per_page) if self.injuries else 1
        self.update_view_buttons() # Initial button setup

    def update_view_buttons(self):
        """Clears and re-adds buttons with updated disabled states."""
        self.clear_items()

        prev_button = Button(
            label="⏮️ Previous",
            style=discord.ButtonStyle.secondary,
            custom_id="injury_prev_page",
            disabled=(self.page == 0)
        )
        prev_button.callback = self.go_to_previous
        self.add_item(prev_button)

        page_indicator = Button(
            label=f"Page {self.page + 1}/{self.total_pages}",
            style=discord.ButtonStyle.secondary,
            custom_id="injury_page_indicator",
            disabled=True # Just a label
        )
        self.add_item(page_indicator)

        next_button = Button(
            label="Next ⏭️",
            style=discord.ButtonStyle.secondary,
            custom_id="injury_next_page",
            disabled=(self.page >= self.total_pages - 1)
        )
        next_button.callback = self.go_to_next
        self.add_item(next_button)

    def get_current_page_embed(self) -> discord.Embed:
        """Creates the embed for the current page of injuries."""
        embed = discord.Embed(
            title=f"🩹 {self.team_name} Injury Report", # Page info moved to button
            color=discord.Color.orange() # Or team-specific color if available
        )
        if self.team_logo:
            embed.set_thumbnail(url=self.team_logo)
        embed.set_footer(text=f"Source: ESPN API | Page {self.page + 1} of {self.total_pages}")

        if not self.injuries:
            embed.description = "No reported injuries found for this team via ESPN API."
            return embed

        start_idx = self.page * self.per_page
        end_idx = start_idx + self.per_page
        current_page_injuries_list = self.injuries[start_idx:end_idx]

        if not current_page_injuries_list:
            embed.description = "No injuries to display on this page (this shouldn't happen)."
        else:
            for injury_item in current_page_injuries_list:
                status = injury_item.get("status", "Unknown Status")
                emoji = get_injury_emoji(status)
                player_name = injury_item.get("name", "Unknown Player")
                comment = injury_item.get("comment", "No additional details provided.")
                
                # Truncate comment if too long for field value
                comment_display = (comment[:1020] + '...') if len(comment) > 1024 else comment

                embed.add_field(
                    name=f"{emoji} {player_name} — {status}",
                    value=comment_display,
                    inline=False
                )
        return embed

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Ensures only the original command user can interact with the paginator."""
        if interaction.user.id == self.author_id:
            return True
        await interaction.response.send_message(
            "Sorry, only the person who ran the command can change pages.",
            ephemeral=True
        )
        return False

    async def _update_message(self, interaction: discord.Interaction):
        """Helper to edit the message with the new embed and view."""
        self.update_view_buttons() # Update button states (like page number)
        try:
            await interaction.response.edit_message(embed=self.get_current_page_embed(), view=self)
        except discord.NotFound:
            logger.warning(f"InjuryPaginator: Failed to edit message for {interaction.custom_id} - message likely deleted.")
            self.stop() # Stop the view if message is gone
        except Exception as e:
            logger.error(f"InjuryPaginator: Error editing message for {interaction.custom_id}: {e}", exc_info=True)

    async def go_to_previous(self, interaction: discord.Interaction):
        if self.page > 0:
            self.page -= 1
            await self._update_message(interaction)
        else:
            # Acknowledge, button should be disabled anyway
            await interaction.response.defer()

    async def go_to_next(self, interaction: discord.Interaction):
        if self.page < self.total_pages - 1:
            self.page += 1
            await self._update_message(interaction)
        else:
            # Acknowledge, button should be disabled anyway
            await interaction.response.defer()

    async def on_timeout(self):
        """Called when the view times out. Optionally disable buttons."""
        logger.debug(f"InjuryPaginator for {self.team_name} timed out for user {self.author_id}.")
        # Optionally, try to edit the original message to remove/disable buttons
        # This requires storing the original message or interaction response
        # For simplicity, we'll let Discord handle graying them out.


# --- Main Injuries Cog ---
class Injuries(commands.Cog):
    def __init__(self, bot: commands.Bot): # Or 'NBAStatsBot'
        self.bot: commands.Bot = bot # Or 'NBAStatsBot'
        self.injury_fetcher = InjuryReportFetcher()
        self._all_injuries_cache: Optional[Dict[str, List[Dict]]] = None
        self._cache_timestamp: Optional[datetime] = None
        self._cache_lock = asyncio.Lock() # Lock for fetching to prevent dogpiling

    async def cog_unload(self):
        """Closes the aiohttp session when the cog is unloaded."""
        await self.injury_fetcher.close_session()
        logger.info("InjuriesCog unloaded, fetcher session closed.")

    async def get_all_injury_data(self, force_refresh: bool = False) -> Tuple[Optional[Dict[str, List[Dict]]], Optional[str]]:
        """
        Gets all injury data, using a time-based cache.
        Includes a lock to prevent multiple concurrent fetches if cache is stale.
        """
        async with self._cache_lock: # Acquire lock before checking/fetching
            now = discord.utils.utcnow() # Timezone-aware UTC datetime
            if not force_refresh and self._all_injuries_cache and self._cache_timestamp:
                if (now - self._cache_timestamp) < timedelta(minutes=INJURY_CACHE_DURATION_MINUTES):
                    logger.info("Using cached injury data.")
                    return self._all_injuries_cache, None
                else:
                    logger.info("Injury cache expired.")
            
            logger.info(f"{'Forcing refresh of' if force_refresh else 'Fetching fresh'} injury data from API.")
            data, error = await self.injury_fetcher.fetch_injuries()

            if data is not None:
                self._all_injuries_cache = data
                self._cache_timestamp = now
                logger.info(f"Injury data cached successfully. Timestamp: {self._cache_timestamp}")
                return data, None # Return data and no error
            else:
                # Don't update cache on error, keep stale data if any, or clear it
                # self._all_injuries_cache = None # Optional: clear cache on fetch error
                # self._cache_timestamp = None
                logger.error(f"Failed to fetch fresh injury data. Error: {error}")
                return self._all_injuries_cache, error # Return stale cache (if any) and error

    async def team_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> List[app_commands.Choice[str]]:
        choices: List[app_commands.Choice[str]] = []
        # Fetch data (will use cache if fresh)
        all_data, fetch_error = await self.get_all_injury_data()

        if fetch_error or not all_data:
            logger.warning(f"Team autocomplete: Injury data fetch failed or empty. Error: {fetch_error}")
            # Try to provide choices from bot's general team data if API fails
            if hasattr(self.bot, 'nba_data'):
                nba_data_teams = self.bot.nba_data.get('teams_list', [])
                if nba_data_teams:
                    logger.debug("Team autocomplete: Falling back to bot.nba_data for team names.")
                    for team_info in nba_data_teams:
                        full_name = team_info.get('full_name')
                        if full_name and current.lower() in full_name.lower():
                            choices.append(app_commands.Choice(name=full_name, value=full_name)) # Value is full name
                            if len(choices) >= 25: break
                    return choices
            return [] # Return empty if fallback also fails

        # Use keys from the fetched (and possibly cached) injury data
        # These keys are the team names as per the injury API source (e.g., ESPN team names)
        api_team_names = list(all_data.keys())
        count = 0
        current_lower = current.lower()

        # Prioritize names starting with current string
        for name in sorted(api_team_names): # Sort for consistent order
            if name.lower().startswith(current_lower):
                choices.append(app_commands.Choice(name=name, value=name)) # Value is the API's team name
                count += 1
                if count >= 25: break
        
        # Fill with names containing current string
        if count < 25:
            for name in sorted(api_team_names):
                if current_lower in name.lower() and not name.lower().startswith(current_lower):
                    # Avoid adding duplicates
                    if not any(c.value == name for c in choices):
                        choices.append(app_commands.Choice(name=name, value=name))
                        count += 1
                        if count >= 25: break
        return choices

    @app_commands.command(name="injuries", description="Get the latest NBA injury report for a specific team.") # Renamed for clarity
    @app_commands.describe(team_name="Enter team name (e.g., Los Angeles Lakers, Boston Celtics)")
    @app_commands.autocomplete(team_name=team_autocomplete)
    async def injury_report_command(self, interaction: discord.Interaction, team_name: str):
        await interaction.response.defer(ephemeral=False)
        logger.info(f"/injuries command invoked by {interaction.user.name} for team: '{team_name}'")

        try:
            all_injuries_data, fetch_error_msg = await self.get_all_injury_data()

            if fetch_error_msg or all_injuries_data is None:
                error_description = fetch_error_msg or "Could not retrieve injury data at this time. The cache might be empty or an API error occurred."
                # Assuming you have an error_embed builder
                # from helpers.embed_builder import error_embed (or similar)
                err_embed = discord.Embed(title="Injury Report Error", description=error_description, color=discord.Color.red())
                await interaction.followup.send(embed=err_embed, ephemeral=True)
                return

            # Use the team_mapper to find the canonical name and logo code
            # find_espn_logo_code expects a list of known API team names to match against.
            api_team_names_list = list(all_injuries_data.keys())
            logo_code, canonical_name_from_api = find_espn_logo_code(team_name, api_team_names_list)

            if not canonical_name_from_api:
                # Attempt to find a close match or suggest from bot.nba_data if API name not found
                # This part depends on how robust find_espn_logo_code is
                logger.warning(f"Team '{team_name}' not found directly in injury API keys. Canonical name: {canonical_name_from_api}")
                await interaction.followup.send(
                    f"❌ Team '{team_name}' not found in the injury data source. "
                    "Please use the autocomplete suggestions or check the team name.",
                    ephemeral=True
                )
                return

            team_injuries_list = all_injuries_data.get(canonical_name_from_api, [])
            team_display_name = canonical_name_from_api # Use the name as returned by the API/mapper
            team_logo_url = ESPN_LOGO_BASE_URL.format(logo_code=logo_code) if logo_code else None

            if not team_injuries_list:
                embed = discord.Embed(
                    title=f"✅ {team_display_name} Injury Report",
                    description="No reported injuries found for this team from ESPN.",
                    color=discord.Color.green()
                )
                if team_logo_url:
                    embed.set_thumbnail(url=team_logo_url)
                embed.set_footer(text="Source: ESPN API")
                await interaction.followup.send(embed=embed)
            elif len(team_injuries_list) <= InjuryPaginator.per_page: # If fits on one page
                embed = discord.Embed(
                    title=f"🩹 {team_display_name} Injury Report",
                    color=discord.Color.orange()
                )
                if team_logo_url:
                    embed.set_thumbnail(url=team_logo_url)
                embed.set_footer(text="Source: ESPN API")
                for injury in team_injuries_list:
                    status = injury.get("status", "Unknown")
                    emoji = get_injury_emoji(status)
                    player = injury.get("name", "N/A")
                    comment = injury.get("comment", "No details")
                    comment_display = (comment[:1020] + '...') if len(comment) > 1024 else comment
                    embed.add_field(
                        name=f"{emoji} {player} — {status}",
                        value=comment_display,
                        inline=False
                    )
                await interaction.followup.send(embed=embed)
            else: # Use Paginator for more than `per_page` injuries
                logger.info(f"Using paginator for {team_display_name} injuries ({len(team_injuries_list)} found).")
                paginator_view = InjuryPaginator(
                    injuries=team_injuries_list,
                    team_name=team_display_name,
                    team_logo=team_logo_url,
                    author_id=interaction.user.id
                )
                initial_embed = paginator_view.get_current_page_embed()
                await interaction.followup.send(embed=initial_embed, view=paginator_view)

        except Exception as e:
            logger.exception(f"Unexpected critical error in /injuries command for team '{team_name}':", exc_info=True)
            # Assuming an error_embed builder
            err_embed = discord.Embed(
                title="❌ Command Error",
                description=f"An unexpected error occurred while processing the injury report for '{team_name}'. Our team has been notified.",
                color=discord.Color.red()
            )
            # Check if interaction is done before sending followup.
            # It should be if defer() was successful.
            await interaction.followup.send(embed=err_embed, ephemeral=True)

async def setup(bot: commands.Bot): # Or 'NBAStatsBot'
    # Ensure necessary utility modules are accessible; Python's import system handles this.
    # If InjuryReportFetcher or other utils raise ImportErrors, the bot won't load this cog.
    # A basic check for the fetcher instantiation capability:
    try:
        InjuryReportFetcher() # Try to instantiate to catch early config/init errors in fetcher
    except Exception as e:
        logger.error(f"Injuries Cog: Failed to instantiate InjuryReportFetcher: {e}. Cog will not be loaded.", exc_info=True)
        return

    # Check for team_mapper and emoji_mapper (can't easily check functions without calling)
    # Trust that imports work or Python will raise ImportError earlier.

    await bot.add_cog(Injuries(bot))
    logger.info("Injuries Cog loaded successfully.")