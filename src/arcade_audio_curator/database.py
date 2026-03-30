"""Database loader for songs and activity profiles."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from arcade_audio_curator.models import ActivityProfile, Song

DATA_DIR = Path(__file__).parent / "data"


@lru_cache(maxsize=1)
def load_songs() -> list[Song]:
    """Load all songs from the database. Cached after first load."""
    path = DATA_DIR / "songs.json"
    raw = json.loads(path.read_text())
    return [Song(**s) for s in raw]


@lru_cache(maxsize=1)
def load_activity_profiles() -> dict[str, ActivityProfile]:
    """Load all activity profiles. Cached after first load."""
    path = DATA_DIR / "activity_profiles.json"
    raw = json.loads(path.read_text())
    return {key: ActivityProfile(**val) for key, val in raw.items()}


def get_activity_profile(activity: str) -> ActivityProfile | None:
    """Return the best-matching activity profile for a given activity name."""
    profiles = load_activity_profiles()
    normalized = activity.lower().strip()

    # Exact match first
    if normalized in profiles:
        return profiles[normalized]

    # Partial match: check if any profile key is contained in the activity string
    for key, profile in profiles.items():
        if key in normalized or normalized in key:
            return profile

    return None


def list_supported_activities() -> list[str]:
    """Return sorted list of supported activity keys."""
    return sorted(load_activity_profiles().keys())
