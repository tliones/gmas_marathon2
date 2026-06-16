# Grandma's Marathon Bus Pickup Finder

A small Streamlit app that helps visitors find the closest race-day bus pickup spot from a hotel, address, or GPS point.

The app includes:

- Bus pickup locations with race/corral-specific recommended boarding windows
- A nearest-pickup calculator using straight-line distance
- Google Maps direction links for actual routing
- An interactive Folium map with pickup spots and reviewed hotel/lodging pins
- Return shuttle route notes
- Other race-weekend transportation notes: bike valet, DTA, Port Town Trolley, skywalk, and Lakewalk

> Important: Pickup coordinates have been aligned to the official Google Maps place links on the race transportation page, and each pickup row includes an official loading-site-map URL. Hotel coordinates have also been reviewed/updated, with source notes in `data/hotels.csv`; verify exact hotel driveways, parking notes, road closures, and race-day logistics before sharing publicly.

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
│   └── geocode_locations.py
└── src/
    ├── data.py
    ├── geo.py
    └── maps.py
```

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

## Updating the data

Most app changes can be made without touching Python code.

### Pickup spots

Edit `data/pickup_locations.csv`.

Key columns:

- `id`: stable machine-readable ID
- `name`, `address`, `city`, `state`, `zip`
- `latitude`, `longitude`
- `half_corral_1`, `half_corral_2`, `half_corral_3`
- `full_corral_a`, `full_corral_b`, `full_corral_c`
- `loading_instructions`, `parking_info`, `best_for`, `access_notes`
- `loading_site_map_url`: official PDF map for the race-morning loading zone
- `coordinate_note`: note about how the pickup pin coordinate was chosen

### Hotels / lodging

Edit `data/hotels.csv`.

The included hotel list mixes hotels from the provided return-shuttle notes with a few common downtown/Canal Park examples. Hotel pins were reviewed and corrected where better public lat/lon data was available. Some rows still use address-based/place coordinates, so exact hotel driveway/pickup points should still be verified before public launch.

You can add rows for any hotel, Airbnb landmark, campground, or neighborhood meeting point. The nearest-pickup calculator only needs `latitude` and `longitude`. The optional `coordinate_status` and `coordinate_notes` columns record whether a pin was updated from a public lat/lon source or checked against the address.

### Return shuttles

Edit `data/return_shuttle_routes.csv`.

Each row is one destination stop served by a return shuttle route.

### Other transportation

Edit `data/other_transportation.json`.

This file powers the "Other transportation" tab.

## Custom address lookup

The app supports custom address entry through `geopy` and OpenStreetMap Nominatim. This is useful for a low-traffic prototype.

For a public production app, consider replacing this with a commercial geocoder such as Google Maps, Mapbox, or HERE. You can store API keys in Streamlit secrets and update `src/geo.py`.

Set a custom user agent if you deploy address lookup:

```bash
export GEOCODER_USER_AGENT="your-app-name-contact-email"
```

## Refreshing coordinates

A helper script is included to geocode rows in `data/hotels.csv` or `data/pickup_locations.csv`. For pickup spots, avoid overwriting the included coordinates unless you are intentionally replacing them; the pickup pins are aligned to the official race transportation Google Maps links, while the loading-site PDF links show the exact race-morning boarding areas.

```bash
python scripts/geocode_locations.py --file data/hotels.csv --overwrite
python scripts/geocode_locations.py --file data/pickup_locations.csv --overwrite
```

The script uses Nominatim, waits between requests, and writes a `.bak` backup before replacing the CSV.

## Deploying on Streamlit Community Cloud

1. Push this folder to a GitHub repository.
2. In Streamlit Community Cloud, create a new app from the repository.
3. Set the main file path to `app.py`.
4. Add any environment variables or secrets you need for production geocoding.
5. Recheck the app on mobile, because many visitors will use this from a phone.

## Limitations to keep in mind

- The nearest-pickup ranking uses straight-line distance, not driving time.
- Google Maps direction links handle actual routing, closures, and travel mode.
- Pickup pins represent official Google Maps place coordinates; the exact boarding area can be a driveway or parking-lot loading zone shown in the official PDF maps.
- Hotel pins are loaded from `data/hotels.csv`; they were reviewed/corrected from public lat/lon or place sources where available, but exact driveways/property entrances should still be verified.
- Official race logistics can change; keep the data files synced with the latest official information.
