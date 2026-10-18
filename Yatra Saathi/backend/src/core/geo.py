"""Geographic validation utilities shared across search, map, and itineraries."""
from __future__ import annotations

import math
from typing import Optional


def is_valid_coord(lat: Optional[float], lng: Optional[float]) -> bool:
    """Validate latitude (-90 to +90) and longitude (-180 to +180).
    Rejects None, booleans, non-numbers, NaN, Infinity, and out-of-range coordinates.
    """
    if lat is None or lng is None:
        return False
    if isinstance(lat, bool) or isinstance(lng, bool):
        return False
    if not isinstance(lat, (int, float)) or not isinstance(lng, (int, float)):
        return False
    if math.isnan(lat) or math.isnan(lng) or math.isinf(lat) or math.isinf(lng):
        return False
    return -90.0 <= lat <= 90.0 and -180.0 <= lng <= 180.0
