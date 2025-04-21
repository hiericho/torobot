# utils/team_mapper.py
import logging

logger = logging.getLogger(__name__)

# Mapping from Full Team Name (from ESPN API) to the code used in ESPN logo URLs
# NOTE: Verify these displayNames match exactly what the API returns!
# You might need to run the fetcher once and log the team_name keys to confirm.
ESPN_TEAM_CODES_FOR_LOGO = {
    "Atlanta Hawks": "atl",
    "Boston Celtics": "bos",
    "Brooklyn Nets": "bkn",
    "Charlotte Hornets": "cha",
    "Chicago Bulls": "chi",
    "Cleveland Cavaliers": "cle",
    "Dallas Mavericks": "dal",
    "Denver Nuggets": "den",
    "Detroit Pistons": "det",
    "Golden State Warriors": "gsw",
    "Houston Rockets": "hou",
    "Indiana Pacers": "ind",
    "LA Clippers": "lac", # Note: API might use "LA" or "Los Angeles"
    "Los Angeles Lakers": "lal",
    "Memphis Grizzlies": "mem",
    "Miami Heat": "mia",
    "Milwaukee Bucks": "mil",
    "Minnesota Timberwolves": "min",
    "New Orleans Pelicans": "nop",
    "New York Knicks": "nyk",
    "Oklahoma City Thunder": "okc",
    "Orlando Magic": "orl",
    "Philadelphia 76ers": "phi",
    "Phoenix Suns": "phx",
    "Portland Trail Blazers": "por",
    "Sacramento Kings": "sac",
    "San Antonio Spurs": "sas",
    "Toronto Raptors": "tor",
    "Utah Jazz": "utah", # Check if API uses 'utah' or 'uta'
    "Washington Wizards": "wsh",
}

# Function to find the logo code based on various inputs, comparing against API names
def find_espn_logo_code(team_input: str, api_team_names: list[str]) -> tuple[str | None, str | None]:
    """
    Finds the ESPN logo code and canonical API team name based on user input.

    Args:
        team_input: User's input string (name, abbr, etc.).
        api_team_names: List of actual displayNames returned by the API.

    Returns:
        A tuple: (espn_logo_code, canonical_api_team_name) or (None, None) if not found.
    """
    team_input_lower = team_input.lower()

    # Exact match against known API names first
    for api_name in api_team_names:
        if team_input_lower == api_name.lower():
            logo_code = ESPN_TEAM_CODES_FOR_LOGO.get(api_name)
            if logo_code:
                return logo_code, api_name
            else:
                 logger.warning(f"Found API name match '{api_name}' but no logo code defined in ESPN_TEAM_CODES_FOR_LOGO.")
                 return None, api_name # Return name even if logo code missing

    # Partial match against API names
    for api_name in api_team_names:
        if team_input_lower in api_name.lower():
             logo_code = ESPN_TEAM_CODES_FOR_LOGO.get(api_name)
             if logo_code:
                 return logo_code, api_name
             else:
                 logger.warning(f"Found partial API name match '{api_name}' but no logo code defined.")
                 return None, api_name

    # Fallback: Check if input matches a value in ESPN_TEAM_CODES_FOR_LOGO (e.g., user typed 'lal')
    for api_name, code in ESPN_TEAM_CODES_FOR_LOGO.items():
         if team_input_lower == code:
              # Ensure this API name actually exists in the fetched data
              if api_name in api_team_names:
                   return code, api_name
              else:
                   logger.warning(f"Input '{team_input}' matched logo code '{code}' but corresponding API name '{api_name}' not found in fetched data.")

    logger.warning(f"Could not map user input '{team_input}' to any known team name or logo code.")
    return None, None # Not found