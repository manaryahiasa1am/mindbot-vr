from __future__ import annotations

import math
from typing import Any

from .hospitals import HOSPITALS_BENI_SUEF


BENI_SUEF_CENTER = {"lat": 29.0661, "lng": 31.0994}


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)

    a = (math.sin(dphi / 2) ** 2) + math.cos(phi1) * math.cos(phi2) * (math.sin(dlambda / 2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return r * c


def estimate_travel_minutes(distance_km: float, avg_kmh: float = 40.0) -> int:
    if avg_kmh <= 0:
        avg_kmh = 40.0
    minutes = (distance_km / avg_kmh) * 60.0
    return int(max(1, round(minutes)))


def nearest_hospital(lat: float, lng: float) -> dict[str, Any]:
    best: dict[str, Any] | None = None
    best_dist = 10**9
    for h in HOSPITALS_BENI_SUEF:
        d = haversine_km(lat, lng, float(h["lat"]), float(h["lng"]))
        if d < best_dist:
            best_dist = d
            best = dict(h)
            best["distance_km"] = round(d, 2)
            best["eta_minutes"] = estimate_travel_minutes(float(best["distance_km"]))
    return best or dict(HOSPITALS_BENI_SUEF[0])

