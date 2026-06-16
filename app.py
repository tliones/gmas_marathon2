from __future__ import annotations

from typing import Optional, Tuple

import pandas as pd
import streamlit as st

try:
    from streamlit_folium import st_folium
except ImportError:  # pragma: no cover - Streamlit UI handles this at runtime
    st_folium = None

from src.data import (
    RACE_CONFIG,
    available_pickups,
    load_hotels,
    load_other_transportation,
    load_pickups,
    load_return_routes,
    pickup_time_column,
)
from src.geo import geocode_address, google_maps_directions_url, google_maps_place_url, haversine_miles
from src.maps import build_pickup_map


st.set_page_config(
    page_title="Grandma's Marathon Bus Pickup Finder",
    page_icon="🚌",
    layout="wide",
)


@st.cache_data(show_spinner=False)
def cached_pickups() -> pd.DataFrame:
    return load_pickups()


@st.cache_data(show_spinner=False)
def cached_hotels() -> pd.DataFrame:
    return load_hotels()


@st.cache_data(show_spinner=False)
def cached_return_routes() -> pd.DataFrame:
    return load_return_routes()


@st.cache_data(show_spinner=False)
def cached_other_transportation() -> list[dict]:
    return load_other_transportation()


@st.cache_data(show_spinner="Looking up that address...")
def cached_geocode(address: str) -> Optional[Tuple[float, float]]:
    return geocode_address(address)


def arrival_window(row: pd.Series, race_key: str, corral: str) -> str:
    col = pickup_time_column(race_key, corral)
    return str(row.get(col, "")).strip()


def coordinate_destination(row: pd.Series) -> str:
    """Return a latitude/longitude destination string matching the map marker."""
    return f"{float(row['latitude']):.7f},{float(row['longitude']):.7f}"


def add_distance_columns(
    pickups: pd.DataFrame,
    origin_lat: float,
    origin_lon: float,
    origin_for_directions: str,
    race_key: str,
    corral: str,
    travelmode: str,
) -> pd.DataFrame:
    ranked = pickups.copy()
    ranked["distance_miles"] = ranked.apply(
        lambda row: haversine_miles(
            origin_lat,
            origin_lon,
            float(row["latitude"]),
            float(row["longitude"]),
        ),
        axis=1,
    )
    ranked["recommended_window"] = ranked.apply(
        lambda row: arrival_window(row, race_key, corral),
        axis=1,
    )
    ranked["directions"] = ranked.apply(
        lambda row: google_maps_directions_url(
            origin=origin_for_directions,
            destination=coordinate_destination(row),
            travelmode=travelmode,
        ),
        axis=1,
    )
    return ranked.sort_values("distance_miles").reset_index(drop=True)


def render_pickup_card(row: pd.Series, race_name: str, corral: str) -> None:
    st.markdown(f"### {row['name']}")
    st.write(f"**Address:** {row['full_address']}")
    st.write(f"**Recommended loading window for {race_name}, Corral {corral}:** {row['recommended_window']}")
    st.write(f"**Straight-line distance:** {row['distance_miles']:.1f} miles")
    st.write(f"**Best for:** {row['best_for']}")
    st.write(f"**Bus loading:** {row['loading_instructions']}")
    st.write(f"**Parking:** {row['parking_info']}")
    if str(row.get("access_notes", "")).strip():
        st.info(str(row["access_notes"]))
    left, right = st.columns(2)
    with left:
        st.link_button("Open directions", row["directions"], use_container_width=True)
    map_url = str(row.get("loading_site_map_url", "")).strip()
    if map_url:
        with right:
            st.link_button("Official loading site map", map_url, use_container_width=True)


def render_time_grid(pickups: pd.DataFrame) -> None:
    st.markdown("#### Garry Bjorklund Half Marathon bus windows")
    half_cols = ["name", "half_corral_1", "half_corral_2", "half_corral_3"]
    st.dataframe(
        pickups[half_cols].rename(
            columns={
                "name": "Pickup spot",
                "half_corral_1": "Corral 1",
                "half_corral_2": "Corral 2",
                "half_corral_3": "Corral 3",
            }
        ),
        hide_index=True,
        use_container_width=True,
    )

    st.markdown("#### Grandma’s Marathon bus windows")
    full_cols = ["name", "full_corral_a", "full_corral_b", "full_corral_c"]
    st.dataframe(
        pickups[full_cols].rename(
            columns={
                "name": "Pickup spot",
                "full_corral_a": "Corral A",
                "full_corral_b": "Corral B",
                "full_corral_c": "Corral C",
            }
        ),
        hide_index=True,
        use_container_width=True,
    )


def render_train_option() -> None:
    st.markdown("### Participant train option from DECC")
    st.warning(
        "The train is not available for transportation to the Garry Bjorklund Half Marathon start line."
    )
    st.write("**Grandma’s Marathon:** 5:00 a.m. to 5:45 a.m.")
    st.write(
        "Limited seating is available on a first-come, first-served basis. The train loads in front of the North gate along Railroad Street."
    )
    st.write(
        "The participant train has bathrooms on board, but it is expected to arrive at the Grandma’s Marathon start line no earlier than 7:10 a.m. If you want more time at the start line, plan to take the bus."
    )


def render_origin_controls(hotels: pd.DataFrame) -> tuple[Optional[Tuple[float, float, str]], Optional[str]]:
    """Render sidebar origin controls.

    Returns (origin tuple, origin string for directions). The tuple is (lat, lon, label).
    """
    st.sidebar.header("Starting point")
    mode = st.sidebar.radio(
        "How do you want to enter your location?",
        ["Choose hotel/lodging", "Enter custom address", "Enter coordinates"],
    )

    if mode == "Choose hotel/lodging":
        hotel_options = ["— Select a hotel or lodging —"] + hotels["display_name"].tolist()
        selected = st.sidebar.selectbox("Hotel / lodging", hotel_options)
        if selected == hotel_options[0]:
            return None, None
        hotel = hotels[hotels["display_name"] == selected].iloc[0]
        label = str(hotel["name"])
        origin = (float(hotel["latitude"]), float(hotel["longitude"]), label)
        origin_for_directions = str(hotel["full_address"])
        st.sidebar.caption(f"Using reviewed hotel coordinates for {label}. Verify exact entrance/driveway before public launch.")
        return origin, origin_for_directions

    if mode == "Enter custom address":
        address = st.sidebar.text_input(
            "Address, hotel, or landmark",
            placeholder="Example: 207 W Superior St, Duluth, MN",
        )
        st.sidebar.caption(
            "Custom address lookup uses OpenStreetMap/Nominatim and is cached. For production traffic, use a commercial geocoder."
        )
        if not address.strip():
            return None, None
        try:
            coords = cached_geocode(address)
        except RuntimeError as exc:
            st.sidebar.error(str(exc))
            return None, None
        if coords is None:
            st.sidebar.warning("I could not geocode that address. Try a fuller address or use coordinates.")
            return None, None
        return (coords[0], coords[1], address.strip()), address.strip()

    st.sidebar.caption("Use this if a user shares a GPS pin or if geocoding is unavailable.")
    lat = st.sidebar.number_input("Latitude", min_value=-90.0, max_value=90.0, value=46.7867, format="%.6f")
    lon = st.sidebar.number_input("Longitude", min_value=-180.0, max_value=180.0, value=-92.1005, format="%.6f")
    label = st.sidebar.text_input("Location label", value="Custom location")
    origin = (float(lat), float(lon), label.strip() or "Custom location")
    origin_for_directions = f"{lat},{lon}"
    return origin, origin_for_directions


def main() -> None:
    pickups = cached_pickups()
    hotels = cached_hotels()
    return_routes = cached_return_routes()
    other_transportation = cached_other_transportation()

    st.title("🚌 Grandma's Marathon Bus Pickup Finder")
    st.caption(
        "A GitHub-ready Streamlit app for helping visitors find the closest race-day bus pickup from a hotel, address, or GPS point."
    )

    st.sidebar.header("Runner details")
    race_name = st.sidebar.selectbox("Race", list(RACE_CONFIG.keys()))
    race_key = str(RACE_CONFIG[race_name]["key"])
    corrals = list(RACE_CONFIG[race_name]["corrals"])
    corral = st.sidebar.selectbox("Corral", corrals)
    travelmode = st.sidebar.selectbox(
        "Directions mode",
        ["driving", "walking", "transit", "bicycling"],
        help="This changes the Google Maps directions link only. Distance ranking uses straight-line distance.",
    )
    top_n = st.sidebar.slider("Number of pickup options to compare", min_value=1, max_value=7, value=3)

    origin, origin_for_directions = render_origin_controls(hotels)

    race_pickups = available_pickups(pickups, race_key)
    time_windows = {
        str(row["id"]): arrival_window(row, race_key, corral)
        for _, row in race_pickups.iterrows()
    }

    ranked = pd.DataFrame()
    selected_pickup_id: Optional[str] = None
    if origin and origin_for_directions:
        ranked = add_distance_columns(
            race_pickups,
            origin[0],
            origin[1],
            origin_for_directions,
            race_key,
            str(corral),
            travelmode,
        )
        selected_pickup_id = str(ranked.iloc[0]["id"])

    tab_finder, tab_map, tab_pickups, tab_return, tab_other = st.tabs(
        ["Find a pickup", "Map", "Pickup details", "Return shuttles", "Other transportation"]
    )

    with tab_finder:
        st.subheader("Closest pickup recommendation")
        st.caption(
            "The ranking uses straight-line distance. Always open directions for actual route, travel time, closures, and parking access."
        )

        if ranked.empty:
            st.info("Choose a hotel/lodging, enter an address, or enter coordinates in the sidebar to calculate the closest pickup spots.")
        else:
            top = ranked.iloc[0]
            left, right = st.columns([1.2, 1])
            with left:
                st.success(
                    f"Closest bus pickup: {top['name']} — {top['distance_miles']:.1f} miles away"
                )
                render_pickup_card(top, race_name, str(corral))
            with right:
                st.markdown("### Compare top options")
                display = ranked.head(top_n).copy()
                display["distance_miles"] = display["distance_miles"].round(1)
                display = display.rename(
                    columns={
                        "name": "Pickup spot",
                        "distance_miles": "Miles",
                        "recommended_window": "Recommended window",
                        "best_for": "Best for",
                        "directions": "Directions",
                    }
                )
                st.dataframe(
                    display[["Pickup spot", "Miles", "Recommended window", "Best for", "Directions"]],
                    hide_index=True,
                    use_container_width=True,
                    column_config={
                        "Directions": st.column_config.LinkColumn("Directions", display_text="Open"),
                    },
                )

            st.markdown("### Details for nearby pickup options")
            for _, row in ranked.head(top_n).iterrows():
                with st.expander(f"{row['name']} — {row['distance_miles']:.1f} miles"):
                    render_pickup_card(row, race_name, str(corral))

        st.divider()
        st.info(str(RACE_CONFIG[race_name]["bag_note"]))
        if race_key == "full":
            render_train_option()

    with tab_map:
        st.subheader("Map of pickup spots and hotel/lodging examples")
        if st_folium is None:
            st.error("streamlit-folium is not installed. Run `pip install -r requirements.txt`.")
        else:
            map_obj = build_pickup_map(
                race_pickups,
                hotels,
                time_windows=time_windows,
                origin=origin,
                selected_pickup_id=selected_pickup_id,
            )
            st_folium(map_obj, height=650, use_container_width=True, returned_objects=[])
        st.caption(
            "Pickup pins use the official Google Maps place coordinates linked from the race transportation page. "
            "Loading zones can be within a parking lot or along a specific drive, so open the official loading site map for race-morning boarding details. "
            "Hotel points come from data/hotels.csv. Pins have been reviewed/updated, but exact hotel entrances and race-day shuttle details should still be verified before public launch."
        )

    with tab_pickups:
        st.subheader("Pickup location details")
        render_time_grid(pickups)
        st.divider()
        for _, row in pickups.iterrows():
            with st.expander(row["name"], expanded=False):
                st.write(f"**Address:** {row['full_address']}")
                st.link_button("Open location in Google Maps", google_maps_place_url(coordinate_destination(row)))
                loading_map_url = str(row.get("loading_site_map_url", "")).strip()
                if loading_map_url:
                    st.link_button("Official loading site map", loading_map_url)
                st.write(f"**Loading:** {row['loading_instructions']}")
                st.write(f"**Parking:** {row['parking_info']}")
                st.write(f"**Best for:** {row['best_for']}")
                if str(row.get("access_notes", "")).strip():
                    st.info(str(row["access_notes"]))
                st.markdown("**Half marathon windows**")
                st.write(
                    f"Corral 1: {row['half_corral_1']} | Corral 2: {row['half_corral_2']} | Corral 3: {row['half_corral_3']}"
                )
                st.markdown("**Full marathon windows**")
                st.write(
                    f"Corral A: {row['full_corral_a']} | Corral B: {row['full_corral_b']} | Corral C: {row['full_corral_c']}"
                )

    with tab_return:
        st.subheader("Return shuttle information")
        st.write(
            "Free return shuttle buses run from the DECC on Railroad Street near the north gate from 8:00 a.m. to 3:30 p.m. on race day."
        )
        st.write(
            "Two Harbors return buses depart on the hour. Other return buses run continuously and depart when full."
        )
        for route_name, group in return_routes.groupby("route_name", sort=False):
            with st.expander(route_name, expanded=True):
                if str(group.iloc[0].get("route_note", "")).strip():
                    st.info(str(group.iloc[0]["route_note"]))
                st.dataframe(
                    group[["stop_name", "stop_type", "notes"]].rename(
                        columns={
                            "stop_name": "Returns to",
                            "stop_type": "Stop type",
                            "notes": "Notes",
                        }
                    ),
                    hide_index=True,
                    use_container_width=True,
                )

    with tab_other:
        st.subheader("Other race-weekend transportation notes")
        for item in other_transportation:
            with st.expander(item["title"], expanded=True):
                for line in item.get("details", []):
                    st.write(line)

        st.divider()
        st.markdown("### Data maintenance")
        st.write(
            "To update this app, edit the CSV and JSON files in the data folder. The app will pick up new pickup spots, hotel points, and shuttle route rows on the next run."
        )


if __name__ == "__main__":
    main()
