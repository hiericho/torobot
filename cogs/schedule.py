# cogs/schedule.py
import json
import discord
from discord import app_commands, Interaction
from discord.ext import commands
import aiohttp # Use asynchronous HTTP client
import logging
from datetime import datetime # To potentially format dates/times
import pytz # Added back for timezone info

# Import helpers and constants
# Assuming embed_builder is in helpers
from helpers import embed_builder
from helpers.constants import (
    EMBED_COLOR_GAME, EMOJI_CALENDAR, EMOJI_LIVE,
    EMOJI_CHECK, EMOJI_AWAY, EMOJI_HOME, EMOJI_PIN
    
)
import asyncio

logger = logging.getLogger(__name__)

class TodayCog(commands.Cog):
    """Cog for displaying today's NBA game schedule and results using ESPN API."""
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.session = aiohttp.ClientSession() # Create session for reuse
        logger.info("TodayCog initialized.")

    async def cog_unload(self):
        # Close the session when the cog unloads
        await self.session.close()
        logger.info("TodayCog unloaded, session closed.")

    def _format_game_status(self, status_data: dict) -> str:
        """Formats the status object into a user-friendly string with emoji."""
        if not isinstance(status_data, dict): return "Status Unknown" # Handle invalid input

        status_type = status_data.get('type', {}).get('name', 'STATUS_UNKNOWN')
        status_detail = status_data.get('type', {}).get('detail', '')
        # state = status_data.get('type', {}).get('state', 'pre') # 'pre', 'in', 'post'

        if status_type == 'STATUS_SCHEDULED':
            emoji = EMOJI_CALENDAR
            return f"{emoji} Scheduled - {status_detail}" # Detail often has time
        elif status_type in ('STATUS_IN_PROGRESS', 'STATUS_HALFTIME'):
            emoji = EMOJI_LIVE
            return f"{emoji} Live - {status_detail}" # Detail has clock/period
        elif status_type == 'STATUS_FINAL':
            emoji = EMOJI_CHECK
            # Detail might just say "Final" or "Final/OT"
            final_detail = status_detail
            # Extract OT info if present (ESPN format varies)
            if "/ot" in status_detail.lower():
                 ot_part = status_detail[status_detail.lower().find("/ot"):].upper()
                 final_detail = f"Final{ot_part}"
            return f"{emoji} {final_detail}"
        elif status_type == 'STATUS_POSTPONED':
            return f"⚠️ Postponed - {status_detail}"
        # Add handlers for other statuses like DELAYED, CANCELED if needed
        else:
             return f"ℹ️ Status: {status_detail} ({status_type})" # Fallback

    @app_commands.command(name="today", description="Shows today's NBA game schedule, scores, and locations.")
    async def today_games(self, interaction: Interaction):
        """Fetches and displays info for NBA games scheduled for the current day."""
        await interaction.response.defer()
        logger.info(f"Received /today command from {interaction.user}")

        # Using the specific ESPN JSON endpoint
        url = "http://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"
        headers = {"User-Agent": "DiscordBot/1.0 (Python/aiohttp)"} # Simple UA
        embed = None # Initialize embed

        try:
            logger.debug(f"Fetching today's games from {url}")
            async with self.session.get(url, headers=headers, timeout=15) as response:
                logger.debug(f"ESPN API response status: {response.status}")
                if response.status != 200:
                    logger.error(f"ESPN Scoreboard API failed: Status {response.status}, Response: {await response.text()}")
                    await interaction.followup.send(embed=embed_builder.error_embed(
                        "API Error", f"Could not fetch today's games (Status: {response.status})."
                    ))
                    return

                # Ensure content type is JSON before parsing
                if 'application/json' not in response.headers.get('Content-Type', '').lower():
                     logger.error(f"ESPN API returned non-JSON content type: {response.headers.get('Content-Type')}")
                     logger.error(f"Response Text: {await response.text()[:500]}") # Log beginning of response
                     await interaction.followup.send(embed=embed_builder.error_embed(
                          "API Data Error", "Received unexpected data format from the ESPN API."
                     ))
                     return

                data = await response.json()
                logger.debug("Successfully parsed JSON response from ESPN.")


            # Safely access events list
            events = data.get("events", []) # Use .get with default empty list
            if not events:
                today_str = datetime.now().strftime("%A, %B %d") # Use current date
                logger.info("No events found in ESPN API response for today.")
                await interaction.followup.send(embed=embed_builder.info_embed(
                    "No Games Today", f"Couldn't find any NBA games scheduled for {today_str} on the ESPN scoreboard."
                ))
                return

            # Create the base embed
            embed = embed_builder.create_embed(
                title=f"{EMOJI_CALENDAR} NBA Games - Today",
                color=EMBED_COLOR_GAME,
                timestamp=True # Add timestamp to show when data was fetched
            )
            # Add date extracted from API if available and reliable
            try:
                 api_date_str = data.get('day', {}).get('date') # Format YYYY-MM-DD
                 if api_date_str:
                     api_date = datetime.strptime(api_date_str, '%Y-%m-%d')
                     embed.title = f"{EMOJI_CALENDAR} NBA Games - {api_date.strftime('%A, %B %d')}"
            except Exception as date_e:
                 logger.warning(f"Could not parse date from API header: {date_e}")


            games_added = 0
            logger.info(f"Processing {len(events)} events found in API data.")
            for game in events:
                 # Limit fields to avoid Discord limits
                 if games_added >= 24: # Leave buffer for potential "more games" message
                     logger.warning("Reached embed field limit, stopping game processing.")
                     if embed.footer is None or "More games scheduled" not in embed.footer.text:
                          embed.add_field(name="...", value="More games scheduled today.", inline=False)
                     break # Stop adding games

                 try:
                    game_id = game.get('id', 'UNKNOWN_ID')
                    logger.debug(f"Processing game ID: {game_id}")
                    competition = game.get("competitions", [{}])[0]
                    competitors = competition.get("competitors", [])
                    status_data = game.get("status", {})
                    venue = competition.get("venue", {})

                    # Find home/away teams
                    home_team, away_team = None, None
                    for comp in competitors:
                         if not isinstance(comp, dict): continue # Skip invalid entries
                         if comp.get('homeAway') == 'home': home_team = comp
                         elif comp.get('homeAway') == 'away': away_team = comp

                    if not home_team or not away_team:
                         logger.warning(f"Could not identify home/away teams for game ID {game_id}")
                         continue

                    # Extract team details safely
                    home_name = home_team.get('team', {}).get('displayName', 'Home Team?')
                    away_name = away_team.get('team', {}).get('displayName', 'Away Team?')
                    home_score = home_team.get('score', '')
                    away_score = away_team.get('score', '')

                    # Extract venue details safely
                    stadium_name = venue.get('fullName', 'Unknown Venue')
                    stadium_city = venue.get('address', {}).get('city') # No default needed, handled below
                    location_str = f"{stadium_name}" + (f", {stadium_city}" if stadium_city else "")
                    if location_str == "Unknown Venue": location_str = "" # Hide if truly unknown

                    # Format status
                    status_str = self._format_game_status(status_data)

                    # Build field name and value
                    field_name = f"{EMOJI_AWAY} {away_name} at {EMOJI_HOME} {home_name}"
                    field_value = f"{status_str}\n"

                    # Add score only if game is live or finished and scores exist
                    game_state = status_data.get('type', {}).get('state') # 'pre', 'in', 'post'
                    # Ensure scores are not empty strings before adding
                    if game_state in ('in', 'post') and home_score != '' and away_score != '':
                        field_value += f"Score: **{away_score} - {home_score}**\n"

                    # Add location pin emoji only if location string isn't empty
                    if location_str:
                        field_value += f"{EMOJI_PIN} {location_str}"
                    else:
                        # Remove trailing newline if no location and no score added
                        field_value = field_value.rstrip('\n')


                    # Ensure field value isn't empty (shouldn't happen with status)
                    if not field_value: field_value = "Details unavailable."

                    embed.add_field(name=field_name, value=field_value, inline=False)
                    games_added += 1
                    logger.debug(f"Added field for game ID: {game_id}")

                 except Exception as e: # Catch broader errors during individual game processing
                     logger.exception(f"Error processing game entry: ID {game.get('id', 'UNKNOWN')}", exc_info=e)
                     continue # Skip problematic game entry


            if games_added == 0 and events: # If loop ran but added nothing useful
                 embed.description = "Could not process game entries from the API data."
            elif games_added == 0 and not events: # Should have been caught earlier, but safety
                 embed.description = "No game data found."

            logger.info(f"Sending embed with {games_added} games.")
            await interaction.followup.send(embed=embed)

        except aiohttp.ClientError as e:
            logger.exception("aiohttp Client Error fetching today's games:", exc_info=e)
            error_embed = embed_builder.error_embed("Network Error", f"Could not connect to the ESPN API: {e.__class__.__name__}")
            try: await interaction.followup.send(embed=error_embed)
            except Exception: pass # Avoid error loop if followup fails
        except json.JSONDecodeError:
            logger.exception("JSONDecodeError fetching today's games. ESPN API returned invalid data.")
            error_embed = embed_builder.error_embed("API Data Error", "Received invalid data from the ESPN API.")
            try: await interaction.followup.send(embed=error_embed)
            except Exception: pass
        except asyncio.TimeoutError: # Catch timeout from session.get
             logger.error("Timeout occurred while fetching today's games from ESPN.")
             error_embed = embed_builder.error_embed("Timeout Error", "The request to ESPN timed out.")
             try: await interaction.followup.send(embed=error_embed)
             except Exception: pass
        except Exception as e:
            logger.exception("Unexpected error in /today command:", exc_info=e)
            error_embed = embed_builder.error_embed("Unexpected Error", f"An error occurred: {type(e).__name__}")
            try: await interaction.followup.send(embed=error_embed)
            except Exception: pass

# Standard Cog setup function
async def setup(bot: commands.Bot):
    # Check for required libraries
    library_missing = False
    try: import aiohttp; logger.debug("aiohttp found.")
    except ImportError: logger.error("Missing required library 'aiohttp'."); library_missing = True
    try: import pytz; logger.debug("pytz found.")
    except ImportError: logger.error("Missing required library 'pytz'."); library_missing = True

    if library_missing:
         logger.error("Schedule cog will not be loaded due to missing libraries. Install with pip.")
         return

    # Check for helpers (basic check)
    if not hasattr(bot, 'helpers') or not hasattr(bot, 'config'):
         logger.error("Bot instance missing 'helpers' or 'config'. Schedule cog may not function correctly.")
         # Decide whether to proceed or return

    await bot.add_cog(TodayCog(bot))
    logger.info("Cog 'TodayCog' loaded successfully.")