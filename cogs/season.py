# cogs/season.py

from discord import app_commands, Interaction
from discord.ext import commands
import logging

# Correct import paths for your helper modules
from helpers.nba_helper import get_season_standings # Assuming this is an async function
from helpers.embed_builder import error_embed, format_standings_embed # error_embed now takes title and description

logger = logging.getLogger(__name__)

# For type hinting your bot instance if it's a custom class
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    # Adjust this path if your bot's main file is named differently or in a different location
    # For example, if your main bot file is 'bot.py' in the parent directory:
    from ..bot import NBAStatsBot
    # If it's 'main.py' in the same directory as cogs (unlikely but possible structure):
    # from main import NBAStatsBot


class SeasonStandings(commands.Cog):
    """Cog for displaying NBA season standings."""

    def __init__(self, bot: 'NBAStatsBot'): # Use the type hint
        self.bot: 'NBAStatsBot' = bot

    @app_commands.command(name="season", description="Displays the current NBA season standings.")
    async def season_standings_command(self, interaction: Interaction):
        """Fetches and displays the current NBA season standings."""
        await interaction.response.defer(ephemeral=False)
        logger.info(f"/season command invoked by {interaction.user} (ID: {interaction.user.id}) in guild {interaction.guild_id or 'DM'}")

        try:
            # Get the current season from the bot's config
            current_season_str = self.bot.config.get("CURRENT_SEASON")
            if not current_season_str:
                logger.error("CURRENT_SEASON not found in bot config.")
                await interaction.followup.send(embed=error_embed(
                    title="Configuration Error",
                    description="The current season is not configured for the bot. Please contact an administrator."
                ))
                return

            # Pass the current_season_str to get_season_standings
            # Ensure get_season_standings is defined as an async function if it makes API calls
            standings_data = await get_season_standings(season=current_season_str)

            if standings_data is None:
                logger.warning("get_season_standings returned None. Sending error embed.")
                await interaction.followup.send(embed=error_embed(
                    title="Data Retrieval Error",
                    description="Could not retrieve the latest season standings at this time. Please try again later."
                ))
                return

            embed = format_standings_embed(standings_data)
            if embed is None: # Should ideally not happen if format_standings_embed returns an error_embed on failure
                logger.error("format_standings_embed returned None. This indicates an issue with embed generation.")
                await interaction.followup.send(embed=error_embed(
                    title="Display Error",
                    description="Could not format the season standings for display. Please report this issue."
                ))
                return

            await interaction.followup.send(embed=embed)

        except Exception as e:
            # Log the full exception details for debugging
            logger.exception(f"An unexpected error occurred in /season command for user {interaction.user.id}:")
            # Send a generic error message to the user
            await interaction.followup.send(embed=error_embed(
                title="Unexpected Error",
                description="An unexpected error occurred while trying to fetch the season standings. The developers have been notified."
            ))

# Standard setup function for cogs
async def setup(bot: 'NBAStatsBot'): # Use the type hint
    await bot.add_cog(SeasonStandings(bot))
    logger.info("Cog 'SeasonStandings' loaded successfully.")