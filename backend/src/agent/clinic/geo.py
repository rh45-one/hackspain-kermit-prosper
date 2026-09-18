"""Straight-line distance helpers for the nearest-site problem."""
from __future__ import annotations

import math
from typing import Any

EARTH_RADIUS_KM = 6371.0088


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def nearest_locations(lat: float, lng: float, locations: list[dict[str, Any]]) -> list[tuple[dict[str, Any], float]]:
    """Return (location, distance_km) sorted by straight-line distance."""
    scored = [
        (loc, haversine_km(lat, lng, float(loc["latitude"]), float(loc["longitude"])))
        for loc in locations
    ]
    scored.sort(key=lambda pair: pair[1])
    return scored
