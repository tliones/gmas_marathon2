"""Data loading helpers for the bus pickup finder app."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"


RACE_CONFIG: Dict[str, Dict[str, object]] = {
    "Garry Bjorklund Half Marathon": {
        "key": "half",
        "corrals": ["1", "2", "3"],
        "display_short": "Half Marathon",
        "bag_note": "No gear bags are allowed on buses to the half marathon start line. Bags must be dropped at the loading location before boarding.",
    },
    "Grandma’s Marathon": {
        "key": "full",
        "corrals": ["A", "B", "C"],
        "display_short": "Full Marathon",
        "bag_note": "Use your official race instructions for gear bag timing and permitted items.",
    },
}


BOOLEAN_COLUMNS = ["has_half_bus", "has_full_bus"]


def _read_csv(name: str) -> pd.DataFrame:
    path = DATA_DIR / name
    if not path.exists():
        raise FileNotFoundError(f"Missing data file: {path}")
    return pd.read_csv(path).fillna("")


def load_pickups() -> pd.DataFrame:
    """Load pickup locations with normalized columns."""
    df = _read_csv("pickup_locations.csv")
    for col in BOOLEAN_COLUMNS:
        if col in df.columns:
            df[col] = df[col].astype(str).str.lower().isin(["true", "1", "yes", "y"])
    for col in ["latitude", "longitude"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["full_address"] = df.apply(
        lambda row: ", ".join(
            str(part).strip()
            for part in [row["address"], row["city"], row["state"], row["zip"]]
            if str(part).strip()
        ),
        axis=1,
    )
    return df


def load_hotels() -> pd.DataFrame:
    """Load hotel/lodging data."""
    df = _read_csv("hotels.csv")
    for col in ["latitude", "longitude"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["full_address"] = df.apply(
        lambda row: ", ".join(
            str(part).strip()
            for part in [row["address"], row["city"], row["state"], row["zip"]]
            if str(part).strip()
        ),
        axis=1,
    )
    df["display_name"] = df["name"] + " — " + df["city"] + ", " + df["state"]
    return df.sort_values(["area", "name"]).reset_index(drop=True)


def load_return_routes() -> pd.DataFrame:
    """Load return shuttle route stops."""
    return _read_csv("return_shuttle_routes.csv")


def load_other_transportation() -> List[dict]:
    """Load race-weekend transportation notes."""
    path = DATA_DIR / "other_transportation.json"
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def pickup_time_column(race_key: str, corral: str) -> str:
    """Return the pickup CSV column containing the selected race/corral window."""
    return f"{race_key}_corral_{str(corral).lower()}"


def available_pickups(pickups: pd.DataFrame, race_key: str) -> pd.DataFrame:
    """Filter pickup locations to ones that serve the selected race."""
    col = "has_half_bus" if race_key == "half" else "has_full_bus"
    return pickups[pickups[col]].copy()
