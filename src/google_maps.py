"""Google Maps helpers for the bus pickup finder.

The app can run without a Google Maps Platform key, but these helpers unlock:
- Google driving distance ranking with Routes API Compute Route Matrix
- Google Maps Embed API directions maps
- Google Maps URLs that use place IDs when available
"""

from __future__ import annotations

import html
import json
from dataclasses import dataclass
from typing import Any, Iterable
from urllib.parse import quote_plus, urlencode

import pandas as pd
import requests

ROUTES_MATRIX_ENDPOINT = "https://routes.googleapis.com/distanceMatrix/v2:computeRouteMatrix"
MAPS_SEARCH_BASE = "https://www.google.com/maps/search/?api=1"
MAPS_DIRECTIONS_BASE = "https://www.google.com/maps/dir/?api=1"
MAPS_EMBED_DIRECTIONS_BASE = "https://www.google.com/maps/embed/v1/directions"


@dataclass(frozen=True)
class RouteResult:
    """One origin-to-pickup route result from Google Routes API."""

    pickup_id: str
    distance_meters: int | None
    duration_seconds: int | None
    condition: str
    error: str = ""

    @property
    def distance_miles(self) -> float | None:
        if self.distance_meters is None:
            return None
        return self.distance_meters / 1609.344

    @property
    def duration_minutes(self) -> float | None:
        if self.duration_seconds is None:
            return None
        return self.duration_seconds / 60


def clean_text(value: Any) -> str:
    """Return a trimmed text value, treating NaN/None as blank."""
    if value is None:
        return ""
    text = str(value).strip()
    if text.lower() in {"nan", "none", "null"}:
        return ""
    return text


def row_location_query(row: pd.Series) -> str:
    """Return the preferred Google Maps text query for a row."""
    query = clean_text(row.get("google_maps_query"))
    if query:
        return query
    full_address = clean_text(row.get("full_address"))
    if full_address:
        return full_address
    parts = [row.get("name"), row.get("address"), row.get("city"), row.get("state"), row.get("zip")]
    return " ".join(clean_text(part) for part in parts if clean_text(part))


def row_place_id(row: pd.Series) -> str:
    """Return a Google place ID if one is stored for this row."""
    return clean_text(row.get("google_place_id"))


def routes_waypoint(query: str = "", place_id: str = "") -> dict[str, str]:
    """Build a Routes API waypoint using a place ID when available, otherwise address text."""
    place_id = clean_text(place_id)
    query = clean_text(query)
    if place_id:
        return {"placeId": place_id}
    if not query:
        raise ValueError("A waypoint needs either a Google place ID or a query/address.")
    return {"address": query}


def parse_google_duration(value: Any) -> int | None:
    """Parse Google duration strings such as '160s' to seconds."""
    text = clean_text(value)
    if not text:
        return None
    if text.endswith("s"):
        text = text[:-1]
    try:
        return int(float(text))
    except ValueError:
        return None


def compute_driving_matrix(
    *,
    api_key: str,
    origin_query: str,
    destinations: Iterable[dict[str, str]],
    traffic_aware: bool = False,
) -> list[RouteResult]:
    """Rank one origin against many pickup destinations by Google driving distance.

    destinations must contain dictionaries with these keys:
        id, query, place_id
    """
    api_key = clean_text(api_key)
    if not api_key:
        raise ValueError("Missing GOOGLE_MAPS_API_KEY.")

    dest_list = list(destinations)
    if not dest_list:
        return []

    body = {
        "origins": [{"waypoint": routes_waypoint(origin_query)}],
        "destinations": [
            {"waypoint": routes_waypoint(dest.get("query", ""), dest.get("place_id", ""))}
            for dest in dest_list
        ],
        "travelMode": "DRIVE",
        "routingPreference": "TRAFFIC_AWARE" if traffic_aware else "TRAFFIC_UNAWARE",
        "languageCode": "en-US",
        "units": "IMPERIAL",
    }
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": "originIndex,destinationIndex,duration,distanceMeters,status,condition",
    }

    response = requests.post(ROUTES_MATRIX_ENDPOINT, headers=headers, json=body, timeout=20)
    response.raise_for_status()
    payload = response.json()
    if isinstance(payload, dict) and "error" in payload:
        message = payload.get("error", {}).get("message", "Google Routes API returned an error.")
        raise RuntimeError(message)
    if not isinstance(payload, list):
        raise RuntimeError("Unexpected Google Routes API response format.")

    by_index: dict[int, RouteResult] = {}
    for item in payload:
        dest_idx = int(item.get("destinationIndex", -1))
        if dest_idx < 0 or dest_idx >= len(dest_list):
            continue
        status = item.get("status") or {}
        status_message = clean_text(status.get("message")) if isinstance(status, dict) else clean_text(status)
        by_index[dest_idx] = RouteResult(
            pickup_id=dest_list[dest_idx]["id"],
            distance_meters=item.get("distanceMeters"),
            duration_seconds=parse_google_duration(item.get("duration")),
            condition=clean_text(item.get("condition")) or "UNKNOWN",
            error=status_message,
        )

    results: list[RouteResult] = []
    for idx, dest in enumerate(dest_list):
        results.append(
            by_index.get(
                idx,
                RouteResult(
                    pickup_id=dest["id"],
                    distance_meters=None,
                    duration_seconds=None,
                    condition="NO_RESULT",
                    error="No route result returned for this pickup.",
                ),
            )
        )
    return results


def google_maps_search_url(query: str, place_id: str = "") -> str:
    """Create a Google Maps search URL, using a place ID when available."""
    query = clean_text(query)
    place_id = clean_text(place_id)
    params = {"api": "1", "query": query}
    if place_id:
        params["query_place_id"] = place_id
    return "https://www.google.com/maps/search/?" + urlencode(params)


def google_maps_directions_url(
    *,
    origin_query: str,
    destination_query: str,
    destination_place_id: str = "",
    travelmode: str = "driving",
) -> str:
    """Create a Google Maps directions URL for the browser/app."""
    params = {
        "api": "1",
        "origin": clean_text(origin_query),
        "destination": clean_text(destination_query),
        "travelmode": travelmode,
    }
    destination_place_id = clean_text(destination_place_id)
    if destination_place_id:
        params["destination_place_id"] = destination_place_id
    return "https://www.google.com/maps/dir/?" + urlencode(params)


def google_embed_directions_url(
    *,
    api_key: str,
    origin_query: str,
    destination_query: str,
    destination_place_id: str = "",
    mode: str = "driving",
) -> str:
    """Create a Google Maps Embed API directions URL."""
    destination_place_id = clean_text(destination_place_id)
    destination = f"place_id:{destination_place_id}" if destination_place_id else clean_text(destination_query)
    params = {
        "key": clean_text(api_key),
        "origin": clean_text(origin_query),
        "destination": destination,
        "mode": mode,
    }
    return MAPS_EMBED_DIRECTIONS_BASE + "?" + urlencode(params)


def _marker_payload(df: pd.DataFrame, *, kind: str) -> list[dict[str, str]]:
    """Create JSON-safe marker payload for the client-side Google map."""
    payload: list[dict[str, str]] = []
    for _, row in df.iterrows():
        payload.append(
            {
                "id": clean_text(row.get("id")),
                "name": clean_text(row.get("name")),
                "query": row_location_query(row),
                "place_id": row_place_id(row),
                "address": clean_text(row.get("full_address")),
                "note": clean_text(row.get("best_for")) or clean_text(row.get("area")),
                "kind": kind,
            }
        )
    return payload


def google_overview_map_html(
    *,
    api_key: str,
    pickups: pd.DataFrame,
    hotels: pd.DataFrame | None = None,
    show_hotels: bool = False,
    selected_pickup_id: str = "",
    height: int = 520,
) -> str:
    """Return HTML for a Google map that geocodes/display pickup and optional hotel markers.

    This uses Google Maps JavaScript API in the browser and geocodes each row's
    `google_place_id` or `google_maps_query`, so the visible marker positions come
    from Google rather than the CSV latitude/longitude columns.
    """
    marker_data = _marker_payload(pickups, kind="pickup")
    if show_hotels and hotels is not None:
        marker_data.extend(_marker_payload(hotels, kind="hotel"))

    marker_json = json.dumps(marker_data, ensure_ascii=False)
    selected_pickup_id = html.escape(clean_text(selected_pickup_id), quote=True)
    api_key_escaped = quote_plus(clean_text(api_key))

    return f"""
<div id="google-map" style="height:{height}px;width:100%;border-radius:14px;border:1px solid #ddd;"></div>
<div id="map-status" style="font: 13px Arial, sans-serif; color:#555; margin-top:6px;"></div>
<script>
const markerData = {marker_json};
const selectedPickupId = "{selected_pickup_id}";
function initBusFinderMap() {{
  const duluth = {{ lat: 46.7867, lng: -92.1005 }};
  const map = new google.maps.Map(document.getElementById("google-map"), {{
    zoom: 10,
    center: duluth,
    mapTypeControl: false,
    streetViewControl: false,
    fullscreenControl: true,
  }});
  const geocoder = new google.maps.Geocoder();
  const bounds = new google.maps.LatLngBounds();
  const infoWindow = new google.maps.InfoWindow();
  let added = 0;
  let failed = 0;

  function pinIcon(kind, selected) {{
    const color = selected ? "DA291C" : (kind === "pickup" ? "C62828" : "1565C0");
    return {{
      url: "https://chart.googleapis.com/chart?chst=d_map_pin_letter&chld=" + (kind === "pickup" ? "B" : "H") + "|" + color + "|FFFFFF",
      scaledSize: new google.maps.Size(30, 48),
    }};
  }}

  function addMarker(item) {{
    const request = item.place_id ? {{ placeId: item.place_id }} : {{ address: item.query }};
    geocoder.geocode(request, (results, status) => {{
      if (status === "OK" && results && results[0]) {{
        const position = results[0].geometry.location;
        const isSelected = item.id === selectedPickupId;
        const marker = new google.maps.Marker({{
          map: map,
          position: position,
          title: item.name,
          icon: pinIcon(item.kind, isSelected),
          zIndex: isSelected ? 1000 : (item.kind === "pickup" ? 500 : 100),
        }});
        const mapsUrl = "https://www.google.com/maps/search/?api=1&query=" + encodeURIComponent(item.query) + (item.place_id ? "&query_place_id=" + encodeURIComponent(item.place_id) : "");
        const kindLabel = item.kind === "pickup" ? "Bus pickup" : "Hotel";
        const content = `<div style="font-family:Arial,sans-serif;max-width:280px;line-height:1.35;">
          <strong>${{item.name}}</strong><br>
          <span>${{kindLabel}}</span><br>
          <span>${{item.address || item.query}}</span><br>
          ${{item.note ? `<span>${{item.note}}</span><br>` : ""}}
          <a target="_blank" rel="noopener" href="${{mapsUrl}}">Open in Google Maps</a>
        </div>`;
        marker.addListener("click", () => {{
          infoWindow.setContent(content);
          infoWindow.open(map, marker);
        }});
        bounds.extend(position);
        added += 1;
        if (added === 1) {{ map.setCenter(position); }}
        if (added > 1) {{ map.fitBounds(bounds); }}
      }} else {{
        failed += 1;
        console.warn("Geocode failed", item.name, status);
      }}
      document.getElementById("map-status").innerText = `${{added}} markers placed from Google; ${{failed}} not found.`;
    }});
  }}
  markerData.forEach(addMarker);
}}
</script>
<script async defer src="https://maps.googleapis.com/maps/api/js?key={api_key_escaped}&callback=initBusFinderMap"></script>
"""
