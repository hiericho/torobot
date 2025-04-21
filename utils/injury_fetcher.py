# utils/injury_fetcher.py
import aiohttp
import logging
import json
from typing import Dict, List, Tuple, Optional
import asyncio

logger = logging.getLogger(__name__)

class InjuryReportFetcher:
    """Fetches and parses injury data from ESPN's API."""

    API_URL = "http://site.api.espn.com/apis/site/v2/sports/basketball/nba/injuries"

    def __init__(self, session: Optional[aiohttp.ClientSession] = None):
        self._session = session
        self.headers = {
             'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
             'Accept': 'application/json'
        }

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(headers=self.headers)
            logger.debug("Created new aiohttp session for InjuryReportFetcher.")
        return self._session

    async def close_session(self):
        if self._session and not self._session.closed:
            await self._session.close()
            logger.info("Closed internal aiohttp session for InjuryReportFetcher.")

    # --- Optimized fetch_injuries function ---
    async def fetch_injuries(self) -> Tuple[Optional[Dict[str, List[Dict]]], Optional[str]]:
        """Fetches injury data for all teams from the ESPN API."""
        session = await self._get_session()
        all_team_injuries: Dict[str, List[Dict]] = {}
        logger.info(f"Fetching all team injuries from ESPN API: {self.API_URL}")

        try:
            async with session.get(self.API_URL, timeout=25) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    logger.error(f"ESPN API request failed with status {resp.status}: {error_text[:500]}")
                    return None, f"ESPN API Error: Status {resp.status}"

                try:
                    data = await resp.json(content_type=None)
                except (json.JSONDecodeError, aiohttp.ContentTypeError) as data_err:
                    raw_text = await resp.text()
                    logger.error(f"Failed to get/decode JSON response from ESPN API: {data_err}")
                    logger.debug(f"Raw response text (first 500 chars): {raw_text[:500]}")
                    return None, f"Received invalid data from ESPN injury API: {type(data_err).__name__}."

                # --- DIRECT ACCESS TO 'injuries' KEY ---
                if isinstance(data, dict):
                    teams_list = data.get('injuries') # Directly get the list using the confirmed key
                    if isinstance(teams_list, list):
                        logger.info("Found teams list under key: 'injuries'.")
                    else:
                        logger.error("API response is a dict, but key 'injuries' does not contain a list.")
                        logger.debug(f"Value under 'injuries' key: {str(teams_list)[:500]}")
                        return None, "API data structure error: 'injuries' key invalid."
                else:
                    # Should not happen based on logs, but keep as safety check
                    logger.error(f"Unexpected API response format. Expected dict, got {type(data)}.")
                    logger.debug(f"API Data Sample: {str(data)[:500]}")
                    return None, "Unexpected data structure (not a dict) received from ESPN injury API."

                # --- Parse the teams_list (common logic remains the same) ---
                for team_data_container in teams_list:
                    # Data might be team_data_container['team'] or just team_data_container
                    if isinstance(team_data_container, dict):
                        # The team info is directly in the container dict based on the sample JSON
                        # team_info = team_data_container.get('team', team_data_container)
                        team_info = team_data_container # Use the container directly

                        team_name = team_info.get('displayName')
                        team_injuries_list = team_info.get('injuries')

                        if team_injuries_list is None or not isinstance(team_injuries_list, list):
                            team_injuries_list = []

                        if not team_name:
                            logger.warning(f"Skipping team data due to missing name: {str(team_info)[:100]}")
                            continue

                        parsed_injuries: List[Dict] = []
                        for injury in team_injuries_list:
                            if not isinstance(injury, dict): continue
                            athlete_info = injury.get('athlete', {})
                            player_name = athlete_info.get('displayName')
                            status = injury.get('status', injury.get('type', {}).get('description')) # Get status
                            comment = injury.get('shortComment', injury.get('longComment', 'No details provided.')) # Get comment

                            if player_name and status:
                                parsed_injuries.append({
                                    "name": player_name.strip(),
                                    "status": status.strip().title(),
                                    "comment": comment.strip() if comment else 'No details provided.'
                                })
                            else: logger.warning(f"Skipping injury entry due to missing name/status: {str(injury)[:100]}")

                        all_team_injuries[team_name] = parsed_injuries
                    else:
                         logger.warning(f"Skipping item in teams_list, expected dict, got {type(team_data_container)}")

                # Log if fewer than 30 teams were parsed, might indicate API issue
                if len(all_team_injuries) < 25: # Lowered threshold slightly
                    logger.warning(f"Parsed injury data for only {len(all_team_injuries)} teams. API might be incomplete?")

                logger.info(f"Successfully parsed injury data for {len(all_team_injuries)} teams.")
                return all_team_injuries, None

        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            logger.error(f"Network/Timeout error fetching ESPN injuries API: {e}")
            return None, f"Could not connect to ESPN API (or request timed out): {type(e).__name__}."
        except Exception as e:
            logger.error(f"Unexpected error processing ESPN injury API data: {e}", exc_info=True)
            return None, "An unexpected error occurred while processing injury data."
    # --- END OF fetch_injuries FUNCTION ---