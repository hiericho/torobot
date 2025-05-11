# helpers/embed_builder.py

import discord
import pandas as pd
import numpy as np # For np.floating type check in format_stat
import logging
from typing import Dict, List, Optional, Any # Added Any
from datetime import datetime # For discord.utils.utcnow() if not using timestamp=True

# Import constants needed using relative import
from .constants import (
    # Colors
    EMBED_COLOR_ERROR, EMBED_COLOR_INFO, EMBED_COLOR_SUCCESS, EMBED_COLOR_STANDINGS,
    # Emojis
    EMOJI_CROSS, EMOJI_CHECK, EMOJI_INFO, EMOJI_TROPHY, EMOJI_TEAMS,
    EMOJI_PLAYER, EMOJI_STATS_BASIC, EMOJI_STATS_ADVANCED,
    # Stats Data (Ensure these are defined in constants.py)
    STAT_DISPLAY_NAMES, PERCENTAGE_STATS,
    TEAM_BASIC_STATS_PRIORITY, TEAM_ADVANCED_STATS_PRIORITY,
    TEAM_BASIC_STATS_OTHER, TEAM_ADVANCED_STATS_OTHER,
    PLAYER_BASIC_STATS_PRIORITY, PLAYER_ADVANCED_STATS_PRIORITY,
    PLAYER_BASIC_STATS_OTHER, PLAYER_ADVANCED_STATS_OTHER
)

logger = logging.getLogger(__name__)


# --- Stat Formatting Utility ---
def format_stat_value(stat_key: str, value: Any, is_percentage_stat: bool = False) -> str:
    """
    Formats a single stat value for display.
    'is_percentage_stat' can be pre-determined for efficiency if calling in a loop.
    """
    if value is None or (isinstance(value, float) and np.isnan(value)) or pd.isna(value):
        return "N/A"
    try:
        if is_percentage_stat or stat_key in PERCENTAGE_STATS: # Check explicit flag or constants
            return f"{float(value) * 100:.1f}%"
        if isinstance(value, (float, np.floating)):
            return f"{int(value)}" if float(value).is_integer() else f"{float(value):.1f}"
        return str(value)
    except (ValueError, TypeError):
        logger.warning(f"Format Error - Stat: '{stat_key}', Value: '{value}' (Type: {type(value)})")
        return str(value) # Fallback to raw string

# --- Core Embed Creation ---
def create_embed(
    title: str,
    description: str = "",
    color: Optional[discord.Color] = None, # Default to None, let Discord choose or set later
    timestamp: Optional[datetime] = None, # Allow passing specific timestamp
    author_name: Optional[str] = None,
    author_icon_url: Optional[str] = None,
    footer_text: Optional[str] = None,
    footer_icon_url: Optional[str] = None,
    thumbnail_url: Optional[str] = None,
    image_url: Optional[str] = None
) -> discord.Embed:
    """Creates a Discord embed with various optional elements."""
    final_color = color if color is not None else EMBED_COLOR_INFO # Default color if None
    embed = discord.Embed(title=title, description=description, color=final_color)

    if author_name:
        embed.set_author(name=author_name, icon_url=author_icon_url or discord.Embed.Empty)
    if footer_text:
        embed.set_footer(text=footer_text, icon_url=footer_icon_url or discord.Embed.Empty)
    if thumbnail_url and isinstance(thumbnail_url, str) and thumbnail_url.startswith('http'):
        embed.set_thumbnail(url=thumbnail_url)
    if image_url and isinstance(image_url, str) and image_url.startswith('http'):
        embed.set_image(url=image_url)
    if timestamp: # If True, use now. If datetime obj, use that.
        embed.timestamp = discord.utils.utcnow() if timestamp is True else timestamp
    return embed

# --- Specialized Embed Helpers ---
def success_embed(title: str, description: str = "") -> discord.Embed:
    return create_embed(f"{EMOJI_CHECK} {title}", description, color=EMBED_COLOR_SUCCESS, timestamp=True)

def warning_embed(title: str, description: str = "") -> discord.Embed: # Renamed from error_embed to avoid confusion
    return create_embed(f"{EMOJI_CROSS} {title}", description, color=EMBED_COLOR_ERROR, timestamp=True)

# MODIFIED error_embed to accept an optional title
def error_embed(description: str, *, title: Optional[str] = None) -> discord.Embed:
    """
    Creates an error embed. Allows an optional custom title.
    If title is not provided, defaults to "Error".
    """
    final_title = title if title else f"{EMOJI_CROSS} Error"
    return create_embed(final_title, description, color=EMBED_COLOR_ERROR, timestamp=True)

def info_embed(title: str, description: str = "") -> discord.Embed:
    return create_embed(f"{EMOJI_INFO} {title}", description, color=EMBED_COLOR_INFO, timestamp=True)

# --- Embed Field Management ---
MAX_EMBED_FIELDS = 25
MAX_FIELD_NAME_LENGTH = 256
MAX_FIELD_VALUE_LENGTH = 1024
MAX_EMBED_TOTAL_LENGTH = 6000

def _can_add_to_embed(embed: discord.Embed, num_fields_to_add: int = 1,
                      name_len: int = 0, value_len: int = 0) -> bool:
    """Checks if adding fields/chars would exceed Discord limits."""
    if len(embed.fields) + num_fields_to_add > MAX_EMBED_FIELDS:
        return False
    
    current_length = len(embed.title or "") + len(embed.description or "") + \
                     len(embed.footer.text or "") + len(embed.author.name or "")
    for field in embed.fields:
        current_length += len(field.name or "") + len(field.value or "")
    
    projected_new_length = name_len + value_len
    if current_length + projected_new_length > MAX_EMBED_TOTAL_LENGTH:
        return False
    return True

def add_stats_section_to_embed(
    embed: discord.Embed,
    section_title: str,
    stats_to_display: List[str], 
    data_source: Dict[str, Any], 
    inline_stats: bool = True,
    section_emoji: str = "" 
) -> int:
    """
    Adds a section of stats to an embed, respecting field and character limits.
    Returns: Number of actual stat value fields added (excluding the section title field).
    """
    if not isinstance(data_source, dict) or not stats_to_display:
        return 0

    stat_fields_to_add: List[Dict[str, Any]] = []
    total_chars_for_stats = 0

    for stat_key in stats_to_display:
        raw_value = data_source.get(stat_key)
        if raw_value is not None and not pd.isna(raw_value):
            display_name = STAT_DISPLAY_NAMES.get(stat_key, stat_key.replace('_', ' ').title())
            is_percent = stat_key in PERCENTAGE_STATS 
            formatted_value = format_stat_value(stat_key, raw_value, is_percentage_stat=is_percent)

            if len(display_name) > MAX_FIELD_NAME_LENGTH:
                logger.warning(f"Stat name '{display_name}' too long, truncating.")
                display_name = display_name[:MAX_FIELD_NAME_LENGTH-3] + "..."
            if len(formatted_value) > MAX_FIELD_VALUE_LENGTH:
                logger.warning(f"Stat value for '{display_name}' too long, truncating.")
                formatted_value = formatted_value[:MAX_FIELD_VALUE_LENGTH-3] + "..."
            
            stat_fields_to_add.append({"name": display_name, "value": formatted_value, "inline": inline_stats})
            total_chars_for_stats += len(display_name) + len(formatted_value)

    if not stat_fields_to_add:
        return 0 

    section_title_str = f"{section_emoji} **{section_title}**" if section_emoji else f"**{section_title}**"
    if not _can_add_to_embed(embed, 1, name_len=0, value_len=len(section_title_str)):
        logger.warning(f"Not enough space in embed for section title: '{section_title}'")
        return 0
    
    embed.add_field(name="\u200b", value=section_title_str, inline=False)
    
    stats_added_this_section = 0
    for field_data in stat_fields_to_add:
        if _can_add_to_embed(embed, 1, name_len=len(field_data["name"]), value_len=len(field_data["value"])):
            embed.add_field(**field_data)
            stats_added_this_section += 1
        else:
            logger.warning(f"Embed limit reached while adding stats for '{section_title}'. "
                           f"{len(stat_fields_to_add) - stats_added_this_section} stats truncated for this section.")
            if _can_add_to_embed(embed, 1, name_len=3, value_len=20):
                 embed.add_field(name="...", value="More stats truncated", inline=inline_stats)
            break
            
    return stats_added_this_section

# --- Team Info Embed Formatter (Example of using add_stats_section) ---
def format_team_profile_embed(
    team_bio_data: Optional[Dict[str, Any]], 
    team_season_stats: Optional[Dict[str, Any]], 
    team_logo_url: Optional[str]
) -> discord.Embed:
    """Formats combined team bio and season stats into an embed."""

    if not team_bio_data:
        # Using the MODIFIED error_embed
        return error_embed(description="Essential team information is missing.", title="Team Data Error")

    team_name = team_bio_data.get('TEAM_NAME', team_bio_data.get('DISPLAY_NAME', 'Unknown Team'))
    team_city = team_bio_data.get('TEAM_CITY', '')
    full_team_name = f"{team_city} {team_name}".strip() if team_city else team_name

    description_parts = []
    if 'TEAM_CONFERENCE' in team_bio_data and team_bio_data['TEAM_CONFERENCE'] != 'N/A':
        description_parts.append(f"Conference: {team_bio_data['TEAM_CONFERENCE']}")
    if 'TEAM_DIVISION' in team_bio_data and team_bio_data['TEAM_DIVISION'] != 'N/A':
        description_parts.append(f"Division: {team_bio_data['TEAM_DIVISION']}")
    
    record = "N/A"
    if team_season_stats and 'W' in team_season_stats and 'L' in team_season_stats:
        record = f"{team_season_stats['W']}-{team_season_stats['L']}"
        description_parts.append(f"Record: {record}")

    embed = create_embed(
        title=f"{EMOJI_TEAMS} {full_team_name}",
        description=" | ".join(filter(None, description_parts)) or "Team Profile",
        color=EMBED_COLOR_INFO, 
        thumbnail_url=team_logo_url,
        timestamp=True
    )

    if team_season_stats and isinstance(team_season_stats, dict) and "error" not in team_season_stats:
        add_stats_section_to_embed(
            embed, "Key Season Stats", TEAM_BASIC_STATS_PRIORITY, team_season_stats,
            inline_stats=True, section_emoji=EMOJI_STATS_BASIC
        )
        add_stats_section_to_embed(
            embed, "Key Advanced Stats", TEAM_ADVANCED_STATS_PRIORITY, team_season_stats,
            inline_stats=True, section_emoji=EMOJI_STATS_ADVANCED
        )
        add_stats_section_to_embed(
            embed, "Other Basic Stats", TEAM_BASIC_STATS_OTHER, team_season_stats,
            inline_stats=True
        )
        add_stats_section_to_embed(
            embed, "Other Advanced Stats", TEAM_ADVANCED_STATS_OTHER, team_season_stats,
            inline_stats=True
        )
    elif team_season_stats and "error" in team_season_stats:
        embed.add_field(name="Statistics Error", value=str(team_season_stats["error"]), inline=False)
    else:
        embed.add_field(name="Statistics", value="Season stats not available or not applicable.", inline=False)

    embed.set_footer(text="Data primarily from stats.nba.com")
    return embed

# --- Player Info Embed Formatter (Example) ---
def format_player_profile_embed(
    player_bio_data: Optional[Dict[str, Any]], 
    player_season_stats: Optional[Dict[str, Any]], 
    current_season_str: str 
) -> discord.Embed:
    """Formats player bio and season stats into an embed."""

    if not player_bio_data:
        return error_embed(description="Essential player information is missing.", title="Player Data Error")

    full_name = player_bio_data.get('full_name', 'Unknown Player')
    team_full = player_bio_data.get('team_full_name', 'N/A')
    team_abbr = player_bio_data.get('team_abbreviation', '')
    jersey = player_bio_data.get('JERSEY', '') 
    position = player_bio_data.get('POSITION', '')
    height = player_bio_data.get('HEIGHT', '')
    weight = player_bio_data.get('WEIGHT', '')
    if weight != 'N/A' and weight: weight += " lbs"

    title_str = f"{jersey} {full_name}".strip()

    description_parts = [
        f"{team_full} ({team_abbr})" if team_abbr and team_full != 'N/A' else team_full,
        position, height, weight
    ]
    description_str = " | ".join(filter(None, [p for p in description_parts if p and p != 'N/A']))
    if not description_str and team_full == 'N/A': description_str = "Free Agent or No Team Info"
    elif not description_str: description_str = "Bio details unavailable."

    embed = create_embed(
        title=f"{EMOJI_PLAYER} {title_str}",
        description=description_str,
        color=EMBED_COLOR_INFO, 
        thumbnail_url=player_bio_data.get('headshot_url'),
        timestamp=True
    )

    if player_season_stats and isinstance(player_season_stats, dict) and "error" not in player_season_stats:
        add_stats_section_to_embed(
            embed, f"Per Game Stats ({current_season_str})", PLAYER_BASIC_STATS_PRIORITY,
            player_season_stats, inline_stats=True, section_emoji=EMOJI_STATS_BASIC
        )
        add_stats_section_to_embed(
            embed, f"Advanced Stats ({current_season_str})", PLAYER_ADVANCED_STATS_PRIORITY,
            player_season_stats, inline_stats=True, section_emoji=EMOJI_STATS_ADVANCED
        )
        add_stats_section_to_embed(
            embed, f"Other Basic Stats ({current_season_str})", PLAYER_BASIC_STATS_OTHER,
            player_season_stats, inline_stats=True
        )
        add_stats_section_to_embed(
            embed, f"Other Advanced Stats ({current_season_str})", PLAYER_ADVANCED_STATS_OTHER,
            player_season_stats, inline_stats=True
        )

    elif player_season_stats and "error" in player_season_stats:
        embed.add_field(name=f"Statistics Error ({current_season_str})", value=str(player_season_stats["error"]), inline=False)
    else:
        embed.add_field(name=f"Statistics ({current_season_str})", value="Season stats not available or player did not play.", inline=False)

    draft_info = []
    if player_bio_data.get('DRAFT_YEAR', 'N/A') not in ['N/A', 'Undrafted', '']:
        draft_info.append(f"Year: {player_bio_data['DRAFT_YEAR']}")
    if player_bio_data.get('DRAFT_ROUND', 'N/A') not in ['N/A', 'Undrafted', '']:
        draft_info.append(f"Rnd: {player_bio_data['DRAFT_ROUND']}")
    if player_bio_data.get('DRAFT_NUMBER', 'N/A') not in ['N/A', 'Undrafted', '']:
        draft_info.append(f"Pick: {player_bio_data['DRAFT_NUMBER']}")
    
    if draft_info:
        if _can_add_to_embed(embed, 1, name_len=5, value_len=len(" | ".join(draft_info))):
             embed.add_field(name="Draft", value=" | ".join(draft_info), inline=True) 
    elif player_bio_data.get('DRAFT_YEAR') == 'Undrafted':
         if _can_add_to_embed(embed, 1, name_len=5, value_len=9):
             embed.add_field(name="Draft", value="Undrafted", inline=True)

    embed.set_footer(text="Data primarily from stats.nba.com")
    return embed

# --- Standings Embed ---
def format_standings_embed(standings_data: Optional[Dict[str, pd.DataFrame]]) -> discord.Embed:
    if not standings_data or not isinstance(standings_data, dict):
        return error_embed(description="Could not retrieve or process standings data.", title="Standings Error")

    embed = create_embed(
        title=f"{EMOJI_TROPHY} NBA Season Standings",
        color=EMBED_COLOR_STANDINGS,
        timestamp=True
    )
    embed.set_footer(text="Data from stats.nba.com | Clinch: C=Playoffs, P=Play-In, D=Div/Conf, E=Elim.")

    for conf_name_key, conf_df in standings_data.items(): 
        if conf_df is None or conf_df.empty:
            embed.add_field(name=f"{conf_name_key} Conference", value="No data available.", inline=False)
            continue

        rank_col = 'PlayoffRank' if 'PlayoffRank' in conf_df.columns else ('ConferenceRank' if 'ConferenceRank' in conf_df.columns else None)
        if rank_col:
            conf_df_sorted = conf_df.sort_values(by=rank_col)
        else:
            conf_df_sorted = conf_df 

        standings_str_parts = []
        for index, row in conf_df_sorted.head(15).iterrows(): 
            rank = row.get(rank_col, index + 1)
            team_name = row.get('TeamName', row.get('TEAM_NAME', 'N/A'))
            record = f"{row.get('WINS', row.get('W', '?'))}-{row.get('LOSSES', row.get('L', '?'))}"
            
            clinch_raw = str(row.get('ClinchIndicator', '')).strip().lower() # Normalize to lower
            clinch_note = ""
            if clinch_raw:
                if '-x' in clinch_raw or '-c' in clinch_raw : clinch_note = " (C)" 
                elif '-p' in clinch_raw or '-pi' in clinch_raw: clinch_note = " (P)" # Added -pi for play-in
                elif '-e' in clinch_raw or '-w' in clinch_raw : clinch_note = " (D)" 
                elif '-o' in clinch_raw : clinch_note = " (E)" 
            
            line = f"`{int(rank):>2}.` {team_name} ({record}){clinch_note}"
            standings_str_parts.append(line)
        
        field_value = "\n".join(standings_str_parts)
        if not field_value: field_value = "No teams to display."
        
        if len(field_value) > MAX_FIELD_VALUE_LENGTH:
            field_value = field_value[:MAX_FIELD_VALUE_LENGTH-20] + "\n...more teams"

        # Using a generic conference emoji or define specific ones in constants
        conf_display_name = f"{EMOJI_INFO} {conf_name_key.title()} Conference"
        if _can_add_to_embed(embed, 1, name_len=len(conf_display_name), value_len=len(field_value)):
            embed.add_field(name=conf_display_name, value=field_value, inline=True) 
        else:
            logger.warning(f"Could not add {conf_name_key} standings to embed due to size limits.")
            break 

    return embed