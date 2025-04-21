
from discord import app_commands, Interaction
from discord.ext import commands
import logging
from helpers.nba_helper import get_season_standings # Correct import path
from helpers.embed_builder import format_season_standings_embed, error_embed

logger = logging.getLogger(__name__)

class SeasonStandings(commands.Cog):
    """Cog for displaying NBA season standings."""
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="season", description="Displays the current NBA season standings.")
    async def season(self, interaction: Interaction):
        """Fetches and displays the current NBA season standings."""
        await interaction.response.defer()
        logger.info(f"Season standings requested by {interaction.user}")
        try:
            standings_data = await get_season_standings() # Assuming helper is async
            if standings_data is None:
                 logger.warning("get_season_standings returned None.")
                 # *** Use error embed builder ***
                 await interaction.followup.send(embed=error_embed(
                    "API Error", "Could not retrieve standings data."
                 ))
                 return

            # *** Use the imported embed builder ***
            embed = format_season_standings_embed(standings_data)
            await interaction.followup.send(embed=embed)

        except Exception as e:
            logger.exception(f"Error occurred in /season command for {interaction.user}:", exc_info=e)
            # *** Use error embed builder ***
            await interaction.followup.send(embed=error_embed(
                 "Unexpected Error", "An error occurred processing the standings."
            ))

# Standard setup function for cogs
async def setup(bot: commands.Bot):
    await bot.add_cog(SeasonStandings(bot))
    logger.info("Cog 'SeasonStandings' loaded successfully.")