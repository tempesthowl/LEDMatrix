"""
Baseball Rankings Manager

Handles team rankings fetching and caching for all baseball leagues.
"""

import logging
import time
from typing import Dict, Optional

try:
    from src.base_classes.data_sources import ESPNDataSource
except ImportError:
    ESPNDataSource = None


class BaseballRankingsManager:
    """Manages team rankings fetching and caching."""

    def __init__(self, logger: logging.Logger):
        """
        Initialize the rankings manager.

        Args:
            logger: Logger instance
        """
        self.logger = logger

        # Initialize data source if available
        if ESPNDataSource:
            try:
                self.data_source = ESPNDataSource(logger)
            except Exception as e:
                self.logger.warning(f"Failed to initialize ESPNDataSource: {e}")
                self.data_source = None
        else:
            self.data_source = None
            self.logger.warning("ESPNDataSource not available - rankings functionality disabled")

        # Rankings cache
        self._team_rankings_cache: Dict[str, Dict[str, int]] = {}  # league_key -> {team_abbr: rank}
        self._rankings_cache_timestamp: Dict[str, float] = {}  # league_key -> timestamp
        self._rankings_cache_duration = 3600  # Cache rankings for 1 hour

    def fetch_rankings(self, sport: str, league: str, league_key: str = None) -> Dict[str, int]:
        """
        Fetch team rankings for a specific league.

        Args:
            sport: Sport name (e.g., "baseball")
            league: League identifier (e.g., "mlb", "college-baseball")
            league_key: League key for caching (e.g., "mlb", "ncaa_baseball")

        Returns:
            Dictionary mapping team abbreviations to ranks, or empty dict if unavailable
        """
        if not self.data_source:
            return {}

        # Use league_key for caching if provided, otherwise use league
        cache_key = league_key or league
        current_time = time.time()

        # Check if we have cached rankings that are still valid
        if (cache_key in self._team_rankings_cache and 
            cache_key in self._rankings_cache_timestamp and
            current_time - self._rankings_cache_timestamp[cache_key] < self._rankings_cache_duration):
            return self._team_rankings_cache[cache_key]

        try:
            data = self.data_source.fetch_standings(sport, league)

            rankings = {}
            rankings_data = data.get('rankings', [])

            if rankings_data:
                # Use the first ranking (usually AP Top 25 or similar)
                first_ranking = rankings_data[0]
                teams = first_ranking.get('ranks', [])

                for team_data in teams:
                    team_info = team_data.get('team', {})
                    team_abbr = team_info.get('abbreviation', '')

                    # Try alternative abbreviation fields
                    if not team_abbr:
                        team_abbr = team_info.get('abbr', '')

                    current_rank = team_data.get('current', 0)

                    # Also try 'rank' field as fallback
                    if current_rank == 0:
                        current_rank = team_data.get('rank', 0)

                    if team_abbr and current_rank > 0:
                        rankings[team_abbr] = current_rank

            # Cache the results
            self._team_rankings_cache[cache_key] = rankings
            self._rankings_cache_timestamp[cache_key] = current_time

            self.logger.debug(f"Fetched rankings for {len(rankings)} teams in {cache_key}")
            return rankings

        except Exception as e:
            self.logger.error(f"Error fetching team rankings for {cache_key}: {e}")
            return {}

    def get_team_rank(self, team_abbr: str, league_key: str) -> int:
        """
        Get ranking for a specific team.

        Args:
            team_abbr: Team abbreviation
            league_key: League key for cache lookup

        Returns:
            Team rank (0 if not ranked or not found)
        """
        rankings = self._team_rankings_cache.get(league_key, {})
        return rankings.get(team_abbr, 0)

    def clear_cache(self, league_key: Optional[str] = None) -> None:
        """
        Clear rankings cache.

        Args:
            league_key: Specific league to clear, or None to clear all
        """
        if league_key:
            self._team_rankings_cache.pop(league_key, None)
            self._rankings_cache_timestamp.pop(league_key, None)
            self.logger.debug(f"Cleared rankings cache for {league_key}")
        else:
            self._team_rankings_cache.clear()
            self._rankings_cache_timestamp.clear()
            self.logger.debug("Cleared all rankings cache")

