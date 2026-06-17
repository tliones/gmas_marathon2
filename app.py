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
    optional_float,
    row_lat_lng,
    row_location_query,
    row_place_id,
    row_routing_query,
    row_visual_route_query,
)

st.set_page_config(
    page_title="Duluth Race Shuttle Finder",
    page_icon="🚌",
    layout="wide",
)

# Bump this when route-ranking inputs change so Streamlit Cloud does not reuse
# old Google route matrix results from earlier app versions.
ROUTE_CACHE_VERSION = "2026-06-17-py314-dataclass-fix-v10"
TRAFFIC_AWARE_ROUTING = True


def inject_layout_css() -> None:
    """Small layout tweaks for a map-first, low-scroll app."""
    st.markdown(
        """
        <style>
        .block-container {
            padding-top: 0.75rem;
            padding-bottom: 0.75rem;
            max-width: 1600px;
        }
        h1 {
            margin-bottom: 0.15rem;
        }
        div[data-testid="stVerticalBlock"] {
            gap: 0.55rem;
        }
        div[data-testid="stMetric"] {
            padding: 0.35rem 0.45rem;
            border: 1px solid rgba(49, 51, 63, 0.15);
            border-radius: 0.75rem;
        }
        div[data-testid="stMetricValue"] {
            font-size: 1.2rem;
        }
        .small-muted {
            color: rgba(49, 51, 63, 0.68);
            font-size: 0.92rem;
            line-height: 1.35;
        }
        </style>
        """,
        unsafe_allow_html=True,
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
    cache_version: str,
    origin_query: str,
    origin_place_id: str,
    origin_latitude: str,
    origin_longitude: str,
    destinations_tuple: tuple[tuple[str, str, str, str, str], ...],
    traffic_aware: bool,
) -> list[dict[str, Any]]:
    """Cached wrapper around the Google Routes API route matrix call."""
    _ = cache_version  # Included only to invalidate stale route caches after patches.
    destinations = [
        {
            "id": item[0],
            "query": item[1],
            "place_id": item[2],
            "latitude": item[3],
            "longitude": item[4],
        }
        for item in destinations_tuple
    ]
    results = compute_driving_matrix(
        api_key=api_key,
        origin_query=origin_query,
        origin_place_id=origin_place_id,
        origin_latitude=origin_latitude,
        origin_longitude=origin_longitude,
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


@st.cache_data(ttl=60 * 60, show_spinner="Drawing selected route...")
def cached_selected_route_polyline(
    api_key: str,
    cache_version: str,
    origin_query: str,
    origin_place_id: str,
    destination_query: str,
    destination_place_id: str,
    traffic_aware: bool,
) -> dict[str, Any]:
    """Cached wrapper for the selected Google Routes API polyline.

    For the visual line, use query/place input only. Coordinates are excellent
    for ranking, but for broad venues such as DECC they can snap to the wrong
    access road and make the overview route look strange.
    """
    _ = cache_version
    result = compute_route_polyline(
        api_key=api_key,
        origin_query=origin_query,
        origin_place_id=origin_place_id,
        destination_query=destination_query,
        destination_place_id=destination_place_id,
        origin_latitude="",
        origin_longitude="",
        destination_latitude="",
        destination_longitude="",
        traffic_aware=traffic_aware,
    )
    return {
        "encoded_polyline": result.encoded_polyline,
        "distance_miles": result.distance_miles,
        "duration_minutes": result.duration_minutes,
        "error": result.error,
    }


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


def stringify_coord(value: Any) -> str:
    coord = optional_float(value)
    if coord is None:
        return ""
    return f"{coord:.8f}"


def destination_tuple(pickups: pd.DataFrame) -> tuple[tuple[str, str, str, str, str], ...]:
    """Routes API destinations: pickup ID, routing query, place ID, latitude, longitude."""
    destinations: list[tuple[str, str, str, str, str]] = []
    for _, row in pickups.iterrows():
        lat, lng = row_lat_lng(row)
        destinations.append(
            (
                clean_text(row.get("id")),
                row_routing_query(row),
                row_place_id(row),
                stringify_coord(lat),
                stringify_coord(lng),
            )
        )
    return tuple(destinations)


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
    search: dict[str, Any],
    api_key: str,
) -> pd.DataFrame:
    routes = cached_route_matrix(
        api_key,
        ROUTE_CACHE_VERSION,
        search["origin_query"],
        search.get("origin_place_id", ""),
        stringify_coord(search.get("origin_latitude")),
        stringify_coord(search.get("origin_longitude")),
        destination_tuple(pickups),
        TRAFFIC_AWARE_ROUTING,
    )
    route_df = pd.DataFrame(routes)
    ranked = pickups.merge(route_df, on="id", how="left")
    ranked = enrich_pickups_for_display(ranked, race_key, corral, search["origin_query"], sort_by_route=True)
    return apply_origin_guardrails(ranked, search)


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
    display["destination_visual_route_query"] = display.apply(row_visual_route_query, axis=1)
    display["destination_map_query"] = display.apply(row_location_query, axis=1)
    display["destination_place_id"] = display.apply(row_place_id, axis=1)
    display["directions_url"] = display.apply(
        lambda row: google_maps_directions_url(
            origin_query=origin_query,
            destination_query=row["destination_visual_route_query"],
            destination_place_id="" if clean_text(row.get("id")) == "decc_bus" else row["destination_place_id"],
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


def apply_origin_guardrails(ranked: pd.DataFrame, search: dict[str, Any]) -> pd.DataFrame:
    """Keep DECC from being penalized by an obviously bad Google result for Canal Park.

    Google route ranking now uses coordinates for the pickup destinations, so this
    should rarely trigger. It is here because earlier address-only searches could
    return a blank or implausibly long DECC result even though DECC is the closest
    pickup for Canal Park / downtown hotels.
    """
    preferred = clean_text(search.get("preferred_pickup_id"))
    if preferred != "decc_bus" or ranked.empty or "id" not in ranked.columns:
        return ranked

    ids = ranked["id"].tolist()
    if "decc_bus" not in ids or "kirby_student_center" not in ids:
        return ranked

    decc_idx = ranked.index[ranked["id"] == "decc_bus"][0]
    kirby_idx = ranked.index[ranked["id"] == "kirby_student_center"][0]
    decc_miles = pd.to_numeric(ranked.loc[decc_idx, "driving_miles"], errors="coerce")
    kirby_miles = pd.to_numeric(ranked.loc[kirby_idx, "driving_miles"], errors="coerce")

    if pd.isna(decc_miles) or (not pd.isna(kirby_miles) and decc_miles > kirby_miles):
        adjusted = ranked.copy()
        adjusted["area_guardrail_sort"] = adjusted["id"].apply(lambda value: -1 if value == "decc_bus" else 0)
        adjusted = adjusted.sort_values(["area_guardrail_sort", "route_sort"], na_position="last")
        return adjusted.drop(columns=["area_guardrail_sort"]).reset_index(drop=True)

    return ranked.reset_index(drop=True)


def render_iframe(src: str, height: int = 620) -> None:
    """Render URL or HTML content in Streamlit's built-in iframe element."""
    st.iframe(src, height=height, width="stretch")


def render_rank_table(ranked: pd.DataFrame, *, show_distance: bool) -> None:
    display = ranked.copy()
    display["Pickup"] = display["name"]
    display["Driving distance"] = (
        display.get("driving_miles", pd.Series(dtype=float)).apply(format_miles)
        if show_distance
        else "Not calculated"
    )
    display["Estimated drive"] = (
        display.get("drive_minutes", pd.Series(dtype=float)).apply(format_minutes)
        if show_distance
        else "Not calculated"
    )
    display["Loading window"] = display["recommended_window"]
    display["Good for"] = display["best_for"]
    display["Directions"] = display["directions_url"]
    display["Official map"] = display["loading_site_map_url"]

    st.dataframe(
        display[
            [
                "Pickup",
                "Driving distance",
                "Estimated drive",
                "Loading window",
                "Good for",
                "Directions",
                "Official map",
            ]
        ],
        hide_index=True,
        width="stretch",
        column_config={
            "Directions": st.column_config.LinkColumn("Directions", display_text="Open route"),
            "Official map": st.column_config.LinkColumn("Official map", display_text="Official map"),
        },
    )


def origin_from_form(
    *,
    start_type: str,
    selected_hotel_label: str,
    custom_origin: str,
    hotels: pd.DataFrame,
) -> dict[str, Any]:
    """Return normalized origin information from the controls."""
    if start_type == "Choose a listed hotel/lodging" and selected_hotel_label != "Select a hotel...":
        hotel_row = hotels.loc[hotels["display_name"] == selected_hotel_label].iloc[0]
        lat, lng = row_lat_lng(hotel_row)
        area = clean_text(hotel_row.get("area"))
        preferred_pickup_id = "decc_bus" if ("canal park" in area.lower() or "downtown" in area.lower()) else ""
        return {
            "origin_query": row_routing_query(hotel_row),
            "origin_map_query": row_location_query(hotel_row),
            "origin_place_id": row_place_id(hotel_row),
            "origin_latitude": lat,
            "origin_longitude": lng,
            "origin_label": clean_text(hotel_row.get("name")),
            "origin_id": clean_text(hotel_row.get("id")),
            "origin_address": clean_text(hotel_row.get("full_address")),
            "origin_area": area,
            "origin_kind": "hotel",
            "preferred_pickup_id": preferred_pickup_id,
        }

    custom_origin = clean_text(custom_origin)
    if custom_origin:
        return {
            "origin_query": custom_origin,
            "origin_map_query": custom_origin,
            "origin_place_id": "",
            "origin_latitude": "",
            "origin_longitude": "",
            "origin_label": custom_origin,
            "origin_id": "",
            "origin_address": custom_origin,
            "origin_area": "Custom address or place",
            "origin_kind": "custom",
            "preferred_pickup_id": "",
        }

    return {
        "origin_query": "",
        "origin_map_query": "",
        "origin_place_id": "",
        "origin_latitude": "",
        "origin_longitude": "",
        "origin_label": "",
        "origin_id": "",
        "origin_address": "",
        "origin_area": "",
        "origin_kind": "",
        "preferred_pickup_id": "",
    }


def render_selected_pickup_summary(
    row: pd.Series,
    *,
    race_name: str,
    corral: str,
    show_distance: bool,
) -> None:
    st.markdown("#### Pickup")
    st.write(f"**{row['name']}**")
    if show_distance:
        metric_cols = st.columns(2)
        metric_cols[0].metric("Drive", format_miles(row.get("driving_miles")))
        metric_cols[1].metric("Time", format_minutes(row.get("drive_minutes")))
    st.write(f"**Window:** {clean_text(row.get('recommended_window')) or 'Check official guide'}")
    st.caption(f"{race_name} · Corral {corral}")
    st.write(row["full_address"])

    button_cols = st.columns(2)
    with button_cols[0]:
        st.link_button("Directions", row["directions_url"], width="stretch")
    with button_cols[1]:
        st.link_button("Pickup map", row["open_in_maps_url"], width="stretch")

    map_url = clean_text(row.get("loading_site_map_url"))
    if map_url:
        st.link_button("Official loading-site PDF", map_url, width="stretch")

    with st.expander("Pickup notes"):
        st.write(f"**Loading:** {row['loading_instructions']}")
        st.write(f"**Parking:** {row['parking_info']}")
        st.write(f"**Best for:** {row['best_for']}")
        if clean_text(row.get("access_notes")):
            st.info(clean_text(row.get("access_notes")))


def pickup_option_label(row: pd.Series, *, show_distance: bool) -> str:
    """Compact selectbox label for pickup options."""
    name = clean_text(row.get("name"))
    if not show_distance:
        return name
    miles = format_miles(row.get("driving_miles"))
    minutes = format_minutes(row.get("drive_minutes"))
    if miles == "—" and minutes == "—":
        return name
    return f"{name} · {miles} · {minutes}"


def render_compact_pickup_card(
    row: pd.Series,
    *,
    race_name: str,
    corral: str,
    show_distance: bool,
) -> None:
    """Compact selected-pickup display for the main Plan tab."""
    if show_distance:
        metric_cols = st.columns(2)
        metric_cols[0].metric("Drive", format_miles(row.get("driving_miles")))
        metric_cols[1].metric("Est. time", format_minutes(row.get("drive_minutes")))

    window = clean_text(row.get("recommended_window")) or "Check official guide"
    st.markdown(f"**Loading window:** {window}")
    st.caption(f"{race_name} · Corral {corral} · {clean_text(row.get('full_address'))}")

    button_cols = st.columns(2)
    with button_cols[0]:
        st.link_button("Directions", row["directions_url"], width="stretch")
    with button_cols[1]:
        st.link_button("Pickup map", row["open_in_maps_url"], width="stretch")

    with st.expander("Loading, parking, and best-for notes"):
        st.write(f"**Loading:** {row['loading_instructions']}")
        st.write(f"**Parking:** {row['parking_info']}")
        st.write(f"**Best for:** {row['best_for']}")
        access_notes = clean_text(row.get("access_notes"))
        if access_notes:
            st.info(access_notes)
        map_url = clean_text(row.get("loading_site_map_url"))
        if map_url:
            st.link_button("Official loading-site PDF", map_url, width="stretch")


def unique_clean_values(values: pd.Series) -> list[str]:
    """Return non-empty unique values while preserving order."""
    seen: set[str] = set()
    cleaned: list[str] = []
    for value in values:
        item = clean_text(value)
        if item and item not in seen:
            cleaned.append(item)
            seen.add(item)
    return cleaned


def route_notes(route_df: pd.DataFrame) -> list[str]:
    """Collect route-level notes and stop-level notes for display."""
    notes: list[str] = []
    notes.extend(unique_clean_values(route_df.get("route_note", pd.Series(dtype=str))))
    notes.extend(unique_clean_values(route_df.get("notes", pd.Series(dtype=str))))
    return notes


def render_return_route_detail(route_df: pd.DataFrame) -> None:
    """Clean, grouped view for one return-shuttle route."""
    if route_df.empty:
        st.info("No return-route details are available yet.")
        return

    route_name = clean_text(route_df.iloc[0].get("route_name"))
    st.markdown(f"#### {route_name}")

    stop_type = route_df["stop_type"].fillna("").astype(str).str.lower()
    pickup_stops = unique_clean_values(
        route_df.loc[stop_type == "pickup location", "stop_name"]
    )
    hotel_stops = unique_clean_values(
        route_df.loc[stop_type == "hotel", "stop_name"]
    )
    other_stops = unique_clean_values(
        route_df.loc[~stop_type.isin(["pickup location", "hotel"]), "stop_name"]
    )

    stop_cols = st.columns(2, gap="large")
    with stop_cols[0]:
        st.markdown("**Returns to pickup/loading location**")
        if pickup_stops:
            for stop in pickup_stops:
                st.markdown(f"- {stop}")
        else:
            st.caption("No pickup-location stop listed.")

    with stop_cols[1]:
        st.markdown("**Hotel / lodging stops**")
        if hotel_stops:
            for stop in hotel_stops:
                st.markdown(f"- {stop}")
        else:
            st.caption("No hotel stops listed for this route.")

    if other_stops:
        st.markdown("**Other stops**")
        for stop in other_stops:
            st.markdown(f"- {stop}")

    notes = route_notes(route_df)
    if notes:
        for note in notes:
            st.info(note, icon="ℹ️")


def render_return_routes_overview(return_routes: pd.DataFrame) -> None:
    """Small all-routes table that is readable instead of raw CSV output."""
    if return_routes.empty:
        return

    rows: list[dict[str, str]] = []
    for route_name, route_df in return_routes.groupby("route_name", sort=False):
        stops = unique_clean_values(route_df["stop_name"])
        notes = route_notes(route_df)
        rows.append(
            {
                "Return route": clean_text(route_name),
                "Stops": ", ".join(stops),
                "Notes": " ".join(notes),
            }
        )

    st.dataframe(
        pd.DataFrame(rows),
        hide_index=True,
        width="stretch",
        column_config={
            "Return route": st.column_config.TextColumn("Return route", width="medium"),
            "Stops": st.column_config.TextColumn("Stops", width="large"),
            "Notes": st.column_config.TextColumn("Notes", width="medium"),
        },
    )


def render_transportation_tips(other_transportation: list[dict[str, Any]]) -> None:
    """Render non-shuttle transportation notes as simple cards, not raw lists."""
    if not other_transportation:
        return

    st.markdown("### Other race-weekend transportation")
    tip_cols = st.columns(2, gap="large")
    for idx, item in enumerate(other_transportation):
        with tip_cols[idx % 2]:
            with st.container(border=True):
                title = clean_text(item.get("title"))
                if title:
                    st.markdown(f"**{title}**")

                details = item.get("details") or []
                if isinstance(details, str):
                    details = [details]
                for detail in details:
                    detail = clean_text(detail)
                    if detail:
                        st.markdown(f"- {detail}")

                schedule = item.get("schedule") or []
                if isinstance(schedule, str):
                    schedule = [schedule]
                for schedule_item in schedule:
                    schedule_item = clean_text(schedule_item)
                    if schedule_item:
                        st.markdown(f"- {schedule_item}")


def main() -> None:
    inject_layout_css()

    pickups = cached_pickups()
    hotels = cached_hotels()
    return_routes = cached_return_routes()
    other_transportation = cached_other_transportation()
    api_key = get_google_maps_api_key()

    st.title("Duluth Race Shuttle Finder")
    st.caption("Map-first guide for choosing a Grandma’s Marathon or Garry Bjorklund Half Marathon bus pickup.")

    if not api_key:
        st.warning(
            "Add `GOOGLE_MAPS_API_KEY` in Streamlit secrets to enable the Google map and driving-distance ranking. "
            "Without a key, this app still creates Google Maps direction links.",
            icon="🔑",
        )

    plan_tab, options_tab, return_tab = st.tabs(
        ["Plan route", "Compare pickups", "Return shuttles + tips"]
    )

    # Defaults are set inside the Plan tab controls, but the Compare tab needs
    # access to the latest ranked result as well.
    ranked: pd.DataFrame | None = None
    show_distance = False
    route_lookup_failed = False
    selected_row: pd.Series | None = None
    selected_pickup_id = ""
    search = st.session_state.get("last_search")

    with plan_tab:
        control_col, map_col = st.columns([0.32, 0.68], gap="medium")

        with control_col:
            st.markdown("### Plan")
            st.markdown("**1. Start**")
            start_type = st.radio(
                "Starting location",
                ["Hotel/lodging", "Custom"],
                horizontal=True,
                label_visibility="collapsed",
                key="start_type",
            )

            selected_hotel_label = ""
            custom_origin = ""
            if start_type == "Hotel/lodging":
                hotel_labels = ["Select a hotel..."] + hotels["display_name"].tolist()
                selected_hotel_label = st.selectbox(
                    "Hotel or lodging",
                    hotel_labels,
                    label_visibility="collapsed",
                    key="selected_hotel_label",
                )
            else:
                custom_origin = st.text_input(
                    "Address, hotel, landmark, or neighborhood",
                    placeholder="Example: Canal Park Lodge, Duluth MN",
                    label_visibility="collapsed",
                    key="custom_origin",
                )

            st.markdown("**2. Race**")
            race_cols = st.columns(2)
            race_options = list(RACE_CONFIG.keys())
            with race_cols[0]:
                race_name = st.selectbox("Race", race_options, key="race_name")
            race_key = str(RACE_CONFIG[race_name]["key"])
            corral_options = list(RACE_CONFIG[race_name]["corrals"])

            # Streamlit preserves widget state across reruns. If the user changes
            # from the half marathon to the full marathon, replace the old numeric
            # corral with the first valid full-marathon corral before rendering the
            # corral selectbox. This makes the A/B/C options appear immediately.
            if st.session_state.get("corral") not in corral_options:
                st.session_state["corral"] = corral_options[0]
            with race_cols[1]:
                corral = st.selectbox("Corral", corral_options, key="corral")

            show_hotels = st.checkbox(
                "Show hotel pins",
                value=True,
                key="show_hotels",
            )

            origin = origin_from_form(
                start_type="Choose a listed hotel/lodging" if start_type == "Hotel/lodging" else "Enter a custom address or place",
                selected_hotel_label=selected_hotel_label,
                custom_origin=custom_origin,
                hotels=hotels,
            )

            if origin["origin_query"]:
                search_signature = (
                    origin.get("origin_query", ""),
                    origin.get("origin_place_id", ""),
                    origin.get("origin_label", ""),
                    race_key,
                )
                if st.session_state.get("search_signature") != search_signature:
                    st.session_state.pop("pickup_selector_id", None)
                    st.session_state.pop("pickup_selector", None)
                    st.session_state["search_signature"] = search_signature

                st.session_state["last_search"] = {
                    **origin,
                    "race_name": race_name,
                    "race_key": race_key,
                    "corral": corral,
                    "show_hotels": show_hotels,
                    "traffic_aware": TRAFFIC_AWARE_ROUTING,
                }
                search = st.session_state.get("last_search")
            else:
                st.session_state.pop("last_search", None)
                st.session_state.pop("search_signature", None)
                st.session_state.pop("pickup_selector_id", None)
                st.session_state.pop("pickup_selector", None)
                search = None

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

        if search and api_key:
            try:
                ranked = make_ranked_pickups(
                    race_pickups,
                    display_race_key,
                    display_corral,
                    search,
                    api_key,
                )
                show_distance = True
            except Exception as exc:
                route_lookup_failed = True
                st.error(
                    "Google driving-distance lookup failed, so the app is showing Google route links without ranking. "
                    f"Details: {exc}"
                )

        with control_col:
            if not search:
                st.info("Choose a hotel or enter a custom starting point. Pickup options and the map update automatically.")
            elif not ranked.empty:
                st.markdown("### Pickup")
                start_line = f"**From:** {search['origin_label']}"
                st.markdown(start_line)
                if clean_text(search.get("origin_area")):
                    st.caption(clean_text(search.get("origin_area")))

                if show_distance and pd.notna(ranked.iloc[0].get("driving_miles")):
                    st.success(
                        f"Recommended: **{ranked.iloc[0]['name']}** · "
                        f"{format_miles(ranked.iloc[0]['driving_miles'])} · "
                        f"{format_minutes(ranked.iloc[0]['drive_minutes'])}",
                        icon="🚌",
                    )
                elif not show_distance and not route_lookup_failed:
                    st.info("Driving-distance ranking appears after the Google Maps key is configured.")

                pickup_ids = ranked["id"].tolist()
                labels_by_id = {
                    clean_text(row.get("id")): pickup_option_label(row, show_distance=show_distance)
                    for _, row in ranked.iterrows()
                }
                current_selected = st.session_state.get("pickup_selector_id")
                default_index = pickup_ids.index(current_selected) if current_selected in pickup_ids else 0
                selected_pickup_id = st.selectbox(
                    "Pickup location",
                    pickup_ids,
                    index=default_index,
                    key="pickup_selector_id",
                    format_func=lambda pickup_id: labels_by_id.get(pickup_id, pickup_id),
                    help="Changing this redraws the purple route on the map.",
                )
                selected_row = ranked.loc[ranked["id"] == selected_pickup_id].iloc[0]
                render_compact_pickup_card(
                    selected_row,
                    race_name=display_race_name,
                    corral=display_corral,
                    show_distance=show_distance,
                )

        with map_col:
            if api_key:
                route_origin_query = ""
                route_origin_place_id = ""
                route_origin_latitude = ""
                route_origin_longitude = ""
                route_destination_query = ""
                route_destination_place_id = ""
                route_destination_latitude = ""
                route_destination_longitude = ""
                route_waypoints: list[dict[str, Any]] = []
                route_polyline = ""

                if search and selected_row is not None:
                    route_origin_query = search.get("origin_query") or search.get("origin_map_query", "")
                    route_origin_place_id = search.get("origin_place_id", "")
                    route_destination_query = clean_text(selected_row.get("destination_visual_route_query")) or clean_text(selected_row.get("destination_query"))
                    route_destination_place_id = "" if clean_text(selected_row.get("id")) == "decc_bus" else clean_text(selected_row.get("destination_place_id"))
                    try:
                        selected_route = cached_selected_route_polyline(
                            api_key,
                            ROUTE_CACHE_VERSION,
                            route_origin_query,
                            route_origin_place_id,
                            route_destination_query,
                            route_destination_place_id,
                            TRAFFIC_AWARE_ROUTING,
                        )
                        route_polyline = clean_text(selected_route.get("encoded_polyline"))
                        if not route_polyline and clean_text(selected_route.get("error")):
                            st.warning(f"Selected route could not be drawn: {selected_route['error']}")
                    except Exception as exc:
                        st.warning(f"Selected route could not be drawn on the map. The Directions button still works. Details: {exc}")

                overview_html = google_overview_map_html(
                    api_key=api_key,
                    pickups=race_pickups,
                    hotels=hotels,
                    show_hotels=display_show_hotels,
                    selected_pickup_id=selected_pickup_id,
                    selected_origin_id=search["origin_id"] if search else "",
                    origin_query=search.get("origin_map_query") or search.get("origin_query") if search else "",
                    origin_label=search["origin_label"] if search else "",
                    origin_latitude=search.get("origin_latitude", "") if search else "",
                    origin_longitude=search.get("origin_longitude", "") if search else "",
                    route_origin_query=route_origin_query,
                    route_origin_place_id=route_origin_place_id,
                    route_origin_latitude=route_origin_latitude,
                    route_origin_longitude=route_origin_longitude,
                    route_destination_query=route_destination_query,
                    route_destination_place_id=route_destination_place_id,
                    route_destination_latitude=route_destination_latitude,
                    route_destination_longitude=route_destination_longitude,
                    route_waypoints=route_waypoints,
                    route_polyline=route_polyline,
                    height=590,
                )
                render_iframe(overview_html, height=625)
                st.caption("Purple line = selected driving route. P = pickup, H = hotel/lodging, S = start.")
            else:
                st.info("The Google map appears after `GOOGLE_MAPS_API_KEY` is configured in Streamlit Secrets.")

    with options_tab:
        st.subheader("Compare all pickup options")
        if search:
            st.caption(
                f"Sorted from **{search['origin_label']}** by traffic-aware Google driving distance when available."
            )
        else:
            st.caption("Choose a starting point in the Plan route tab to sort by Google driving distance.")

        if ranked is None:
            current_race_name = list(RACE_CONFIG.keys())[0]
            current_race_key = str(RACE_CONFIG[current_race_name]["key"])
            current_corral = RACE_CONFIG[current_race_name]["corrals"][0]
            ranked = make_unranked_pickups(
                available_pickups(pickups, current_race_key),
                current_race_key,
                current_corral,
                "Duluth, MN",
            )
        render_rank_table(ranked, show_distance=show_distance)

        if selected_row is not None:
            st.markdown("#### Selected pickup details")
            render_selected_pickup_summary(
                selected_row,
                race_name=display_race_name,
                corral=display_corral,
                show_distance=show_distance,
            )

    with return_tab:
        st.subheader("Return shuttles + race-weekend tips")
        st.markdown(
            "Use this tab after the race to see where the free return shuttles go, plus a few race-weekend transportation notes."
        )

        summary_cols = st.columns(3)
        summary_cols[0].metric("Return buses run", "8:00 a.m.–3:30 p.m.")
        summary_cols[1].metric("Depart from", "DECC north gate")
        summary_cols[2].metric("Two Harbors", "Hourly returns")

        st.info(
            "Return shuttles depart from the DECC on Railroad Street near the north gate. "
            "All routes except Two Harbors run continuously and depart when full.",
            icon="🚌",
        )

        if not return_routes.empty:
            route_names = unique_clean_values(return_routes["route_name"])
            lookup_col, detail_col = st.columns([0.30, 0.70], gap="large")

            with lookup_col:
                selected_return_route = st.selectbox(
                    "Where are you returning?",
                    route_names,
                    key="selected_return_route",
                    help="Choose a return-shuttle route to see its pickup-location and hotel stops.",
                )

                st.markdown("**Quick reminders**")
                st.markdown("- Return buses are free for participants and spectators.")
                st.markdown("- Two Harbors buses depart on the hour.")
                st.markdown("- Racecourse-area stops may be served as near as possible while the event is ongoing.")

            with detail_col:
                selected_route_df = return_routes.loc[return_routes["route_name"] == selected_return_route]
                render_return_route_detail(selected_route_df)

            with st.expander("Show all return routes", expanded=False):
                render_return_routes_overview(return_routes)

        st.markdown("---")
        render_transportation_tips(other_transportation)

        st.caption(
            "Race-day logistics can change. Verify final loading windows, road closures, and shuttle details with the official race guide before publishing."
        )


if __name__ == "__main__":
    main()
