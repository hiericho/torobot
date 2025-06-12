# NBA Stats Bot (ToroBot) - [V2]

🏀 **Welcome, to a feature-rich Discord bot providing NBA stats, game information, and more!** 🏀

## Table of Contents

- [About The Project](#about-the-project)
- [Features](#features)
- [Commands](#commands)
- [Getting Started](#getting-started)
  - [Prerequisites](#prerequisites)
  - [Installation & Setup](#installation--setup)
- [Usage](#usage)
- [Configuration](#configuration)
- [Technology Stack](#technology-stack)
- [Contributing](#contributing)
- [License](#license)
- [Acknowledgements](#acknowledgements)

## About The Project

ToroBot is a Discord bot designed for basketball enthusiasts. It leverages the [nba_api](https://github.com/swar/nba_api) to fetch real-time and historical NBA data, providing users with player stats, team information, game schedules, live scores, and even some fun predictions.

This bot was created to make NBA information easily accessible on Discord, learn Python and discord.py, experiment with sports APIs.

## Features

*   **Live Game Scores & Updates:** Get today's game information.
*   **Comprehensive Player Statistics:** Detailed stats for any active NBA player.
*   **Team Information:** Team rosters, season stats, and general team details.
*   **League Standings:** Up-to-date conference and division standings.
*   **Game Schedules:** View upcoming games.
*   **Injury Reports:** Stay informed about player injuries.
*   **Machine Learning Predictions!** 
*   **Dynamic Bot Status:** Bot's presence changes periodically to reflect NBA activities.
*   **User-Friendly Commands:** Easy-to-use slash commands with autocomplete.

## Commands

Here's a list of the primary slash commands available:

*   `/today`: Displays today's NBA games, including live scores and upcoming matchups.
*   `/commands`: Shows a list of all available bot commands and their descriptions.
*   `/playerstats [player_name]`: Fetches and displays detailed statistics for the specified player.
*   `/teamstats [team_name_or_id]`: Provides statistics and information for the specified NBA team.
*   `/injuries [team_name_or_id (optional)]`: Shows current injury reports, optionally filtered by team.
*   `/ping`: Checks the bot's latency to Discord.
*   `/schedule [team_name_or_id (optional)] [date (optional)]`: Displays the NBA game schedule, filterable by team and date.
*   `/machinelearning [parameters...]`: predicts game outcomes based on team matchups.
*   `/season`: Shows the current NBA season standings.
*   `/typeseason [away_team] [home_team] [typeseason (optional)]`: Provides Head-to-Head stats and a prediction for a matchup, filterable by the type of season (Regular, Playoffs, etc.).
*   `/compareteams [team1] [team2]`: Compares two NBA teams based on various statistical categories.
*   
For more details on command usage, type `/commands` in a server where the bot is present.

## Getting Started

To get a local copy up and running for development or self-hosting, follow these steps.

### Prerequisites

*   Python 3.10 or higher
*   pip (Python package installer)
*   Git (for cloning the repository)
*   A Discord Bot Token (Create one on the [Discord Developer Portal](https://discord.com/developers/applications))

### Installation & Setup

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/hiericho/torobot
    ```

2.  **Create and activate a virtual environment (recommended):**
    ```bash
    python3 -m venv venv
    source venv/bin/activate
    # On Windows: venv\Scripts\activate
    ```

3.  **Install dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

4.  **Set up environment variables:**
    Create a `.env` file in the root project directory:
    ```env
    DISCORD_TOKEN=YOUR_DISCORD_BOT_TOKEN_HERE
    ```
    Replace `YOUR_DISCORD_BOT_TOKEN_HERE` with your actual bot token.

5.  **Configure the bot (if necessary):**
    Review `config.py` or the configuration section in `bot.py`/`main.py` for any default settings you might want to adjust (e.g., `CURRENT_SEASON`, `API_TIMEOUT_SECONDS`).

6.  **Run the bot:**
    ```bash
    python bot.py  # Or your main script name (e.g., main.py)
    ```

## Usage

Once the bot is running and invited to your Discord server:

1.  Make sure the bot has the necessary permissions in the channels where you want to use it (Read Messages, Send Messages, Embed Links, Use Application Commands).
2.  Start using the slash commands listed in the [Commands](#commands) section (e.g., `/today`, `/playerstats LeBron James`).

## Configuration

The main configuration for the bot. Key configurable items include:

*   `CURRENT_SEASON`: The default NBA season string (e.g., "2023-24", "2024-25").
*   `PREVIOUS_SEASON`: The previous NBA season string.
*   `API_TIMEOUT_SECONDS`: Timeout for calls to the NBA API.
*   `DEFAULT_STREAMING_URL`: Default URL used for some "Streaming" statuses.

Environment variables (like `DISCORD_TOKEN`) are managed in the `.env` file.

## Technology Stack

*   **Language:** Python 3
*   **Library:** [discord.py](https://discordpy.readthedocs.io/en/stable/)
*   **API:** [nba-api](https://github.com/swar/nba_api) (for NBA data)
*   **Data Handling:** [Pandas](https://pandas.pydata.org/)
*   **Asynchronous Operations:** [asyncio](https://docs.python.org/3/library/asyncio.html)
*   **Environment Management:** [python-dotenv](https://pypi.org/project/python-dotenv/)
*   [Add any other significant libraries or technologies, e.g., aiohttp, specific database libraries, scikit-learn for ML]

## Contributing

Contributions are what make the open-source community such an amazing place to learn, inspire, and create. Any contributions you make are **greatly appreciated**.

If you have a suggestion that would make this better, please fork the repo and create a pull request. You can also simply open an issue with the tag "enhancement".
Don't forget to give the project a star! Thanks again!

1.  Fork the Project
2.  Create your Feature Branch (`git checkout -b feature/AmazingFeature`)
3.  Commit your Changes (`git commit -m 'Add some AmazingFeature'`)
4.  Push to the Branch (`git push origin feature/AmazingFeature`)
5.  Open a Pull Request

## License

Distributed under the MIT License. See `LICENSE.txt` for more information.

## Acknowledgements

*   The [nba_api Python library](https://github.com/swar/nba_api) by Swar Shah and contributors.
*   [stats.nba.com](https://stats.nba.com) for providing the data.
*   The [discord.py](https://github.com/Rapptz/discord.py) library and its community.
