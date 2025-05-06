from discord import app_commands, Interaction
from discord.ext import commands
import logging

# Assuming NBAStatsBot is your custom bot class defined elsewhere
# If not, and you're just using commands.Bot, that's fine too.
# from ..bot import NBAStatsBot # Example if bot.py is one level up

# Correct import paths for your helper modules
from helpers.nba_helper import get_season_standings
from helpers.embed_builder import format_season_standings_embed, error_embed

logger = logging.getLogger(__name__)
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from ..bot import NBAStatsBot # Adjust path as needed

class SeasonStandings(commands.Cog):
    """Cog for displaying NBA season standings."""

    # Use string literal for forward reference if NBAStatsBot is defined in a file
    # that might import this cog, to avoid circular imports.
    # If get_season_standings and embed_builder don't need custom bot attributes,
    # commands.Bot is perfectly fine.
    def __init__(self, bot: 'NBAStatsBot'): # Or bot: commands.Bot
        self.bot: 'NBAStatsBot' = bot       # Or self.bot: commands.Bot = bot

    @app_commands.command(name="season", description="Displays the current NBA season standings.")
    async def season_standings_command(self, interaction: Interaction): # Renamed for clarity from just "season"
        """Fetches and displays the current NBA season standings."""
        await interaction.response.defer(ephemeral=False) # ephemeral=False is default but good to be explicit
        logger.info(f"/season command invoked by {interaction.user} (ID: {interaction.user.id}) in guild {interaction.guild_id or 'DM'}")

        try:
            # Assuming get_season_standings is an async function that handles its own API calls
            standings_data = await get_season_standings()

            if standings_data is None:
                logger.warning("get_season_standings returned None. Sending error embed.")
                await interaction.followup.send(embed=error_embed(
                    title="Data Retrieval Error",
                    message="Could not retrieve the latest season standings at this time. Please try again later."
                ))
                return

            # format_season_standings_embed should ideally handle cases where standings_data might be malformed
            embed = format_season_standings_embed(standings_data)
            if embed is None: # If embed builder itself can return None on error
                logger.error("format_season_standings_embed returned None. This indicates an issue with embed generation.")
                await interaction.followup.send(embed=error_embed(
                    title="Display Error",
                    message="Could not format the season standings for display. Please report this issue."
                ))
                return

            await interaction.followup.send(embed=embed)

        except Exception as e:
            # Log the full exception details for debugging
            logger.exception(f"An unexpected error occurred in /season command for user {interaction.user.id}:")
            # Send a generic error message to the user
            await interaction.followup.send(embed=error_embed(
                title="Unexpected Error",
                message="An unexpected error occurred while trying to fetch the season standings. The developers have been notified."
            ))

# Standard setup function for cogs
async def setup(bot: 'NBAStatsBot'): # Or bot: commands.Bot
    await bot.add_cog(SeasonStandings(bot))
    logger.info("Cog 'SeasonStandings' loaded successfully.")