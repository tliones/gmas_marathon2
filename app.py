from __future__ import annotations

import os
from typing import Any

import pandas as pd
import streamlit as st

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
    compute_route_polyline,
    google_maps_directions_url,
    google_maps_search_url,
    google_overview_map_html,
    row_location_query,
    row_place_id,
    row_routing_query,
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


@st.cache_data(ttl=60 * 60, show_spinner="Drawing selected Google route...")
def cached_selected_route_polyline(
    api_key: str,
    origin_query: str,
    destination_query: str,
    destination_place_id: str,
    traffic_aware: bool,
) -> dict[str, Any]:
    route = compute_route_polyline(
        api_key=api_key,
        origin_query=origin_query,
        destination_query=destination_query,
        destination_place_id=destination_place_id,
        traffic_aware=traffic_aware,
    )
    return {
        "encoded_polyline": route.encoded_polyline,
        "distance_miles": route.distance_miles,
        "duration_minutes": route.duration_minutes,
        "error": route.error,
    }


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
    """Routes API destinations: stable pickup ID, routing query, optional place ID."""
    return tuple(
        (
            clean_text(row.get("id")),
            row_routing_query(row),
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
    return enrich_pickups_for_display(ranked, race_key, corral, origin_query, sort_by_route=True)


def make_unranked_pickups(
    pickups: pd.DataFrame, race_key: str, corral: str, origin_query: str
) -> pd.DataFrame:
    return enrich_pickups_for_display(pickups.copy(), race_key, corral, origin_query, sort_by_route=False)


def enrich_pickups_for_display(
    pickups: pd.DataFrame,
    race_key: str,
    corral: str,
    origin_query: str,
    *,
    sort_by_route: bool,
) -> pd.DataFrame:
    display = pickups.copy()
    display["recommended_window"] = display.apply(
        lambda row: arrival_window(row, race_key, corral),
        axis=1,
    )
    display["destination_query"] = display.apply(row_routing_query, axis=1)
    display["destination_map_query"] = display.apply(row_location_query, axis=1)
    display["destination_place_id"] = display.apply(row_place_id, axis=1)
    display["directions_url"] = display.apply(
        lambda row: google_maps_directions_url(
            origin_query=origin_query,
            destination_query=row["destination_query"],
            destination_place_id=row["destination_place_id"],
        ),
        axis=1,
    )
    display["open_in_maps_url"] = display.apply(
        lambda row: google_maps_search_url(row["destination_map_query"], row["destination_place_id"]),
        axis=1,
    )
    display["route_sort"] = pd.to_numeric(display.get("driving_miles"), errors="coerce")
    if sort_by_route:
        display = display.sort_values("route_sort", na_position="last")
    return display.reset_index(drop=True)


def render_iframe(src: str, height: int = 620) -> None:
    """Render URL or HTML content in Streamlit's built-in iframe element."""
    st.iframe(src, height=height, width="stretch")


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
    """Return normalized origin information from the controls."""
    if start_type == "Choose a listed hotel/lodging" and selected_hotel_label != "Select a hotel...":
        hotel_row = hotels.loc[hotels["display_name"] == selected_hotel_label].iloc[0]
        return {
            "origin_query": row_routing_query(hotel_row),
            "origin_map_query": row_location_query(hotel_row),
            "origin_place_id": row_place_id(hotel_row),
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
            "origin_map_query": custom_origin,
            "origin_place_id": "",
            "origin_label": custom_origin,
            "origin_id": "",
            "origin_address": custom_origin,
            "origin_area": "Custom address or place",
            "origin_kind": "custom",
        }

    return {
        "origin_query": "",
        "origin_map_query": "",
        "origin_place_id": "",
        "origin_label": "",
        "origin_id": "",
        "origin_address": "",
        "origin_area": "",
        "origin_kind": "",
    }


def selected_route_polyline(
    *,
    api_key: str,
    search: dict[str, Any] | None,
    selected_row: pd.Series | None,
) -> tuple[str, str]:
    """Return selected route polyline and warning message, if any."""
    if not api_key or not search or selected_row is None:
        return "", ""
    try:
        route = cached_selected_route_polyline(
            api_key,
            search["origin_query"],
            clean_text(selected_row.get("destination_query")),
            clean_text(selected_row.get("destination_place_id")),
            bool(search.get("traffic_aware")),
        )
        if clean_text(route.get("error")):
            return "", clean_text(route.get("error"))
        return clean_text(route.get("encoded_polyline")), ""
    except Exception as exc:
        return "", f"Google route drawing failed: {exc}"


def render_selected_pickup_summary(
    row: pd.Series,
    *,
    search: dict[str, Any],
    race_name: str,
    corral: str,
    show_distance: bool,
) -> None:
    st.markdown("#### Pickup location")
    st.write(f"**{row['name']}**")
    if show_distance:
        metric_cols = st.columns(2)
        metric_cols[0].metric("Drive", format_miles(row.get("driving_miles")))
        metric_cols[1].metric("Time", format_minutes(row.get("drive_minutes")))
    st.write(f"**Loading window:** {clean_text(row.get('recommended_window')) or 'Check official guide'}")
    st.caption(f"{race_name} · Corral {corral}")
    st.write(f"**Address:** {row['full_address']}")
    st.write(f"**Loading:** {row['loading_instructions']}")

    map_url = clean_text(row.get("loading_site_map_url"))
    button_cols = st.columns(2 if not map_url else 3)
    with button_cols[0]:
        st.link_button("Directions", row["directions_url"], width="stretch")
    with button_cols[1]:
        st.link_button("Pickup map", row["open_in_maps_url"], width="stretch")
    if map_url:
        with button_cols[2]:
            st.link_button("Official map", map_url, width="stretch")

    with st.expander("More pickup notes"):
        st.write(f"**Parking:** {row['parking_info']}")
        st.write(f"**Best for:** {row['best_for']}")
        if clean_text(row.get("access_notes")):
            st.info(clean_text(row.get("access_notes")))
        if clean_text(row.get("google_query_note")):
            st.caption(clean_text(row.get("google_query_note")))


def main() -> None:
    pickups = cached_pickups()
    hotels = cached_hotels()
    return_routes = cached_return_routes()
    other_transportation = cached_other_transportation()
    api_key = get_google_maps_api_key()

    st.title("Duluth Race Shuttle Finder")
    st.caption("Choose where you are staying, pick a race/corral, and compare Google driving routes to the race-morning bus pickups.")

    if not api_key:
        st.warning(
            "Add `GOOGLE_MAPS_API_KEY` in Streamlit secrets to enable the main Google map, route line, and driving-distance ranking. "
            "Without a key, this app still creates Google Maps direction links.",
            icon="🔑",
        )

    control_col, map_col = st.columns([0.34, 0.66], gap="large")

    with control_col:
        st.subheader("Choose route")
        with st.form("route_settings_form"):
            start_type = st.radio(
                "Starting location",
                ["Choose a listed hotel/lodging", "Enter a custom address or place"],
                horizontal=False,
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

            race_name = st.selectbox("Race", list(RACE_CONFIG.keys()))
            race_key = str(RACE_CONFIG[race_name]["key"])
            corral = st.selectbox("Corral", RACE_CONFIG[race_name]["corrals"])
            show_hotels = st.checkbox("Show hotel pins", value=True)
            traffic_aware = st.checkbox(
                "Use traffic-aware estimates",
                value=False,
                help="Off keeps ranking closer to normal planning distance. On uses traffic-aware estimates where Google supports them.",
            )
            submitted = st.form_submit_button("Update map", type="primary", width="stretch")

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
                st.session_state.pop("selected_pickup_name", None)
                st.session_state["last_search"] = {
                    **origin,
                    "race_name": race_name,
                    "race_key": race_key,
                    "corral": corral,
                    "show_hotels": show_hotels,
                    "traffic_aware": traffic_aware,
                }

    search = st.session_state.get("last_search")
    display_race_name = search["race_name"] if search else race_name
    display_race_key = search["race_key"] if search else race_key
    display_corral = search["corral"] if search else corral
    display_show_hotels = bool(search.get("show_hotels", True)) if search else show_hotels
    race_pickups = available_pickups(pickups, display_race_key)

    ranked = make_unranked_pickups(
        race_pickups,
        display_race_key,
        display_corral,
        search["origin_query"] if search else "Duluth, MN",
    )
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

    with control_col:
        if not search:
            st.info("Pick a starting location and click **Update map**. The map will show all hotels and pickup spots until a route is selected.")
        elif not ranked.empty:
            st.markdown("#### Starting location")
            st.write(f"**{search['origin_label']}**")
            if clean_text(search.get("origin_area")):
                st.caption(clean_text(search.get("origin_area")))
            if clean_text(search.get("origin_address")):
                st.write(clean_text(search.get("origin_address")))
            st.link_button(
                "Open start in Google Maps",
                google_maps_search_url(search.get("origin_map_query") or search["origin_query"], search.get("origin_place_id", "")),
                width="stretch",
            )

            if show_distance and pd.notna(ranked.iloc[0].get("driving_miles")):
                st.success(
                    f"Closest by driving distance: **{ranked.iloc[0]['name']}** "
                    f"({format_miles(ranked.iloc[0]['driving_miles'])}, about {format_minutes(ranked.iloc[0]['drive_minutes'])}).",
                    icon="🚌",
                )
            elif not show_distance and not route_lookup_failed:
                st.info("Driving-distance ranking appears after the Google Maps key is configured.")

            selected_name = st.selectbox(
                "Pickup location",
                ranked["name"].tolist(),
                index=0,
                key="selected_pickup_name",
                help="Changing this redraws the route on the main map.",
            )
            selected_row = ranked.loc[ranked["name"] == selected_name].iloc[0]
            selected_pickup_id = clean_text(selected_row.get("id"))

            render_selected_pickup_summary(
                selected_row,
                search=search,
                race_name=display_race_name,
                corral=display_corral,
                show_distance=show_distance,
            )

            st.info(f"Bag note: {RACE_CONFIG[display_race_name]['bag_note']}")

    route_polyline, route_warning = selected_route_polyline(
        api_key=api_key,
        search=search,
        selected_row=selected_row,
    )

    with map_col:
        st.subheader("Map")
        st.caption(
            "Hotels and pickup spots are resolved by Google Maps from place names/addresses. "
            "When a pickup is selected, the purple line shows the Google driving route."
        )
        if api_key:
            overview_html = google_overview_map_html(
                api_key=api_key,
                pickups=race_pickups,
                hotels=hotels,
                show_hotels=display_show_hotels,
                selected_pickup_id=selected_pickup_id,
                selected_origin_id=search["origin_id"] if search else "",
                origin_query=search.get("origin_map_query") or search.get("origin_query") if search else "",
                origin_label=search["origin_label"] if search else "",
                route_polyline=route_polyline,
                height=690,
            )
            render_iframe(overview_html, height=730)
            if route_warning:
                st.warning(route_warning)
        else:
            st.info("The Google map appears after `GOOGLE_MAPS_API_KEY` is configured in Streamlit Secrets.")

    st.divider()
    st.subheader("All pickup options")
    if not search:
        st.caption("Timing overview. Choose a starting location to sort by Google driving distance.")
    else:
        st.caption("Sorted by Google driving distance when the API key is configured. DECC uses the stable official venue address for route ranking, with the official PDF showing the exact North Gate/Railroad Street loading area.")
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
