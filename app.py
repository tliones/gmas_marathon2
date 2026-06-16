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


def card_container():
    """Return a bordered container when available, with a plain-container fallback."""
    try:
        return st.container(border=True)
    except TypeError:
        return st.container()


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


def render_rank_table(ranked: pd.DataFrame, *, show_distance: bool) -> None:
    display = ranked.copy()
    display["Google directions"] = display["directions_url"]
    display["Official loading map"] = display["loading_site_map_url"]
    if show_distance:
        display["Driving distance"] = display.get("driving_miles", pd.Series(dtype=float)).apply(format_miles)
        display["Estimated drive"] = display.get("drive_minutes", pd.Series(dtype=float)).apply(format_minutes)
    else:
        display["Driving distance"] = "Not calculated"
        display["Estimated drive"] = "Not calculated"
    display["Recommended loading window"] = display["recommended_window"]
    display["Pickup"] = display["name"]
    display["Good for"] = display["best_for"]
    columns = [
        "Pickup",
        "Driving distance",
        "Estimated drive",
        "Recommended loading window",
        "Good for",
        "Google directions",
        "Official loading map",
    ]
    st.dataframe(
        display[columns],
        hide_index=True,
        width="stretch",
        column_config={
            "Google directions": st.column_config.LinkColumn("Google directions", display_text="Open route"),
            "Official loading map": st.column_config.LinkColumn("Official loading map", display_text="Official map"),
        },
    )


def origin_from_form(
    *,
    start_type: str,
    selected_hotel_label: str,
    custom_origin: str,
    hotels: pd.DataFrame,
) -> dict[str, str]:
    """Return normalized origin information from the form widgets."""
    if start_type == "Choose a listed hotel/lodging" and selected_hotel_label != "Select a hotel...":
        hotel_row = hotels.loc[hotels["display_name"] == selected_hotel_label].iloc[0]
        return {
            "origin_query": row_location_query(hotel_row),
            "origin_label": clean_text(hotel_row.get("name")),
            "origin_id": clean_text(hotel_row.get("id")),
            "origin_address": clean_text(hotel_row.get("full_address")),
            "origin_area": clean_text(hotel_row.get("area")),
            "origin_kind": "hotel",
        }

    custom_origin = clean_text(custom_origin)
    if custom_origin:
        return {
            "origin_query": custom_origin,
            "origin_label": custom_origin,
            "origin_id": "",
            "origin_address": custom_origin,
            "origin_area": "Custom address or place",
            "origin_kind": "custom",
        }

    return {
        "origin_query": "",
        "origin_label": "",
        "origin_id": "",
        "origin_address": "",
        "origin_area": "",
        "origin_kind": "",
    }


def render_origin_card(search: dict[str, Any]) -> None:
    with card_container():
        st.markdown("#### 1. Starting location")
        st.write(f"**{search['origin_label']}**")
        if clean_text(search.get("origin_area")):
            st.caption(clean_text(search.get("origin_area")))
        if clean_text(search.get("origin_address")):
            st.write(clean_text(search.get("origin_address")))
        st.link_button(
            "Open start in Google Maps",
            google_maps_search_url(search["origin_query"]),
            width="stretch",
        )


def render_selected_pickup_card(row: pd.Series, *, race_name: str, corral: str, show_distance: bool) -> None:
    with card_container():
        st.markdown("#### 2. Pickup location")
        st.write(f"**{row['name']}**")
        st.write(f"**Loading window:** {clean_text(row.get('recommended_window')) or 'Check official guide'}")
        st.write(f"**Address:** {row['full_address']}")
        if show_distance:
            metric_cols = st.columns(2)
            metric_cols[0].metric("Driving distance", format_miles(row.get("driving_miles")))
            metric_cols[1].metric("Estimated drive", format_minutes(row.get("drive_minutes")))
        st.write(f"**Bus loading:** {row['loading_instructions']}")
        st.write(f"**Best for:** {row['best_for']}")
        if clean_text(row.get("access_notes")):
            st.info(clean_text(row.get("access_notes")))
        st.caption(f"Race: {race_name} · Corral {corral}")

        button_cols = st.columns(3)
        with button_cols[0]:
            st.link_button("Directions", row["directions_url"], width="stretch")
        with button_cols[1]:
            st.link_button("Pickup map", row["open_in_maps_url"], width="stretch")
        map_url = clean_text(row.get("loading_site_map_url"))
        if map_url:
            with button_cols[2]:
                st.link_button("Official map", map_url, width="stretch")


def main() -> None:
    pickups = cached_pickups()
    hotels = cached_hotels()
    return_routes = cached_return_routes()
    other_transportation = cached_other_transportation()
    api_key = get_google_maps_api_key()

    st.title("Duluth Race Shuttle Finder")
    st.caption("A Google Maps-based helper for choosing a race-morning bus pickup from a hotel, lodging spot, or custom location.")

    if api_key:
        st.caption("Google Maps is connected: all-location map, Google marker placement, embedded routes, and driving-distance ranking are enabled.")
    else:
        st.warning(
            "Add `GOOGLE_MAPS_API_KEY` in Streamlit secrets to enable the main Google map, embedded routes, and driving-distance ranking. "
            "Without a key, this app still creates Google Maps direction links.",
            icon="🔑",
        )

    with st.form("find_pickup_form"):
        start_col, race_col = st.columns([1.1, 0.9], gap="large")
        with start_col:
            st.markdown("#### 1. Starting location")
            start_type = st.radio(
                "How should the app find your start?",
                ["Choose a listed hotel/lodging", "Enter a custom address or place"],
                horizontal=True,
            )
            selected_hotel_label = ""
            custom_origin = ""
            if start_type == "Choose a listed hotel/lodging":
                hotel_labels = ["Select a hotel..."] + hotels["display_name"].tolist()
                selected_hotel_label = st.selectbox("Hotel/lodging", hotel_labels)
            else:
                custom_origin = st.text_input(
                    "Address, hotel, landmark, or neighborhood",
                    placeholder="Example: Canal Park Lodge, Duluth MN",
                )

        with race_col:
            st.markdown("#### 2. Race details")
            race_name = st.selectbox("Race", list(RACE_CONFIG.keys()))
            race_key = str(RACE_CONFIG[race_name]["key"])
            corral = st.selectbox("Corral", RACE_CONFIG[race_name]["corrals"])
            traffic_aware = st.checkbox(
                "Use traffic-aware drive-time estimates",
                value=False,
                help="Off keeps the ranking closer to normal planning distance. On uses live-style traffic estimates where Google supports them.",
            )

        submitted = st.form_submit_button("Find closest pickup options", type="primary")

    if submitted:
        origin = origin_from_form(
            start_type=start_type,
            selected_hotel_label=selected_hotel_label,
            custom_origin=custom_origin,
            hotels=hotels,
        )
        if not origin["origin_query"]:
            st.warning("Choose a hotel or enter a starting address first.")
        else:
            st.session_state["last_search"] = {
                **origin,
                "race_name": race_name,
                "race_key": race_key,
                "corral": corral,
                "traffic_aware": traffic_aware,
            }

    search = st.session_state.get("last_search")
    display_race_name = search["race_name"] if search else race_name
    display_race_key = search["race_key"] if search else race_key
    display_corral = search["corral"] if search else corral
    race_pickups = available_pickups(pickups, display_race_key)

    ranked = make_unranked_pickups(race_pickups, display_race_key, display_corral, search["origin_query"] if search else "Duluth MN")
    show_distance = False
    route_lookup_failed = False

    if search and api_key:
        try:
            ranked = make_ranked_pickups(
                race_pickups,
                display_race_key,
                display_corral,
                search["origin_query"],
                api_key,
                bool(search["traffic_aware"]),
            )
            show_distance = True
        except Exception as exc:
            route_lookup_failed = True
            st.error(
                "Google driving-distance lookup failed, so the app is showing Google route links without ranking. "
                f"Details: {exc}"
            )

    selected_row: pd.Series | None = None
    selected_pickup_id = ""
    if search and not ranked.empty:
        top = ranked.iloc[0]
        if show_distance and pd.notna(top.get("driving_miles")):
            st.success(
                f"Closest by Google driving distance: **{top['name']}** "
                f"({format_miles(top['driving_miles'])}, about {format_minutes(top['drive_minutes'])}).",
                icon="🚌",
            )
        elif not show_distance and not route_lookup_failed:
            st.info("Driving-distance ranking requires a Google Maps Platform key. Route links are still available.")

        pickup_names = ranked["name"].tolist()
        selected_name = st.selectbox(
            "Pickup to highlight and route to",
            pickup_names,
            index=0,
            help="The map will highlight this pickup. The route section below will show details for it.",
        )
        selected_row = ranked.loc[ranked["name"] == selected_name].iloc[0]
        selected_pickup_id = clean_text(selected_row.get("id"))

    st.divider()
    map_header_col, map_option_col = st.columns([0.78, 0.22], vertical_alignment="bottom")
    with map_header_col:
        st.subheader("Map: hotels + bus pickup spots")
        st.caption("Pins are resolved by Google Maps from hotel/place names, addresses, and optional place IDs — not plotted from the CSV latitude/longitude columns.")
    with map_option_col:
        show_hotels = st.checkbox("Show hotels", value=True, help="Keep this on for the full visitor overview map.")

    if api_key:
        overview_html = google_overview_map_html(
            api_key=api_key,
            pickups=race_pickups,
            hotels=hotels,
            show_hotels=show_hotels,
            selected_pickup_id=selected_pickup_id,
            selected_origin_id=search["origin_id"] if search else "",
            origin_query=search["origin_query"] if search else "",
            origin_label=search["origin_label"] if search else "",
            height=640,
        )
        components.html(overview_html, height=680, scrolling=False)
        st.caption("Marker legend: P = bus pickup, H = hotel/lodging, S = selected starting location. Purple P marks the selected pickup route.")
    else:
        st.info("The main Google map appears after `GOOGLE_MAPS_API_KEY` is configured in Streamlit Secrets.")

    if not search:
        st.info("Choose a starting location above to rank pickup spots by Google driving distance. Until then, the table below is a timing overview.")
        st.subheader("Pickup timing overview")
        render_rank_table(ranked, show_distance=False)
    elif selected_row is not None:
        st.subheader("Selected route")
        st.caption("Starting location and pickup location are shown side by side so the route is easier to scan.")
        origin_col, pickup_col = st.columns(2, gap="large")
        with origin_col:
            render_origin_card(search)
        with pickup_col:
            render_selected_pickup_card(
                selected_row,
                race_name=display_race_name,
                corral=display_corral,
                show_distance=show_distance,
            )

        st.write(f"**Bag note:** {RACE_CONFIG[display_race_name]['bag_note']}")

        route_map_col, options_col = st.columns([1.25, 0.75], gap="large")
        with route_map_col:
            st.markdown("#### Google route")
            if api_key:
                embed_url = google_embed_directions_url(
                    api_key=api_key,
                    origin_query=search["origin_query"],
                    destination_query=selected_row["destination_query"],
                    destination_place_id=selected_row["destination_place_id"],
                )
                render_iframe(embed_url, height=520)
            else:
                st.info("Embedded Google route maps appear after `GOOGLE_MAPS_API_KEY` is configured.")
                st.link_button("Open this route in Google Maps", selected_row["directions_url"], type="primary")

        with options_col:
            st.markdown("#### Pickup notes")
            st.write(f"**Parking:** {selected_row['parking_info']}")
            if clean_text(selected_row.get("google_query_note")):
                st.caption(clean_text(selected_row.get("google_query_note")))
            if clean_text(selected_row.get("coordinate_note")):
                st.caption(clean_text(selected_row.get("coordinate_note")))

        st.subheader("All pickup options")
        render_rank_table(ranked, show_distance=show_distance)

    with st.expander("Return shuttles and other transportation"):
        st.markdown(
            "**Return buses:** Free return shuttle service runs from the DECC on Railroad Street near the north gate "
            "from 8:00 a.m. to 3:30 p.m. Two Harbors returns depart on the hour."
        )
        if not return_routes.empty:
            st.dataframe(return_routes, hide_index=True, width="stretch")
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
