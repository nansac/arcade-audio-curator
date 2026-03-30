"""
Arcade evals for arcade-audio-curator.

Tests that the LLM correctly selects and invokes tools in response
to natural language requests.

Run with: arcade evals run evals/eval_tools.py
"""

from __future__ import annotations

from arcade_tdk.evals import EvalRubric, EvalSuite, ExpectedToolCall, tool_eval

suite = EvalSuite(
    name="arcade-audio-curator evals",
    system_prompt=(
        "You are a music curator assistant. You have tools to get activity profiles, "
        "filter songs, curate playlists, and explain recommendations. "
        "Use the most appropriate tool for each request."
    ),
)

rubric = EvalRubric(
    fail_threshold=0.7,
    warn_threshold=0.9,
)


# ---------------------------------------------------------------------------
# GetActivityProfile evals
# ---------------------------------------------------------------------------


@tool_eval()
def eval_get_profile_yard_work():
    """User asks about yard work constraints — should call get_activity_profile_tool."""
    return suite.add_case(
        name="get_profile_yard_work",
        user_message="What kind of music works best for yard work?",
        expected_tool_calls=[
            ExpectedToolCall(
                func=get_activity_profile_tool,  # noqa: F821
                args={"activity": "yard work"},
            )
        ],
        rubric=rubric,
    )


@tool_eval()
def eval_get_profile_running():
    """User asks about running — should call get_activity_profile_tool."""
    return suite.add_case(
        name="get_profile_running",
        user_message="I'm going for a run. What BPM should my music be?",
        expected_tool_calls=[
            ExpectedToolCall(
                func=get_activity_profile_tool,  # noqa: F821
                args={"activity": "running"},
            )
        ],
        rubric=rubric,
    )


# ---------------------------------------------------------------------------
# CuratePlaylist evals
# ---------------------------------------------------------------------------


@tool_eval()
def eval_curate_playlist_yard_work():
    """Playlist request for yard work — should call curate_playlist."""
    return suite.add_case(
        name="curate_playlist_yard_work",
        user_message="Make me a 45 minute playlist for yard work.",
        expected_tool_calls=[
            ExpectedToolCall(
                func=curate_playlist,  # noqa: F821
                args={
                    "activity": "yard work",
                    "target_duration_minutes": 45,
                },
            )
        ],
        rubric=rubric,
    )


@tool_eval()
def eval_curate_playlist_with_duration():
    """Playlist with explicit duration — model should extract minutes correctly."""
    return suite.add_case(
        name="curate_playlist_30min_running",
        user_message="Give me 30 minutes of running music.",
        expected_tool_calls=[
            ExpectedToolCall(
                func=curate_playlist,  # noqa: F821
                args={
                    "activity": "running",
                    "target_duration_minutes": 30,
                },
            )
        ],
        rubric=rubric,
    )


@tool_eval()
def eval_curate_playlist_cooking():
    """Cooking playlist — must not use running or workout profile."""
    return suite.add_case(
        name="curate_playlist_cooking",
        user_message="I'm making dinner tonight, give me some good background music.",
        expected_tool_calls=[
            ExpectedToolCall(
                func=curate_playlist,  # noqa: F821
                args={"activity": "cooking"},
            )
        ],
        rubric=rubric,
    )


# ---------------------------------------------------------------------------
# ExplainRecommendation evals
# ---------------------------------------------------------------------------


@tool_eval()
def eval_explain_daft_punk_yard_work():
    """Explain why Daft Punk doesn't fit yard work — should call explain_recommendation."""
    return suite.add_case(
        name="explain_daft_punk_yard_work",
        user_message="Why wouldn't 'One More Time' by Daft Punk work for yard work?",
        expected_tool_calls=[
            ExpectedToolCall(
                func=explain_recommendation,  # noqa: F821
                args={
                    "song_title": "One More Time",
                    "song_artist": "Daft Punk",
                    "activity": "yard work",
                },
            )
        ],
        rubric=rubric,
    )


@tool_eval()
def eval_explain_good_fit():
    """Explain a good fit — Jack Johnson for yard work."""
    return suite.add_case(
        name="explain_jack_johnson_yard_work",
        user_message="Why is Jack Johnson's 'Banana Pancakes' good for yard work?",
        expected_tool_calls=[
            ExpectedToolCall(
                func=explain_recommendation,  # noqa: F821
                args={
                    "song_title": "Banana Pancakes",
                    "song_artist": "Jack Johnson",
                    "activity": "yard work",
                },
            )
        ],
        rubric=rubric,
    )


# ---------------------------------------------------------------------------
# FilterSongs evals
# ---------------------------------------------------------------------------


@tool_eval()
def eval_filter_songs_studying():
    """Browsing songs for studying — should call filter_songs_by_profile."""
    return suite.add_case(
        name="filter_songs_studying",
        user_message="Show me songs that work well for studying.",
        expected_tool_calls=[
            ExpectedToolCall(
                func=filter_songs_by_profile,  # noqa: F821
                args={"activity": "studying"},
            )
        ],
        rubric=rubric,
    )
