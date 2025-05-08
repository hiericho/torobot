# cogs/injuries.py
import discord
from discord import app_commands, Interaction
from discord.ext import commands
from typing import Dict, List, Tuple, Optional, Any # Added Any
from discord.ui import View, Button
import math
import logging
import asyncio
from datetime import datetime, timedelta

# --- Import from utils ---
# Ensure these paths are correct relative to your project structure
# If 'utils' is a top-level directory:
from utils.injury_fetcher import InjuryReportFetcher
from utils.team_mapper import find_espn_logo_code
from utils.emoji_mapper import get_injury_emoji
# from helpers.embed_builder import error_embed # Assuming you have this for consistency

logger = logging.getLogger(__name__)

# --- Constants for this Cog ---
INJURY_CACHE_DURATION_MINUTES = 10 # Cache injury data for 10 minutes
PAGINATOR_TIMEOUT_SECONDS = 180    # How long paginator buttons stay active
SINGLE_PAGE_INJURY_LIMIT = 5       # Max injuries before paginating
ESPN_LOGO_BASE_URL = "https://a.espncdn.com/i/teamlogos/nba/500/{logo_code}.png"

# --- Fallback Error Embed (if not importing from a shared embed_builder) ---
def _local_error_embed(title: str, description: str) -> discord.Embed:
    """A local fallback error embed creator."""
    return discord.Embed(title=f"❌ {title}", description=description, color=discord.Color.red())

# --- InjuryPaginator View ---
class InjuryPaginator(View):
    def __init__(self, injuries: List[Dict[str, Any]], team_name: str, team_logo_url: Optional[str], author_id: int):
        super().__init__(timeout=PAGINATOR_TIMEOUT_SECONDS)
        self.injuries: List[Dict[str, Any]] = injuries if injuries else []
        self.team_name: str = team_name
        self.team_logo_url: Optional[str] = team_logo_url
        self.current_page_index: int = 0 # Renamed for clarity
        self.items_per_page: int = SINGLE_PAGE_INJURY_LIMIT # Use the same constant
        self.author_id: int = author_id
        self.total_pages: int = math.ceil(len(self.injuries) / self.items_per_page) if self.injuries else 1
        
        self._update_buttons() # Initial button setup

    def _update_buttons(self):
        """Clears and re-adds buttons with updated states and page indicator."""
        self.clear_items()

        # Previous Button
        prev_button = Button(
            label="⏮️ Previous",
            style=discord.ButtonStyle.secondary,
            custom_id="injury_prev_page",
            disabled=(self.current_page_index == 0)
        )
        prev_button.callback = self.go_to_previous_page
        self.add_item(prev_button)

        # Page Indicator Button (Disabled)
        page_indicator = Button(
            label=f"Page {self.current_page_index + 1}/{self.total_pages}",
            style=discord.ButtonStyle.secondary, # Keep it consistent or use .primary
            custom_id="injury_page_indicator",
            disabled=True # Acts purely as a label
        )
        self.add_item(page_indicator)

        # Next Button
        next_button = Button(
            label="Next ⏭️",
            style=discord.ButtonStyle.secondary,
            custom_id="injury_next_page",
            disabled=(self.current_page_index >= self.total_pages - 1)
        )
        next_button.callback = self.go_to_next_page
        self.add_item(next_button)

    def create_page_embed(self) -> discord.Embed:
        """Creates the embed for the current page of injuries."""
        embed = discord.Embed(
            title=f"🩹 {self.team_name} Injury Report",
            color=discord.Color.orange()
        )
        if self.team_logo_url:
            embed.set_thumbnail(url=self.team_logo_url)
        
        embed.set_footer(text=f"Source: ESPN API | Page {self.current_page_index + 1} of {self.total_pages}")
        embed.timestamp = discord.utils.utcnow()


        if not self.injuries:
            embed.description = "No reported injuries found for this team via ESPN API."
            return embed

        start_index = self.current_page_index * self.items_per_page
        end_index = start_index + self.items_per_page
        current_page_injuries_list = self.injuries[start_index:end_index]

        if not current_page_injuries_list:
            embed.description = "No injuries to display on this page (data may have changed)."
        else:
            for injury_item in current_page_injuries_list:
                status = injury_item.get("status", "Unknown Status")
                emoji = get_injury_emoji(status) # From utils.emoji_mapper
                player_name = injury_item.get("name", "Unknown Player")
                comment = injury_item.get("comment", "No additional details provided.")
                
                comment_display = (comment[:1020] + '...') if len(comment) > 1024 else comment

                embed.add_field(
                    name=f"{emoji} {player_name} — {status}",
                    value=comment_display,
                    inline=False
                )
        return embed

    async def interaction_check(self, interaction: Interaction) -> bool:
        """Ensures only the original command user can interact with the paginator."""
        if interaction.user.id == self.author_id:
            return True
        await interaction.response.send_message(
            "Sorry, only the person who ran the command can change pages.",
            ephemeral=True
        )
        return False

    async def _edit_message_with_new_page(self, interaction: Interaction):
        """Helper to edit the message with the new embed and view."""
        self._update_buttons() # Update button states (like page number and disabled status)
        try:
            await interaction.response.edit_message(embed=self.create_page_embed(), view=self)
        except discord.NotFound:
            logger.warning(f"InjuryPaginator: Failed to edit message for {interaction.custom_id} - message likely deleted.")
            self.stop() # Stop the view if the message is gone
        except discord.HTTPException as e: # Catch other Discord API errors
            logger.error(f"InjuryPaginator: Discord API error editing message for {interaction.custom_id}: {e}", exc_info=True)
            # Optionally try to inform user, or just stop
            self.stop()


    async def go_to_previous_page(self, interaction: Interaction):
        if self.current_page_index > 0:
            self.current_page_index -= 1
            await self._edit_message_with_new_page(interaction)
        else:
            # Button should be disabled, but acknowledge if somehow clicked
            await interaction.response.defer()

    async def go_to_next_page(self, interaction: Interaction):
        if self.current_page_index < self.total_pages - 1:
            self.current_page_index += 1
            await self._edit_message_with_new_page(interaction)
        else:
            # Button should be disabled
            await interaction.response.defer()

    async def on_timeout(self):
        """Called when the view times out. Buttons will be disabled by Discord automatically."""
        logger.debug(f"InjuryPaginator for '{self.team_name}' (Author ID: {self.author_id}) has timed out.")
        # Optionally, you could try to edit the original message to remove the view (buttons)
        # For example:
        # if self.message: # if you store the message upon sending
        #     try:
        #         await self.message.edit(view=None)
        #     except discord.HTTPException:
        #         pass # Message might have been deleted or other issue


# --- Main Injuries Cog ---
class Injuries(commands.Cog):
    def __init__(self, bot: commands.Bot): # Or 'NBAStatsBot' if using custom attributes
        self.bot: commands.Bot = bot
        self.injury_fetcher = InjuryReportFetcher() # From utils.injury_fetcher
        self._all_injuries_cache: Optional[Dict[str, List[Dict[str, Any]]]] = None
        self._cache_timestamp: Optional[datetime] = None
        self._cache_lock = asyncio.Lock()

    async def cog_unload(self):
        """Closes the aiohttp session when the cog is unloaded."""
        await self.injury_fetcher.close_session()
        logger.info("InjuriesCog unloaded, fetcher's aiohttp session closed.")

    async def get_all_injury_data(self, force_refresh: bool = False) -> Tuple[Optional[Dict[str, List[Dict[str, Any]]]], Optional[str]]:
        """
        Gets all injury data, using a time-based cache with an asyncio.Lock.
        Returns (data, error_message_or_none).
        """
        async with self._cache_lock:
            now = discord.utils.utcnow() # Timezone-aware UTC datetime
            if not force_refresh and self._all_injuries_cache and self._cache_timestamp:
                if (now - self._cache_timestamp) < timedelta(minutes=INJURY_CACHE_DURATION_MINUTES):
                    logger.info("Using cached injury data.")
                    return self._all_injuries_cache, None
                else:
                    logger.info(f"Injury cache expired (older than {INJURY_CACHE_DURATION_MINUTES} mins).")
            
            action = "Forcing refresh of" if force_refresh else "Fetching fresh"
            logger.info(f"{action} injury data from API.")
            
            # data will be a dict like {'Team Name': [injuries_list]} or None
            # error will be a string or None
            data, error_msg = await self.injury_fetcher.fetch_injuries()

            if data is not None: # Success
                self._all_injuries_cache = data
                self._cache_timestamp = now
                logger.info(f"Injury data cached/refreshed successfully. Timestamp: {self._cache_timestamp}")
                return data, None
            else: # Error fetching
                logger.error(f"Failed to fetch fresh injury data. Error from fetcher: {error_msg}")
                # Return stale cache if it exists, otherwise None, along with the error message
                return self._all_injuries_cache, error_msg or "Unknown error fetching injury data."

    async def team_autocomplete(
        self, interaction: Interaction, current: str
    ) -> List[app_commands.Choice[str]]:
        """Autocompletes team names using keys from the (cached) injury data."""
        choices: List[app_commands.Choice[str]] = []
        if not current: return choices # Don't show anything if no input

        all_data, fetch_error = await self.get_all_injury_data()

        if fetch_error or not all_data:
            logger.warning(f"Team autocomplete: Injury data fetch failed or was empty. Error: {fetch_error}")
            # Fallback: Try using team names from the bot's main nba_data if available
            # This depends on self.bot having an 'nba_data' attribute structured as expected
            if hasattr(self.bot, 'nba_data') and isinstance(self.bot.nba_data, dict):
                teams_list_from_bot = self.bot.nba_data.get('teams_list', [])
                if teams_list_from_bot:
                    logger.debug("Team autocomplete: Falling back to bot.nba_data for team names.")
                    for team_info in teams_list_from_bot:
                        full_name = team_info.get('full_name')
                        if full_name and current.lower() in full_name.lower():
                            # Value for autocomplete should ideally be what the command expects.
                            # If the command uses ESPN names, this fallback might need mapping.
                            choices.append(app_commands.Choice(name=full_name, value=full_name))
                            if len(choices) >= 25: break
                    return choices[:25]
            return [] # Return empty if main source and fallback fail

        # Primary source: Team names from the injury API data
        api_team_names = sorted(list(all_data.keys())) # Sort for consistent suggestion order
        
        current_lower = current.lower()
        # Prioritize starts_with matches
        for name in api_team_names:
            if name.lower().startswith(current_lower):
                if not any(c.value == name for c in choices): # Avoid duplicates
                    choices.append(app_commands.Choice(name=name, value=name)) # Value is the API's team name
                    if len(choices) >= 25: break
        
        # Then add contains matches if space permits
        if len(choices) < 25:
            for name in api_team_names:
                if current_lower in name.lower() and not name.lower().startswith(current_lower):
                    if not any(c.value == name for c in choices): # Avoid duplicates
                        choices.append(app_commands.Choice(name=name, value=name))
                        if len(choices) >= 25: break
        
        return choices[:25] # Ensure not more than 25 choices

    @app_commands.command(name="injuries", description="Get the latest NBA injury report for a specific team (via ESPN).")
    @app_commands.describe(team_input="Enter team name (e.g., Los Angeles Lakers, Boston Celtics)")
    @app_commands.autocomplete(team_input=team_autocomplete) # Use the refined autocomplete
    async def injury_report_command(self, interaction: Interaction, team_input: str):
        await interaction.response.defer(ephemeral=False)
        logger.info(f"/injuries command invoked by {interaction.user.name} (ID: {interaction.user.id}) for team: '{team_input}'")

        try:
            all_injuries_data, fetch_error_msg = await self.get_all_injury_data()

            if fetch_error_msg or all_injuries_data is None:
                error_desc = fetch_error_msg or "Could not retrieve injury data. The API might be down or the cache is empty."
                await interaction.followup.send(embed=_local_error_embed("Data Retrieval Failed", error_desc), ephemeral=True)
                return

            # Use the team_mapper to find the canonical name (from ESPN's perspective) and logo code
            api_team_names_list = list(all_injuries_data.keys()) # These are keys like "Boston Celtics", "Los Angeles Lakers" from ESPN
            
            # find_espn_logo_code should ideally return the matched API key (canonical_name) and the logo code
            logo_code_str, canonical_api_team_name = find_espn_logo_code(team_input, api_team_names_list)

            if not canonical_api_team_name:
                logger.warning(f"Team '{team_input}' not mapped to a known API team name. Mapper returned: {canonical_api_team_name}")
                await interaction.followup.send(
                    f"❌ Team '{team_input}' could not be matched to our injury data source. "
                    "Please use one of the autocomplete suggestions or check the spelling.",
                    ephemeral=True
                )
                return

            # Now use the canonical_api_team_name to get injuries
            team_specific_injuries = all_injuries_data.get(canonical_api_team_name, [])
            display_team_name = canonical_api_team_name # Use the name that corresponds to the data
            team_logo_full_url = ESPN_LOGO_BASE_URL.format(logo_code=logo_code_str) if logo_code_str else None


            if not team_specific_injuries:
                no_injuries_embed = discord.Embed(
                    title=f"✅ {display_team_name} Injury Report",
                    description="No reported injuries found for this team from ESPN.",
                    color=discord.Color.green()
                )
                if team_logo_full_url:
                    no_injuries_embed.set_thumbnail(url=team_logo_full_url)
                no_injuries_embed.set_footer(text="Source: ESPN API")
                no_injuries_embed.timestamp = discord.utils.utcnow()
                await interaction.followup.send(embed=no_injuries_embed)
            
            elif len(team_specific_injuries) <= SINGLE_PAGE_INJURY_LIMIT: # Fits on one page
                single_page_embed = discord.Embed(
                    title=f"🩹 {display_team_name} Injury Report",
                    color=discord.Color.orange()
                )
                if team_logo_full_url:
                    single_page_embed.set_thumbnail(url=team_logo_full_url)
                
                for injury in team_specific_injuries:
                    status = injury.get("status", "Unknown")
                    emoji = get_injury_emoji(status)
                    player = injury.get("name", "N/A Player")
                    comment = injury.get("comment", "No details.")
                    comment_display = (comment[:1020] + '...') if len(comment) > 1024 else comment
                    single_page_embed.add_field(
                        name=f"{emoji} {player} — {status}",
                        value=comment_display,
                        inline=False
                    )
                single_page_embed.set_footer(text="Source: ESPN API")
                single_page_embed.timestamp = discord.utils.utcnow()
                await interaction.followup.send(embed=single_page_embed)
            
            else: # Use Paginator
                logger.info(f"Using paginator for '{display_team_name}' injuries ({len(team_specific_injuries)} found).")
                paginator_view = InjuryPaginator(
                    injuries=team_specific_injuries,
                    team_name=display_team_name,
                    team_logo_url=team_logo_full_url,
                    author_id=interaction.user.id
                )
                initial_page_embed = paginator_view.create_page_embed()
                await interaction.followup.send(embed=initial_page_embed, view=paginator_view)

        except Exception as e:
            logger.exception(f"Unexpected critical error in /injuries command for team '{team_input}':", exc_info=True)
            await interaction.followup.send(
                embed=_local_error_embed(
                    "Command Execution Error",
                    f"An unexpected error occurred while processing the injury report for '{team_input}'. Developers have been notified."
                ),
                ephemeral=True
            )

async def setup(bot: commands.Bot): # Or type hint with your specific 'NBAStatsBot'
    # Basic check for utility instantiation
    try:
        # Ensure InjuryReportFetcher can be instantiated (catches missing aiohttp/bs4 implicitly)
        _ = InjuryReportFetcher()
        # You could also add simple checks for your mapper functions if they have init steps
        # or if they rely on external files that might be missing.
    except ImportError as e:
        logger.error(f"Injuries Cog: Missing critical library dependency for InjuryReportFetcher ({e}). Cog will not be loaded.")
        logger.error("Please ensure 'aiohttp' and 'beautifulsoup4' are installed: pip install aiohttp beautifulsoup4")
        return
    except Exception as e:
        logger.error(f"Injuries Cog: Failed to initialize a required utility (e.g., InjuryReportFetcher): {e}. Cog not loaded.", exc_info=True)
        return

    await bot.add_cog(Injuries(bot))
    logger.info("Injuries Cog loaded successfully.")