"""Scoring engine: computes how well a song fits an activity profile."""

from __future__ import annotations

from arcade_audio_curator.models import ActivityProfile, ScoredSong, Song


def score_song(song: Song, profile: ActivityProfile) -> ScoredSong:
    """
    Score a song against an activity profile.

    Scoring breakdown:
      - BPM fit:    30 points  (within range = full, outside = scaled penalty)
      - Energy fit: 25 points  (within range = full, outside = scaled penalty)
      - Mood fit:   30 points  (based on overlap with preferred moods)
      - Genre fit:  15 points  (based on overlap with preferred genres)

    Mood exclusions apply a hard 0.0 override — excluded moods disqualify a song.
    """
    match_reasons: list[str] = []
    mismatch_reasons: list[str] = []
    total_score = 0.0

    # --- Excluded mood check (hard disqualifier) ---
    song_moods = set(song.moods)
    excluded_hits = song_moods & set(profile.excluded_moods)
    if excluded_hits:
        mismatch_reasons.append(
            f"Mood '{', '.join(sorted(excluded_hits))}' is excluded for {profile.label}"
        )
        return ScoredSong(
            song=song,
            score=0.0,
            match_reasons=match_reasons,
            mismatch_reasons=mismatch_reasons,
        )

    # --- BPM score (30 pts) ---
    bpm_lo, bpm_hi = profile.bpm_range
    if bpm_lo <= song.bpm <= bpm_hi:
        total_score += 30.0
        match_reasons.append(f"BPM {song.bpm} fits range {bpm_lo}–{bpm_hi}")
    else:
        distance = min(abs(song.bpm - bpm_lo), abs(song.bpm - bpm_hi))
        # Penalty: -1 pt per BPM outside range, floor at 0
        bpm_pts = max(0.0, 30.0 - distance * 2)
        total_score += bpm_pts
        mismatch_reasons.append(
            f"BPM {song.bpm} is outside ideal range {bpm_lo}–{bpm_hi} (−{distance} BPM)"
        )

    # --- Energy score (25 pts) ---
    e_lo, e_hi = profile.energy_range
    if e_lo <= song.energy <= e_hi:
        total_score += 25.0
        match_reasons.append(f"Energy {song.energy}/9 fits range {e_lo}–{e_hi}")
    else:
        distance = min(abs(song.energy - e_lo), abs(song.energy - e_hi))
        energy_pts = max(0.0, 25.0 - distance * 8)
        total_score += energy_pts
        mismatch_reasons.append(
            f"Energy {song.energy}/9 is outside ideal range {e_lo}–{e_hi}"
        )

    # --- Mood score (30 pts) ---
    preferred_moods = set(profile.preferred_moods)
    mood_overlap = song_moods & preferred_moods
    if mood_overlap:
        mood_ratio = len(mood_overlap) / len(preferred_moods)
        mood_pts = round(30.0 * min(mood_ratio * 2, 1.0), 2)  # cap at 30
        total_score += mood_pts
        match_reasons.append(
            f"Mood match: {', '.join(sorted(mood_overlap))}"
        )
    else:
        mismatch_reasons.append("No mood overlap with activity profile")

    # --- Genre score (15 pts) ---
    song_genres = set(song.genres)
    preferred_genres = set(profile.preferred_genres)
    genre_overlap = song_genres & preferred_genres
    if genre_overlap:
        genre_pts = 15.0 * min(len(genre_overlap) / max(len(song_genres), 1), 1.0)
        total_score += genre_pts
        match_reasons.append(
            f"Genre match: {', '.join(sorted(genre_overlap))}"
        )
    else:
        mismatch_reasons.append(
            f"Genre(s) {', '.join(sorted(song_genres))} not in preferred list"
        )

    return ScoredSong(
        song=song,
        score=round(total_score / 100.0, 3),
        match_reasons=match_reasons,
        mismatch_reasons=mismatch_reasons,
    )


def rank_songs(songs: list[Song], profile: ActivityProfile) -> list[ScoredSong]:
    """Score and rank all songs against a profile, best fit first."""
    scored = [score_song(s, profile) for s in songs]
    return sorted(scored, key=lambda s: s.score, reverse=True)
