# cogs/general.py
import discord
from discord.ext import commands
from discord import app_commands
import logging

logger = logging.getLogger(__name__)

# Glossary Data (Expand as needed)
GLOSSARY_TERMS = {
    "Points (PTS)": "The total number of points scored by a player or team.",
    "Rebounds (REB)": "Securing the ball after a missed shot. Can be Offensive (OREB) or Defensive (DREB).",
    "Assists (AST)": "A pass that directly leads to a made basket by a teammate.",
    "Steals (STL)": "Taking the ball away from an opponent.",
    "Blocks (BLK)": "Deflecting an opponent's shot attempt.",
    "Field Goal % (FG%)": "Percentage of shots made from the field (excluding free throws).",
    "3-Point % (3P%)": "Percentage of shots made from beyond the three-point line.",
    "Free Throw % (FT%)": "Percentage of free throws made.",
    "Plus/Minus (+/-)": "The point differential for the team while a player is on the court.",
    "Player Efficiency Rating (PER)": "A complex stat created by John Hollinger that attempts to boil down all of a player's contributions into one number per minute.",
    "True Shooting % (TS%)": "A measure of shooting efficiency that takes into account 2-point field goals, 3-point field goals, and free throws.",
    "Usage Rate (USG%)": "An estimate of the percentage of team plays used by a player while they were on the floor.",
    "Offensive Rating (OffRtg)": "Points scored per 100 possessions by a player or team.",
    "Defensive Rating (DefRtg)": "Points allowed per 100 possessions by a player or team.",
    "Net Rating (NetRtg)": "The difference between Offensive Rating and Defensive Rating (OffRtg - DefRtg).",
    "Player Impact Estimate (PIE)": "A measure of a player's overall statistical contribution against the total statistics in games they play in."
}


class General(commands.Cog):
    """Cog for general bot commands like help and glossary."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name='commands', description='Shows the list of available commands.')
    async def commands_slash(self, interaction: discord.Interaction):
        """Displays an embed with all available slash commands."""
        # ... (Logic from previous version is generally fine) ...
        help_embed = discord.Embed(title="📋 Available Slash Commands", description="Use these commands to get NBA stats and info:", color=discord.Color.blue())
        try:
            commands_list = self.bot.tree.get_commands()
            if not commands_list:
                 commands_list = await self.bot.tree.fetch_commands()

            if commands_list:
                for cmd in sorted(commands_list, key=lambda c: c.name):
                    desc = cmd.description or "No description."
                    name_with_args = f"`/{cmd.name}`"
                    try:
                        params = getattr(cmd, '_params', getattr(cmd, 'options', None))
                        if params:
                           if isinstance(params, dict): params = params.values() # Adjust if _params is dict
                           args_str = " ".join(f"`<{p.display_name or p.name}>`" for p in params if p.required)
                           opt_args_str = " ".join(f"`[{p.display_name or p.name}]`" for p in params if not p.required)
                           if args_str: name_with_args += f" {args_str}"
                           if opt_args_str: name_with_args += f" {opt_args_str}"
                    except Exception as param_e:
                        logger.warning(f"Could not format params for {cmd.name}: {param_e}")
                    help_embed.add_field(name=name_with_args, value=desc, inline=False)
            else: # Fallback
                help_embed.description = "Could not dynamically load commands. Defaulting:"
                # Add default fields if needed
        except Exception as e:
            logger.error(f"Error building help command: {e}", exc_info=True)
            help_embed.description = "Error loading commands. Defaulting:"
            # Add default fields if needed

        bot_avatar = self.bot.user.display_avatar.url if self.bot.user else None
        help_embed.set_footer(text=f"{self.bot.user.name if self.bot.user else 'Bot'}", icon_url=bot_avatar)
        await interaction.response.send_message(embed=help_embed, ephemeral=True)


    @app_commands.command(name='glossary', description='Explains common NBA statistical terms.')
    async def glossary_slash(self, interaction: discord.Interaction):
        """Displays definitions for NBA stats."""
        await interaction.response.defer(ephemeral=True)
        embed = discord.Embed(
            title="🏀 NBA Stats Glossary",
            description="Definitions for common (and some advanced) NBA statistics:",
            color=discord.Color.green()
        )

        for term, definition in GLOSSARY_TERMS.items():
             # Ensure field value doesn't exceed limit (1024)
             embed.add_field(name=term, value=definition[:1024], inline=False)
             if len(embed.fields) >= 25:
                 embed.description += "\n*More terms exist, but the embed limit was reached.*"
                 break

        embed.set_footer(text="Data sourced from common NBA knowledge.")
        await interaction.followup.send(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(General(bot))
    logger.info("General Cog loaded.")