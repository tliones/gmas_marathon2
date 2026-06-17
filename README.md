# Duluth Race Shuttle Finder

A streamlined Streamlit app that helps out-of-town race participants choose a race-morning bus pickup from a hotel, lodging spot, or custom address.

The app is centered around one main Google map: pickup and hotel pins are shown together, and the selected pickup route is drawn directly on that same map.

## What it does

- Shows a main Google map with bus pickup spots and hotel/lodging locations.
- Lets a visitor choose a listed hotel/lodging spot or enter a custom address/place.
- Lets a visitor choose their race and corral.
- Ranks bus pickup spots by Google driving distance when `GOOGLE_MAPS_API_KEY` is configured.
- Draws the selected Google driving route directly on the main map.
- Shows the pickup selector and route details to the left of the map.
- Shows the full pickup-options table underneath the map.
- Keeps official loading-site PDF links next to each pickup.
- Includes return shuttle and other transportation notes in a collapsed section.

## Latest changes

This version simplifies the page into:

1. **Left panel:** starting location, race/corral, hotel-pin toggle, pickup selector, and selected-pickup notes.
2. **Main map:** all pickup/hotel markers plus the selected route line.
3. **Bottom table:** all pickup options, sorted by Google driving distance when available.

It also fixes the DECC ranking issue by adding a separate `routing_query` field. The DECC map/routing query now uses the stable official venue address:

```text
Duluth Entertainment Convention Center, 350 Harbor Drive, Duluth, MN 55802
```

The app still displays the race-morning note that buses load at the North Gate along Railroad Street, and the official loading-site PDF remains linked for exact loading-zone details. The earlier `North Gate Railroad Street` text query was too fragile for Google route ranking and could cause DECC to be missing or pushed below farther locations.

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

- **Routes API** — used for driving-distance ranking and the selected route polyline.
- **Maps JavaScript API** — used for the main all-location map.
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

## Why this version is better for map accuracy

The earlier Folium version used latitude/longitude columns for visible pins. That was fragile because hotel pins and large venues can land slightly away from the driveway, entrance, or loading side that Google Maps would actually use.

This version uses Google-facing fields instead:

- `google_maps_query`: display/search query used for map markers, such as a hotel name plus address.
- `routing_query`: routing query used for driving-distance ranking and route-line calculation. This can be a stable official address when a more detailed loading-zone phrase is too fragile.
- `google_place_id`: optional exact Google place ID. When present, the app can use it for routing/maps instead of only text queries.

The existing `latitude` and `longitude` columns can stay in the CSV for reference, but the main app does not depend on them for visible map pins or nearest-pickup ranking.

## Updating pickup spots

Edit `data/pickup_locations.csv`.

Important columns:

- `id`: stable machine-readable ID.
- `name`, `address`, `city`, `state`, `zip`: displayed to users.
- `google_maps_query`: Google map marker/search query.
- `routing_query`: Google routing query for driving distance and the purple route line.
- `google_place_id`: optional exact Google place ID. Leave blank until verified.
- `google_query_note`: note explaining why the query was chosen.
- `has_half_bus`, `has_full_bus`: controls which race sees the pickup.
- `half_corral_1`, `half_corral_2`, `half_corral_3`, `full_corral_a`, `full_corral_b`, `full_corral_c`: recommended loading windows.
- `loading_instructions`, `parking_info`, `best_for`, `access_notes`: displayed in pickup details.
- `loading_site_map_url`: official loading-zone PDF link.

For large venues, keep `routing_query` stable and boring. Use the loading instructions and official PDF to explain the exact race-morning loading zone.

## Updating hotels/lodging

Edit `data/hotels.csv`.

Important columns:

- `name`, `address`, `city`, `state`, `zip`: displayed to users.
- `google_maps_query`: Google map marker/search query. Usually hotel name plus address.
- `routing_query`: Google routing query. Usually the same as `google_maps_query`, but can be tuned separately.
- `google_place_id`: optional exact Google place ID. This is the best way to avoid hotel pin drift.
- `area`, `category`, `return_shuttle_group`, `notes`: displayed/context fields.

Hotel markers are shown on the overview map by default. Users can turn them off with the `Show hotel pins` checkbox when they want a less crowded pickup-only view.

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

## Deployment notes

- Keep the GitHub repo public or private as needed, but never commit the real Google Maps key.
- On Streamlit Community Cloud, store `GOOGLE_MAPS_API_KEY` in Secrets.
- Apply API key restrictions in Google Cloud, such as HTTP referrer restrictions for browser APIs and API restrictions to the specific Google Maps APIs used here.
- Review Google Maps Platform billing/quotas before public launch.

## Important race-day disclaimer

Race-day transportation details, road closures, and loading zones can change. Before sharing the app publicly, verify all pickup instructions, loading windows, return shuttle stops, official loading-site PDF links, and road closure notes against the official race guide.
