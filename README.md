# Duluth Race Shuttle Finder

A streamlined Streamlit app that helps out-of-town race participants find a race-morning bus pickup from a hotel, lodging spot, or custom address.

The app is now centered around a Google Maps overview showing bus pickup spots and hotel/lodging locations together. With a Google Maps Platform key configured, it ranks pickup spots by Google driving distance from the selected start location and shows an embedded Google route for the selected pickup.

## What it does

- Shows a main Google map with all bus pickup spots and hotel/lodging locations.
- Uses Google-resolved marker positions from place names, addresses, and optional place IDs instead of plotting CSV latitude/longitude pins.
- Lets a visitor choose a listed hotel/lodging spot or enter any custom address/place.
- Lets a visitor choose their race and corral.
- Ranks bus pickup spots by Google driving distance when `GOOGLE_MAPS_API_KEY` is configured.
- Highlights the selected starting location and selected pickup on the main map.
- Shows starting location and pickup location side by side for easier scanning.
- Shows an embedded Google Maps route for the selected pickup.
- Keeps official loading-site PDF links next to each pickup.
- Includes return shuttle and other transportation notes.

## Recent cleanup

This version includes three UI fixes:

1. The all-location map is back as the main item on the page.
2. The selected route is organized as `Starting location` → `Pickup location` instead of being buried in tabs.
3. Streamlit’s deprecated `use_container_width` argument has been replaced with `width="stretch"`.

The map icons no longer use the old external `chart.googleapis.com` pin-image URL. They are now drawn as native Google Maps vector symbols, so they should render reliably as:

- `P` = bus pickup
- `H` = hotel/lodging
- `S` = selected starting location
- purple `P` = selected pickup route

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

Without a Google Maps Platform key, the app still opens Google Maps direction links. The main Google map, driving-distance ranking, and embedded route map require a key.

## Google Maps setup

Create a Google Maps Platform API key and enable these APIs for the project:

- **Routes API** — used for driving-distance ranking through Compute Route Matrix.
- **Maps Embed API** — used for the selected route map inside Streamlit.
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

The earlier Folium version used latitude/longitude columns for map pins. That was fragile because hotel pins and large venues can land slightly away from the driveway, entrance, or loading side that Google Maps would actually route to.

This version uses these fields instead:

- `google_maps_query`: the text query sent to Google, such as a hotel name plus address or a specific loading-side query like `JCPenney Miller Hill Mall 1600 Miller Trunk Highway Duluth MN 55811`.
- `google_place_id`: optional but preferred. When present, the app uses the place ID for routing/maps instead of only the text query.

The existing `latitude` and `longitude` columns can stay in the CSV for reference, but the main app does not depend on them for visible map pins or nearest-pickup ranking.

## Updating pickup spots

Edit `data/pickup_locations.csv`.

Important columns:

- `id`: stable machine-readable ID.
- `name`, `address`, `city`, `state`, `zip`: displayed to users.
- `google_maps_query`: Google routing/map query. Tune this when a marker or route lands in the wrong part of a large venue.
- `google_place_id`: optional exact Google place ID. Leave blank until verified.
- `google_query_note`: internal/public note explaining why the query was chosen.
- `has_half_bus`, `has_full_bus`: controls which race sees the pickup.
- `half_corral_1`, `half_corral_2`, `half_corral_3`, `full_corral_a`, `full_corral_b`, `full_corral_c`: recommended loading windows.
- `loading_instructions`, `parking_info`, `best_for`, `access_notes`: displayed in pickup details.
- `loading_site_map_url`: official loading-zone PDF link.

The `google_maps_query` values for several pickup locations intentionally aim for the loading side of the venue when the official notes are more specific than the mailing address.

## Updating hotels/lodging

Edit `data/hotels.csv`.

Important columns:

- `name`, `address`, `city`, `state`, `zip`: displayed to users.
- `google_maps_query`: Google routing/map query. Usually hotel name plus address.
- `google_place_id`: optional exact Google place ID. This is the best way to avoid hotel pin drift.
- `area`, `category`, `return_shuttle_group`, `notes`: displayed/context fields.

Hotel markers are shown on the overview map by default. Users can turn them off with the `Show hotels` checkbox when they want a less crowded pickup-only view.

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

## Deployment notes

- Keep the GitHub repo public or private as needed, but never commit the real Google Maps key.
- On Streamlit Community Cloud, store `GOOGLE_MAPS_API_KEY` in Secrets.
- Apply API key restrictions in Google Cloud, such as HTTP referrer restrictions for browser APIs and API restrictions to the specific Google Maps APIs used here.
- Review Google Maps Platform billing/quotas before public launch.

## Important race-day disclaimer

Race-day transportation details, road closures, and loading zones can change. Before sharing the app publicly, verify all pickup instructions, loading windows, return shuttle stops, official loading-site PDF links, and road closure notes against the official race guide.
