#!/usr/bin/env python3
"""Resolve Google place IDs for pickup or hotel CSV rows.

Usage:
    export GOOGLE_MAPS_API_KEY="your-key"
    python scripts/resolve_google_place_ids.py --file data/pickup_locations.csv
    python scripts/resolve_google_place_ids.py --file data/hotels.csv

The script uses Places API Text Search (New). It fills these columns when present
or creates them if missing:
    google_place_id, google_display_name, google_formatted_address,
    google_latitude, google_longitude, google_place_resolution_status

Review the CSV after running. Place IDs are very helpful for routing accuracy,
but you still need to verify exact race-morning loading zones against the
official loading-site maps.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path
from typing import Any

import pandas as pd
import requests

PLACES_TEXT_SEARCH_ENDPOINT = "https://places.googleapis.com/v1/places:searchText"


def clean(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if text.lower() in {"nan", "none", "null"}:
        return ""
    return text


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Resolve Google place IDs for a CSV file.")
    parser.add_argument("--file", required=True, help="CSV file to update, such as data/hotels.csv")
    parser.add_argument("--query-column", default="google_maps_query", help="Column containing the Google text query")
    parser.add_argument("--overwrite", action="store_true", help="Refresh rows that already have google_place_id")
    parser.add_argument("--sleep", type=float, default=0.15, help="Delay between requests in seconds")
    return parser.parse_args()


def search_place(api_key: str, query: str) -> dict[str, Any] | None:
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": "places.id,places.displayName,places.formattedAddress,places.location",
    }
    payload = {"textQuery": query, "languageCode": "en"}
    response = requests.post(PLACES_TEXT_SEARCH_ENDPOINT, headers=headers, json=payload, timeout=20)
    response.raise_for_status()
    places = response.json().get("places", [])
    return places[0] if places else None


def main() -> int:
    args = parse_args()
    api_key = clean(os.getenv("GOOGLE_MAPS_API_KEY"))
    if not api_key:
        print("Missing GOOGLE_MAPS_API_KEY environment variable.", file=sys.stderr)
        return 1

    path = Path(args.file)
    if not path.exists():
        print(f"File not found: {path}", file=sys.stderr)
        return 1

    df = pd.read_csv(path).fillna("")
    if args.query_column not in df.columns:
        print(f"Missing query column: {args.query_column}", file=sys.stderr)
        return 1

    for column in [
        "google_place_id",
        "google_display_name",
        "google_formatted_address",
        "google_latitude",
        "google_longitude",
        "google_place_resolution_status",
    ]:
        if column not in df.columns:
            df[column] = ""

    updated = 0
    skipped = 0
    failed = 0

    for idx, row in df.iterrows():
        existing = clean(row.get("google_place_id"))
        if existing and not args.overwrite:
            skipped += 1
            continue

        query = clean(row.get(args.query_column))
        if not query:
            df.at[idx, "google_place_resolution_status"] = "missing_query"
            failed += 1
            continue

        print(f"Resolving row {idx}: {query}")
        try:
            place = search_place(api_key, query)
        except requests.HTTPError as exc:
            print(f"  API error: {exc}", file=sys.stderr)
            df.at[idx, "google_place_resolution_status"] = f"api_error: {exc.response.status_code}"
            failed += 1
            continue
        except requests.RequestException as exc:
            print(f"  Request error: {exc}", file=sys.stderr)
            df.at[idx, "google_place_resolution_status"] = "request_error"
            failed += 1
            continue

        if not place:
            print("  No place found")
            df.at[idx, "google_place_resolution_status"] = "not_found"
            failed += 1
        else:
            display_name = place.get("displayName", {}).get("text", "")
            location = place.get("location", {})
            df.at[idx, "google_place_id"] = clean(place.get("id"))
            df.at[idx, "google_display_name"] = clean(display_name)
            df.at[idx, "google_formatted_address"] = clean(place.get("formattedAddress"))
            df.at[idx, "google_latitude"] = clean(location.get("latitude"))
            df.at[idx, "google_longitude"] = clean(location.get("longitude"))
            df.at[idx, "google_place_resolution_status"] = "resolved_needs_review"
            updated += 1
            print(f"  -> {display_name} | {place.get('formattedAddress', '')}")

        if args.sleep:
            time.sleep(args.sleep)

    df.to_csv(path, index=False)
    print(f"Done. Updated: {updated}; skipped: {skipped}; failed: {failed}; wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
