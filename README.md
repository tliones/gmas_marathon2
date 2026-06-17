# Duluth Race Shuttle Finder

A streamlined Streamlit app that helps out-of-town race participants choose a race-morning bus pickup from a hotel, lodging spot, or custom address.

The app is centered around one main Google map: pickup and hotel pins are shown together, and the selected pickup route is drawn directly on that same map.

## What it does

- Shows a main Google map with bus pickup spots and hotel/lodging locations.
- Lets a visitor choose a listed hotel/lodging spot or enter a custom address/place.
- Lets a visitor choose their race and corral.
- Ranks bus pickup spots by traffic-aware Google driving distance when `GOOGLE_MAPS_API_KEY` is configured.
- Draws the selected traffic-aware Google driving route directly on the main map.
- Shows the pickup selector and route details to the left of the map.
- Keeps the main Plan route view compact so most users do not need to scroll.
- Moves the full pickup-options table into a separate **Compare pickups** tab.
- Keeps return shuttles and race-weekend transportation notes in a cleaner lookup-style tab.
- Keeps official loading-site PDF links next to each pickup.

## Latest changes

This version keeps the cleaner tabbed design, keeps the Plan route controls live-updating, and cleans up the Return shuttles + tips tab so it no longer displays raw CSV/JSON-style output.

1. **Plan route:** compact controls on the left, large Google map on the right, and the selected driving route drawn directly on the map. Hotel/custom start controls, race, corral, and hotel-pin visibility now update without a submit button.
2. **Compare pickups:** the full pickup-options table, sorted by traffic-aware Google driving distance after a starting location is chosen. Race and corral changes update the table immediately.
3. **Return shuttles + tips:** a return-route selector, grouped stop lists, a compact all-routes overview, and card-style bike valet / DTA / trolley / skywalk / Lakewalk notes.

The main Plan route tab intentionally removes the table from below the map so the core workflow fits better on one screen. There is no separate “Find pickup options” button; once a valid hotel or custom location is present, the app recalculates automatically.

Traffic-aware routing is always on. The app uses `TRAFFIC_AWARE_OPTIMAL` for Google Routes API calls so the chosen route more closely matches what users see in Google Maps.

It also fixes the DECC visual-route issue differently from the previous patch:

- **The purple route line no longer uses the browser-side `DirectionsRenderer`.** The app now asks Google Routes API for the selected route geometry on the Streamlit server and draws the returned encoded polyline on the main map. This keeps the all-pins overview map, but avoids the odd DECC loop that the browser-side renderer was producing.
- **DECC visual routing uses an address-only target:** `350 Harbor Dr, Duluth, MN 55802`. The marker can still show the DECC venue, and distance ranking can still use practical routing anchors, but the route line targets the simple Harbor Drive address that behaves more like a normal Google Maps directions search.
- **No DECC via-waypoint nudge is used anymore.** The previous South Lake Avenue / Harbor Drive via point was removed because it could still inherit the same venue-snap issue.
- **DECC is protected from bad address-search ranking.** Driving-distance ranking still sends pickup destination route anchors to Google Route Matrix instead of relying only on a text query. This keeps DECC from being missed or ranked behind Kirby for Canal Park / downtown hotels because of an ambiguous address or venue-name match.

For visible markers, the map still tries Google-resolved locations first:

1. `google_place_id`, when available
2. Google Places text search using `google_maps_query`
3. Google Geocoder fallback
4. CSV latitude/longitude as a final fallback

## Project structure

```text
grandmas_bus_finder/
├── app.py
├── requirements.txt
├── README.md
├── data/
│   ├── pickup_locations.csv
│   ├── hotels.csv
│   ├── return_shuttle_routes.csv
│   └── other_transportation.json
├── scripts/
│   └── resolve_google_place_ids.py
└── src/
    ├── data.py
    └── google_maps.py
```

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

Without a Google Maps Platform key, the app still opens Google Maps direction links. The main Google map, driving-distance ranking, and route line require a key.

## Google Maps setup

Create a Google Maps Platform API key and enable these APIs for the project:

- **Routes API** — used for traffic-aware Route Matrix driving-distance ranking and selected-route geometry.
- **Maps JavaScript API** — used for the main all-location map and for drawing the selected route polyline.
- **Places API / Places Library** — used by the map to resolve hotel and venue names to Google place locations when a place ID is not stored.

For local development, copy the example secrets file and add your real key:

```bash
cp .streamlit/secrets.example.toml .streamlit/secrets.toml
```

Then edit `.streamlit/secrets.toml`:

```toml
GOOGLE_MAPS_API_KEY = "paste-your-google-maps-platform-key-here"
```

Do not commit `.streamlit/secrets.toml`. The `.gitignore` file already excludes it.

For Streamlit Community Cloud, add the same key in the app's Secrets settings:

```toml
GOOGLE_MAPS_API_KEY = "paste-your-google-maps-platform-key-here"
```

## Map and routing accuracy

The app uses three related but separate ideas of location:

- **Visible marker location:** resolved in the browser by Google Maps using `google_place_id`, `google_maps_query`, or the geocoder. CSV coordinates are the final fallback.
- **Driving-distance ranking location:** sent to Google Route Matrix using traffic-aware routing. For pickup destinations, the app prefers `routing_latitude` / `routing_longitude`, then falls back to `latitude` / `longitude`, then text. For listed hotels, it also sends hotel coordinates when available to avoid brand/name ambiguity.
- **Selected route line:** requested from Google Routes API as traffic-aware encoded route geometry, then decoded and drawn on the main Google map. The route line uses `visual_route_query` when present; for DECC this is the simple Harbor Drive address.

This means large venues can keep a readable search query for map display while using a practical vehicle-access point for distance calculations.

## Updating pickup spots

Edit `data/pickup_locations.csv`.

Important columns:

- `id`: stable machine-readable ID.
- `name`, `address`, `city`, `state`, `zip`: displayed to users.
- `google_maps_query`: Google map marker/search query.
- `routing_query`: Google routing query used for Google Maps URLs and ranking text fallback.
- `visual_route_query`: optional address/query used for the selected purple route line. For DECC this intentionally uses the address-only Harbor Drive target.
- `latitude`, `longitude`: general marker fallback coordinates.
- `routing_latitude`, `routing_longitude`: preferred coordinates for driving-distance ranking. For large venues, these should be near a practical vehicle-access point rather than the geometric center of the complex.
- `routing_anchor_note`: explains why a routing anchor was chosen.
- `google_place_id`: optional exact Google place ID. Leave blank until verified.
- `google_query_note`: note explaining why the query was chosen.
- `has_half_bus`, `has_full_bus`: controls which race sees the pickup.
- `half_corral_1`, `half_corral_2`, `half_corral_3`, `full_corral_a`, `full_corral_b`, `full_corral_c`: recommended loading windows.
- `loading_instructions`, `parking_info`, `best_for`, `access_notes`: displayed in pickup details.
- `loading_site_map_url`: official loading-zone PDF link.

For large venues, keep `routing_query` stable and boring, tune `routing_latitude` / `routing_longitude` to the practical driving endpoint, and use `visual_route_query` when the visible route line should target a simpler address. Use the loading instructions and official PDF to explain the exact race-morning loading zone.

## Updating hotels/lodging

Edit `data/hotels.csv`.

Important columns:

- `name`, `address`, `city`, `state`, `zip`: displayed to users.
- `google_maps_query`: Google map marker/search query. Usually hotel name plus address.
- `routing_query`: Google routing query. Usually the same as `google_maps_query`, but can be tuned separately.
- `latitude`, `longitude`: used by Google Route Matrix for listed-hotel driving-distance ranking when present.
- `google_place_id`: optional exact Google place ID. This is the best way to avoid hotel pin drift.
- `area`, `category`, `return_shuttle_group`, `notes`: displayed/context fields.

Hotel markers are shown on the Plan route map by default. Users can turn them off with the `Show hotel pins` checkbox when they want a less crowded pickup-only view.

## Optional: resolve Google place IDs

After adding `GOOGLE_MAPS_API_KEY`, you can ask Google to resolve place IDs for the pickup or hotel CSVs:

```bash
export GOOGLE_MAPS_API_KEY="your-key"
python scripts/resolve_google_place_ids.py --file data/pickup_locations.csv
python scripts/resolve_google_place_ids.py --file data/hotels.csv
```

Review every resolved row before publishing. The script marks rows as `resolved_needs_review` because the first Google result may not always be the exact venue, driveway, or loading side you want.

To refresh existing IDs:

```bash
python scripts/resolve_google_place_ids.py --file data/hotels.csv --overwrite
```

## Streamlit version note

This project requires **Streamlit 1.58 or newer** because it uses Streamlit's built-in `st.iframe()` API instead of the deprecated `st.components.v1.html()` / `st.components.v1.iframe()` helpers.

This patch also avoids `@dataclass` in `src/google_maps.py`. Some Streamlit Cloud hot-reload builds using Python 3.14 raised an import-time dataclasses error before the app UI loaded. The small route-result containers are now plain Python classes, with no change to the route calculations or map behavior.

## Deployment notes

- Keep the GitHub repo public or private as needed, but never commit the real Google Maps key.
- On Streamlit Community Cloud, store `GOOGLE_MAPS_API_KEY` in Secrets.
- Apply API key restrictions in Google Cloud, such as HTTP referrer restrictions for browser APIs and API restrictions to the specific Google Maps APIs used here.
- Review Google Maps Platform billing/quotas before public launch.
- If you still see old distance rankings after deploying, restart the Streamlit app or clear cached data. This version includes a cache-version bump to avoid reusing earlier DECC route results, earlier traffic-unaware route results, or old live-control state.

## Important race-day disclaimer

Race-day transportation details, road closures, and loading zones can change. Before sharing the app publicly, verify all pickup instructions, loading windows, return shuttle stops, official loading-site PDF links, and road closure notes against the official race guide.
