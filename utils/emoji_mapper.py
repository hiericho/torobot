# utils/emoji_mapper.py
INJURY_EMOJIS = {
    "Out": "❌",
    "Day-To-Day": "🤔",
    "Questionable": "❓",
    "Probable": "✅",
    "Game Time Decision": "🤔",
    "Suspension": "⚖️",
    "Personal": "👤",
    "Illness": "🤒",
    "Default": "🩼" # Fallback
}

def get_injury_emoji(status_string: str) -> str:
    """Gets emoji based on status (case-sensitive)."""
    return INJURY_EMOJIS.get(status_string, INJURY_EMOJIS["Default"])