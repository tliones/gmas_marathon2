"""Geography helpers for the bus pickup finder app."""

from __future__ import annotations

import math
import os
from typing import Optional, Tuple
from urllib.parse import quote_plus


EARTH_RADIUS_MILES = 3958.7613


def haversine_miles(
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float,
) -> float:
    """Return straight-line distance in miles between two latitude/longitude points."""
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)

    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return EARTH_RADIUS_MILES * c


def address_from_parts(
    address: str,
    city: str,
    state: str,
    postal_code: str | int | None = None,
) -> str:
    """Build a single-line address from address parts."""
    postal = "" if postal_code is None else str(postal_code).strip()
    return ", ".join(part for part in [address, city, state, postal] if str(part).strip())


def google_maps_directions_url(
    origin: str,
    destination: str,
    travelmode: str = "driving",
) -> str:
    """Create a Google Maps directions URL.

    travelmode can be driving, walking, bicycling, or transit.
    """
    return (
        "https://www.google.com/maps/dir/?api=1"
        f"&origin={quote_plus(origin)}"
        f"&destination={quote_plus(destination)}"
        f"&travelmode={quote_plus(travelmode)}"
    )


def google_maps_place_url(destination: str) -> str:
    """Create a Google Maps search/place URL."""
    return f"https://www.google.com/maps/search/?api=1&query={quote_plus(destination)}"


def geocode_address(address: str) -> Optional[Tuple[float, float]]:
    """Geocode an address with OpenStreetMap Nominatim through geopy.

    This is intentionally simple for a starter app. For a high-traffic public app,
    replace this with a paid geocoding provider such as Google, Mapbox, or HERE and
    store the key in Streamlit secrets.
    """
    cleaned = address.strip()
    if not cleaned:
        return None

    try:
        from geopy.exc import GeocoderServiceError, GeocoderTimedOut
        from geopy.geocoders import Nominatim
    except ImportError as exc:  # pragma: no cover - UI displays this to the user
        raise RuntimeError(
            "geopy is not installed. Add geopy to requirements.txt or use manual coordinates."
        ) from exc

    user_agent = os.getenv("GEOCODER_USER_AGENT", "grandmas-bus-finder-streamlit")
    geolocator = Nominatim(user_agent=user_agent, timeout=10)

    try:
        location = geolocator.geocode(cleaned, country_codes="us", exactly_one=True)
    except (GeocoderTimedOut, GeocoderServiceError):
        return None

    if location is None:
        return None

    return float(location.latitude), float(location.longitude)
