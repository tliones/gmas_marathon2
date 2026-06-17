"""Google Maps helpers for the Duluth race shuttle finder.

The app can run without a Google Maps Platform key, but these helpers unlock:
- Traffic-aware Google driving-distance ranking with Routes API Compute Route Matrix
- Google Maps JavaScript maps with Google-resolved marker positions
- Routes API selected-route polylines drawn on the main Google map
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
ROUTES_COMPUTE_ENDPOINT = "https://routes.googleapis.com/directions/v2:computeRoutes"


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


@dataclass(frozen=True)
class RoutePolyline:
    """A selected route line that can be drawn on the Google overview map."""

    encoded_polyline: str
    distance_meters: int | None = None
    duration_seconds: int | None = None
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


def optional_float(value: Any) -> float | None:
    """Return a float, or None for blank/invalid values."""
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    text = clean_text(value)
    if not text:
        return None
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def row_location_query(row: pd.Series) -> str:
    """Return the preferred Google Maps display/search query for a row."""
    query = clean_text(row.get("google_maps_query"))
    if query:
        return query
    full_address = clean_text(row.get("full_address"))
    if full_address:
        return full_address
    parts = [row.get("name"), row.get("address"), row.get("city"), row.get("state"), row.get("zip")]
    return " ".join(clean_text(part) for part in parts if clean_text(part))


def row_routing_query(row: pd.Series) -> str:
    """Return the preferred Google routing query for ranking and route links.

    Large sites can use a precise display/search query for map markers and a more
    stable official address for routing. If latitude/longitude are available, the
    route ranking code uses those coordinates first; this query remains useful for
    Google Maps URLs.
    """
    query = clean_text(row.get("routing_query"))
    if query:
        return query
    return row_location_query(row)


def row_visual_route_query(row: pd.Series) -> str:
    """Return the address/query used for the selected route polyline.

    This is intentionally separate from marker placement and distance ranking.
    The DECC is a broad venue, so the visual route should target the simple
    Harbor Drive address rather than a venue centroid or a north-gate loading
    description.
    """
    query = clean_text(row.get("visual_route_query"))
    if query:
        return query
    return row_routing_query(row)


def row_place_id(row: pd.Series) -> str:
    """Return a Google place ID if one is stored for this row."""
    return clean_text(row.get("google_place_id"))


def row_lat_lng(row: pd.Series) -> tuple[float | None, float | None]:
    """Return route coordinates, preferring explicit routing columns when present."""
    lat = optional_float(row.get("routing_latitude"))
    lng = optional_float(row.get("routing_longitude"))
    if lat is None or lng is None:
        lat = optional_float(row.get("latitude"))
        lng = optional_float(row.get("longitude"))
    return lat, lng


def routes_waypoint(
    query: str = "",
    place_id: str = "",
    latitude: Any = None,
    longitude: Any = None,
) -> dict[str, Any]:
    """Build a Routes API Waypoint.

    The Routes API Waypoint accepts exactly one location type: geographic location,
    place ID, address, or navigation point token. For route ranking, coordinates
    are preferred when they are present because they avoid address/name ambiguity.
    """
    lat = optional_float(latitude)
    lng = optional_float(longitude)
    if lat is not None and lng is not None:
        return {"location": {"latLng": {"latitude": lat, "longitude": lng}}}

    place_id = clean_text(place_id)
    query = clean_text(query)
    if place_id:
        return {"placeId": place_id}
    if query:
        return {"address": query}
    raise ValueError("A waypoint needs coordinates, a Google place ID, or a query/address.")


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


def google_error_message(response: requests.Response) -> str:
    """Extract the useful Google API error message from a non-2xx response."""
    try:
        payload = response.json()
    except Exception:
        payload = None

    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            parts = [clean_text(error.get("status")), clean_text(error.get("message"))]
            detail_bits: list[str] = []
            for detail in error.get("details", []) or []:
                if isinstance(detail, dict):
                    reason = clean_text(detail.get("reason"))
                    field_violations = detail.get("fieldViolations")
                    if reason:
                        detail_bits.append(reason)
                    if isinstance(field_violations, list):
                        for violation in field_violations:
                            if isinstance(violation, dict):
                                field = clean_text(violation.get("field"))
                                description = clean_text(violation.get("description"))
                                if field or description:
                                    detail_bits.append(f"{field}: {description}".strip(": "))
            message = " — ".join(part for part in parts if part)
            if detail_bits:
                message = f"{message} ({'; '.join(detail_bits)})" if message else "; ".join(detail_bits)
            if message:
                return message
    return f"HTTP {response.status_code}: {clean_text(response.text)[:500]}"


def raise_for_google_response(response: requests.Response) -> None:
    """Raise a RuntimeError with Google's JSON error body instead of a generic HTTPError."""
    if response.ok:
        return
    raise RuntimeError(google_error_message(response))


def compute_driving_matrix(
    *,
    api_key: str,
    origin_query: str,
    destinations: Iterable[dict[str, Any]],
    origin_place_id: str = "",
    origin_latitude: Any = None,
    origin_longitude: Any = None,
    traffic_aware: bool = True,
) -> list[RouteResult]:
    """Rank one origin against many pickup destinations by Google driving distance.

    When traffic_aware is true, the app uses TRAFFIC_AWARE_OPTIMAL. That is slower
    than the basic mode, but with one origin and a small number of pickup spots it
    gives routes that more closely match Google Maps.

    destinations must contain dictionaries with these keys:
        id, query, place_id, latitude, longitude
    """
    api_key = clean_text(api_key)
    if not api_key:
        raise ValueError("Missing GOOGLE_MAPS_API_KEY.")

    dest_list = list(destinations)
    if not dest_list:
        return []

    body = {
        "origins": [
            {
                "waypoint": routes_waypoint(
                    origin_query,
                    origin_place_id,
                    origin_latitude,
                    origin_longitude,
                )
            }
        ],
        "destinations": [
            {
                "waypoint": routes_waypoint(
                    dest.get("query", ""),
                    dest.get("place_id", ""),
                    dest.get("latitude"),
                    dest.get("longitude"),
                )
            }
            for dest in dest_list
        ],
        "travelMode": "DRIVE",
        "routingPreference": "TRAFFIC_AWARE_OPTIMAL" if traffic_aware else "TRAFFIC_UNAWARE",
        "languageCode": "en-US",
        "units": "IMPERIAL",
    }
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": "originIndex,destinationIndex,duration,distanceMeters,status,condition",
    }

    response = requests.post(ROUTES_MATRIX_ENDPOINT, headers=headers, json=body, timeout=20)
    raise_for_google_response(response)
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


def compute_route_polyline(
    *,
    api_key: str,
    origin_query: str,
    destination_query: str,
    origin_place_id: str = "",
    destination_place_id: str = "",
    origin_latitude: Any = None,
    origin_longitude: Any = None,
    destination_latitude: Any = None,
    destination_longitude: Any = None,
    traffic_aware: bool = True,
) -> RoutePolyline:
    """Compute a selected driving route polyline with Google Routes API.

    When traffic_aware is true, the selected route uses TRAFFIC_AWARE_OPTIMAL so
    the drawn route better matches the route a visitor sees in Google Maps.

    The main app uses this to get the selected route geometry. ComputeRoutes
    expects origin and destination as Waypoint objects directly, not nested
    inside `waypoint` like Compute Route Matrix.
    """
    api_key = clean_text(api_key)
    if not api_key:
        raise ValueError("Missing GOOGLE_MAPS_API_KEY.")

    body = {
        "origin": routes_waypoint(origin_query, origin_place_id, origin_latitude, origin_longitude),
        "destination": routes_waypoint(
            destination_query,
            destination_place_id,
            destination_latitude,
            destination_longitude,
        ),
        "travelMode": "DRIVE",
        "routingPreference": "TRAFFIC_AWARE_OPTIMAL" if traffic_aware else "TRAFFIC_UNAWARE",
        "languageCode": "en-US",
        "units": "IMPERIAL",
        "polylineQuality": "OVERVIEW",
        "polylineEncoding": "ENCODED_POLYLINE",
    }
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": "routes.duration,routes.distanceMeters,routes.polyline.encodedPolyline",
    }

    response = requests.post(ROUTES_COMPUTE_ENDPOINT, headers=headers, json=body, timeout=20)
    raise_for_google_response(response)
    payload = response.json()
    if isinstance(payload, dict) and "error" in payload:
        message = payload.get("error", {}).get("message", "Google Routes API returned an error.")
        raise RuntimeError(message)

    routes = payload.get("routes", []) if isinstance(payload, dict) else []
    if not routes:
        return RoutePolyline(encoded_polyline="", error="No route returned for the selected pickup.")

    route = routes[0]
    polyline = route.get("polyline", {}) if isinstance(route, dict) else {}
    encoded = clean_text(polyline.get("encodedPolyline")) if isinstance(polyline, dict) else ""
    if not encoded:
        return RoutePolyline(encoded_polyline="", error="Google returned a route but no encoded polyline.")

    return RoutePolyline(
        encoded_polyline=encoded,
        distance_meters=route.get("distanceMeters"),
        duration_seconds=parse_google_duration(route.get("duration")),
    )


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


def _marker_payload(df: pd.DataFrame, *, kind: str) -> list[dict[str, str]]:
    """Create JSON-safe marker payload for the client-side Google map."""
    payload: list[dict[str, str]] = []
    for _, row in df.iterrows():
        note = clean_text(row.get("best_for")) if kind == "pickup" else clean_text(row.get("area"))
        if kind == "hotel" and clean_text(row.get("return_shuttle_group")):
            note = (
                f"{note} · Return shuttle: {clean_text(row.get('return_shuttle_group'))}"
                if note
                else f"Return shuttle: {clean_text(row.get('return_shuttle_group'))}"
            )
        lat, lng = row_lat_lng(row)
        payload.append(
            {
                "id": clean_text(row.get("id")),
                "name": clean_text(row.get("name")),
                "query": row_location_query(row),
                "routing_query": row_routing_query(row),
                "place_id": row_place_id(row),
                "address": clean_text(row.get("full_address")),
                "note": note,
                "kind": kind,
                "lat": "" if lat is None else str(lat),
                "lng": "" if lng is None else str(lng),
            }
        )
    return payload


def google_overview_map_html(
    *,
    api_key: str,
    pickups: pd.DataFrame,
    hotels: pd.DataFrame | None = None,
    show_hotels: bool = True,
    selected_pickup_id: str = "",
    selected_origin_id: str = "",
    origin_query: str = "",
    origin_label: str = "",
    origin_latitude: Any = None,
    origin_longitude: Any = None,
    route_origin_query: str = "",
    route_origin_place_id: str = "",
    route_origin_latitude: Any = None,
    route_origin_longitude: Any = None,
    route_destination_query: str = "",
    route_destination_place_id: str = "",
    route_destination_latitude: Any = None,
    route_destination_longitude: Any = None,
    route_waypoints: list[dict[str, Any]] | None = None,
    route_polyline: str = "",
    height: int = 620,
) -> str:
    """Return HTML for a Google map with pickup/hotel markers and an optional route.

    Marker positions are resolved in the browser with Google Maps JavaScript:
    - `google_place_id` when present
    - Places text search from `google_maps_query` when possible
    - Geocoder fallback from `google_maps_query`
    - CSV coordinates as a final fallback

    The selected route is drawn from a server-side Routes API encoded polyline.
    This avoids client-side DirectionsRenderer quirks around broad venues such as
    the DECC while keeping all hotel and pickup markers on the same map.
    """
    marker_data = _marker_payload(pickups, kind="pickup")
    if show_hotels and hotels is not None:
        marker_data.extend(_marker_payload(hotels, kind="hotel"))

    selected_origin_id = clean_text(selected_origin_id)
    origin_query = clean_text(origin_query)
    origin_label = clean_text(origin_label) or "Starting location"
    existing_marker_ids = {item["id"] for item in marker_data}
    if origin_query and (not selected_origin_id or selected_origin_id not in existing_marker_ids):
        selected_origin_id = selected_origin_id or "__custom_origin__"
        marker_data.append(
            {
                "id": selected_origin_id,
                "name": origin_label,
                "query": origin_query,
                "routing_query": origin_query,
                "place_id": "",
                "address": origin_query,
                "note": "Selected starting location",
                "kind": "origin",
                "lat": "" if optional_float(origin_latitude) is None else str(optional_float(origin_latitude)),
                "lng": "" if optional_float(origin_longitude) is None else str(optional_float(origin_longitude)),
            }
        )

    sanitized_waypoints: list[dict[str, Any]] = []
    for waypoint in route_waypoints or []:
        lat = optional_float(waypoint.get("lat") or waypoint.get("latitude"))
        lng = optional_float(waypoint.get("lng") or waypoint.get("longitude"))
        sanitized_waypoints.append(
            {
                "query": clean_text(waypoint.get("query")),
                "place_id": clean_text(waypoint.get("place_id")),
                "lat": "" if lat is None else str(lat),
                "lng": "" if lng is None else str(lng),
                "stopover": bool(waypoint.get("stopover", False)),
            }
        )

    replacements = {
        "__HEIGHT__": html.escape(str(int(height)), quote=True),
        "__MARKER_JSON__": json.dumps(marker_data, ensure_ascii=False),
        "__SELECTED_PICKUP_ID__": json.dumps(clean_text(selected_pickup_id), ensure_ascii=False),
        "__SELECTED_ORIGIN_ID__": json.dumps(selected_origin_id, ensure_ascii=False),
        "__ROUTE_POLYLINE__": json.dumps(clean_text(route_polyline), ensure_ascii=False),
        "__ROUTE_ORIGIN_QUERY__": json.dumps(clean_text(route_origin_query), ensure_ascii=False),
        "__ROUTE_ORIGIN_PLACE_ID__": json.dumps(clean_text(route_origin_place_id), ensure_ascii=False),
        "__ROUTE_ORIGIN_LAT__": json.dumps("" if optional_float(route_origin_latitude) is None else str(optional_float(route_origin_latitude))),
        "__ROUTE_ORIGIN_LNG__": json.dumps("" if optional_float(route_origin_longitude) is None else str(optional_float(route_origin_longitude))),
        "__ROUTE_DESTINATION_QUERY__": json.dumps(clean_text(route_destination_query), ensure_ascii=False),
        "__ROUTE_DESTINATION_PLACE_ID__": json.dumps(clean_text(route_destination_place_id), ensure_ascii=False),
        "__ROUTE_DESTINATION_LAT__": json.dumps("" if optional_float(route_destination_latitude) is None else str(optional_float(route_destination_latitude))),
        "__ROUTE_DESTINATION_LNG__": json.dumps("" if optional_float(route_destination_longitude) is None else str(optional_float(route_destination_longitude))),
        "__ROUTE_WAYPOINTS__": json.dumps(sanitized_waypoints, ensure_ascii=False),
        "__API_KEY__": quote_plus(clean_text(api_key)),
    }

    template = r"""
<div id="bus-finder-map-wrap" style="width:100%;">
  <div id="google-map" style="height:__HEIGHT__px;width:100%;border-radius:16px;border:1px solid #d7d7d7;"></div>
  <div id="map-status" style="font:13px Arial,sans-serif;color:#555;margin-top:7px;">Loading Google map markers…</div>
</div>
<script>
const markerData = __MARKER_JSON__;
const selectedPickupId = __SELECTED_PICKUP_ID__;
const selectedOriginId = __SELECTED_ORIGIN_ID__;
const routePolyline = __ROUTE_POLYLINE__;
const routeOriginQuery = __ROUTE_ORIGIN_QUERY__;
const routeOriginPlaceId = __ROUTE_ORIGIN_PLACE_ID__;
const routeOriginLat = __ROUTE_ORIGIN_LAT__;
const routeOriginLng = __ROUTE_ORIGIN_LNG__;
const routeDestinationQuery = __ROUTE_DESTINATION_QUERY__;
const routeDestinationPlaceId = __ROUTE_DESTINATION_PLACE_ID__;
const routeDestinationLat = __ROUTE_DESTINATION_LAT__;
const routeDestinationLng = __ROUTE_DESTINATION_LNG__;
const routeWaypoints = __ROUTE_WAYPOINTS__;

function escapeHtml(value) {
  return String(value || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function parseCoordinate(value) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function latLngFromPair(latValue, lngValue) {
  const lat = parseCoordinate(latValue);
  const lng = parseCoordinate(lngValue);
  if (lat === null || lng === null) {
    return null;
  }
  return new google.maps.LatLng(lat, lng);
}

function waypointForDirections(query, placeId, latValue, lngValue) {
  // Prefer the same place/address text a user would type into Google Maps.
  // Raw coordinates are only a fallback; for large venues, coordinates can snap
  // to an odd nearby road segment and produce a strange visual route.
  if (placeId) {
    return { placeId: placeId };
  }
  if (query) {
    return query;
  }
  return latLngFromPair(latValue, lngValue);
}

function directionsWaypointFromPayload(item) {
  const location = waypointForDirections(item.query || "", item.place_id || "", item.lat || "", item.lng || "");
  if (!location) {
    return null;
  }
  return { location: location, stopover: Boolean(item.stopover) };
}

function initBusFinderMap() {
  const duluth = { lat: 46.7867, lng: -92.1005 };
  const map = new google.maps.Map(document.getElementById("google-map"), {
    zoom: 10,
    center: duluth,
    mapTypeControl: false,
    streetViewControl: false,
    fullscreenControl: true,
  });
  const geocoder = new google.maps.Geocoder();
  const placesService = google.maps.places ? new google.maps.places.PlacesService(map) : null;
  const bounds = new google.maps.LatLngBounds();
  const infoWindow = new google.maps.InfoWindow();
  let added = 0;
  let failed = 0;
  let processed = 0;
  let routeDrawn = false;
  let routeFailed = false;

  function markerVisual(item, isSelectedPickup, isSelectedOrigin) {
    let color = "#1565C0";
    let label = "H";
    let scale = 9;
    if (item.kind === "pickup") {
      color = "#C62828";
      label = "P";
    }
    if (item.kind === "origin" || isSelectedOrigin) {
      color = "#2E7D32";
      label = "S";
      scale = 12;
    }
    if (isSelectedPickup) {
      color = "#6A1B9A";
      label = "P";
      scale = 12;
    }
    return {
      icon: {
        path: google.maps.SymbolPath.CIRCLE,
        fillColor: color,
        fillOpacity: 0.95,
        strokeColor: "#FFFFFF",
        strokeWeight: 2,
        scale: scale,
      },
      label: {
        text: label,
        color: "#FFFFFF",
        fontSize: isSelectedPickup || isSelectedOrigin ? "13px" : "11px",
        fontWeight: "700",
      },
    };
  }

  function statusText() {
    const legend = "P = pickup · H = hotel/lodging · S = selected start";
    const route = routeDrawn ? " Selected driving route is shown in purple." : (routeFailed ? " Selected route could not be drawn; use the Directions button." : "");
    return `${added} markers placed from Google locations; ${failed} not found. ${legend}.${route}`;
  }

  function fitMarkerBoundsIfNeeded() {
    if (routeDrawn) {
      return;
    }
    if (added === 1) {
      map.setCenter(bounds.getCenter());
      map.setZoom(13);
    } else if (added > 1) {
      map.fitBounds(bounds, 54);
    }
  }

  function drawEncodedRoutePolyline() {
    if (!routePolyline || !google.maps.geometry || !google.maps.geometry.encoding) {
      return false;
    }
    try {
      const path = google.maps.geometry.encoding.decodePath(routePolyline);
      if (!path || !path.length) {
        return false;
      }
      const line = new google.maps.Polyline({
        path: path,
        geodesic: false,
        strokeColor: "#6A1B9A",
        strokeOpacity: 0.9,
        strokeWeight: 6,
        map: map,
      });
      const routeBounds = new google.maps.LatLngBounds();
      path.forEach((point) => routeBounds.extend(point));
      map.fitBounds(routeBounds, 64);
      routeDrawn = true;
      document.getElementById("map-status").innerText = statusText();
      return true;
    } catch (err) {
      console.warn("Could not draw encoded route polyline", err);
      return false;
    }
  }

  function drawGoogleDirectionsRoute() {
    // Intentionally disabled. Selected route geometry comes from the
    // server-side Routes API encoded polyline. The legacy browser
    // DirectionsRenderer can choose odd snaps for the broad DECC venue.
    routeFailed = Boolean(routeOriginQuery && routeDestinationQuery && !routePolyline);
    document.getElementById("map-status").innerText = statusText();
  }


  function mapsUrlFor(item, resolvedPlaceId) {
    const placeId = item.place_id || resolvedPlaceId || "";
    return "https://www.google.com/maps/search/?api=1&query=" + encodeURIComponent(item.query || item.name) + (placeId ? "&query_place_id=" + encodeURIComponent(placeId) : "");
  }

  function addResolvedMarker(item, resolved) {
    const isSelectedPickup = item.kind === "pickup" && item.id === selectedPickupId;
    const isSelectedOrigin = item.id === selectedOriginId;
    const visual = markerVisual(item, isSelectedPickup, isSelectedOrigin);
    const zIndex = isSelectedOrigin ? 1200 : (isSelectedPickup ? 1100 : (item.kind === "pickup" ? 700 : 300));
    const marker = new google.maps.Marker({
      map: map,
      position: resolved.location,
      title: item.name,
      icon: visual.icon,
      label: visual.label,
      zIndex: zIndex,
    });
    const kindLabel = isSelectedOrigin ? "Selected start" : (item.kind === "pickup" ? "Bus pickup" : "Hotel/lodging");
    const addressLine = resolved.formattedAddress || item.address || item.query;
    const mapsUrl = mapsUrlFor(item, resolved.placeId || "");
    const content = `<div style="font-family:Arial,sans-serif;max-width:310px;line-height:1.35;">
      <strong>${escapeHtml(item.name)}</strong><br>
      <span>${escapeHtml(kindLabel)}</span><br>
      <span>${escapeHtml(addressLine)}</span><br>
      ${item.note ? `<span>${escapeHtml(item.note)}</span><br>` : ""}
      <a target="_blank" rel="noopener" href="${mapsUrl}">Open in Google Maps</a>
    </div>`;
    marker.addListener("click", () => {
      infoWindow.setContent(content);
      infoWindow.open(map, marker);
    });
    bounds.extend(resolved.location);
    added += 1;
  }

  function coordinateFallback(item) {
    const lat = parseCoordinate(item.lat);
    const lng = parseCoordinate(item.lng);
    if (lat === null || lng === null) {
      return null;
    }
    return {
      location: new google.maps.LatLng(lat, lng),
      formattedAddress: item.address || item.query || "",
      placeId: item.place_id || "",
    };
  }

  function finish(item, resolved, sourceStatus) {
    processed += 1;
    if (resolved && resolved.location) {
      addResolvedMarker(item, resolved);
    } else {
      const fallback = coordinateFallback(item);
      if (fallback) {
        addResolvedMarker(item, fallback);
      } else {
        failed += 1;
        console.warn("Map marker could not be resolved", item.name, sourceStatus);
      }
    }
    if (processed === markerData.length) {
      fitMarkerBoundsIfNeeded();
      document.getElementById("map-status").innerText = statusText();
      if (added === 0) {
        document.getElementById("map-status").innerText = "No markers could be placed. Check API restrictions and enabled Google Maps APIs.";
      }
    } else {
      document.getElementById("map-status").innerText = statusText();
    }
  }

  function geocodeItem(item, statusPrefix) {
    const request = item.place_id ? { placeId: item.place_id } : { address: item.query };
    geocoder.geocode(request, (results, status) => {
      if (status === "OK" && results && results[0] && results[0].geometry) {
        finish(item, {
          location: results[0].geometry.location,
          formattedAddress: results[0].formatted_address || "",
          placeId: results[0].place_id || "",
        }, statusPrefix + " geocoder OK");
      } else {
        finish(item, null, statusPrefix + " geocoder " + status);
      }
    });
  }

  function resolveItem(item) {
    // Prefer Google's place/address resolution for visible markers. CSV
    // coordinates remain a final fallback when Google cannot resolve a marker.
    if (item.place_id) {
      geocodeItem(item, "place_id");
      return;
    }
    if (placesService && item.query) {
      placesService.findPlaceFromQuery(
        {
          query: item.query,
          fields: ["name", "geometry", "formatted_address", "place_id"],
        },
        (results, status) => {
          if (status === "OK" && results && results[0] && results[0].geometry) {
            finish(item, {
              location: results[0].geometry.location,
              formattedAddress: results[0].formatted_address || "",
              placeId: results[0].place_id || "",
            }, "places OK");
          } else {
            geocodeItem(item, "places " + status + "; fallback");
          }
        }
      );
    } else {
      geocodeItem(item, "no places service");
    }
  }

  if (!drawEncodedRoutePolyline()) {
    drawGoogleDirectionsRoute();
  }

  if (!markerData.length) {
    document.getElementById("map-status").innerText = "No map locations are configured.";
    return;
  }
  markerData.forEach(resolveItem);
}
</script>
<script async defer src="https://maps.googleapis.com/maps/api/js?key=__API_KEY__&libraries=places,geometry&callback=initBusFinderMap"></script>
"""

    for key, value in replacements.items():
        template = template.replace(key, value)
    return template
