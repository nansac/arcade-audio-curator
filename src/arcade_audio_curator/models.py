"""Shared Pydantic models for arcade-audio-curator."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class Song(BaseModel):
    """Represents a song in the database."""

    id: str
    title: str
    artist: str
    bpm: int
    energy: int = Field(ge=1, le=9, description="Energy level from 1 (calm) to 9 (intense)")
    genres: list[str]
    moods: list[str]
    duration_seconds: int

    @property
    def duration_display(self) -> str:
        minutes, seconds = divmod(self.duration_seconds, 60)
        return f"{minutes}:{seconds:02d}"


class ActivityProfile(BaseModel):
    """Profile defining musical constraints for a given activity."""

    label: str
    description: str
    bpm_range: tuple[int, int]
    energy_range: tuple[int, int]
    preferred_genres: list[str]
    preferred_moods: list[str]
    excluded_moods: list[str]
    energy_arc: Literal["steady", "build", "peak", "varied"]


class ScoredSong(BaseModel):
    """A song with a computed fit score for a given activity."""

    song: Song
    score: float = Field(ge=0.0, le=1.0, description="Fit score from 0.0 (poor) to 1.0 (perfect)")
    match_reasons: list[str]
    mismatch_reasons: list[str]


class PlaylistTrack(BaseModel):
    """A song in a curated playlist with position metadata."""

    position: int
    song: Song
    score: float
    phase: Literal["intro", "build", "peak", "cooldown", "steady"]
    cumulative_duration_seconds: int


class Playlist(BaseModel):
    """A curated playlist for a specific activity."""

    activity: str
    activity_label: str
    target_duration_minutes: int
    actual_duration_seconds: int
    tracks: list[PlaylistTrack]
    energy_arc: str

    @property
    def actual_duration_display(self) -> str:
        minutes, seconds = divmod(self.actual_duration_seconds, 60)
        return f"{minutes}:{seconds:02d}"

    @property
    def track_count(self) -> int:
        return len(self.tracks)
