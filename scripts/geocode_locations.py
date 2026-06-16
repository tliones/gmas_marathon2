#!/usr/bin/env python3
"""Geocode rows in a CSV file that has address/city/state/zip columns.

Examples:
    python scripts/geocode_locations.py --file data/hotels.csv --overwrite
    python scripts/geocode_locations.py --file data/pickup_locations.csv
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

import pandas as pd
from geopy.extra.rate_limiter import RateLimiter
from geopy.geocoders import Nominatim


REQUIRED_COLUMNS = {"address", "city", "state", "zip", "latitude", "longitude"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Geocode address rows in a CSV file.")
    parser.add_argument("--file", required=True, help="CSV file to update, such as data/hotels.csv")
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Refresh all coordinates. Without this flag, only blank latitude/longitude rows are geocoded.",
    )
    return parser.parse_args()


def full_address(row: pd.Series) -> str:
    return ", ".join(
        str(row.get(part, "")).strip()
        for part in ["address", "city", "state", "zip"]
        if str(row.get(part, "")).strip()
    )


def main() -> int:
    args = parse_args()
    path = Path(args.file)
    if not path.exists():
        print(f"File not found: {path}", file=sys.stderr)
        return 1

    df = pd.read_csv(path)
    missing = REQUIRED_COLUMNS - set(df.columns)
    if missing:
        print(f"Missing required columns: {', '.join(sorted(missing))}", file=sys.stderr)
        return 1

    user_agent = os.getenv("GEOCODER_USER_AGENT", "grandmas-bus-finder-geocode-script")
    geolocator = Nominatim(user_agent=user_agent, timeout=10)
    geocode = RateLimiter(geolocator.geocode, min_delay_seconds=1.1)

    updated = 0
    for idx, row in df.iterrows():
        has_coords = pd.notna(row.get("latitude")) and pd.notna(row.get("longitude"))
        if has_coords and str(row.get("latitude")).strip() and str(row.get("longitude")).strip() and not args.overwrite:
            continue

        query = full_address(row)
        if not query:
            print(f"Skipping row {idx}: no address")
            continue

        print(f"Geocoding row {idx}: {query}")
        location = geocode(query, country_codes="us", exactly_one=True)
        if location is None:
            print(f"  No result")
            continue

        df.at[idx, "latitude"] = round(float(location.latitude), 6)
        df.at[idx, "longitude"] = round(float(location.longitude), 6)
        updated += 1
        print(f"  -> {location.latitude}, {location.longitude}")

    if updated:
        backup = path.with_suffix(path.suffix + ".bak")
        shutil.copy2(path, backup)
        df.to_csv(path, index=False)
        print(f"Updated {updated} row(s). Backup written to {backup}")
    else:
        print("No rows updated.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
