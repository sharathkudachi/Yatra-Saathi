"""Geocoding Service for Yatra Emergency Assistance.

Provides search / autocomplete for manual location entry in the Emergency Assistance
modal using OpenStreetMap Nominatim with local database fallback.

Adheres strictly to Nominatim Usage Policy:
- Explicit custom User-Agent identifying the application
- Max 1 request per second (rate limit tracking)
- In-memory result caching to avoid redundant queries
- OpenStreetMap attribution ('Data © OpenStreetMap contributors, ODbL 1.0')
- Graceful offline and error handling without unhandled exceptions
"""
from __future__ import annotations

import logging
import re
import sqlite3
import time
from typing import Any, Dict, List, Optional, Tuple

import httpx

from src.schemas.emergency import GeocodePlaceResult, GeocodeSearchResponse

logger = logging.getLogger("yatra.emergency.geocoding")

OSM_ATTRIBUTION = "Data © OpenStreetMap contributors, ODbL 1.0"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
DEFAULT_USER_AGENT = "Yatra-Saathi-EmergencySOS/1.0 (https://github.com/sharathkudachi/Yatra-Saathi; sharathkudachi30@gmail.com)"

# In-memory query cache: query -> (timestamp, GeocodeSearchResponse)
_CACHE: Dict[str, Tuple[float, GeocodeSearchResponse]] = {}
CACHE_TTL_SECONDS = 3600.0  # 1 hour
MAX_CACHE_SIZE = 250

# Rate limiter state: tracks last external request timestamp
_LAST_REQUEST_TIMESTAMP: float = 0.0
MIN_REQUEST_INTERVAL_SECONDS = 1.05


def _normalize_query(query: str) -> str:
    return re.sub(r"\s+", " ", query.strip().lower())


class GeocodingService:
    def __init__(
        self,
        conn: Optional[sqlite3.Connection] = None,
        user_agent: str = DEFAULT_USER_AGENT,
        timeout_seconds: float = 4.0,
    ):
        self.conn = conn
        self.user_agent = user_agent
        self.timeout_seconds = timeout_seconds

    def search_places(self, query: str, limit: int = 5) -> GeocodeSearchResponse:
        """Search for locations matching query.

        Checks cache, respects rate limits, queries Nominatim, and falls back
        gracefully to local database or empty result on error.
        """
        clean_query = query.strip()
        if not clean_query or len(clean_query) < 2:
            return GeocodeSearchResponse(
                query=clean_query,
                results=[],
                attribution=OSM_ATTRIBUTION,
                provider="nominatim",
                rate_limited=False,
            )

        norm_q = _normalize_query(clean_query)
        now = time.time()

        # 1. Check in-memory cache
        if norm_q in _CACHE:
            cached_time, cached_resp = _CACHE[norm_q]
            if now - cached_time < CACHE_TTL_SECONDS:
                return cached_resp

        # 2. Query Nominatim with rate limiting
        global _LAST_REQUEST_TIMESTAMP
        time_since_last = now - _LAST_REQUEST_TIMESTAMP
        if time_since_last < MIN_REQUEST_INTERVAL_SECONDS:
            sleep_needed = MIN_REQUEST_INTERVAL_SECONDS - time_since_last
            if sleep_needed > 0:
                time.sleep(sleep_needed)

        results: List[GeocodePlaceResult] = []
        is_rate_limited = False
        provider_used = "nominatim"

        try:
            _LAST_REQUEST_TIMESTAMP = time.time()
            headers = {
                "User-Agent": self.user_agent,
                "Accept": "application/json",
            }
            params = {
                "q": clean_query,
                "format": "jsonv2",
                "addressdetails": "1",
                "limit": str(limit),
                "countrycodes": "in",
            }

            with httpx.Client(timeout=self.timeout_seconds) as client:
                resp = client.get(NOMINATIM_URL, params=params, headers=headers)

            if resp.status_code == 429:
                logger.warning("Nominatim rate limit encountered for query: %s", clean_query)
                is_rate_limited = True
                results = self._fallback_local_search(clean_query, limit)
                provider_used = "local_database_fallback"
            elif resp.status_code == 200:
                raw_data = resp.json()
                if isinstance(raw_data, list):
                    for item in raw_data:
                        parsed = self._parse_nominatim_item(item)
                        if parsed:
                            results.append(parsed)

                # If country-filtered search returned nothing, try without country filter
                if not results:
                    params_global = {
                        "q": clean_query,
                        "format": "jsonv2",
                        "addressdetails": "1",
                        "limit": str(limit),
                    }
                    time.sleep(MIN_REQUEST_INTERVAL_SECONDS)
                    _LAST_REQUEST_TIMESTAMP = time.time()
                    with httpx.Client(timeout=self.timeout_seconds) as client:
                        resp_global = client.get(NOMINATIM_URL, params=params_global, headers=headers)
                    if resp_global.status_code == 200:
                        raw_data_global = resp_global.json()
                        if isinstance(raw_data_global, list):
                            for item in raw_data_global:
                                parsed = self._parse_nominatim_item(item)
                                if parsed:
                                    results.append(parsed)

        except Exception as exc:
            logger.info("External geocoding failed (%s). Falling back to local database.", exc)
            results = self._fallback_local_search(clean_query, limit)
            provider_used = "local_database_fallback"

        # If still no results and we have a local connection, search local db
        if not results and self.conn:
            results = self._fallback_local_search(clean_query, limit)
            if results:
                provider_used = "local_database_fallback"

        response = GeocodeSearchResponse(
            query=clean_query,
            results=results,
            attribution=OSM_ATTRIBUTION,
            provider=provider_used,
            rate_limited=is_rate_limited,
        )

        # Store in cache
        if len(_CACHE) >= MAX_CACHE_SIZE:
            # Evict oldest entry
            oldest_key = min(_CACHE.keys(), key=lambda k: _CACHE[k][0])
            _CACHE.pop(oldest_key, None)
        _CACHE[norm_q] = (now, response)

        return response

    def _parse_nominatim_item(self, item: Dict[str, Any]) -> Optional[GeocodePlaceResult]:
        try:
            place_id = str(item.get("place_id") or item.get("osm_id") or "")
            lat = float(item["lat"])
            lon = float(item["lon"])
            display_name = str(item.get("display_name") or "")
            addr = item.get("address", {}) or {}

            # Determine primary name
            name = (
                item.get("name")
                or addr.get("city")
                or addr.get("town")
                or addr.get("suburb")
                or addr.get("village")
                or (display_name.split(",")[0] if display_name else "Unknown Location")
            )

            locality = (
                addr.get("suburb")
                or addr.get("neighbourhood")
                or addr.get("city_district")
                or addr.get("county")
                or addr.get("city")
                or addr.get("town")
            )
            state = addr.get("state")
            country = addr.get("country") or "India"

            bbox = None
            raw_bbox = item.get("boundingbox")
            if isinstance(raw_bbox, list) and len(raw_bbox) == 4:
                try:
                    bbox = [float(x) for x in raw_bbox]
                except (ValueError, TypeError):
                    bbox = None

            return GeocodePlaceResult(
                place_id=place_id,
                display_name=display_name,
                name=name,
                locality=locality,
                state=state,
                country=country,
                latitude=round(lat, 6),
                longitude=round(lon, 6),
                bounding_box=bbox,
            )
        except Exception as err:
            logger.debug("Failed to parse Nominatim item: %s", err)
            return None

    def _fallback_local_search(self, query: str, limit: int = 5) -> List[GeocodePlaceResult]:
        """Local database fallback using active cities when external service is offline or rate limited."""
        if not self.conn:
            return []

        results: List[GeocodePlaceResult] = []
        try:
            wildcard = f"%{query.strip()}%"
            cursor = self.conn.execute(
                """SELECT city_id, name, state, country_code, lat, lng
                   FROM cities
                   WHERE status = 'active' AND (name LIKE ? OR state LIKE ?)
                   ORDER BY name ASC
                   LIMIT ?""",
                (wildcard, wildcard, limit),
            )
            rows = cursor.fetchall()
            for r in rows:
                if isinstance(r, sqlite3.Row) or isinstance(r, dict):
                    lat = r["lat"]
                    lng = r["lng"]
                    c_name = r["name"]
                    c_state = r["state"]
                    c_id = r["city_id"]
                else:
                    c_id, c_name, c_state, _, lat, lng = r[0], r[1], r[2], r[3], r[4], r[5]

                if lat is not None and lng is not None:
                    display = f"{c_name}, {c_state}, India"
                    results.append(
                        GeocodePlaceResult(
                            place_id=f"local_city_{c_id}",
                            display_name=display,
                            name=c_name,
                            locality=c_name,
                            state=c_state,
                            country="India",
                            latitude=float(lat),
                            longitude=float(lng),
                        )
                    )
        except Exception as exc:
            logger.debug("Local fallback city search failed: %s", exc)

        return results
