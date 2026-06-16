from __future__ import annotations

import os
from typing import Any

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from src.data import (
    RACE_CONFIG,
    available_pickups,
    load_hotels,
    load_other_transportation,
    load_pickups,
    load_return_routes,
    pickup_time_column,
)
from src.google_maps import (
    clean_text,
    compute_driving_matrix,
    google_embed_directions_url,
    google_maps_directions_url,
    google_maps_search_url,
    google_overview_map_html,
    row_location_query,
    row_place_id,
)

st.set_page_config(
    page_title="Duluth Race Shuttle Finder",
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
def cached_other_transportation() -> list[dict[str, Any]]:
    return load_other_transportation()


@st.cache_data(ttl=60 * 60, show_spinner="Checking Google driving distances...")
def cached_route_matrix(
    api_key: str,
    origin_query: str,
    destinations_tuple: tuple[tuple[str, str, str], ...],
    traffic_aware: bool,
) -> list[dict[str, Any]]:
    destinations = [
        {"id": item[0], "query": item[1], "place_id": item[2]}
        for item in destinations_tuple
    ]
    results = compute_driving_matrix(
        api_key=api_key,
        origin_query=origin_query,
        destinations=destinations,
        traffic_aware=traffic_aware,
    )
    return [
        {
            "id": result.pickup_id,
            "driving_miles": result.distance_miles,
            "drive_minutes": result.duration_minutes,
            "route_condition": result.condition,
            "route_error": result.error,
        }
        for result in results
    ]


def get_google_maps_api_key() -> str:
    """Read the Google Maps Platform key from Streamlit secrets or the environment."""
    try:
        key = st.secrets["GOOGLE_MAPS_API_KEY"]
    except Exception:
        key = os.getenv("GOOGLE_MAPS_API_KEY", "")
    return clean_text(key)


def arrival_window(row: pd.Series, race_key: str, corral: str) -> str:
    col = pickup_time_column(race_key, corral)
    return clean_text(row.get(col))


def destination_tuple(pickups: pd.DataFrame) -> tuple[tuple[str, str, str], ...]:
    return tuple(
        (
            clean_text(row.get("id")),
            row_location_query(row),
            row_place_id(row),
        )
        for _, row in pickups.iterrows()
    )


def format_miles(value: Any) -> str:
    try:
        if pd.isna(value):
            return "—"
        return f"{float(value):.1f} mi"
    except Exception:
        return "—"


def format_minutes(value: Any) -> str:
    try:
        if pd.isna(value):
            return "—"
        minutes = float(value)
        if minutes < 1:
            return "<1 min"
        return f"{round(minutes):.0f} min"
    except Exception:
        return "—"


def make_ranked_pickups(
    pickups: pd.DataFrame,
    race_key: str,
    corral: str,
    origin_query: str,
    api_key: str,
    traffic_aware: bool,
) -> pd.DataFrame:
    routes = cached_route_matrix(
        api_key,
        origin_query,
        destination_tuple(pickups),
        traffic_aware,
    )
    route_df = pd.DataFrame(routes)
    ranked = pickups.merge(route_df, on="id", how="left")
    ranked["recommended_window"] = ranked.apply(
        lambda row: arrival_window(row, race_key, corral),
        axis=1,
    )
    ranked["destination_query"] = ranked.apply(row_location_query, axis=1)
    ranked["destination_place_id"] = ranked.apply(row_place_id, axis=1)
    ranked["directions_url"] = ranked.apply(
        lambda row: google_maps_directions_url(
            origin_query=origin_query,
            destination_query=row["destination_query"],
            destination_place_id=row["destination_place_id"],
        ),
        axis=1,
    )
    ranked["open_in_maps_url"] = ranked.apply(
        lambda row: google_maps_search_url(row["destination_query"], row["destination_place_id"]),
        axis=1,
    )
    ranked["route_sort"] = pd.to_numeric(ranked["driving_miles"], errors="coerce")
    return ranked.sort_values("route_sort", na_position="last").reset_index(drop=True)


def make_unranked_pickups(pickups: pd.DataFrame, race_key: str, corral: str, origin_query: str) -> pd.DataFrame:
    unranked = pickups.copy()
    unranked["recommended_window"] = unranked.apply(
        lambda row: arrival_window(row, race_key, corral),
        axis=1,
    )
    unranked["destination_query"] = unranked.apply(row_location_query, axis=1)
    unranked["destination_place_id"] = unranked.apply(row_place_id, axis=1)
    unranked["directions_url"] = unranked.apply(
        lambda row: google_maps_directions_url(
            origin_query=origin_query,
            destination_query=row["destination_query"],
            destination_place_id=row["destination_place_id"],
        ),
        axis=1,
    )
    unranked["open_in_maps_url"] = unranked.apply(
        lambda row: google_maps_search_url(row["destination_query"], row["destination_place_id"]),
        axis=1,
    )
    return unranked.reset_index(drop=True)


def render_iframe(url: str, height: int = 520) -> None:
    """Render an iframe with compatibility across Streamlit versions."""
    if hasattr(st, "iframe"):
        try:
            st.iframe(url, height=height)
            return
        except TypeError:
            pass
    components.iframe(url, height=height, scrolling=False)


def render_pickup_summary(row: pd.Series, *, race_name: str, corral: str, show_distance: bool) -> None:
    st.markdown(f"### {row['name']}")
    cols = st.columns(3 if show_distance else 2)
    with cols[0]:
        st.metric("Loading window", clean_text(row.get("recommended_window")) or "Check official guide")
    if show_distance:
        with cols[1]:
            st.metric("Driving distance", format_miles(row.get("driving_miles")))
        with cols[2]:
            st.metric("Estimated drive", format_minutes(row.get("drive_minutes")))
    else:
        with cols[1]:
            st.metric("Race / corral", f"{race_name}, {corral}")

    st.write(f"**Address:** {row['full_address']}")
    st.write(f"**Best for:** {row['best_for']}")
    st.write(f"**Bus loading:** {row['loading_instructions']}")
    st.write(f"**Parking:** {row['parking_info']}")
    if clean_text(row.get("access_notes")):
        st.info(clean_text(row.get("access_notes")))
    if clean_text(row.get("google_query_note")):
        st.caption(clean_text(row.get("google_query_note")))

    buttons = st.columns(3)
    with buttons[0]:
        st.link_button("Open Google directions", row["directions_url"], use_container_width=True)
    with buttons[1]:
        st.link_button("Open pickup in Google Maps", row["open_in_maps_url"], use_container_width=True)
    map_url = clean_text(row.get("loading_site_map_url"))
    if map_url:
        with buttons[2]:
            st.link_button("Official loading map", map_url, use_container_width=True)


def render_rank_table(ranked: pd.DataFrame, *, show_distance: bool) -> None:
    display = ranked.copy()
    display["Google directions"] = display["directions_url"]
    display["Official loading map"] = display["loading_site_map_url"]
    display["Driving distance"] = display.get("driving_miles", pd.Series(dtype=float)).apply(format_miles) if show_distance else "Requires API key"
    display["Estimated drive"] = display.get("drive_minutes", pd.Series(dtype=float)).apply(format_minutes) if show_distance else "Requires API key"
    display["Recommended loading window"] = display["recommended_window"]
    display["Pickup"] = display["name"]
    display["Good for"] = display["best_for"]
    columns = ["Pickup", "Driving distance", "Estimated drive", "Recommended loading window", "Good for", "Google directions", "Official loading map"]
    st.dataframe(
        display[columns],
        hide_index=True,
        use_container_width=True,
        column_config={
            "Google directions": st.column_config.LinkColumn("Google directions", display_text="Open route"),
            "Official loading map": st.column_config.LinkColumn("Official loading map", display_text="Official map"),
        },
    )


def main() -> None:
    pickups = cached_pickups()
    hotels = cached_hotels()
    return_routes = cached_return_routes()
    other_transportation = cached_other_transportation()
    api_key = get_google_maps_api_key()

    st.title("Duluth Race Shuttle Finder")
    st.caption("Find a race-morning bus pickup from a hotel or custom location using Google Maps routing.")

    if api_key:
        st.success("Google Maps is connected. Driving-distance ranking and embedded Google maps are enabled.", icon="✅")
    else:
        st.warning(
            "Add `GOOGLE_MAPS_API_KEY` in Streamlit secrets to enable Google driving-distance ranking and embedded maps. "
            "Until then, the app can still create Google Maps direction links.",
            icon="🔑",
        )

    race_col, corral_col = st.columns(2)
    with race_col:
        race_name = st.selectbox("Race", list(RACE_CONFIG.keys()))
    race_key = str(RACE_CONFIG[race_name]["key"])
    with corral_col:
        corral = st.selectbox("Corral", RACE_CONFIG[race_name]["corrals"])

    race_pickups = available_pickups(pickups, race_key)

    with st.form("find_pickup_form"):
        st.subheader("Where are you starting from?")
        start_type = st.radio(
            "Starting point",
            ["Choose a listed hotel/lodging", "Enter a custom address or place"],
            horizontal=True,
        )
        selected_hotel_label = ""
        custom_origin = ""
        if start_type == "Choose a listed hotel/lodging":
            hotel_labels = ["Select a hotel..."] + hotels["display_name"].tolist()
            selected_hotel_label = st.selectbox("Hotel/lodging", hotel_labels)
            st.caption("Hotel pins are no longer used for nearest calculations; Google routes from the hotel name/address instead.")
        else:
            custom_origin = st.text_input(
                "Address, hotel, landmark, or neighborhood",
                placeholder="Example: Canal Park Lodge, Duluth MN",
            )
        traffic_aware = st.checkbox(
            "Use traffic-aware estimates",
            value=False,
            help="Most visitors probably want normal driving distance while planning. Turn this on for a live-traffic style ETA check.",
        )
        submitted = st.form_submit_button("Find pickup options", type="primary")

    if submitted:
        origin_query = ""
        origin_label = ""
        if start_type == "Choose a listed hotel/lodging" and selected_hotel_label != "Select a hotel...":
            hotel_row = hotels.loc[hotels["display_name"] == selected_hotel_label].iloc[0]
            origin_query = row_location_query(hotel_row)
            origin_label = clean_text(hotel_row.get("name"))
        elif start_type == "Enter a custom address or place":
            origin_query = clean_text(custom_origin)
            origin_label = origin_query

        if not origin_query:
            st.warning("Choose a hotel or enter a starting address first.")
        else:
            st.session_state["last_search"] = {
                "origin_query": origin_query,
                "origin_label": origin_label,
                "race_name": race_name,
                "race_key": race_key,
                "corral": corral,
                "traffic_aware": traffic_aware,
            }

    search = st.session_state.get("last_search")

    if not search:
        st.divider()
        st.subheader("Pickup spots")
        st.write("Start by choosing a hotel or entering an address. You can also review the pickup spots below.")
        render_rank_table(make_unranked_pickups(race_pickups, race_key, corral, "Duluth MN"), show_distance=False)
    else:
        origin_query = search["origin_query"]
        origin_label = search["origin_label"]
        race_name = search["race_name"]
        race_key = search["race_key"]
        corral = search["corral"]
        traffic_aware = bool(search["traffic_aware"])
        race_pickups = available_pickups(pickups, race_key)

        st.divider()
        st.subheader(f"Pickup options from {origin_label}")
        st.caption(f"Race: {race_name} · Corral {corral}")

        ranked: pd.DataFrame
        show_distance = bool(api_key)
        if api_key:
            try:
                ranked = make_ranked_pickups(race_pickups, race_key, corral, origin_query, api_key, traffic_aware)
            except Exception as exc:
                show_distance = False
                st.error(
                    "Google driving-distance lookup failed. The app will show Google route links instead. "
                    f"Details: {exc}"
                )
                ranked = make_unranked_pickups(race_pickups, race_key, corral, origin_query)
        else:
            ranked = make_unranked_pickups(race_pickups, race_key, corral, origin_query)

        if show_distance and pd.notna(ranked.iloc[0].get("driving_miles")):
            top = ranked.iloc[0]
            st.success(
                f"Closest by Google driving distance: **{top['name']}** "
                f"({format_miles(top['driving_miles'])}, about {format_minutes(top['drive_minutes'])}).",
                icon="🚌",
            )
        elif not show_distance:
            st.info(
                "Driving-distance ranking requires the Google Routes API key. The buttons below still open each route in Google Maps."
            )

        table_tab, route_tab, map_tab = st.tabs(["Best options", "Selected route", "Google pickup map"])

        with table_tab:
            render_rank_table(ranked, show_distance=show_distance)

        pickup_names = ranked["name"].tolist()
        default_pickup = pickup_names[0] if pickup_names else None

        with route_tab:
            if not pickup_names:
                st.warning("No pickup spots are configured for this race.")
            else:
                selected_name = st.selectbox("Pickup to view", pickup_names, index=0)
                selected_row = ranked.loc[ranked["name"] == selected_name].iloc[0]
                left, right = st.columns([1, 1.15], gap="large")
                with left:
                    render_pickup_summary(selected_row, race_name=race_name, corral=corral, show_distance=show_distance)
                    st.write(f"**Bag note:** {RACE_CONFIG[race_name]['bag_note']}")
                with right:
                    if api_key:
                        embed_url = google_embed_directions_url(
                            api_key=api_key,
                            origin_query=origin_query,
                            destination_query=selected_row["destination_query"],
                            destination_place_id=selected_row["destination_place_id"],
                        )
                        render_iframe(embed_url, height=560)
                    else:
                        st.info("Embedded Google route maps appear after `GOOGLE_MAPS_API_KEY` is configured.")
                        st.link_button("Open this route in Google Maps", selected_row["directions_url"], type="primary")

        with map_tab:
            if api_key:
                show_hotels = st.toggle(
                    "Show hotel/lodging markers too",
                    value=False,
                    help="Off by default to keep the map simple and avoid clutter. Hotel markers are geocoded by Google when shown.",
                )
                selected_id = clean_text(ranked.iloc[0].get("id")) if len(ranked) else ""
                html = google_overview_map_html(
                    api_key=api_key,
                    pickups=race_pickups,
                    hotels=hotels,
                    show_hotels=show_hotels,
                    selected_pickup_id=selected_id,
                    height=540,
                )
                components.html(html, height=570, scrolling=False)
                st.caption(
                    "This map geocodes each pickup from its Google query/place ID instead of plotting the CSV latitude/longitude values. "
                    "Use the official loading-site PDF for exact race-morning driveway or parking-lot details."
                )
            else:
                st.info("The Google pickup map requires a Google Maps Platform key. Use the route links in the table for now.")

    with st.expander("Return shuttles and other transportation"):
        st.markdown("**Return buses:** Free return shuttle service runs from the DECC on Railroad Street near the north gate from 8:00 a.m. to 3:30 p.m. Two Harbors returns depart on the hour.")
        if not return_routes.empty:
            st.dataframe(return_routes, hide_index=True, use_container_width=True)
        st.markdown("---")
        for item in other_transportation:
            st.markdown(f"**{item.get('title', '')}**")
            if item.get("details"):
                st.write(item["details"])
            if item.get("schedule"):
                for schedule_item in item["schedule"]:
                    st.write(f"- {schedule_item}")

    st.caption(
        "Race-day logistics can change. Verify final loading windows, road closures, and shuttle details with the official race guide before publishing."
    )


if __name__ == "__main__":
    main()
