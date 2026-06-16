# Grandma's Marathon Bus Pickup Finder

A small Streamlit app that helps visitors find the closest race-day bus pickup spot from a hotel, address, or GPS point.

The app includes:

- Bus pickup locations with race/corral-specific recommended boarding windows
- A nearest-pickup calculator using straight-line distance
- Google Maps direction links for actual routing
- An interactive Folium map with pickup spots and starter hotel/lodging data
- Return shuttle route notes
- Other race-weekend transportation notes: bike valet, DTA, Port Town Trolley, skywalk, and Lakewalk

> Important: This is a starter project. Verify all coordinates, hotel names, parking notes, race-day road closures, and official race transportation details before sharing publicly.

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

### Hotels / lodging

Edit `data/hotels.csv`.

The included hotel list is starter data, mixing hotels from the provided return-shuttle notes with a few common downtown/Canal Park examples. Review every coordinate before public launch.

You can add rows for any hotel, Airbnb landmark, campground, or neighborhood meeting point. The nearest-pickup calculator only needs `latitude` and `longitude`.

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

A helper script is included to geocode rows in `data/hotels.csv` or `data/pickup_locations.csv`.

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
- Hotel coordinates are starter values and should be verified.
- Official race logistics can change; keep the data files synced with the latest official information.
