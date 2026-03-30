"""
Tests for arcade-audio-curator toolkit.

Covers: database loading, scoring engine, all four MCP tools,
edge cases, and regression tests for the Daft Punk / yard work problem.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from arcade_audio_curator.database import (
    get_activity_profile,
    list_supported_activities,
    load_songs,
)
from arcade_audio_curator.models import ActivityProfile, Song
from arcade_audio_curator.scoring import rank_songs, score_song
from arcade_audio_curator.server import (
    curate_playlist,
    explain_recommendation,
    filter_songs_by_profile,
    get_activity_profile_tool,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def yard_work_profile() -> ActivityProfile:
    profile = get_activity_profile("yard work")
    assert profile is not None
    return profile


@pytest.fixture
def running_profile() -> ActivityProfile:
    profile = get_activity_profile("running")
    assert profile is not None
    return profile


@pytest.fixture
def all_songs() -> list[Song]:
    return load_songs()


@pytest.fixture
def daft_punk_one_more_time(all_songs) -> Song:
    song = next((s for s in all_songs if "One More Time" in s.title and "Daft Punk" in s.artist), None)
    assert song is not None, "One More Time by Daft Punk must be in database"
    return song


@pytest.fixture
def jack_johnson_banana_pancakes(all_songs) -> Song:
    song = next((s for s in all_songs if "Banana Pancakes" in s.title), None)
    assert song is not None
    return song


# ---------------------------------------------------------------------------
# Database tests
# ---------------------------------------------------------------------------


class TestDatabase:
    def test_songs_load(self, all_songs):
        assert len(all_songs) >= 80, "Database should have at least 80 songs"

    def test_songs_have_required_fields(self, all_songs):
        for song in all_songs:
            assert song.id
            assert song.title
            assert song.artist
            assert 40 <= song.bpm <= 220, f"BPM out of range for {song.title}: {song.bpm}"
            assert 1 <= song.energy <= 9, f"Energy out of range for {song.title}: {song.energy}"
            assert len(song.genres) >= 1
            assert len(song.moods) >= 1
            assert song.duration_seconds > 0

    def test_song_ids_unique(self, all_songs):
        ids = [s.id for s in all_songs]
        assert len(ids) == len(set(ids)), "All song IDs must be unique"

    def test_activity_profiles_load(self):
        profiles = list_supported_activities()
        assert len(profiles) >= 8

    def test_required_activities_present(self):
        required = ["yard work", "running", "cooking", "studying"]
        for act in required:
            profile = get_activity_profile(act)
            assert profile is not None, f"Profile missing for '{act}'"

    def test_activity_profile_partial_match(self):
        # "yard" should match "yard work"
        profile = get_activity_profile("yard")
        assert profile is not None

    def test_activity_profile_unknown_returns_none(self):
        profile = get_activity_profile("skydiving at night")
        assert profile is None

    def test_song_duration_display(self, jack_johnson_banana_pancakes):
        song = jack_johnson_banana_pancakes
        display = song.duration_display
        assert ":" in display
        minutes, seconds = display.split(":")
        assert int(minutes) >= 0
        assert 0 <= int(seconds) < 60


# ---------------------------------------------------------------------------
# Scoring engine tests
# ---------------------------------------------------------------------------


class TestScoring:
    def test_daft_punk_scores_low_for_yard_work(self, daft_punk_one_more_time, yard_work_profile):
        """Regression test: euphoric/intense songs must not score well for yard work."""
        scored = score_song(daft_punk_one_more_time, yard_work_profile)
        assert scored.score == 0.0, (
            f"Daft Punk 'One More Time' should score 0.0 for yard work "
            f"(euphoric mood excluded), got {scored.score}"
        )
        assert len(scored.mismatch_reasons) > 0

    def test_jack_johnson_scores_well_for_yard_work(self, jack_johnson_banana_pancakes, yard_work_profile):
        scored = score_song(jack_johnson_banana_pancakes, yard_work_profile)
        assert scored.score >= 0.5, (
            f"Jack Johnson 'Banana Pancakes' should score >= 0.5 for yard work, "
            f"got {scored.score}"
        )

    def test_score_in_valid_range(self, all_songs, yard_work_profile):
        for song in all_songs:
            scored = score_song(song, yard_work_profile)
            assert 0.0 <= scored.score <= 1.0, f"Score out of range for {song.title}: {scored.score}"

    def test_ranking_is_descending(self, all_songs, yard_work_profile):
        ranked = rank_songs(all_songs, yard_work_profile)
        scores = [s.score for s in ranked]
        assert scores == sorted(scores, reverse=True), "rank_songs must return descending order"

    def test_excluded_mood_is_hard_zero(self, all_songs, yard_work_profile):
        """Any song with an excluded mood must score exactly 0.0."""
        excluded = set(yard_work_profile.excluded_moods)
        for song in all_songs:
            if set(song.moods) & excluded:
                scored = score_song(song, yard_work_profile)
                assert scored.score == 0.0, (
                    f"{song.title} has excluded mood but scored {scored.score}"
                )

    def test_bpm_out_of_range_reduces_score(self, yard_work_profile):
        """A song with BPM way outside range should score lower than one in range."""
        songs = load_songs()
        in_range = [s for s in songs if yard_work_profile.bpm_range[0] <= s.bpm <= yard_work_profile.bpm_range[1]]
        out_of_range = [s for s in songs if s.bpm > 160]

        if in_range and out_of_range:
            avg_in = sum(score_song(s, yard_work_profile).score for s in in_range) / len(in_range)
            # Filter out excluded songs before comparing
            out_scored = [score_song(s, yard_work_profile).score for s in out_of_range]
            out_nonzero = [sc for sc in out_scored if sc > 0]
            if out_nonzero:
                avg_out = sum(out_nonzero) / len(out_nonzero)
                assert avg_in >= avg_out, "Songs in BPM range should score higher on average"

    def test_running_prefers_high_energy(self, running_profile):
        songs = load_songs()
        ranked = rank_songs(songs, running_profile)
        top5 = [s for s in ranked[:5] if s.score > 0]
        avg_energy = sum(s.song.energy for s in top5) / len(top5)
        assert avg_energy >= 6, f"Top songs for running should have high energy, got avg {avg_energy}"

    def test_match_reasons_populated_for_good_fit(self, jack_johnson_banana_pancakes, yard_work_profile):
        scored = score_song(jack_johnson_banana_pancakes, yard_work_profile)
        assert len(scored.match_reasons) > 0

    def test_mismatch_reasons_populated_for_excluded(self, daft_punk_one_more_time, yard_work_profile):
        scored = score_song(daft_punk_one_more_time, yard_work_profile)
        assert len(scored.mismatch_reasons) > 0
        assert any("excluded" in r.lower() or "mood" in r.lower() for r in scored.mismatch_reasons)


# ---------------------------------------------------------------------------
# MCP tool tests
# ---------------------------------------------------------------------------


class TestGetActivityProfileTool:
    def test_returns_profile_for_known_activity(self):
        result = get_activity_profile_tool("yard work")
        assert "error" not in result
        assert result["label"] == "Yard Work"
        assert "bpm_range" in result
        assert "preferred_genres" in result
        assert "excluded_moods" in result

    def test_returns_error_for_unknown_activity(self):
        result = get_activity_profile_tool("underwater basket weaving")
        assert "error" in result
        assert "supported_activities" in result

    def test_energy_arc_present(self):
        result = get_activity_profile_tool("running")
        assert "energy_arc" in result
        assert result["energy_arc"] in ("steady", "build", "peak", "varied")

    def test_yard_work_excludes_intense_moods(self):
        result = get_activity_profile_tool("yard work")
        assert "intense" in result["excluded_moods"] or "euphoric" in result["excluded_moods"]


class TestFilterSongsByProfile:
    def test_returns_songs_above_threshold(self):
        result = filter_songs_by_profile("yard work", min_score=0.4)
        assert "error" not in result
        assert result["returned"] > 0
        for song in result["songs"]:
            assert song["fit_score"] >= 0.4

    def test_results_sorted_by_score(self):
        result = filter_songs_by_profile("yard work")
        scores = [s["fit_score"] for s in result["songs"]]
        assert scores == sorted(scores, reverse=True)

    def test_daft_punk_not_in_yard_work_results(self):
        result = filter_songs_by_profile("yard work", min_score=0.01)
        titles = [s["title"] for s in result["songs"]]
        # "One More Time" is excluded (euphoric mood)
        assert "One More Time" not in titles

    def test_respects_limit(self):
        result = filter_songs_by_profile("yard work", limit=5)
        assert result["returned"] <= 5

    def test_limit_capped_at_50(self):
        result = filter_songs_by_profile("yard work", limit=999)
        assert result["returned"] <= 50

    def test_error_on_unknown_activity(self):
        result = filter_songs_by_profile("zorbing")
        assert "error" in result

    def test_songs_have_required_fields(self):
        result = filter_songs_by_profile("cooking")
        required_keys = {"id", "title", "artist", "bpm", "energy", "fit_score", "duration"}
        for song in result["songs"]:
            assert required_keys.issubset(song.keys())


class TestCuratePlaylist:
    def test_returns_playlist_for_known_activity(self):
        result = curate_playlist("yard work", target_duration_minutes=30)
        assert "error" not in result
        assert result["track_count"] > 0

    def test_duration_is_close_to_target(self):
        target = 45
        result = curate_playlist("yard work", target_duration_minutes=target)
        actual_minutes = result["actual_duration_seconds"] / 60
        # Allow up to one song length of overshoot (~7 minutes)
        assert actual_minutes >= target * 0.7, "Playlist too short"
        assert actual_minutes <= target + 10, "Playlist too long"

    def test_no_duplicate_tracks(self):
        result = curate_playlist("yard work", target_duration_minutes=60)
        ids = [t["title"] + t["artist"] for t in result["tracks"]]
        assert len(ids) == len(set(ids)), "Playlist must not have duplicate tracks"

    def test_tracks_have_phase_labels(self):
        result = curate_playlist("morning workout", target_duration_minutes=30)
        valid_phases = {"intro", "build", "peak", "cooldown", "steady"}
        for track in result["tracks"]:
            assert track["phase"] in valid_phases

    def test_positions_sequential(self):
        result = curate_playlist("cooking", target_duration_minutes=30)
        positions = [t["position"] for t in result["tracks"]]
        assert positions == list(range(1, len(positions) + 1))

    def test_cumulative_time_increases(self):
        result = curate_playlist("running", target_duration_minutes=20)
        # duration_seconds used per-track in loop below
        cumulative = 0
        for i, track in enumerate(result["tracks"]):
            cumulative += track["duration_seconds"]
            displayed = track["cumulative_time"]
            mins, secs = displayed.split(":")
            displayed_seconds = int(mins) * 60 + int(secs)
            assert displayed_seconds == cumulative, f"Cumulative time mismatch at position {i+1}"

    def test_error_on_unknown_activity(self):
        result = curate_playlist("ice fishing in space")
        assert "error" in result

    def test_energy_arc_in_result(self):
        result = curate_playlist("yard work")
        assert result["energy_arc"] in ("steady", "build", "peak", "varied")

    def test_all_track_scores_above_min(self):
        min_score = 0.5
        result = curate_playlist("yard work", min_score=min_score)
        for track in result["tracks"]:
            assert track["fit_score"] >= min_score


class TestExplainRecommendation:
    def test_explains_daft_punk_for_yard_work(self):
        result = explain_recommendation("One More Time", "Daft Punk", "yard work")
        assert "error" not in result
        assert result["fit_score"] == 0.0
        assert "Poor fit" in result["verdict"] or result["fit_score"] < 0.3
        # Breakdown should mention mood exclusion
        mood_breakdown = result["breakdown"]["mood"]
        assert "FAIL" in mood_breakdown or "excluded" in mood_breakdown.lower()

    def test_explains_jack_johnson_for_yard_work(self):
        result = explain_recommendation("Banana Pancakes", "Jack Johnson", "yard work")
        assert "error" not in result
        assert result["fit_score"] >= 0.5
        assert result["verdict"] in ("Good fit", "Excellent fit")

    def test_returns_error_for_unknown_song(self):
        result = explain_recommendation("Imaginary Song XYZ", "Unknown Artist", "yard work")
        assert "error" in result

    def test_returns_error_for_unknown_activity(self):
        result = explain_recommendation("Banana Pancakes", "Jack Johnson", "deep sea welding")
        assert "error" in result

    def test_breakdown_has_all_dimensions(self):
        result = explain_recommendation("Africa", "Toto", "yard work")
        assert "breakdown" in result
        for dim in ("bpm", "energy", "mood", "genre"):
            assert dim in result["breakdown"]

    def test_summary_is_nonempty_string(self):
        result = explain_recommendation("Take It Easy", "Eagles", "road trip")
        assert isinstance(result.get("summary"), str)
        assert len(result["summary"]) > 0

    def test_partial_title_match(self):
        # "Take It" should match "Take It Easy"
        result = explain_recommendation("Take It", "Eagles", "road trip")
        assert "error" not in result
        assert result["song"]["title"] == "Take It Easy"


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------


class TestIntegration:
    def test_pipeline_yard_work(self):
        """Full pipeline: profile → filter → playlist, yard work."""
        profile_result = get_activity_profile_tool("yard work")
        assert "error" not in profile_result

        filter_result = filter_songs_by_profile("yard work", min_score=0.4, limit=20)
        assert filter_result["returned"] > 0

        playlist_result = curate_playlist("yard work", target_duration_minutes=30)
        assert playlist_result["track_count"] > 0

        # Every playlist song should be in the filter results

        for track in playlist_result["tracks"]:
            # Find song id from filter results by title+artist match
            matched = next(
                (s for s in filter_result["songs"]
                 if s["title"] == track["title"] and s["artist"] == track["artist"]),
                None,
            )
            assert matched is not None, (
                f"Playlist track '{track['title']}' not found in filter results"
            )

    def test_pipeline_running(self):
        """Full pipeline for running — high energy activity."""
        playlist = curate_playlist("running", target_duration_minutes=25)
        assert playlist["track_count"] >= 4
        avg_energy = sum(t["energy"] for t in playlist["tracks"]) / len(playlist["tracks"])
        assert avg_energy >= 6, f"Running playlist should have high avg energy, got {avg_energy:.1f}"

    def test_genre_context_matters_more_than_bpm_alone(self):
        """
        Regression: 'Get Lucky' by Daft Punk (BPM 116, funk/dance) should score
        better than 'One More Time' (BPM 123, electronic/house) for yard work,
        because Get Lucky is groovy/happy while One More Time is euphoric.
        """
        songs = load_songs()
        profile = get_activity_profile("yard work")

        get_lucky = next((s for s in songs if "Get Lucky" in s.title), None)
        one_more_time = next((s for s in songs if "One More Time" in s.title), None)

        if get_lucky and one_more_time and profile:
            scored_lucky = score_song(get_lucky, profile)
            scored_omt = score_song(one_more_time, profile)
            assert scored_lucky.score > scored_omt.score, (
                f"Get Lucky ({scored_lucky.score}) should outscore "
                f"One More Time ({scored_omt.score}) for yard work"
            )


# ---------------------------------------------------------------------------
# Spotify tool tests (mocked — no real Spotify credentials needed)
# ---------------------------------------------------------------------------




class TestCreateSpotifyPlaylist:
    """Tests for the Spotify integration tool.

    These tests mock the Spotify API and patch the env token so no real
    credentials are needed in CI.
    """

    def _make_spotify_track(self, title: str, artist: str, idx: int = 1) -> dict:
        return {
            "uri": f"spotify:track:mock{idx:04d}",
            "external_urls": {"spotify": f"https://open.spotify.com/track/mock{idx:04d}"},
            "name": title,
            "artists": [{"name": artist}],
        }

    @pytest.mark.asyncio
    async def test_returns_error_without_token(self, monkeypatch):
        """Tool must return error dict when no Spotify token is present."""
        from arcade_audio_curator.server import create_spotify_playlist
        monkeypatch.delenv("SPOTIFY_ACCESS_TOKEN", raising=False)

        result = await create_spotify_playlist("yard work")
        assert "error" in result
        assert "SPOTIFY_ACCESS_TOKEN" in result["error"]

    @pytest.mark.asyncio
    async def test_returns_error_for_unknown_activity(self, monkeypatch):
        """Tool must return error when activity is not found."""
        import httpx as _httpx
        import respx

        from arcade_audio_curator.server import create_spotify_playlist
        monkeypatch.setenv("SPOTIFY_ACCESS_TOKEN", "mock-token")

        with respx.mock:
            respx.get("https://api.spotify.com/v1/me").mock(
                return_value=_httpx.Response(200, json={"id": "mock_user"})
            )
            result = await create_spotify_playlist("underwater basket weaving")

        assert "error" in result

    @pytest.mark.asyncio
    async def test_successful_playlist_creation(self, monkeypatch):
        """Happy path: all tracks found, playlist created, URL returned."""
        import httpx as _httpx
        import respx

        from arcade_audio_curator.server import create_spotify_playlist
        monkeypatch.setenv("SPOTIFY_ACCESS_TOKEN", "mock-token")

        playlist_data = curate_playlist("yard work", target_duration_minutes=15)
        tracks = playlist_data["tracks"]

        with respx.mock:
            respx.get("https://api.spotify.com/v1/me").mock(
                return_value=_httpx.Response(200, json={"id": "mock_user"})
            )
            for i, t in enumerate(tracks):
                respx.get("https://api.spotify.com/v1/search").mock(
                    return_value=_httpx.Response(200, json={
                        "tracks": {"items": [self._make_spotify_track(t["title"], t["artist"], i)]}
                    })
                )
            respx.post("https://api.spotify.com/v1/users/mock_user/playlists").mock(
                return_value=_httpx.Response(201, json={
                    "id": "mock_playlist_id",
                    "external_urls": {"spotify": "https://open.spotify.com/playlist/mockid"},
                })
            )
            respx.post("https://api.spotify.com/v1/playlists/mock_playlist_id/tracks").mock(
                return_value=_httpx.Response(201, json={"snapshot_id": "mock"})
            )

            result = await create_spotify_playlist("yard work", target_duration_minutes=15)

        assert result.get("success") is True
        assert "playlist_url" in result
        assert result["tracks_added"] > 0
        assert "open.spotify.com" in result["playlist_url"]

    @pytest.mark.asyncio
    async def test_unmatched_tracks_reported(self, monkeypatch):
        """Songs not found on Spotify (strict AND loose) appear in unmatched_tracks."""
        import httpx as _httpx
        import respx

        from arcade_audio_curator.server import create_spotify_playlist
        monkeypatch.setenv("SPOTIFY_ACCESS_TOKEN", "mock-token")

        call_count = {"n": 0}

        def search_side_effect(request, route):
            call_count["n"] += 1
            if call_count["n"] <= 2:
                return _httpx.Response(200, json={"tracks": {"items": []}})
            return _httpx.Response(200, json={
                "tracks": {"items": [self._make_spotify_track("Title", "Artist", call_count["n"])]}
            })

        with respx.mock:
            respx.get("https://api.spotify.com/v1/me").mock(
                return_value=_httpx.Response(200, json={"id": "mock_user"})
            )
            respx.get("https://api.spotify.com/v1/search").mock(side_effect=search_side_effect)
            respx.post("https://api.spotify.com/v1/users/mock_user/playlists").mock(
                return_value=_httpx.Response(201, json={
                    "id": "mock_playlist_id",
                    "external_urls": {"spotify": "https://open.spotify.com/playlist/mockid"},
                })
            )
            respx.post("https://api.spotify.com/v1/playlists/mock_playlist_id/tracks").mock(
                return_value=_httpx.Response(201, json={"snapshot_id": "mock"})
            )
            result = await create_spotify_playlist("yard work", target_duration_minutes=10)

        assert result.get("success") is True
        assert result["tracks_not_found"] >= 1

    @pytest.mark.asyncio
    async def test_custom_playlist_name(self, monkeypatch):
        """Custom playlist_name argument is used in the Spotify create call."""
        import json

        import httpx as _httpx
        import respx

        from arcade_audio_curator.server import create_spotify_playlist
        monkeypatch.setenv("SPOTIFY_ACCESS_TOKEN", "mock-token")

        playlist_data = curate_playlist("yard work", target_duration_minutes=10)
        tracks = playlist_data["tracks"]
        created_payload = {}

        def capture_create(request, route):
            created_payload.update(json.loads(request.content))
            return _httpx.Response(201, json={
                "id": "pid",
                "external_urls": {"spotify": "https://open.spotify.com/playlist/pid"},
            })

        with respx.mock:
            respx.get("https://api.spotify.com/v1/me").mock(
                return_value=_httpx.Response(200, json={"id": "u"})
            )
            for i, t in enumerate(tracks):
                respx.get("https://api.spotify.com/v1/search").mock(
                    return_value=_httpx.Response(200, json={
                        "tracks": {"items": [self._make_spotify_track(t["title"], t["artist"], i)]}
                    })
                )
            respx.post("https://api.spotify.com/v1/users/u/playlists").mock(side_effect=capture_create)
            respx.post("https://api.spotify.com/v1/playlists/pid/tracks").mock(
                return_value=_httpx.Response(201, json={"snapshot_id": "s"})
            )

            await create_spotify_playlist(
                "yard work", target_duration_minutes=10, playlist_name="My Custom Mix"
            )

        assert created_payload.get("name") == "My Custom Mix"
