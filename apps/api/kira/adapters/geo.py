"""Great-circle distance, shared by every adapter and service that needs it."""

from __future__ import annotations

import math


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Return great-circle distance for coordinates, where floats are appropriate."""
    radius = 6371.0
    rad = math.pi / 180
    d_lat = (lat2 - lat1) * rad
    d_lng = (lng2 - lng1) * rad
    h = (
        math.sin(d_lat / 2) ** 2
        + math.cos(lat1 * rad) * math.cos(lat2 * rad) * math.sin(d_lng / 2) ** 2
    )
    return 2 * radius * math.asin(math.sqrt(h))
