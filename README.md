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

This version keeps the simple three-part layout:

1. **Left panel:** starting location, race/corral, hotel-pin toggle, pickup selector, and selected-pickup notes.
2. **Main map:** all pickup/hotel markers plus the selected route line.
3. **Bottom table:** all pickup options, sorted by Google driving distance when available.

It also fixes two route issues:

- **Route drawing no longer uses a server-side ComputeRoutes call.** The previous version sent an invalid ComputeRoutes body shape for route drawing, which could produce `400 Bad Request`. The main map now draws the selected route in the browser with Google Maps JavaScript `DirectionsRenderer`.
- **DECC is protected from bad address-search ranking.** Driving-distance ranking now sends pickup destination coordinates to Google Route Matrix instead of relying only on a text query. This keeps DECC from being missed or ranked behind Kirby for Canal Park / downtown hotels because of an ambiguous address or venue-name match.

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

- **Routes API** — used for Route Matrix driving-distance ranking.
- **Maps JavaScript API** — used for the main all-location map and browser-side route drawing.
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

The app uses two separate ideas of location:

- **Visible marker location:** resolved in the browser by Google Maps using `google_place_id`, `google_maps_query`, or the geocoder. CSV coordinates are only the final marker fallback.
- **Driving-distance ranking location:** sent to Google Route Matrix. For pickup destinations, the app now prefers the CSV latitude/longitude so large venues like DECC do not disappear or rank incorrectly because of an ambiguous text search. For listed hotels, the app also sends hotel coordinates when available to avoid brand/name ambiguity.

This means the map can still display Google’s best place marker, while the distance table uses stable route inputs.

## Updating pickup spots

Edit `data/pickup_locations.csv`.

Important columns:

- `id`: stable machine-readable ID.
- `name`, `address`, `city`, `state`, `zip`: displayed to users.
- `google_maps_query`: Google map marker/search query.
- `routing_query`: Google routing query used for Google Maps URLs and browser route drawing.
- `latitude`, `longitude`: used by Google Route Matrix for driving-distance ranking. Keep these near the actual pickup venue/loading area.
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
- `latitude`, `longitude`: used by Google Route Matrix for listed-hotel driving-distance ranking when present.
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
- If you still see old distance rankings after deploying, restart the Streamlit app or clear cached data. This version includes a cache-version bump to avoid reusing the earlier DECC route results.

## Important race-day disclaimer

Race-day transportation details, road closures, and loading zones can change. Before sharing the app publicly, verify all pickup instructions, loading windows, return shuttle stops, official loading-site PDF links, and road closure notes against the official race guide.
