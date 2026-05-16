"""WiGLE SSID geolocation lookup with caching.

On-demand client for the WiGLE API v2.  Returns observed locations
for a given SSID, scoped by the GPS bounding box in config.json.
Disabled gracefully when WIGLE_API_TOKEN is not set.
"""

import logging
import os

import requests

from cyt.input_validation import InputValidator

logger = logging.getLogger(__name__)

_WIGLE_SEARCH_URL = "https://api.wigle.net/api/v2/network/search"
_REQUEST_TIMEOUT = 25  # seconds — WiGLE free tier is slow (~10s typical)


class WiGLEError(Exception):
    """Base exception for WiGLE client errors."""


class WiGLERateLimited(WiGLEError):
    """Raised when the WiGLE API returns 429."""


class WiGLEClient:
    """Thin wrapper around the WiGLE network search endpoint.

    Parameters
    ----------
    api_token : str or None
        WiGLE API token.  Falls back to the ``WIGLE_API_TOKEN`` env var.
    search_bounds : dict or None
        GPS bounding box with keys ``lat_min``, ``lat_max``,
        ``lon_min``, ``lon_max``.  Omit or pass empty dict to
        search globally.
    """

    def __init__(self, api_token: str | None = None, search_bounds: dict | None = None):
        self._token = api_token or os.environ.get("WIGLE_API_TOKEN", "")
        self._bounds = search_bounds or {}
        self._enabled = bool(self._token)
        if not self._enabled:
            logger.info("WiGLE API token not configured — geolocation disabled")

    @property
    def enabled(self) -> bool:
        return self._enabled

    def lookup_ssid(self, ssid: str) -> list[dict]:
        """Query WiGLE for observed locations of *ssid*.

        Returns a list of dicts, each with keys:
        ``lat``, ``lon``, ``city``, ``region``, ``country``,
        ``first_seen``, ``last_seen``.

        Returns an empty list on validation failure, missing token,
        or any non-rate-limit error.  Raises ``WiGLERateLimited``
        on a 429 response so callers can surface quota feedback.
        """
        if not self._enabled:
            return []

        if not InputValidator.validate_ssid(ssid):
            logger.warning("WiGLE lookup rejected — invalid SSID: %r", ssid)
            return []

        params: dict = {"ssid": ssid}
        if self._bounds:
            for key in ("lat_min", "lat_max", "lon_min", "lon_max"):
                val = self._bounds.get(key)
                if val and float(val) != 0.0:
                    # WiGLE API uses latrange1/latrange2/longrange1/longrange2
                    api_key = {
                        "lat_min": "latrange1",
                        "lat_max": "latrange2",
                        "lon_min": "longrange1",
                        "lon_max": "longrange2",
                    }[key]
                    params[api_key] = float(val)

        headers = {
            "Authorization": f"Basic {self._token}",
            "Accept": "application/json",
        }

        try:
            resp = requests.get(
                _WIGLE_SEARCH_URL,
                params=params,
                headers=headers,
                timeout=_REQUEST_TIMEOUT,
            )
        except requests.RequestException as exc:
            logger.error("WiGLE API request failed: %s", exc)
            return []

        if resp.status_code == 429:
            logger.warning("WiGLE API rate limit reached")
            raise WiGLERateLimited("WiGLE API quota exceeded")

        if resp.status_code == 401:
            logger.error("WiGLE API authentication failed — check WIGLE_API_TOKEN")
            return []

        if resp.status_code != 200:
            logger.error("WiGLE API returned %d: %s", resp.status_code, resp.text[:200])
            return []

        try:
            data = resp.json()
        except ValueError:
            logger.error("WiGLE API returned non-JSON response")
            return []

        # WiGLE returns 200 with {"success":false,"message":"too many queries today"}
        if not data.get("success", True):
            msg = data.get("message", "")
            if "too many" in msg.lower() or "quota" in msg.lower():
                logger.warning("WiGLE API daily quota exceeded")
                raise WiGLERateLimited("WiGLE API quota exceeded")
            logger.error("WiGLE API error: %s", msg)
            return []

        results = []
        for net in data.get("results", []):
            results.append({
                "lat": net.get("trilat"),
                "lon": net.get("trilong"),
                "city": net.get("city", ""),
                "region": net.get("region", ""),
                "country": net.get("country", ""),
                "first_seen": net.get("firsttime", ""),
                "last_seen": net.get("lasttime", ""),
            })

        logger.info("WiGLE lookup for SSID %r returned %d results", ssid, len(results))
        return results
