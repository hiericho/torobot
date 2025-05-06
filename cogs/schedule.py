import json
import discord
from discord import app_commands, Interaction
from discord.ext import commands
import aiohttp # Use asynchronous HTTP client
import logging
from datetime import datetime, timezone # Use standard library timezone if possible
import pytz # Keep if specific non-UTC timezone parsing/conversion is needed for game times

# Import helpers and constants
from helpers import embed_builder # Assuming this is your custom embed builder
from helpers.constants import (
    EMBED_COLOR_GAME, EMOJI_CALENDAR, EMOJI_LIVE,
    EMOJI_CHECK, EMOJI_AWAY, EMOJI_HOME, EMOJI_PIN,
    ESPN_NBA_SCOREBOARD_URL # Example: move URL to constants
)
import asyncio

logger = logging.getLogger(__name__)

# Consider moving to constants if used elsewhere or for configurabili


class TodayCog(commands.Cog):
    """Cog for displaying today's NBA game schedule and results using ESPN API."""

    def __init__(self, bot: commands.Bot): # Or 'NBAStatsBot' if using custom bot class
        self.bot: commands.Bot = bot # Or 'NBAStatsBot'
        self.session = aiohttp.ClientSession()
        logger.info("TodayCog initialized with a new aiohttp.ClientSession.")

    async def cog_unload(self):
        """Cleanly close the aiohttp session when the cog is unloaded."""
        if self.session and not self.session.closed:
            await self.session.close()
            logger.info("TodayCog unloaded: aiohttp.ClientSession closed.")

    def _parse_game_time(self, status_detail: str, game_date_utc_str: str | None) -> str:
        """
        Attempts to parse and format game time, converting to a user-friendly local time if possible.
        status_detail: e.g., "7:00 PM ET", "Scheduled", "TBD"
        game_date_utc_str: ISO format string from API, e.g., "2023-10-25T23:00Z"
        """
        if not game_date_utc_str:
            return status_detail # Fallback to API's detail if no specific time

        try:
            # ESPN game times are usually in UTC (indicated by 'Z')
            game_dt_utc = datetime.fromisoformat(game_date_utc_str.replace('Z', '+00:00'))
            
            # Convert to a common, user-friendly timezone, e.g., US/Eastern, or server's local.
            # For simplicity, let's format it and note it's UTC, or let Discord handle relative time.
            # For actual conversion to local time, you'd need user's timezone or a default.
            # Example: Display as "7:00 PM ET" if that's what status_detail provides and is reliable.
            # If status_detail is like "Scheduled", use the parsed time.
            if "scheduled" in status_detail.lower() or "tbd" in status_detail.lower() or not any(c.isdigit() for c in status_detail):
                # Use Discord's relative timestamp for scheduled games
                return f"<t:{int(game_dt_utc.timestamp())}:t>" # Shows time like "7:00 PM" in user's local TZ

        except ValueError:
            logger.warning(f"Could not parse game date string: {game_date_utc_str}")
            # Fallback to the raw detail from ESPN if parsing fails
            return status_detail
        
        # If status_detail already contains a formatted time like "7:00 PM ET", use it.
        # This part requires careful checking of ESPN API's typical `status_detail` content.
        if " ET" in status_detail or " CT" in status_detail or " MT" in status_detail or " PT" in status_detail:
            return status_detail

        return status_detail # Fallback

    def _format_game_status(self, status_data: dict, game_date_utc_str: str | None) -> str:
        """Formats the status object into a user-friendly string with emoji."""
        if not isinstance(status_data, dict):
            return "Status Unknown"

        status_type = status_data.get('type', {}).get('name', 'STATUS_UNKNOWN')
        status_detail = status_data.get('type', {}).get('detail', '')
        # state = status_data.get('type', {}).get('state', 'pre') # 'pre', 'in', 'post'

        if status_type == 'STATUS_SCHEDULED':
            emoji = EMOJI_CALENDAR
            # Use the parsed game time for more accurate/local display
            formatted_time = self._parse_game_time(status_detail, game_date_utc_str)
            return f"{emoji} {formatted_time}"
        elif status_type in ('STATUS_IN_PROGRESS', 'STATUS_HALFTIME'):
            emoji = EMOJI_LIVE
            return f"{emoji} Live - {status_detail}" # Detail has clock/period
        elif status_type == 'STATUS_FINAL':
            emoji = EMOJI_CHECK
            final_detail = status_detail
            if "/ot" in status_detail.lower():
                ot_match = status_detail.lower().rfind("/ot") # Find last occurrence
                if ot_match != -1:
                    ot_part = status_detail[ot_match:].upper().replace("/OT", " OT") # Make it " OT"
                    final_detail = f"Final{ot_part}"
                else: final_detail = "Final" # Should not happen if /ot is present
            return f"{emoji} {final_detail}"
        elif status_type == 'STATUS_POSTPONED':
            return f"⚠️ Postponed - {status_detail}"
        elif status_type == 'STATUS_CANCELED':
            return f"❌ Canceled - {status_detail}"
        elif status_type == 'STATUS_DELAYED':
            return f"⏳ Delayed - {status_detail}"
        else:
            return f"ℹ️ Status: {status_detail} ({status_type})"


    @app_commands.command(name="today", description="Shows today's NBA game schedule, scores, and locations.")
    async def today_games_command(self, interaction: Interaction): # Renamed method
        """Fetches and displays info for NBA games scheduled for the current day."""
        await interaction.response.defer(ephemeral=False)
        logger.info(f"/today command invoked by {interaction.user} (ID: {interaction.user.id}) in guild {interaction.guild_id or 'DM'}")

        # Use constant for URL
        url = ESPN_NBA_SCOREBOARD_URL # from helpers.constants
        headers = {"User-Agent": f"DiscordBot/{self.bot.user.name if self.bot.user else 'Bot'}/1.0 (Python/aiohttp)"}
        api_timeout_seconds = 15

        try:
            logger.debug(f"Fetching today's games from {url}")
            async with self.session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=api_timeout_seconds)) as response:
                response_text_preview = await response.text() # Read text once
                logger.debug(f"ESPN API response status: {response.status}")

                if response.status != 200:
                    logger.error(f"ESPN Scoreboard API failed: Status {response.status}, Response: {response_text_preview[:500]}")
                    await interaction.followup.send(embed=embed_builder.error_embed(
                        "API Error", f"Could not fetch today's games (Status: {response.status}). The API might be temporarily down."
                    ))
                    return

                if 'application/json' not in response.headers.get('Content-Type', '').lower():
                    logger.error(f"ESPN API returned non-JSON content type: {response.headers.get('Content-Type')}")
                    logger.error(f"Response Text (first 500 chars): {response_text_preview[:500]}")
                    await interaction.followup.send(embed=embed_builder.error_embed(
                        "API Data Error", "Received an unexpected data format from the ESPN API. Please try again later."
                    ))
                    return
                
                try:
                    data = json.loads(response_text_preview) # Parse the already read text
                except json.JSONDecodeError as json_e: # Specific catch for parsing the text
                    logger.exception("JSONDecodeError parsing ESPN API response.", exc_info=json_e)
                    logger.error(f"Problematic JSON text (first 500 chars): {response_text_preview[:500]}")
                    await interaction.followup.send(embed=embed_builder.error_embed(
                        "API Data Error", "Failed to parse data from the ESPN API. The format might have changed."
                    ))
                    return

            logger.debug("Successfully parsed JSON response from ESPN.")

            events = data.get("events", [])
            if not events:
                api_date_str = data.get('day', {}).get('date')
                display_date = datetime.now().strftime("%A, %B %d") # Default to current server date
                if api_date_str:
                    try: display_date = datetime.strptime(api_date_str, '%Y-%m-%d').strftime("%A, %B %d")
                    except ValueError: pass # Keep default if parsing fails
                
                logger.info(f"No events found in ESPN API response for {display_date}.")
                await interaction.followup.send(embed=embed_builder.info_embed(
                    "No Games Today", f"It seems there are no NBA games scheduled for {display_date} on the ESPN scoreboard."
                ))
                return

            embed_title_date_str = datetime.now().strftime('%A, %B %d') # Default
            try:
                api_date_str = data.get('day', {}).get('date') # YYYY-MM-DD
                if api_date_str:
                    api_date_obj = datetime.strptime(api_date_str, '%Y-%m-%d')
                    embed_title_date_str = api_date_obj.strftime('%A, %B %d')
            except (ValueError, TypeError) as date_e:
                logger.warning(f"Could not parse date from API for embed title: {date_e}")

            embed = embed_builder.create_embed(
                title=f"{EMOJI_CALENDAR} NBA Games - {embed_title_date_str}",
                color=EMBED_COLOR_GAME,
                timestamp=True # Shows when the data was fetched
            )

            games_added_count = 0
            max_fields = 24 # Discord limit is 25, leave one for "more games" if needed

            for game_idx, game_data in enumerate(events):
                if games_added_count >= max_fields:
                    logger.warning(f"Reached embed field limit ({max_fields}). Remaining {len(events) - game_idx} games not shown.")
                    embed.add_field(
                        name="More Games Scheduled",
                        value=f"There are {len(events) - game_idx} more game(s) today not shown due to display limits.",
                        inline=False
                    )
                    break

                try:
                    game_id = game_data.get('id', f'UNKNOWN_ID_{game_idx}')
                    logger.debug(f"Processing game ID: {game_id}")

                    # Main competition details
                    competition = game_data.get("competitions", [{}])[0] # Take the first competition
                    if not competition:
                        logger.warning(f"No competition data for game ID {game_id}. Skipping.")
                        continue

                    competitors_list = competition.get("competitors", [])
                    status_data = game_data.get("status", {})
                    venue_data = competition.get("venue", {})
                    game_date_utc_str = game_data.get("date") # e.g., "2023-10-25T23:00Z"


                    home_team_data, away_team_data = None, None
                    for comp_data in competitors_list:
                        if not isinstance(comp_data, dict): continue
                        if comp_data.get('homeAway') == 'home': home_team_data = comp_data
                        elif comp_data.get('homeAway') == 'away': away_team_data = comp_data

                    if not home_team_data or not away_team_data:
                        logger.warning(f"Could not identify home/away teams for game ID {game_id}. Skipping.")
                        continue

                    home_name = home_team_data.get('team', {}).get('displayName', 'Home Team')
                    away_name = away_team_data.get('team', {}).get('displayName', 'Away Team')
                    home_score = home_team_data.get('score', '')
                    away_score = away_team_data.get('score', '')

                    stadium_name = venue_data.get('fullName', '')
                    stadium_city = venue_data.get('address', {}).get('city', '')
                    location_str = stadium_name
                    if stadium_city and stadium_name: location_str += f", {stadium_city}"
                    elif stadium_city: location_str = stadium_city # Only city if no stadium name

                    status_str = self._format_game_status(status_data, game_date_utc_str)

                    field_name = f"{EMOJI_AWAY} {away_name} at {EMOJI_HOME} {home_name}"
                    field_value_parts = [status_str]

                    game_state = status_data.get('type', {}).get('state') # 'pre', 'in', 'post'
                    if game_state in ('in', 'post') and home_score and away_score: # Check for non-empty
                        field_value_parts.append(f"Score: **`{away_score} - {home_score}`**")

                    if location_str:
                        field_value_parts.append(f"{EMOJI_PIN} {location_str}")
                    
                    final_field_value = "\n".join(filter(None, field_value_parts)) # Join non-empty parts
                    if not final_field_value: final_field_value = "Details unavailable."


                    embed.add_field(name=field_name, value=final_field_value, inline=False)
                    games_added_count += 1
                    logger.debug(f"Added field for game '{away_name} vs {home_name}' (ID: {game_id})")

                except Exception as process_game_e:
                    game_id_for_log = game_data.get('id', f'UNKNOWN_AT_INDEX_{game_idx}')
                    logger.exception(f"Error processing individual game entry (ID: {game_id_for_log}):", exc_info=process_game_e)
                    # Optionally add a field indicating an error for this game, or just skip
                    if games_added_count < max_fields: # Only add error field if space
                         embed.add_field(name="⚠️ Error Processing Game", value=f"Details for one game could not be displayed.", inline=False)
                         games_added_count +=1 # Count it as a field used
                    continue

            if games_added_count == 0: # If no games were successfully processed from events list
                if events: # Events existed but none could be processed
                    embed.description = "Could not process any game entries from the API data. There might be an issue with the data format."
                # If !events, it was handled before embed creation.
            
            logger.info(f"Sending embed with {games_added_count} games to {interaction.user}.")
            await interaction.followup.send(embed=embed)

        except aiohttp.ClientError as e: # Covers connection errors, etc.
            logger.exception("aiohttp ClientError in /today command:", exc_info=e)
            err_embed = embed_builder.error_embed("Network Error", f"A network issue occurred while contacting ESPN: {e.__class__.__name__}")
            await interaction.followup.send(embed=err_embed, ephemeral=True)
        except asyncio.TimeoutError: # Specifically for aiohttp.ClientTimeout
            logger.error("TimeoutError in /today command: Request to ESPN API timed out.")
            err_embed = embed_builder.error_embed("API Timeout", "The request to the ESPN API timed out. Please try again in a moment.")
            await interaction.followup.send(embed=err_embed, ephemeral=True)
        # JSONDecodeError already handled after reading response text
        except Exception as e: # Broadest catch-all at the end
            logger.exception("Unexpected error in /today command global try-block:", exc_info=e)
            err_embed = embed_builder.error_embed("Unexpected Error", "An unexpected error occurred. The developers have been notified.")
            await interaction.followup.send(embed=err_embed, ephemeral=True)


async def setup(bot: commands.Bot): # Or 'NBAStatsBot'
    # Library checks are good for dev, but rely on requirements.txt for deployment
    # if not all(lib in globals() for lib in ['aiohttp', 'pytz']):
    #     logger.error("TodayCog: Missing one or more required libraries (aiohttp, pytz). Cog not loaded.")
    #     return

    # Assuming constants like ESPN_NBA_SCOREBOARD_URL are imported and available
    if not hasattr(embed_builder, 'create_embed') or not hasattr(embed_builder, 'error_embed'):
        logger.error("TodayCog: embed_builder helper module or its functions are missing. Cog not loaded.")
        return
    if not ESPN_NBA_SCOREBOARD_URL: # Check if constant is loaded
        logger.error("TodayCog: ESPN_NBA_SCOREBOARD_URL constant is not defined/imported. Cog not loaded.")
        return

    await bot.add_cog(TodayCog(bot))
    logger.info("Cog 'TodayCog' loaded successfully.")