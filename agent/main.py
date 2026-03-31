#!/usr/bin/env python3
"""
arcade-audio-curator agent CLI

Uses Claude claude-sonnet-4 to orchestrate calls to the MCP tools and produce
a human-friendly playlist output.

Usage:
    python agent/main.py "make me a 45 minute playlist for yard work"
    python agent/main.py "I'm going for a run, give me high energy music for 30 minutes"
    python agent/main.py --explain "One More Time" "Daft Punk" "yard work"
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Add src to path so we can import the toolkit directly for tool execution
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from arcade_audio_curator.database import get_activity_profile, list_supported_activities
from arcade_audio_curator.server import (
    curate_playlist,
    explain_recommendation,
    filter_songs_by_profile,
    get_activity_profile_tool,
)

try:
    import anthropic
except ImportError:
    print("ERROR: anthropic package not installed. Run: pip install anthropic")
    sys.exit(1)


SYSTEM_PROMPT = """You are an expert music curator assistant powered by the arcade-audio-curator toolkit.

You have access to four tools:
1. get_activity_profile_tool(activity) — get musical constraints for an activity
2. filter_songs_by_profile(activity, min_score, limit) — find matching songs
3. curate_playlist(activity, target_duration_minutes, min_score) — build a sequenced playlist
4. explain_recommendation(song_title, song_artist, activity) — explain a song's fit

When a user asks for a playlist:
1. First call get_activity_profile_tool to understand constraints
2. Then call curate_playlist with appropriate duration
3. Format the result as a readable playlist with clear track listing

When explaining a recommendation, call explain_recommendation and present the verdict clearly.

Always be specific about why songs were chosen — reference BPM, mood, genre fit.
If the user mentions an activity not in the supported list, map it to the closest match.
"""

TOOL_DEFINITIONS = [
    {
        "name": "get_activity_profile_tool",
        "description": "Get musical constraints (BPM range, genres, moods) for a physical activity.",
        "input_schema": {
            "type": "object",
            "properties": {
                "activity": {
                    "type": "string",
                    "description": "Activity name e.g. 'yard work', 'running', 'cooking'",
                }
            },
            "required": ["activity"],
        },
    },
    {
        "name": "filter_songs_by_profile",
        "description": "Filter and rank songs from the database that fit a given activity.",
        "input_schema": {
            "type": "object",
            "properties": {
                "activity": {"type": "string"},
                "min_score": {
                    "type": "number",
                    "description": "Minimum fit score 0.0–1.0, default 0.4",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max songs to return, default 20",
                },
            },
            "required": ["activity"],
        },
    },
    {
        "name": "curate_playlist",
        "description": "Curate a sequenced playlist for an activity with a target duration.",
        "input_schema": {
            "type": "object",
            "properties": {
                "activity": {"type": "string"},
                "target_duration_minutes": {
                    "type": "integer",
                    "description": "Desired playlist length in minutes, default 45",
                },
                "min_score": {
                    "type": "number",
                    "description": "Minimum fit score, default 0.45",
                },
            },
            "required": ["activity"],
        },
    },
    {
        "name": "explain_recommendation",
        "description": "Explain why a specific song does or does not fit an activity.",
        "input_schema": {
            "type": "object",
            "properties": {
                "song_title": {"type": "string"},
                "song_artist": {"type": "string"},
                "activity": {"type": "string"},
            },
            "required": ["song_title", "song_artist", "activity"],
        },
    },
]

TOOL_FUNCTIONS = {
    "get_activity_profile_tool": get_activity_profile_tool,
    "filter_songs_by_profile": filter_songs_by_profile,
    "curate_playlist": curate_playlist,
    "explain_recommendation": explain_recommendation,
}


def call_tool(name: str, inputs: dict) -> str:
    """Execute a tool and return JSON string result."""
    fn = TOOL_FUNCTIONS.get(name)
    if fn is None:
        return json.dumps({"error": f"Unknown tool: {name}"})
    result = fn(**inputs)
    return json.dumps(result, indent=2)


def run_agent(user_message: str, verbose: bool = False) -> None:
    """Run the agentic loop: Claude calls tools until it has a final answer."""
    client = anthropic.Anthropic()
    messages = [{"role": "user", "content": user_message}]

    print(f"\n🎵 arcade-audio-curator\n{'─' * 50}")
    if verbose:
        print(f"Request: {user_message}\n")

    while True:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            tools=TOOL_DEFINITIONS,
            messages=messages,
        )

        # Collect assistant message content
        assistant_content = response.content
        messages.append({"role": "assistant", "content": assistant_content})

        # Check stop reason
        if response.stop_reason == "end_turn":
            # Extract and print final text response
            for block in assistant_content:
                if hasattr(block, "text"):
                    print(block.text)
            break

        if response.stop_reason == "tool_use":
            # Execute all tool calls in this turn
            tool_results = []
            for block in assistant_content:
                if block.type == "tool_use":
                    if verbose:
                        print(f"  → calling {block.name}({json.dumps(block.input)})")
                    result = call_tool(block.name, block.input)
                    if verbose:
                        parsed = json.loads(result)
                        preview = json.dumps(parsed, indent=2)[:300]
                        print(f"  ← {preview}{'...' if len(preview) == 300 else ''}\n")
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result,
                    })

            messages.append({"role": "user", "content": tool_results})
        else:
            # Unexpected stop reason
            print(f"Unexpected stop reason: {response.stop_reason}")
            break


def main() -> None:
    parser = argparse.ArgumentParser(
        description="arcade-audio-curator: AI-powered activity playlist generator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s "make me a 45 minute playlist for yard work"
  %(prog)s "I'm going for a morning run, 30 minutes, high energy"
  %(prog)s "dinner party music for 2 hours"
  %(prog)s --explain "One More Time" "Daft Punk" "yard work"
  %(prog)s --list-activities
        """,
    )
    parser.add_argument(
        "request",
        nargs="?",
        help="Natural language playlist request",
    )
    parser.add_argument(
        "--explain",
        nargs=3,
        metavar=("TITLE", "ARTIST", "ACTIVITY"),
        help="Explain why TITLE by ARTIST fits (or doesn't) ACTIVITY",
    )
    parser.add_argument(
        "--list-activities",
        action="store_true",
        help="List all supported activities",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Show tool calls and raw results",
    )

    args = parser.parse_args()

    if args.list_activities:
        activities = list_supported_activities()
        print("\nSupported activities:")
        for a in activities:
            profile = get_activity_profile(a)
            print(f"  • {a:<20} {profile.description if profile else ''}")
        return

    if args.explain:
        title, artist, activity = args.explain
        request = f"Explain why '{title}' by {artist} does or doesn't fit '{activity}'"
        run_agent(request, verbose=args.verbose)
        return

    if args.request:
        run_agent(args.request, verbose=args.verbose)
        return

    parser.print_help()


if __name__ == "__main__":
    main()
