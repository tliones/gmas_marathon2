"""Folium map construction for the bus pickup finder app."""

from __future__ import annotations

from html import escape
from typing import Dict, Optional, Tuple

import folium
import pandas as pd


DEFAULT_CENTER = (46.7867, -92.1005)  # Duluth waterfront-ish


def _popup_html(title: str, lines: list[str]) -> str:
    safe_title = escape(title)
    safe_lines = "".join(f"<li>{escape(line)}</li>" for line in lines if str(line).strip())
    return f"<strong>{safe_title}</strong><ul style='margin-left: 1rem; padding-left: 0.2rem;'>{safe_lines}</ul>"


def build_pickup_map(
    pickups: pd.DataFrame,
    hotels: pd.DataFrame,
    time_windows: Dict[str, str] | None = None,
    origin: Optional[Tuple[float, float, str]] = None,
    selected_pickup_id: Optional[str] = None,
) -> folium.Map:
    """Build an interactive Folium map.

    origin should be a tuple of (lat, lon, label) when a user has selected or entered a
    starting point.
    """
    time_windows = time_windows or {}

    if origin:
        center = (origin[0], origin[1])
        zoom_start = 11
    elif not pickups.empty:
        center = (float(pickups["latitude"].mean()), float(pickups["longitude"].mean()))
        zoom_start = 10
    else:
        center = DEFAULT_CENTER
        zoom_start = 10

    m = folium.Map(location=center, zoom_start=zoom_start, control_scale=True)

    pickup_group = folium.FeatureGroup(name="Bus pickup spots", show=True)
    for _, row in pickups.iterrows():
        pickup_id = str(row["id"])
        marker_lines = [
            str(row.get("full_address", "")),
            f"Recommended window: {time_windows.get(pickup_id, 'Select race/corral')}",
            f"Loading: {row.get('loading_instructions', '')}",
            str(row.get("best_for", "")),
        ]
        popup = folium.Popup(_popup_html(str(row["name"]), marker_lines), max_width=340)
        folium.Marker(
            location=(float(row["latitude"]), float(row["longitude"])),
            tooltip=str(row["name"]),
            popup=popup,
            icon=folium.Icon(color="red", icon="bus", prefix="fa"),
        ).add_to(pickup_group)
    pickup_group.add_to(m)

    hotel_group = folium.FeatureGroup(name="Hotels / lodging examples", show=True)
    for _, row in hotels.dropna(subset=["latitude", "longitude"]).iterrows():
        lines = [
            str(row.get("full_address", "")),
            f"Area: {row.get('area', '')}",
            f"Return shuttle group: {row.get('return_shuttle_group', '')}",
        ]
        popup = folium.Popup(_popup_html(str(row["name"]), lines), max_width=340)
        folium.Marker(
            location=(float(row["latitude"]), float(row["longitude"])),
            tooltip=str(row["name"]),
            popup=popup,
            icon=folium.Icon(color="blue", icon="bed", prefix="fa"),
        ).add_to(hotel_group)
    hotel_group.add_to(m)

    if origin:
        origin_lat, origin_lon, origin_label = origin
        folium.Marker(
            location=(origin_lat, origin_lon),
            tooltip=origin_label,
            popup=folium.Popup(escape(origin_label), max_width=260),
            icon=folium.Icon(color="green", icon="map-marker", prefix="fa"),
        ).add_to(m)

    if origin and selected_pickup_id:
        match = pickups[pickups["id"].astype(str) == str(selected_pickup_id)]
        if not match.empty:
            row = match.iloc[0]
            folium.PolyLine(
                locations=[
                    (origin[0], origin[1]),
                    (float(row["latitude"]), float(row["longitude"])),
                ],
                tooltip="Straight-line distance only; open directions for actual route.",
                weight=4,
                opacity=0.8,
            ).add_to(m)

    folium.LayerControl(collapsed=False).add_to(m)
    return m
