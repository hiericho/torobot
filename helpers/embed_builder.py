# helpers/embed_builder.py

import discord
import pandas as pd
import numpy as np # For np.floating type check in format_stat
import logging
from typing import Dict, List, Optional # For type hinting
import pytz # For timezone conversion

# Import constants needed using relative import
from .constants import (
    # Colors
    EMBED_COLOR_ERROR, EMBED_COLOR_INFO, EMBED_COLOR_SUCCESS, EMBED_COLOR_STANDINGS,
    EMBED_COLOR_GAME, EMBED_COLOR_PREDICT, EMBED_COLOR_UTILITY,
    # Emojis
    EMOJI_CROSS, EMOJI_CHECK, EMOJI_INFO, EMOJI_TROPHY, EMOJI_TEAMS,
    EMOJI_PLAYER, EMOJI_STATS_BASIC, EMOJI_STATS_ADVANCED,
    # Stats Data (Ensure these are defined in constants.py)
    STAT_DISPLAY_NAMES, PERCENTAGE_STATS,
    TEAM_BASIC_STATS, TEAM_ADVANCED_STATS,
    PLAYER_BASIC_STATS, PLAYER_ADVANCED_STATS
)

# DO NOT import nba_helper or espn_helper at the top level here

logger = logging.getLogger(__name__)


# --- Stat Formatting Utility (Moved Here) ---
def format_stat(stat_name: str, value) -> str:
    """
    Formats stats for display (percentages, floats). Located within embed_builder.
    Relies on PERCENTAGE_STATS defined in constants.py.
    """
    if value is None or pd.isna(value):
        return "N/A"
    try:
        # Format percentages using the list from constants
        if stat_name in PERCENTAGE_STATS:
            # Ensure value can be converted to float before formatting
            return f"{float(value) * 100:.1f}%"

        # Format floats (check for numpy float types too)
        if isinstance(value, (float, np.floating)):
            # Check if the float represents a whole number
            if float(value).is_integer():
                return str(int(value))
            else:
                # Format other floats to 1 decimal place
                return f"{float(value):.1f}"

        # Default case: Convert any other type to string
        return str(value)

    except (ValueError, TypeError) as e:
        # Log error if formatting fails unexpectedly
        logger.warning(f"Format Error - Stat: '{stat_name}', Value: '{value}' (Type: {type(value)}): {e}")
        # Return the original value as a string in case of error
        return str(value)

# --- Core Embed Creation ---
def create_embed(
    title: str,
    description: str = "",
    color: discord.Color = EMBED_COLOR_INFO,
    author_name: str = None,
    author_icon_url: str = None,
    footer_text: str = None,
    footer_icon_url: str = None,
    thumbnail_url: str = None,
    image_url: str = None,
    timestamp: bool = False
    ) -> discord.Embed:
    """
    Creates a standardized Discord embed with various optional elements.
    """
    embed = discord.Embed(title=title, description=description, color=color)
    if author_name:
        icon = author_icon_url if author_icon_url else discord.Embed.Empty
        embed.set_author(name=author_name, icon_url=icon)
    if footer_text:
        icon = footer_icon_url if footer_icon_url else discord.Embed.Empty
        embed.set_footer(text=footer_text, icon_url=icon)
    if thumbnail_url:
        # Basic check for valid URL structure (optional but helpful)
        if isinstance(thumbnail_url, str) and thumbnail_url.startswith('http'):
            embed.set_thumbnail(url=thumbnail_url)
        else:
             logger.warning(f"Invalid thumbnail_url provided: {thumbnail_url}")
    if image_url:
        if isinstance(image_url, str) and image_url.startswith('http'):
             embed.set_image(url=image_url)
        else:
            logger.warning(f"Invalid image_url provided: {image_url}")
    if timestamp:
        embed.timestamp = discord.utils.utcnow() # Use Discord's utility for UTC timestamp
    return embed

# --- Specialized Embed Helpers ---
def success_embed(title: str, description: str = "") -> discord.Embed:
    """Creates a standardized success embed."""
    return create_embed(f"{EMOJI_CHECK} {title}", description, EMBED_COLOR_SUCCESS)

def error_embed(title: str, description: str = "") -> discord.Embed:
    """Creates a standardized error embed."""
    return create_embed(f"{EMOJI_CROSS} Error", f"**{title}**\n{description}", EMBED_COLOR_ERROR)

def info_embed(title: str, description: str = "") -> discord.Embed:
    """Creates a standardized informational embed."""
    return create_embed(f"{EMOJI_INFO} {title}", description, EMBED_COLOR_INFO)


# --- REVISED add_stats_section to respect limits more carefully ---
def add_stats_section(
    embed: discord.Embed,
    title: str,
    stats_list: List[str],
    data: Dict,
    inline: bool = True
    ) -> int: # Return number of stats successfully added
    """
    Adds stats fields, respecting the embed's field limit.
    Returns the number of stat value fields successfully added.
    """
    stats_added_count = 0
    if not isinstance(data, dict): return 0 # Cannot process non-dict data

    max_fields = 25
    fields_to_add = [] # Collect potential fields

    # Prepare fields first
    for stat_key in stats_list:
        stat_value = data.get(stat_key)
        if stat_value is not None and not pd.isna(stat_value):
            display_name = STAT_DISPLAY_NAMES.get(stat_key, stat_key)
            formatted_value = format_stat(stat_key, stat_value)
            fields_to_add.append({"name": display_name, "value": formatted_value, "inline": inline})

    if not fields_to_add:
         return 0 # Nothing to add for this section

    # Check how many slots are left *before* adding anything from this section
    # Need 1 slot for header + N slots for stats + maybe 1 for '...'
    slots_available = max_fields - len(embed.fields)
    if slots_available <= 0:
         logger.warning(f"No slots left in embed to add section '{title}'")
         return 0 # No room left at all

    # Add header if there's room for it and at least one stat
    if slots_available >= 2 or (slots_available >= 1 and len(fields_to_add) > 0):
         embed.add_field(name="\u200b", value=f"**{title}**", inline=False)
         slots_available -= 1 # Decrement after adding header
    else:
         logger.warning(f"Not enough slots for header/stats in '{title}'")
         return 0 # Can't even add the header and one stat

    # Add the stat fields, checking slots remaining
    for i, field_dict in enumerate(fields_to_add):
        if slots_available > 0:
            embed.add_field(**field_dict)
            stats_added_count += 1
            slots_available -= 1

            # If this was the last available slot, AND there are more stats pending, add '...'
            if slots_available == 0 and i < len(fields_to_add) - 1:
                 logger.warning(f"Adding '...' indicator for '{title}', {len(fields_to_add) - (i + 1)} stats truncated.")
                 # Try adding overflow indicator IF another field hasn't pushed us over 25 *exactly*
                 # It's tricky to guarantee this last field slot calculation is perfect
                 if len(embed.fields) < max_fields:
                     embed.add_field(name="...", value=" ", inline=inline) # Add placeholder ...
                 break # Stop adding more stats
        else:
            logger.warning(f"Ran out of embed slots while adding stats for '{title}'. {len(fields_to_add) - stats_added_count} stats truncated.")
            break # No more slots

    return stats_added_count


# --- REVISED format_team_info_embed to be more selective ---
def format_team_info_embed(
    espn_team_details: Optional[Dict],
    nba_api_stats: Optional[Dict]
    ) -> discord.Embed:
    """Formats combined team info, prioritizing key stats due to field limits."""
    # ... (Initial setup: get name, logo, record, standing - SAME AS BEFORE) ...
    if not espn_team_details and not nba_api_stats:
        return error_embed("Data Error", "Could not load any team data.")

    if espn_team_details:
         team_name = espn_team_details.get('displayName', 'Unknown Team')
         logo = espn_team_details.get('logos', [{}])[0].get('href')
         record_summary = "N/A"; standing_summary = espn_team_details.get('standingSummary', '')
         try:
             if 'record' in espn_team_details and espn_team_details['record'].get('items'):
                 record_summary = espn_team_details['record']['items'][0].get('summary', 'N/A')
         except Exception as e: logger.warning(f"ESPN Record parse error: {e}")
         embed = create_embed(title=f"{EMOJI_TEAMS} {team_name} Info", color=EMBED_COLOR_INFO)
         if logo: embed.set_thumbnail(url=logo)
         embed.add_field(name="Record", value=record_summary, inline=True)
         if standing_summary: embed.add_field(name="Standing", value=standing_summary, inline=True)
    elif nba_api_stats: # Fallback base info
        team_name = nba_api_stats.get('TEAM_NAME', 'Unknown Team')
        embed = create_embed(title=f"{EMOJI_TEAMS} {team_name} Info", color=EMBED_COLOR_INFO)
        record_summary = f"{nba_api_stats.get('W', '?')}-{nba_api_stats.get('L', '?')}"
        embed.add_field(name="Record (nba_api)", value=record_summary, inline=False)
    else: return error_embed("Data Error","No data to display.") # Should be caught earlier

    # --- PRIORITIZE which stats to show ---
    prioritized_basic_stats = [ # Key stats to ensure are shown
        'PTS', 'REB', 'AST', 'FG_PCT', 'FG3_PCT', 'PLUS_MINUS', 'W', 'L'
    ]
    prioritized_advanced_stats = [ # Key advanced stats if available
         'OFF_RATING', 'DEF_RATING', 'NET_RATING', 'TS_PCT'
    ]
    # Remaining stats from constants (will be added only if space allows)
    remaining_basic = [s for s in TEAM_BASIC_STATS if s not in prioritized_basic_stats]
    remaining_advanced = [s for s in TEAM_ADVANCED_STATS if s not in prioritized_advanced_stats]


    stats_source = "stats.nba.com"
    if nba_api_stats and isinstance(nba_api_stats, dict) and "error" not in nba_api_stats:
        # Add prioritized stats first
        stats_added = add_stats_section(
            embed, f"{EMOJI_STATS_BASIC} Key Stats ({stats_source})",
            prioritized_basic_stats, nba_api_stats, inline=True
        )
        adv_added = add_stats_section(
             embed, f"{EMOJI_STATS_ADVANCED} Key Adv. Stats ({stats_source})",
             prioritized_advanced_stats, nba_api_stats, inline=True
        )

        # Add remaining stats *only if space allows*
        # Check remaining field count roughly
        if len(embed.fields) < 20: # Leave buffer for roster + footer etc.
             add_stats_section(
                 embed, f"Other Basic Stats ({stats_source})",
                 remaining_basic, nba_api_stats, inline=True
            )
        if len(embed.fields) < 20:
            add_stats_section(
                embed, f"Other Adv. Stats ({stats_source})",
                remaining_advanced, nba_api_stats, inline=True
            )
        if stats_added == 0 and adv_added == 0:
             embed.add_field(name="Statistics", value="No stats found via stats.nba.com.", inline=False)

    elif "error" in (nba_api_stats or {}):
        embed.add_field(name="Statistics Error", value=nba_api_stats["error"], inline=False)
    else:
        embed.add_field(name="\u200b", value=f"*Detailed stats were unavailable from {stats_source}.*", inline=False)

    # --- Add Roster from ESPN data (Check limit *before* adding) ---
    if espn_team_details and isinstance(espn_team_details, dict) and len(embed.fields) < 24: # Leave room for footer
        roster_list = espn_team_details.get('athletes', [])
        if roster_list:
            MAX_PLAYERS_DISPLAY = 10 # Reduce displayed roster if needed
            player_names = [p.get("displayName", "?") for p in roster_list[:MAX_PLAYERS_DISPLAY]]
            roster_str = ", ".join(player_names)
            if len(roster_list) > MAX_PLAYERS_DISPLAY:
                roster_str += f", ... ({len(roster_list) - MAX_PLAYERS_DISPLAY} more)"
            embed.add_field(name="👥 Roster Snippet (ESPN)", value=roster_str, inline=False)


    # --- Set Footer ---
    footer_parts = []
    if espn_team_details: footer_parts.append("ESPN")
    if nba_api_stats: footer_parts.append("stats.nba.com")
    footer_text = f"Sources: {', '.join(footer_parts)}" if footer_parts else "Source Unknown"
    embed.set_footer(text=footer_text)

    # Final length check (although checks within add_stats_section should prevent this)
    if len(embed) > 6000: # Embed total character limit
         logger.error(f"Embed character limit exceeded for team {team_name}. Trimming necessary.")
         # Implement trimming if needed, but field limits usually hit first
    if len(embed.fields) > 25:
         logger.error(f"FATAL: Exceeded 25 fields AFTER adding stats/roster for team {team_name}.")
         # Remove last field as emergency fallback?
         # embed.remove_field(-1)

    return embed


# --- Season Standings Embed Formatter ---
def format_season_standings_embed(standings_data: Optional[Dict]) -> discord.Embed:
    """Formats fetched season standings data into a Discord Embed."""
    if not standings_data or not isinstance(standings_data, dict):
        logger.warning("format_season_standings_embed received invalid data.")
        return info_embed(f"{EMOJI_TROPHY} NBA Standings", "Could not retrieve standings.")

    embed = create_embed(
        title=f"{EMOJI_TROPHY} NBA Regular Season Standings",
        color=EMBED_COLOR_STANDINGS, timestamp=True
    )
    embed.set_footer(text="Data from stats.nba.com")

    # Columns to display from the DataFrame - keys are DF column names
    cols_to_display_map = {
        'PlayoffRank': 'Rank', 'TeamName': 'Team', 'Record': 'Rec',
        'WinPCT': 'Win%', 'strCurrentStreak': 'Streak', 'ClinchIndicator': 'Note'
    }

    for conf_name, conf_df in standings_data.items():
        if conf_df is None or conf_df.empty:
            embed.add_field(name=f"{conf_name} Conference", value="No data available.", inline=False)
            continue

        display_df = pd.DataFrame()
        valid_cols = []
        # Select and map available columns
        for api_col, display_name in cols_to_display_map.items():
            if api_col in conf_df.columns:
                display_df[display_name] = conf_df[api_col]
                valid_cols.append(display_name)
            else: logger.debug(f"Column '{api_col}' missing for {conf_name} standings.")

        if display_df.empty: continue

        # --- Formatting ---
        if 'Win%' in valid_cols: display_df['Win%'] = display_df['Win%'].apply(lambda x: f"{float(x):.3f}".lstrip('0') if pd.notna(x) else '-')
        if 'Note' in valid_cols:
             clinch_map = {'-w': 'Div', '-p': 'Playoffs', '-e': 'Conf', '-c': 'Clinched', '-o': '', '-x': 'Clinched', ' ': '', '': '', None: ''}
             display_df['Note'] = conf_df['ClinchIndicator'].map(clinch_map).fillna(' ') # Map codes to readable notes
             display_df['Note'] = display_df['Note'].str.ljust(1) # Minimal padding

        # --- Create Fixed-Width Table ---
        display_df = display_df[valid_cols] # Ensure correct column order
        widths = {col: max(display_df[col].astype(str).map(len).max(), len(col)) for col in valid_cols}
        header = " | ".join(f"{col.ljust(widths[col])}" for col in valid_cols)
        separator = "-+-".join("-" * widths[col] for col in valid_cols)
        body = "\n".join(
            " | ".join(f"{str(row[col]).ljust(widths[col])}" for col in valid_cols)
            for _, row in display_df.iterrows()
        )
        table_string = f"```\n{header}\n{separator}\n{body}\n```"
        embed.add_field(name=f"{conf_name} Conference", value=table_string, inline=False)

    return embed


# --- Player Info Formatter (Placeholder/Example) ---
# If you have a player info command, create a similar formatter for it
def format_player_info_embed(player_bio: Optional[Dict], player_stats: Optional[Dict]) -> discord.Embed:
    """Formats player bio (nba_api) and stats (nba_api) into an embed."""
    if not player_bio:
        return error_embed("Player Data Error", "Could not load player bio.")

    full_name = player_bio.get('full_name', 'Unknown Player')
    team_abbr = player_bio.get('team_abbreviation', 'N/A')
    headshot_url = player_bio.get('headshot_url')
    player_id = player_bio.get('id', 'N/A') # Needed? Maybe just for footer reference.

    embed = create_embed(
        title=f"{EMOJI_PLAYER} {full_name} ({team_abbr})",
        color=EMBED_COLOR_INFO,
        thumbnail_url=headshot_url
    )

    # Add Bio Fields (Selectively)
    bio_fields = [
        ("Team", player_bio.get('team')), ("Pos", player_bio.get('position')),
        ("Ht", player_bio.get('height')), ("Wt", player_bio.get('weight')),
        ("#", player_bio.get('jersey_number')), ("Country", player_bio.get('country')),
    ]
    inline_added = 0
    max_inline_bio = 6
    for name, value in bio_fields:
        if value and str(value).strip() != 'N/A':
            embed.add_field(name=name, value=str(value), inline=(inline_added < max_inline_bio))
            if inline_added < max_inline_bio: inline_added += 1

    # Draft Info (less critical, maybe non-inline or footer)
    draft = f"{player_bio.get('draft_year','N/A')} R{player_bio.get('draft_round','N/A')}-P{player_bio.get('draft_number','N/A')}"
    if "N/A" not in draft:
        embed.add_field(name="Draft", value=draft, inline=False)

    # Add Stats using nba_api data and add_stats_section
    stats_season = "N/A"
    if player_stats and isinstance(player_stats, dict) and "error" not in player_stats:
         stats_season = player_stats.get('SEASON_ID', 'Unknown')
         add_stats_section(embed, f"{EMOJI_STATS_BASIC} Stats (Per Game, {stats_season})", PLAYER_BASIC_STATS, player_stats, inline=True)
         add_stats_section(embed, f"{EMOJI_STATS_ADVANCED} Adv. Stats ({stats_season})", PLAYER_ADVANCED_STATS, player_stats, inline=True)
    elif "error" in (player_stats or {}):
        embed.add_field(name="Stats Error", value=player_stats["error"], inline=False)
    else:
         embed.add_field(name="\u200b", value="*Detailed stats could not be retrieved.*", inline=False)

    embed.set_footer(text=f"Source: stats.nba.com | Season: {stats_season}")
    return embed

# helpers/embed_builder.py

import discord
import pandas as pd
from datetime import datetime

# *** Import constants from the dedicated file ***
from .constants import (
    EMBED_COLOR_INFO, EMBED_COLOR_GAME, EMBED_COLOR_PREDICT, EMBED_COLOR_SUCCESS,
    EMBED_COLOR_ERROR, EMBED_COLOR_UTILITY, EMBED_COLOR_STANDINGS,
    EMOJI_AWAY, EMOJI_HOME, EMOJI_ROAD_WIN, EMOJI_FORM, EMOJI_TROPHY, EMOJI_TARGET,
    EMOJI_SCORE, EMOJI_TOTAL, EMOJI_WINNER, EMOJI_CLOSE, EMOJI_STATS, EMOJI_CALENDAR,
    EMOJI_EAST, EMOJI_WEST, EMOJI_ERROR, EMOJI_WARNING, EMOJI_TEAMS, EMOJI_COMMANDS,
    EMOJI_LIVE, EMOJI_CLOCK, EMOJI_FINAL, EMOJI_INFO, EMOJI_BALL # Add other needed emojis
)

# --- Versus Embed ---
def format_versus_embed(
    away_abbr, home_abbr, away_full, home_full,
    away_recent_form_str, home_recent_form_str, away_form_pct, home_form_pct,
    form_season_away, form_season_home,
    away_h2h_wins_comb, home_h2h_wins_comb,
    away_h2h_winrate_comb, home_h2h_winrate_comb,
    away_avg_pts_comb, home_avg_pts_comb,
    away_road_winrate_str, home_road_winrate_str,
    predicted_score_away, predicted_score_home, total_predicted_points,
    away_winprob, home_winprob, pred_winner, form_season_used,
    h2h_footer_comb, api_error_occurred,
    current_season, previous_season
) -> discord.Embed:

    # *** Use color from constants ***
    embed = discord.Embed(
        title=f"{EMOJI_AWAY} {away_abbr} @ {EMOJI_HOME} {home_abbr} — Multi-Season Analysis",
        description=f"Comparing recent form and H2H data from {current_season} & {previous_season}.",
        color=EMBED_COLOR_PREDICT # Use prediction color
    )

    # *** Use emojis from constants ***
    embed.add_field(name=f"{EMOJI_AWAY} {away_abbr} ({away_full})", value=(
        f"{EMOJI_FORM} **Recent Form (Last 5)**: {away_recent_form_str} `({away_form_pct*100:.0f}%)` `(S: {form_season_away})`\n"
        f"{EMOJI_TROPHY} **H2H Wins (Comb.)**: `{away_h2h_wins_comb}`\n"
        f"{EMOJI_STATS} **H2H Winrate (Comb.)**: `{away_h2h_winrate_comb:.1f}%`\n"
        f"{EMOJI_TARGET} **Avg H2H PTS (Comb.)**: `{away_avg_pts_comb}`\n"
        f"{EMOJI_ROAD_WIN} **Winrate @ {home_abbr}**: `{away_road_winrate_str}`"
    ), inline=True)

    embed.add_field(name=f"{EMOJI_HOME} {home_abbr} ({home_full})", value=(
        f"{EMOJI_FORM} **Recent Form (Last 5)**: {home_recent_form_str} `({home_form_pct*100:.0f}%)` `(S: {form_season_home})`\n"
        f"{EMOJI_TROPHY} **H2H Wins (Comb.)**: `{home_h2h_wins_comb}`\n"
        f"{EMOJI_STATS} **H2H Winrate (Comb.)**: `{home_h2h_winrate_comb:.1f}%`\n"
        f"{EMOJI_TARGET} **Avg H2H PTS (Comb.)**: `{home_avg_pts_comb}`\n"
        f"{EMOJI_ROAD_WIN} **Winrate @ {away_abbr}**: `{home_road_winrate_str}`"
    ), inline=True)

    embed.add_field(name="--- Predictions ---", value="\u200b", inline=False)

    embed.add_field(name=f"{EMOJI_SCORE} Predicted Score ({previous_season[2:]}/{current_season[2:]})",
                    value=f"**`{predicted_score_away} - {predicted_score_home}`**", inline=True)
    embed.add_field(name=f"{EMOJI_TOTAL} Predicted Total",
                    value=f"**`{total_predicted_points}`**", inline=True)

    if pred_winner not in ["N/A", "Too Close"]:
         embed.add_field(name=f"{EMOJI_WINNER} Winner", value=f"**{pred_winner}**", inline=True)
    elif pred_winner == "Too Close":
         embed.add_field(name=f"{EMOJI_WINNER} Winner", value=f"{EMOJI_CLOSE} Too Close", inline=True)
    else: embed.add_field(name="\u200b", value="\u200b", inline=True) # Spacer

    embed.add_field(name=f"{EMOJI_STATS} Win Probability (Form Season: {form_season_used})",
                    value=f"`{EMOJI_AWAY}{away_abbr}: {away_winprob}%` | `{EMOJI_HOME}{home_abbr}: {home_winprob}%`", inline=False)

    embed.set_footer(text=f"{h2h_footer_comb} | Pred. Score uses weighted PPG + H2H Adj. | Road Win% uses combined H2H.")

    if api_error_occurred:
        embed.description += f"\n{EMOJI_WARNING} *Note: Some API data might be missing due to errors.*"

    return embed

# --- Standings Embed ---
def format_season_standings_embed(standings_data: dict) -> discord.Embed:
    east_df = standings_data.get('East')
    west_df = standings_data.get('West')
    if east_df is None or west_df is None: return error_embed("Data Error", "Could not process standings.")

    # *** Use color from constants ***
    embed = discord.Embed(
        title=f"{EMOJI_CALENDAR} NBA Regular Season Standings",
        description=f"Current standings as of {datetime.now().strftime('%Y-%m-%d')}",
        color=EMBED_COLOR_STANDINGS # Use standings color
    )

    sort_key = 'ConferenceRank' if 'ConferenceRank' in east_df.columns else 'WinPCT'
    ascending_sort = True if sort_key == 'ConferenceRank' else False
    try:
        east_df = east_df.sort_values(by=sort_key, ascending=ascending_sort)
        west_df = west_df.sort_values(by=sort_key, ascending=ascending_sort)
    except KeyError: embed.description += f"\n{EMOJI_WARNING} Could not sort standings by rank."

    east_standings = ""; west_standings = ""
    for index, row in east_df.iterrows():
        rank = f"{int(row.get(sort_key, index + 1)) if pd.notna(row.get(sort_key)) else index + 1}." # Ensure rank is int
        team_name = row.get('TeamName', 'N/A'); record = f"{row.get('WINS', 'N/A')}-{row.get('LOSSES', 'N/A')}"
        pct = f"{row.get('WinPCT', 0.0)*100:.1f}%" if pd.notna(row.get('WinPCT')) else "N/A"
        clinch = f" ({row['ClinchIndicator']})" if pd.notna(row.get('ClinchIndicator')) and row['ClinchIndicator'] else ""
        east_standings += f"`{rank:<3}` {team_name} ({record} | {pct}){clinch}\n"
        if len(east_standings) > 950: east_standings += "..."; break
    for index, row in west_df.iterrows():
        rank = f"{int(row.get(sort_key, index + 1)) if pd.notna(row.get(sort_key)) else index + 1}."
        team_name = row.get('TeamName', 'N/A'); record = f"{row.get('WINS', 'N/A')}-{row.get('LOSSES', 'N/A')}"
        pct = f"{row.get('WinPCT', 0.0)*100:.1f}%" if pd.notna(row.get('WinPCT')) else "N/A"
        clinch = f" ({row['ClinchIndicator']})" if pd.notna(row.get('ClinchIndicator')) and row['ClinchIndicator'] else ""
        west_standings += f"`{rank:<3}` {team_name} ({record} | {pct}){clinch}\n"
        if len(west_standings) > 950: west_standings += "..."; break

    # *** Add conference emojis if defined in constants ***
    # EMOJI_EAST = "<:east_emoji_id>" # Example custom emoji
    # EMOJI_WEST = "<:west_emoji_id>" # Example custom emoji
    # If using text or default emojis:
    EMOJI_EAST = "🇪" # Example default
    EMOJI_WEST = "🇼" # Example default

    embed.add_field(name=f"{EMOJI_EAST} Eastern Conference", value=east_standings or "N/A", inline=True)
    embed.add_field(name=f"{EMOJI_WEST} Western Conference", value=west_standings or "N/A", inline=True)
    embed.set_footer(text="Data from stats.nba.com | Clinch: x=Playoffs, pi=Play-In, e/w=Conf#, o=Eliminated")
    return embed

# --- Today Games Embed ---
def format_today_games_embed(games_data: list, today_date_eastern: datetime.date) -> discord.Embed:
    """Formats today's games into a Discord embed."""
    # *** Use color from constants ***
    embed = discord.Embed(
        title=f"{EMOJI_CALENDAR} NBA Schedule – {today_date_eastern.strftime('%b %d, %Y')} (ET)",
        description="Today's NBA matchups:",
        color=EMBED_COLOR_GAME # Use game color
    )
    eastern = pytz.timezone('US/Eastern') # Need timezone for conversion if not done prior

    if not games_data:
        embed.description = f"No NBA games found scheduled for {today_date_eastern.strftime('%b %d, %Y')}."
        return embed

    # Ensure games are sorted (should be done before calling this ideally)
    # games_data.sort(key=lambda game: game.get('gameTimeEastern', datetime.max.replace(tzinfo=pytz.utc)))

    for game in games_data:
        home = game.get('homeTeam', {}); away = game.get('awayTeam', {})
        home_tricode = home.get('teamTricode', 'TBD'); away_tricode = away.get('teamTricode', 'TBD')
        matchup_str = f"**{EMOJI_AWAY}{away_tricode} @ {EMOJI_HOME}{home_tricode}**"

        status_num = game.get('statusNum', 0); status_text = game.get('gameStatusText', 'Scheduled')
        time_discord_fmt = "Time TBD"
        game_time_et = game.get('gameTimeEastern') # Assumes this was added in the cog
        if not game_time_et and 'gameTimeUTC' in game: # Fallback conversion if needed
             game_time_utc_str = game.get('gameTimeUTC')
             try:
                 game_time_utc = datetime.strptime(game_time_utc_str, '%Y-%m-%dT%H:%M:%SZ')
                 game_time_utc = pytz.utc.localize(game_time_utc)
                 game_time_et = game_time_utc.astimezone(eastern)
             except: pass # Ignore conversion error here

        if game_time_et:
            timestamp = int(game_time_et.timestamp())
            time_discord_fmt = f"<t:{timestamp}:t> (<t:{timestamp}:R>)"

        status_line = f"{EMOJI_INFO} Status: {status_text}"
        if status_num == 1: status_line = f"{EMOJI_CLOCK} {time_discord_fmt}"
        elif status_num == 2:
            period = game.get('period', 0); clock = game.get('gameClock', ''); home_score = home.get('score', 0); away_score = away.get('score', 0)
            clock_info = f"({clock} Q{period})" if clock else f"(Q{period})"; status_line = f"{EMOJI_LIVE} **LIVE: {away_score} - {home_score}** {clock_info}"
        elif status_num == 3: home_score = home.get('score', 0); away_score = away.get('score', 0); status_line = f"{EMOJI_FINAL} **FINAL: {away_score} - {home_score}**"

        embed.add_field(name=matchup_str, value=status_line, inline=False)
        if len(embed.fields) >= 25:
             embed.set_footer(text="More games scheduled today (Embed limit reached)...")
             break
    else: # If loop completes without breaking
        if not embed.footer: embed.set_footer(text="All times are US/Eastern.")

    return embed


# --- Teams List Embed ---
def format_teams_list_embed(teams_list: list) -> discord.Embed:
    """Formats the list of teams into an embed."""
    if not teams_list:
        return error_embed("Data Error", "Could not retrieve team list.")

    sorted_teams_info = sorted(teams_list, key=lambda t: t['full_name'])
    # *** Use color and emoji from constants ***
    embed = discord.Embed(
        title=f"{EMOJI_TEAMS} NBA Teams List",
        description="Use the Full Name, Nickname, or Abbreviation (e.g., `LAL`) in commands.",
        color=EMBED_COLOR_UTILITY # Use utility color
    )
    teams_string = "\n".join(f"• {team['full_name']} (`{team['abbreviation']}`)" for team in sorted_teams_info)
    if len(teams_string) <= 4096: embed.description += f"\n\n{teams_string}"
    else:
        # Simple split logic
        midpoint = len(sorted_teams_info) // 2
        col1 = "\n".join(f"• {team['full_name']} (`{team['abbreviation']}`)" for team in sorted_teams_info[:midpoint])
        col2 = "\n".join(f"• {team['full_name']} (`{team['abbreviation']}`)" for team in sorted_teams_info[midpoint:])
        embed.add_field(name="Teams (A-M approx.)", value=col1[:1024], inline=True)
        embed.add_field(name="Teams (N-Z approx.)", value=col2[:1024], inline=True)
    embed.set_footer(text="Commands are case-insensitive.")
    embed.set_thumbnail(url="https://cdn.nba.com/logos/nba/nba-logoman-75-word_white.svg")
    return embed

# --- Commands List Embed ---
def format_commands_list_embed(bot, commands_list) -> discord.Embed:
    """Formats the list of available commands."""
    # *** Use color and emoji from constants ***
    embed = discord.Embed(
        title=f"{EMOJI_COMMANDS} Available Slash Commands",
        description="Use these commands to get NBA stats and info:",
        color=EMBED_COLOR_INFO # Use info color
    )
    if commands_list:
        for cmd in sorted(commands_list, key=lambda c: c.name):
            desc = cmd.description or "No description available."
            name_with_args = f"`/{cmd.name}`"
            try:
                if hasattr(cmd, 'parameters') and cmd.parameters: args_str = " ".join(f"`<{p.name}>`" for p in cmd.parameters); name_with_args += f" {args_str}"
            except Exception as param_e: logger.warning(f"Could not format parameters for command {cmd.name}: {param_e}") # Use logger
            embed.add_field(name=name_with_args, value=desc, inline=False)
    else: # Fallback
        embed.description = "Could not dynamically load commands. Here are the known ones:"
        embed.add_field(name="`/today`", value="Shows NBA games scheduled for today.", inline=False)
        embed.add_field(name="`/teams`", value="Displays all 30 NBA teams.", inline=False)
        embed.add_field(name="`/commands`", value="Shows this list of commands.", inline=False)
        embed.add_field(name="`/versus <away_team> <home_team>`", value=f"Head-to-head stats (Multi-Season).", inline=False)
        embed.add_field(name="`/season`", value="Displays the current NBA season standings.", inline=False)

    bot_avatar_url = bot.user.display_avatar.url if bot.user else None
    embed.set_footer(text=f"{bot.user.name if bot.user else 'Bot'} | Made with nba-api", icon_url=bot_avatar_url)
    return embed


# --- Error Embed ---
def error_embed(title: str = "Error", message: str = "An unexpected error occurred.") -> discord.Embed:
    """Creates a standardized error embed."""
    # *** Use color from constants ***
    return discord.Embed(
        title=f"{EMOJI_ERROR} {title}",
        description=message,
        color=EMBED_COLOR_ERROR # Use error color
    )