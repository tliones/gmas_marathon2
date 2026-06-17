"""Google Maps helpers for the bus pickup finder.

The app can run without a Google Maps Platform key, but these helpers unlock:
- Google driving distance ranking with Routes API Compute Route Matrix
- Google route polylines with Routes API Compute Routes
- Google Maps JavaScript maps with Google-resolved marker positions
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
    """Return the preferred Google routing query for a row.

    Large sites can use a precise display/search query for map markers and a more
    stable official address for Routes API calls. This avoids fragile searches like
    "North Gate" failing and pushing a valid destination, such as DECC, to the bottom
    of the ranked list.
    """
    query = clean_text(row.get("routing_query"))
    if query:
        return query
    return row_location_query(row)


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


def compute_route_polyline(
    *,
    api_key: str,
    origin_query: str,
    destination_query: str,
    destination_place_id: str = "",
    traffic_aware: bool = False,
) -> RoutePolyline:
    """Compute a selected driving route polyline with Google Routes API.

    This is used to draw the selected route on the main Google map, instead of
    showing a second embedded directions map below the overview.
    """
    api_key = clean_text(api_key)
    if not api_key:
        raise ValueError("Missing GOOGLE_MAPS_API_KEY.")

    body = {
        "origin": {"waypoint": routes_waypoint(origin_query)},
        "destination": {"waypoint": routes_waypoint(destination_query, destination_place_id)},
        "travelMode": "DRIVE",
        "routingPreference": "TRAFFIC_AWARE" if traffic_aware else "TRAFFIC_UNAWARE",
        "languageCode": "en-US",
        "units": "IMPERIAL",
        "polylineQuality": "HIGH_QUALITY",
        "polylineEncoding": "ENCODED_POLYLINE",
    }
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": "routes.duration,routes.distanceMeters,routes.polyline.encodedPolyline",
    }

    response = requests.post(ROUTES_COMPUTE_ENDPOINT, headers=headers, json=body, timeout=20)
    response.raise_for_status()
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
    route_polyline: str = "",
    height: int = 620,
) -> str:
    """Return HTML for a Google map showing pickup/hotel markers and an optional route.

    Marker positions are resolved in the browser with Google Maps JavaScript:
    - `google_place_id` when present
    - Places text search from `google_maps_query` when possible
    - Geocoder fallback from `google_maps_query`

    The selected driving route is drawn from a Routes API encoded polyline computed
    server-side. That keeps the route on the main map while using the same driving
    route engine used for the pickup ranking.
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
            }
        )

    replacements = {
        "__HEIGHT__": html.escape(str(int(height)), quote=True),
        "__MARKER_JSON__": json.dumps(marker_data, ensure_ascii=False),
        "__SELECTED_PICKUP_ID__": json.dumps(clean_text(selected_pickup_id), ensure_ascii=False),
        "__SELECTED_ORIGIN_ID__": json.dumps(selected_origin_id, ensure_ascii=False),
        "__ROUTE_POLYLINE__": json.dumps(clean_text(route_polyline), ensure_ascii=False),
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

function escapeHtml(value) {
  return String(value || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
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
    const route = routeDrawn ? " Selected driving route is shown in purple." : "";
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

  function drawRoutePolyline() {
    if (!routePolyline || !google.maps.geometry || !google.maps.geometry.encoding) {
      return;
    }
    try {
      const path = google.maps.geometry.encoding.decodePath(routePolyline);
      if (!path || !path.length) {
        return;
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
      return line;
    } catch (err) {
      console.warn("Could not draw route polyline", err);
    }
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

  function finish(item, resolved, sourceStatus) {
    processed += 1;
    if (resolved && resolved.location) {
      addResolvedMarker(item, resolved);
    } else {
      failed += 1;
      console.warn("Map marker could not be resolved", item.name, sourceStatus);
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

  drawRoutePolyline();

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
