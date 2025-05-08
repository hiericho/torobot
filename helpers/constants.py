# helpers/constants.py
import discord

# --- Season Definitions ---
CURRENT_SEASON = "2024-25" # Consider making this dynamic (e.g., fetch from bot init)
PREVIOUS_SEASON = "2023-24" # Consider making this dynamic

# --- API Settings ---
NBA_API_TIMEOUT = 20 # Default timeout for NBA API calls in seconds (adjusted from 30 for responsiveness)
FUZZY_MATCH_THRESHOLD = 80 # Minimum score (0-100) for fuzzy name matching

# --- URLs ---
PLAYER_HEADSHOT_URL_TEMPLATE = "https://cdn.nba.com/headshots/nba/latest/1040x760/{player_id}.png"
TEAM_LOGO_URL_TEMPLATE = "https://cdn.nba.com/logos/nba/{team_id}/primary/L/logo.svg"
TEAM_LOGO_URL_ESPN = "https://a.espncdn.com/i/teamlogos/nba/500/{team_abbr_lower}.png" # ESPN example
ESPN_NBA_SCOREBOARD_URL = "http://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"

# --- Prediction Defaults ---
DEFAULT_AVG_PPG = 112.0 # Default PPG if API fails or season hasn't started
WEIGHT_CURRENT = 0.70   # Weight for current season in predictions
WEIGHT_PREVIOUS = 0.30  # Weight for previous season in predictions

# --- Embed Colors (Lighter/Clearer Palette) ---
EMBED_COLOR_INFO = discord.Color.from_rgb(100, 149, 237) # Cornflower Blue
EMBED_COLOR_GAME = discord.Color.from_rgb(255, 165, 0)   # Orange
EMBED_COLOR_PREDICT = discord.Color.from_rgb(153, 50, 204) # Dark Orchid
EMBED_COLOR_SUCCESS = discord.Color.from_rgb(60, 179, 113)  # Medium Sea Green
EMBED_COLOR_ERROR = discord.Color.from_rgb(220, 20, 60)    # Crimson
EMBED_COLOR_UTILITY = discord.Color.from_rgb(211, 211, 211) # Light Gray
EMBED_COLOR_STANDINGS = discord.Color.from_rgb(255, 215, 0) # Gold

# --- Emojis (Selected for current commands + general use) ---
# General
EMOJI_BALL = "🏀"
EMOJI_CHECK = "✅"
EMOJI_CROSS = "❌"
EMOJI_INFO = "ℹ️"
EMOJI_ERROR = "❗"
EMOJI_WARNING = "⚠️"
EMOJI_CALENDAR = "📅"
EMOJI_CLOCK = "🕒"
EMOJI_PIN = "📌"
EMOJI_STAR = "⭐"
EMOJI_PLAYER = "⛹️‍♂️" # <-- ADDED (or use 👤, 🧑)
EMOJI_STATS_BASIC = "📊" # <-- ADDED
EMOJI_STATS_ADVANCED = "✨" # <-- ADDED (or use 🔬, 📈)
EMOJI_EAST = "➡️" # <-- ADDED
EMOJI_WEST = "⬅️" # <-- ADDED

# Command Specific
EMOJI_COMMANDS = "📋"
EMOJI_TEAMS = "🏀" # Reuse ball for /teams list
EMOJI_LIVE = "🔴"
EMOJI_FINAL = EMOJI_CHECK

# Versus Command
EMOJI_AWAY = "✈️"
EMOJI_HOME = "🏠"
EMOJI_ROAD_WIN = "🛣️"
EMOJI_FORM = "📈"
EMOJI_TROPHY = "🏆" # For H2H Wins / Record
EMOJI_STATS = "📊" # For H2H Winrate / Win Prob / +/- (Reusing basic stats emoji)
EMOJI_TARGET = "🎯" # For Avg PTS / APG / 3P%
EMOJI_SCORE = "🔢"
EMOJI_TOTAL = EMOJI_FORM # Reuse graph emoji for total
EMOJI_WINNER = "🔮"
EMOJI_CLOSE = "⚖️"

# Stats Specific (Can be used in STAT_DISPLAY_NAMES or future commands)
EMOJI_RECORD = EMOJI_TROPHY
EMOJI_PPG = "🔥"
EMOJI_RPG = EMOJI_BALL
EMOJI_APG = EMOJI_TARGET
EMOJI_SPG = "🖐️"
EMOJI_BPG = EMOJI_CROSS
EMOJI_FG_PCT = "⚙️"
EMOJI_3P_PCT = EMOJI_TARGET
EMOJI_FT_PCT = EMOJI_CLOSE
EMOJI_PLUS_MINUS = EMOJI_STATS # Reuse basic stats emoji
EMOJI_TOV = EMOJI_ERROR
EMOJI_EFF = EMOJI_STAR

# --- Stat Lists (For potential future use/standardization) ---
PLAYER_BASIC_STATS = ["GP", "MIN","PTS", "AST", "REB", "STL", "BLK", "TOV","FGM", "FGA", "FG3M", "FG3A", "FTM", "FTA","FG_PCT", "FG3_PCT", "FT_PCT","OREB", "DREB","PF", "PLUS_MINUS", "EFF"]
PLAYER_ADVANCED_STATS = ["PFD","AST_TOV","TS_PCT","OFF_RATING","DEF_RATING","NET_RATING","AST_PCT"]
ALL_PLAYER_STATS_REQUESTED = list(set(PLAYER_BASIC_STATS + PLAYER_ADVANCED_STATS))
TEAM_BASIC_STATS = ['W', 'L', 'W_PCT','PTS', 'REB', 'AST','FG_PCT', 'FG3_PCT', "FT_PCT",'OREB', 'DREB', 'STL', 'BLK', 'TOV','PF', 'PLUS_MINUS', 'EFF','GP', 'MIN','CONF_RANK', 'DIV_RANK']
TEAM_ADVANCED_STATS = ["PFD","OFF_RATING","DEF_RATING","NET_RATING","AST_RATIO","AST_TOV","OREB_PCT","DREB_PCT","REB_PCT","TM_TOV_PCT","EFG_PCT","TS_PCT","EFF"]
ALL_TEAM_STATS_REQUESTED = list(set(TEAM_BASIC_STATS + TEAM_ADVANCED_STATS))
# helpers/constants.py
# ... other constants ...

STAT_DISPLAY_NAMES = {
    'PTS': 'Points', 'REB': 'Rebounds', 'AST': 'Assists', # ... and so on for ALL stat keys you use
    'FG_PCT': 'FG%', 'FG3_PCT': '3P%', 'FT_PCT': 'FT%',
    'OFF_RATING': 'Off. Rating', 'DEF_RATING': 'Def. Rating', 'NET_RATING': 'Net Rating',
    'TS_PCT': 'TS%', 'EFG_PCT': 'eFG%', 'USG_PCT': 'USG%', 'PACE': 'Pace',
    # ... add all player and team stat keys you fetch from nba-api
}

PERCENTAGE_STATS = [
    'FG_PCT', 'FG3_PCT', 'FT_PCT', 'TS_PCT', 'EFG_PCT', 'USG_PCT', 'WIN_PCT', 'REB_PCT'
    # Add any other stat keys that represent percentages and need '*' 100 and '%'
]

# --- For Team Embeds ---
TEAM_BASIC_STATS_PRIORITY = ['PTS', 'REB', 'AST', 'FG_PCT', 'FG3_PCT', 'PLUS_MINUS'] # Example
TEAM_ADVANCED_STATS_PRIORITY = ['OFF_RATING', 'DEF_RATING', 'NET_RATING', 'TS_PCT', 'PACE'] # Example
TEAM_BASIC_STATS_OTHER = ['STL', 'BLK', 'TOV', 'FT_PCT', 'W', 'L'] # Example
TEAM_ADVANCED_STATS_OTHER = ['EFG_PCT', 'PIE'] # Example

# --- For Player Embeds ---
PLAYER_BASIC_STATS_PRIORITY = ['PTS', 'REB', 'AST', 'STL', 'BLK', 'FG_PCT', 'FG3_PCT'] # Example
PLAYER_ADVANCED_STATS_PRIORITY = ['TS_PCT', 'USG_PCT', 'NET_RATING', 'PIE'] # Example PER might be from B-Ref
PLAYER_BASIC_STATS_OTHER = ['TOV', 'FT_PCT', 'MIN', 'GP', 'PLUS_MINUS'] # Example
PLAYER_ADVANCED_STATS_OTHER = ['EFG_PCT', 'PACE', 'OFF_RATING', 'DEF_RATING'] # Example
# --- Stat Display Names (Optional - can be expanded) ---
# This dictionary allows you to map internal stat keys to user-friendly names/emojis
STAT_DISPLAY_NAMES = {
    # Team Stats
    "W": f"{EMOJI_RECORD} Wins", "L": f"{EMOJI_RECORD} Losses", "W_PCT": f"{EMOJI_RECORD} Win%",
    "CONF_RANK": f"{EMOJI_TROPHY} Conf Rank", "DIV_RANK": f"{EMOJI_TROPHY} Div Rank",
    "PTS": f"{EMOJI_PPG} PPG", "REB": f"{EMOJI_RPG} RPG", "AST": f"{EMOJI_APG} APG",
    "STL": f"{EMOJI_SPG} SPG", "BLK": f"{EMOJI_BPG} BPG", "TOV": f"{EMOJI_TOV} TOV",
    "FG_PCT": f"{EMOJI_FG_PCT} FG%", "FG3_PCT": f"{EMOJI_3P_PCT} 3P%", "FT_PCT": f"{EMOJI_FT_PCT} FT%",
    "PLUS_MINUS": f"{EMOJI_PLUS_MINUS} +/- PG",
    # Player Stats (Add similar mappings)
    "GP": "Games Played", "MIN": "MPG",
    # Advanced Stats
    "OFF_RATING": "Off Rtg", "DEF_RATING": "Def Rtg", "NET_RATING": "Net Rtg",
    "AST_RATIO": "Ast Ratio", "AST_TOV": "Ast/TO", "OREB_PCT": "OReb%", "DREB_PCT": "DReb%",
    "REB_PCT": "Reb%", "TM_TOV_PCT": "TOV%", "EFG_PCT": "eFG%", "TS_PCT": "TS%",
    "PIE": f"{EMOJI_STATS_ADVANCED} PIE",
    "EFF": f"{EMOJI_EFF} EFF"
    # Add more mappings as needed...
}

# --- Stat Formatting Rules ---
# Stats that should be displayed as percentages
PERCENTAGE_STATS = [
    "FG_PCT", "FG3_PCT", "FT_PCT", "W_PCT", # Basic %
    "AST_PCT", "OREB_PCT", "DREB_PCT", "REB_PCT", # Advanced %
    "TM_TOV_PCT", "EFG_PCT", "TS_PCT", "PIE", # Advanced %
]

# Stats that typically have one decimal place
ONE_DECIMAL_STATS = [
    "PTS", "REB", "AST", "STL", "BLK", "TOV", "PF", "MIN", # Basic Per Game
    "OFF_RATING", "DEF_RATING", "NET_RATING", "AST_RATIO", "AST_TOV", # Advanced Ratings/Ratios
    "PLUS_MINUS", # Often shown with one decimal place per game
]

# Stats that are often signed (+/-)
SIGNED_STATS = ["PLUS_MINUS", "NET_RATING"]