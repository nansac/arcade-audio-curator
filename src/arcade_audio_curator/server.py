#!/usr/bin/env python3
"""arcade-audio-curator MCP server.

Curates music playlists tailored to physical activities using genre,
mood, BPM, and energy level — not just tempo alone.
"""

import sys
from typing import Annotated

import httpx
from arcade_mcp_server import MCPApp

from arcade_audio_curator.database import (
    get_activity_profile,
    list_supported_activities,
    load_songs,
)
from arcade_audio_curator.models import Playlist, PlaylistTrack
from arcade_audio_curator.scoring import rank_songs, score_song
import os

from dotenv import load_dotenv
load_dotenv()

app = MCPApp(name="arcade_audio_curator", version="1.0.0", log_level="WARNING")


# ---------------------------------------------------------------------------
# Tool 1 — GetActivityProfile
# ---------------------------------------------------------------------------


@app.tool
def get_activity_profile_tool(
    activity: Annotated[str, "Activity name, e.g. 'yard work', 'running', 'cooking', 'studying'."],
) -> dict:
    """Get the musical profile for a physical activity.

    Returns BPM range, energy range, preferred genres, preferred moods,
    excluded moods, and the recommended energy arc for playlist sequencing.

    Supported activities: yard work, running, cooking, studying, morning workout,
    road trip, dinner party, hiking, commute, party.
    """
    profile = get_activity_profile(activity)

    if profile is None:
        supported = list_supported_activities()
        return {
            "error": f"No profile found for '{activity}'.",
            "supported_activities": supported,
            "suggestion": (
                "Try one of the supported activities, or describe your activity "
                "differently (e.g. 'yard work' instead of 'gardening')."
            ),
        }

    return {
        "activity": activity,
        "label": profile.label,
        "description": profile.description,
        "bpm_range": list(profile.bpm_range),
        "energy_range": list(profile.energy_range),
        "preferred_genres": profile.preferred_genres,
        "preferred_moods": profile.preferred_moods,
        "excluded_moods": profile.excluded_moods,
        "energy_arc": profile.energy_arc,
    }


# ---------------------------------------------------------------------------
# Tool 2 — FilterSongsByProfile
# ---------------------------------------------------------------------------


@app.tool
def filter_songs_by_profile(
    activity: Annotated[str, "Activity name to filter songs for, e.g. 'yard work', 'running'."],
    min_score: Annotated[float, "Minimum fit score threshold 0.0–1.0. Default 0.4."] = 0.4,
    limit: Annotated[int, "Maximum number of songs to return. Default 20, max 50."] = 20,
) -> dict:
    """Filter and rank songs from the database that fit a given activity.

    Songs are scored across four dimensions: BPM fit (30pts), energy fit (25pts),
    mood overlap (30pts), and genre overlap (15pts). Songs with excluded moods
    for the activity score 0.0 and are filtered out at any threshold above 0.

    Returns a ranked list of matching songs with scores and reasoning.
    """
    profile = get_activity_profile(activity)
    if profile is None:
        return {
            "error": f"No profile found for '{activity}'.",
            "supported_activities": list_supported_activities(),
        }

    limit = min(limit, 50)
    songs = load_songs()
    ranked = rank_songs(songs, profile)
    filtered = [s for s in ranked if s.score >= min_score][:limit]

    return {
        "activity": activity,
        "activity_label": profile.label,
        "total_songs_in_db": len(songs),
        "songs_above_threshold": len([s for s in ranked if s.score >= min_score]),
        "returned": len(filtered),
        "min_score_used": min_score,
        "songs": [
            {
                "id": s.song.id,
                "title": s.song.title,
                "artist": s.song.artist,
                "bpm": s.song.bpm,
                "energy": s.song.energy,
                "genres": s.song.genres,
                "moods": s.song.moods,
                "duration": s.song.duration_display,
                "duration_seconds": s.song.duration_seconds,
                "fit_score": s.score,
                "match_reasons": s.match_reasons,
                "mismatch_reasons": s.mismatch_reasons,
            }
            for s in filtered
        ],
    }


# ---------------------------------------------------------------------------
# Tool 3 — CuratePlaylist
# ---------------------------------------------------------------------------


@app.tool
def curate_playlist(
    activity: Annotated[str, "Activity name the playlist is for, e.g. 'yard work', 'morning workout'."],
    target_duration_minutes: Annotated[int, "Desired playlist length in minutes. Default 45."] = 45,
    min_score: Annotated[float, "Minimum fit score for songs to be included. Default 0.45."] = 0.45,
) -> dict:
    """Curate a sequenced playlist for a specific activity and target duration.

    Assembles songs from the filtered pool and sequences them according to the
    activity's energy arc (steady / build / peak / varied).

    Returns a playlist with track-by-track details, cumulative timing,
    and phase labels: intro / build / peak / cooldown / steady.
    """
    profile = get_activity_profile(activity)
    if profile is None:
        return {
            "error": f"No profile found for '{activity}'.",
            "supported_activities": list_supported_activities(),
        }

    songs = load_songs()
    ranked = rank_songs(songs, profile)
    candidates = [s for s in ranked if s.score >= min_score]

    if not candidates:
        return {
            "error": f"No songs scored above {min_score} for '{activity}'. Try lowering min_score.",
            "activity": activity,
        }

    target_seconds = target_duration_minutes * 60
    arc = profile.energy_arc

    by_energy_asc = sorted(candidates, key=lambda s: (s.song.energy, -s.score))
    by_energy_desc = sorted(candidates, key=lambda s: (-s.song.energy, -s.score))
    by_score = list(candidates)

    if arc == "build":
        pool = by_energy_asc
    elif arc == "peak":
        pool = by_energy_desc
    else:
        pool = by_score

    tracks: list[PlaylistTrack] = []
    used_ids: set[str] = set()
    cumulative = 0
    position = 1

    while cumulative < target_seconds and pool:
        candidate = next((s for s in pool if s.song.id not in used_ids), None)
        if candidate is None:
            break

        used_ids.add(candidate.song.id)
        progress = cumulative / target_seconds if target_seconds > 0 else 0

        if arc == "build":
            phase = "intro" if progress < 0.25 else ("build" if progress < 0.75 else "peak")
        elif arc == "peak":
            phase = "peak"
        elif arc == "varied":
            phase = "intro" if progress < 0.15 else ("steady" if progress < 0.85 else "cooldown")
        else:
            phase = "steady"

        cumulative += candidate.song.duration_seconds
        tracks.append(
            PlaylistTrack(
                position=position,
                song=candidate.song,
                score=candidate.score,
                phase=phase,
                cumulative_duration_seconds=cumulative,
            )
        )
        position += 1

    playlist = Playlist(
        activity=activity,
        activity_label=profile.label,
        target_duration_minutes=target_duration_minutes,
        actual_duration_seconds=cumulative,
        tracks=tracks,
        energy_arc=arc,
    )

    return {
        "activity": playlist.activity,
        "activity_label": playlist.activity_label,
        "target_duration_minutes": playlist.target_duration_minutes,
        "actual_duration": playlist.actual_duration_display,
        "actual_duration_seconds": playlist.actual_duration_seconds,
        "track_count": playlist.track_count,
        "energy_arc": playlist.energy_arc,
        "tracks": [
            {
                "position": t.position,
                "title": t.song.title,
                "artist": t.song.artist,
                "bpm": t.song.bpm,
                "energy": t.song.energy,
                "duration": t.song.duration_display,
                "duration_seconds": t.song.duration_seconds,
                "phase": t.phase,
                "fit_score": t.score,
                "cumulative_time": _fmt(t.cumulative_duration_seconds),
                "genres": t.song.genres,
                "moods": t.song.moods,
            }
            for t in playlist.tracks
        ],
    }


# ---------------------------------------------------------------------------
# Tool 4 — ExplainRecommendation
# ---------------------------------------------------------------------------


@app.tool
def explain_recommendation(
    song_title: Annotated[str, "Title of the song to explain (case-insensitive partial match)."],
    song_artist: Annotated[str, "Artist name of the song (case-insensitive partial match)."],
    activity: Annotated[str, "Activity to explain the fit for, e.g. 'yard work', 'running'."],
) -> dict:
    """Explain why a specific song does or does not fit an activity.

    Returns a detailed breakdown of BPM fit, energy fit, mood alignment,
    and genre alignment, plus an overall verdict with natural-language reasoning.

    Useful for understanding recommendations and for evaluation/debugging.
    """
    songs = load_songs()
    title_lower = song_title.lower()
    artist_lower = song_artist.lower()
    matches = [
        s for s in songs
        if title_lower in s.title.lower() and artist_lower in s.artist.lower()
    ]

    if not matches:
        return {
            "error": f"Song '{song_title}' by '{song_artist}' not found in database.",
            "suggestion": "Check spelling or try a partial match.",
        }

    song = matches[0]
    profile = get_activity_profile(activity)
    if profile is None:
        return {
            "error": f"No profile found for '{activity}'.",
            "supported_activities": list_supported_activities(),
        }

    scored = score_song(song, profile)

    bpm_lo, bpm_hi = profile.bpm_range
    bpm_ok = bpm_lo <= song.bpm <= bpm_hi
    bpm_verdict = (
        f"PASS  BPM {song.bpm} is within ideal range {bpm_lo}–{bpm_hi}."
        if bpm_ok
        else f"FAIL  BPM {song.bpm} is {'too fast' if song.bpm > bpm_hi else 'too slow'} "
        f"for {profile.label} (ideal: {bpm_lo}–{bpm_hi})."
    )

    e_lo, e_hi = profile.energy_range
    e_ok = e_lo <= song.energy <= e_hi
    energy_verdict = (
        f"PASS  Energy {song.energy}/9 fits range {e_lo}–{e_hi}."
        if e_ok
        else f"FAIL  Energy {song.energy}/9 is too "
        f"{'high' if song.energy > e_hi else 'low'} for {profile.label} (ideal: {e_lo}–{e_hi})."
    )

    song_moods = set(song.moods)
    excluded_hits = song_moods & set(profile.excluded_moods)
    preferred_hits = song_moods & set(profile.preferred_moods)

    if excluded_hits:
        mood_verdict = (
            f"FAIL  Mood '{', '.join(sorted(excluded_hits))}' is excluded for {profile.label}. "
            "This disqualifies the song."
        )
    elif preferred_hits:
        mood_verdict = f"PASS  Mood overlap: {', '.join(sorted(preferred_hits))}."
    else:
        mood_verdict = f"WARN  No mood overlap with {profile.label}."

    song_genres = set(song.genres)
    genre_hits = song_genres & set(profile.preferred_genres)
    genre_verdict = (
        f"PASS  Genre match: {', '.join(sorted(genre_hits))}."
        if genre_hits
        else f"WARN  Genre(s) '{', '.join(sorted(song_genres))}' not in preferred list for {profile.label}."
    )

    if scored.score >= 0.75:
        verdict, summary = "Excellent fit", f"'{song.title}' is a great match for {profile.label}."
    elif scored.score >= 0.5:
        verdict, summary = "Good fit", f"'{song.title}' fits well for {profile.label} with minor trade-offs."
    elif scored.score >= 0.25:
        verdict, summary = "Marginal fit", f"'{song.title}' has partial alignment with {profile.label}."
    else:
        verdict = "Poor fit"
        summary = (
            f"'{song.title}' is not a good match for {profile.label}. "
            + (f"Key issue: excluded mood '{', '.join(sorted(excluded_hits))}'." if excluded_hits else "")
        )

    return {
        "song": {
            "title": song.title,
            "artist": song.artist,
            "bpm": song.bpm,
            "energy": song.energy,
            "genres": song.genres,
            "moods": song.moods,
        },
        "activity": activity,
        "activity_label": profile.label,
        "fit_score": scored.score,
        "verdict": verdict,
        "summary": summary,
        "breakdown": {
            "bpm": bpm_verdict,
            "energy": energy_verdict,
            "mood": mood_verdict,
            "genre": genre_verdict,
        },
        "match_reasons": scored.match_reasons,
        "mismatch_reasons": scored.mismatch_reasons,
    }


# ---------------------------------------------------------------------------
# Tool 5 — CreateSpotifyPlaylist
# ---------------------------------------------------------------------------

SPOTIFY_API = "https://api.spotify.com/v1"


@app.tool
async def create_spotify_playlist(
    activity: Annotated[str, "Activity name the playlist is for, e.g. 'yard work', 'running'."],
    target_duration_minutes: Annotated[int, "Desired playlist length in minutes. Default 45."] = 45,
    playlist_name: Annotated[str, "Custom playlist name. Defaults to an auto-generated name."] = "",
    public: Annotated[bool, "Whether the Spotify playlist should be public. Default True."] = True,
) -> dict:
    """Curate a playlist and create it directly in the user's Spotify account.

    Combines curate_playlist with Spotify's API to:
    1. Curate the best songs for the activity
    2. Search Spotify for each song to get track URIs
    3. Create a new playlist in the user's account
    4. Add all matched tracks to the playlist
    5. Return the Spotify playlist URL

    Requires a valid SPOTIFY_ACCESS_TOKEN in the environment or .env file.
    Get a token at: https://developer.spotify.com/console/post-playlists
    """

    token = os.environ.get("SPOTIFY_ACCESS_TOKEN", "")
    if not token:
        return {
            "error": "No Spotify token found. Set SPOTIFY_ACCESS_TOKEN in your .env file.",
            "how_to_get_token": "Visit https://developer.spotify.com/console/post-playlists, click 'Get Token', check playlist-modify-public scope, copy the token into .env",
        }

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    # Step 1: curate the playlist using our existing logic
    playlist_data = curate_playlist(activity, target_duration_minutes)
    if "error" in playlist_data:
        return playlist_data

    tracks = playlist_data["tracks"]
    activity_label = playlist_data["activity_label"]

    # Step 2: get the current Spotify user ID
    async with httpx.AsyncClient() as client:
        me_resp = await client.get(f"{SPOTIFY_API}/me", headers=headers)
        if me_resp.status_code != 200:
            return {
                "error": "Failed to get Spotify user profile.",
                "spotify_status": me_resp.status_code,
                "detail": me_resp.text,
            }
        user_id = me_resp.json()["id"]

        # Step 3: search Spotify for each track and collect URIs
        track_uris: list[str] = []
        matched: list[dict] = []
        unmatched: list[dict] = []

        for track in tracks:
            query = f"track:{track['title']} artist:{track['artist']}"
            search_resp = await client.get(
                f"{SPOTIFY_API}/search",
                headers=headers,
                params={"q": query, "type": "track", "limit": 1},
            )
            if search_resp.status_code == 200:
                items = search_resp.json().get("tracks", {}).get("items", [])
                if items:
                    spotify_track = items[0]
                    track_uris.append(spotify_track["uri"])
                    matched.append({
                        "position": track["position"],
                        "title": track["title"],
                        "artist": track["artist"],
                        "spotify_uri": spotify_track["uri"],
                        "spotify_url": spotify_track["external_urls"].get("spotify", ""),
                    })
                else:
                    # Fallback: try a looser query without field filters
                    loose_resp = await client.get(
                        f"{SPOTIFY_API}/search",
                        headers=headers,
                        params={"q": f"{track['title']} {track['artist']}", "type": "track", "limit": 1},
                    )
                    loose_items = loose_resp.json().get("tracks", {}).get("items", []) if loose_resp.status_code == 200 else []
                    if loose_items:
                        spotify_track = loose_items[0]
                        track_uris.append(spotify_track["uri"])
                        matched.append({
                            "position": track["position"],
                            "title": track["title"],
                            "artist": track["artist"],
                            "spotify_uri": spotify_track["uri"],
                            "spotify_url": spotify_track["external_urls"].get("spotify", ""),
                        })
                    else:
                        unmatched.append({"title": track["title"], "artist": track["artist"]})

        if not track_uris:
            return {
                "error": "Could not find any tracks on Spotify.",
                "unmatched": unmatched,
            }

        # Step 4: create the Spotify playlist
        name = playlist_name or f"{activity_label} Mix · {target_duration_minutes} min"
        description = (
            f"Curated by arcade-audio-curator for {activity_label}. "
            f"{len(matched)} tracks · ~{target_duration_minutes} min."
        )

        create_resp = await client.post(
            f"{SPOTIFY_API}/users/{user_id}/playlists",
            headers=headers,
            json={"name": name, "description": description, "public": public},
        )
        if create_resp.status_code not in (200, 201):
            return {
                "error": "Failed to create Spotify playlist.",
                "spotify_status": create_resp.status_code,
                "detail": create_resp.text,
            }

        playlist_id = create_resp.json()["id"]
        playlist_url = create_resp.json()["external_urls"].get("spotify", "")

        # Step 5: add tracks (Spotify allows max 100 per request)
        for i in range(0, len(track_uris), 100):
            batch = track_uris[i:i + 100]
            await client.post(
                f"{SPOTIFY_API}/playlists/{playlist_id}/tracks",
                headers=headers,
                json={"uris": batch},
            )

    return {
        "success": True,
        "playlist_name": name,
        "playlist_url": playlist_url,
        "playlist_id": playlist_id,
        "tracks_added": len(matched),
        "tracks_not_found": len(unmatched),
        "matched_tracks": matched,
        "unmatched_tracks": unmatched,
        "activity": activity,
        "activity_label": activity_label,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fmt(total_seconds: int) -> str:
    minutes, seconds = divmod(total_seconds, 60)
    return f"{minutes}:{seconds:02d}"


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    transport = sys.argv[1] if len(sys.argv) > 1 else "stdio"
    app.run(transport=transport, host="127.0.0.1", port=8000)
