import discord
from discord.ext import commands
from discord import app_commands, Interaction # Explicitly import Interaction
import logging
from typing import Dict, List # For type hints

logger = logging.getLogger(__name__)

# Glossary Data (Could be moved to a separate file if it grows very large)
# Consider adding more terms like AST/TOV Ratio, Pace, etc.
GLOSSARY_TERMS: Dict[str, str] = {
    "PTS (Points)": "The total number of points scored by a player or team.",
    "REB (Rebounds)": "Securing the ball after a missed shot. Can be Offensive (OREB) or Defensive (DREB).",
    "AST (Assists)": "A pass that directly leads to a made basket by a teammate.",
    "STL (Steals)": "Taking the ball away from an opponent.",
    "BLK (Blocks)": "Deflecting an opponent's shot attempt.",
    "TOV (Turnovers)": "Losing possession of the ball to the opposing team.",
    "FG% (Field Goal Percentage)": "Percentage of shots made from the field (2-pointers and 3-pointers).",
    "3P% (3-Point Percentage)": "Percentage of shots made from beyond the three-point line.",
    "FT% (Free Throw Percentage)": "Percentage of free throws made.",
    "GP (Games Played)": "The number of games a player has participated in.",
    "MPG (Minutes Per Game)": "The average number of minutes a player plays per game.",
    "+/- (Plus/Minus)": "The team's point differential when a specific player is on the court.",
    "PER (Player Efficiency Rating)": "A per-minute rating developed by John Hollinger, summing up all a player's positive accomplishments, subtracting the negative ones, and returning a per-minute rating of a player's performance.",
    "TS% (True Shooting Percentage)": "A measure of shooting efficiency that takes into account 2-point field goals, 3-point field goals, and free throws. Formula: PTS / (2 * (FGA + 0.44 * FTA)).",
    "eFG% (Effective Field Goal Percentage)": "Adjusts field goal percentage to account for the fact that three-point field goals are worth more than two-point field goals. Formula: (FGM + 0.5 * 3PM) / FGA.",
    "USG% (Usage Percentage/Rate)": "An estimate of the percentage of team plays 'used' by a player while they were on the floor. A play is 'used' when a player takes a shot, gets to the free-throw line, or turns the ball over.",
    "OffRtg (Offensive Rating)": "An estimate of points produced (for an individual) or scored (for a team) per 100 possessions.",
    "DefRtg (Defensive Rating)": "An estimate of points allowed per 100 possessions by a player or team.",
    "NetRtg (Net Rating)": "The difference between a player's/team's Offensive Rating and Defensive Rating (OffRtg - DefRtg). Represents point differential per 100 possessions.",
    "AST Ratio (Assist Ratio)": "The percentage of a player's possessions that end in an assist.",
    "TOV Ratio (Turnover Ratio/Percentage)": "An estimate of turnovers committed per 100 plays.", # Or TM_TOV_PCT for team
    "REB% (Rebound Percentage)": "An estimate of the percentage of missed shots a player (or team) rebounds while they are on the floor.",
    "PACE (Pace Factor)": "An estimate of the number of possessions a team (or a player's team while they are on the floor) has per 48 minutes."
}

# Max terms per glossary page if paginating in the future
GLOSSARY_ITEMS_PER_PAGE = 10

class General(commands.Cog):
    """Cog for general bot commands like help and glossary."""

    def __init__(self, bot: commands.Bot): # Or 'NBAStatsBot'
        self.bot: commands.Bot = bot       # Or 'NBAStatsBot'

    @app_commands.command(name='commands', description='Shows the list of available commands and their usage.')
    async def commands_slash(self, interaction: Interaction):
        """Displays an embed with all available slash commands and their parameters."""
        await interaction.response.defer(ephemeral=True) # Defer response, make it ephemeral

        help_embed = discord.Embed(
            title="📋 Bot Commands Guide",
            description="Here's a list of available commands and how to use them:",
            color=discord.Color.teal() # Changed color for variety
        )

        try:
            # Get global commands. For guild-specific, pass guild_id to get_commands
            # Prefer get_commands if tree is synced, fallback to fetch_commands if necessary
            app_cmds: List[app_commands.AppCommand] = self.bot.tree.get_commands()
            if not app_cmds:
                logger.info("/commands: No commands found via get_commands, attempting fetch_commands.")
                # fetch_commands is an API call, use sparingly or ensure it's needed
                # app_cmds = await self.bot.tree.fetch_commands() # Uncomment if you need this fallback

            if app_cmds:
                sorted_cmds = sorted(app_cmds, key=lambda c: c.name)
                for cmd in sorted_cmds:
                    # Handle top-level commands and command groups
                    if isinstance(cmd, app_commands.Command):
                        desc = cmd.description or "No description provided."
                        param_str_parts = []
                        for option in cmd.options: # cmd.options is the standard way
                            # Use display_name if available (for choices, localized names etc.)
                            name_to_display = option.display_name or option.name
                            param_str_parts.append(f"`{'<' if option.required else '['}{name_to_display}{'>' if option.required else ']'}`")
                        
                        param_display_str = " ".join(param_str_parts)
                        command_signature = f"`/{cmd.name}{' ' + param_display_str if param_display_str else ''}`"
                        help_embed.add_field(name=command_signature, value=desc, inline=False)

                    elif isinstance(cmd, app_commands.Group):
                        # For command groups, list subcommands
                        group_description = cmd.description or f"Commands related to {cmd.name}."
                        sub_cmds_strs = []
                        for sub_cmd in sorted(cmd.commands, key=lambda sc: sc.name):
                            sub_param_str_parts = []
                            for option in sub_cmd.options:
                                name_to_display = option.display_name or option.name
                                sub_param_str_parts.append(f"`{'<' if option.required else '['}{name_to_display}{'>' if option.required else ']'}`")
                            sub_param_display_str = " ".join(sub_param_str_parts)
                            sub_cmds_strs.append(f"`/{cmd.name} {sub_cmd.name}{' ' + sub_param_display_str if sub_param_display_str else ''}`: {sub_cmd.description or 'No description.'}")
                        
                        if sub_cmds_strs:
                            help_embed.add_field(name=f"↔️ Group: `/{cmd.name}`", value=f"{group_description}\n" + "\n".join(sub_cmds_strs), inline=False)
                        else:
                             help_embed.add_field(name=f"↔️ Group: `/{cmd.name}`", value=group_description, inline=False)


                if len(help_embed.fields) == 0: # Should not happen if app_cmds is populated
                    help_embed.description = "No slash commands seem to be registered or an error occurred fetching them."

            else:
                logger.warning("/commands: No slash commands found even after attempting fetch (or fetch disabled).")
                help_embed.description = (
                    "Could not dynamically load the command list at this time.\n"
                    "Please try common commands like `/today`, `/player [name]`, `/team [name]`."
                )
        except Exception as e:
            logger.error(f"Error building the /commands list: {e}", exc_info=True)
            help_embed.description = (
                "An error occurred while generating the command list.\n"
                "You can try common commands like `/today`, `/player`, `/team`, `/injuries`, etc."
            )
        
        bot_user = self.bot.user
        if bot_user:
            help_embed.set_footer(text=f"{bot_user.name} | Your NBA Stats Companion", icon_url=bot_user.display_avatar.url)
        else:
            help_embed.set_footer(text="Your NBA Stats Companion")
            
        await interaction.followup.send(embed=help_embed)


    @app_commands.command(name='glossary', description='Explains common NBA statistical terms.')
    async def glossary_slash(self, interaction: Interaction):
        """Displays definitions for common NBA statistics."""
        await interaction.response.defer(ephemeral=True) # Ephemeral for user-specific info

        # Sort terms alphabetically for consistent display
        sorted_glossary_terms = sorted(GLOSSARY_TERMS.items())

        embed = discord.Embed(
            title="🏀 NBA Stats Glossary",
            description="Common (and some advanced) NBA statistics explained:",
            color=discord.Color.dark_green() # Changed color
        )

        fields_added = 0
        for term, definition in sorted_glossary_terms:
            if fields_added >= 25: # Discord embed field limit
                embed.description += "\n\n*More terms exist, but the display limit for this message was reached.*"
                logger.warning(f"/glossary: Reached embed field limit. Only displayed {fields_added} terms.")
                break
            
            # Ensure definition fits within field value limits (1024 chars)
            definition_display = (definition[:1020] + "...") if len(definition) > 1024 else definition
            embed.add_field(name=term, value=definition_display, inline=False)
            fields_added += 1

        embed.set_footer(text="Definitions based on common NBA terminology.")
        await interaction.followup.send(embed=embed)


async def setup(bot: commands.Bot): # Or 'NBAStatsBot'
    await bot.add_cog(General(bot))
    logger.info("General Cog loaded successfully.")