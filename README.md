# arcade-audio-curator

> An MCP server that curates activity-aware music playlists using **genre, mood, BPM, and energy level** — not tempo alone — and creates them directly in your Spotify account.

Built with [Arcade.dev](https://arcade.dev) as a take-home engineering project.

---

## The Problem

Most music recommendation systems treat BPM as a proxy for intensity. But BPM alone is a bad signal:

- Daft Punk's *One More Time* is **wrong** for yard work — not because of its 123 BPM, but because it's *euphoric* and *intense*. Those moods are excluded for that activity.
- Jack Johnson's *Banana Pancakes* is **right** for yard work — warm, acoustic, laid-back, outdoorsy.

`arcade-audio-curator` solves this by reasoning about **activity → genre/mood constraints → BPM within that context**.

---

## Demo

Ask Claude Desktop (with this MCP server connected):

> *"Create a 30 minute yard work playlist in Spotify"*

Result: [🎵 Open the actual generated playlist](https://open.spotify.com/playlist/7MGPcZfyceIh9XJZWbBhg4)

---

## MCP Tools

| Tool | Description |
|------|-------------|
| `get_activity_profile_tool` | Maps an activity → musical constraints (BPM range, genres, moods, energy arc) |
| `filter_songs_by_profile` | Scores and ranks songs against an activity profile with fit reasoning |
| `curate_playlist` | Assembles a sequenced playlist shaped by the activity's energy arc |
| `explain_recommendation` | Explains why a specific song does or doesn't fit an activity |
| `create_spotify_playlist` | Curates a playlist and creates it directly in your Spotify account |

### Scoring breakdown

Each song is scored across four dimensions:

| Dimension | Weight | Logic |
|-----------|--------|-------|
| BPM fit | 30 pts | Full score within range; scaled penalty outside |
| Energy fit | 25 pts | Full score within range; scaled penalty outside |
| Mood overlap | 30 pts | Proportional overlap with preferred moods. **Excluded moods = hard 0.0 override** |
| Genre overlap | 15 pts | Proportional overlap with preferred genres |

Total normalized to 0.0–1.0. The hard 0.0 override on excluded moods is what keeps Daft Punk out of the yard work playlist regardless of BPM.

---

## Supported Activities

| Activity | Arc | BPM Range | Excluded Moods |
|----------|-----|-----------|----------------|
| yard work | steady | 70–115 | intense, euphoric |
| running | peak | 140–180 | laid-back |
| cooking | steady | 80–120 | intense, euphoric |
| studying | steady | 60–100 | euphoric, intense, energetic |
| morning workout | build | 120–175 | laid-back |
| road trip | varied | 85–130 | intense |
| dinner party | steady | 70–110 | intense, euphoric, focused |
| hiking | build | 85–130 | laid-back |
| commute | steady | 85–130 | intense, euphoric |
| party | peak | 115–180 | laid-back |

---

## Quickstart

### Requirements

- Python 3.10+
- Anthropic API key (for the agent CLI)
- Spotify account + access token (for `create_spotify_playlist`)

### Install

```bash
git clone https://github.com/YOUR_USERNAME/arcade-audio-curator
cd arcade-audio-curator
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### Run tests (no API keys needed)

```bash
pytest tests/ -v
# 52 passed
```

### Set up Spotify (for playlist creation)

Obtain a Spotify OAuth token with `playlist-modify-public` and `playlist-modify-private` scopes via [Spotify's authorization guide](https://developer.spotify.com/documentation/web-api/concepts/authorization). Add it to your `.env` file:
```bash
SPOTIFY_ACCESS_TOKEN=BQD...your_token_here...
```

> **Note:** Tokens expire after 1 hour. For a production deployment this would use Spotify's full OAuth flow via `arcade deploy`.

### Test the Spotify connection

```bash
python3 -c "
import httpx, os
from dotenv import load_dotenv
load_dotenv()
token = os.environ.get('SPOTIFY_ACCESS_TOKEN', '')
r = httpx.get('https://api.spotify.com/v1/me', headers={'Authorization': f'Bearer {token}'})
user = r.json()
print(f'Connected as: {user[\"display_name\"]} ({user[\"id\"]})')
"
```

### Connect to Claude Desktop

Add to `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "arcade-audio-curator": {
      "command": "/full/path/to/arcade-audio-curator/.venv/bin/python",
      "args": ["/full/path/to/arcade-audio-curator/src/arcade_audio_curator/server.py"]
    }
  }
}
```

Restart Claude Desktop. Then ask:

> *"Make me a 45 minute playlist for yard work in Spotify"*
> *"Explain why One More Time by Daft Punk doesn't fit yard work"*
> *"30 minutes of running music"*

### Run the agent CLI

```bash
export ANTHROPIC_API_KEY=sk-ant-...
python agent/main.py "make me a 45 minute playlist for yard work"
python agent/main.py --explain "One More Time" "Daft Punk" "yard work"
python agent/main.py --list-activities
python agent/main.py -v "30 minute running playlist"  # shows tool calls
```

---

## Project Structure

```
arcade-audio-curator/
├── src/arcade_audio_curator/
│   ├── server.py                   # MCP server — 5 tools
│   ├── models.py                   # Pydantic models
│   ├── database.py                 # Data loading + activity matching
│   ├── scoring.py                  # Scoring engine
│   └── data/
│       ├── songs.json              # 100-song curated database
│       └── activity_profiles.json # 10 activity profiles
├── agent/main.py                   # Claude-powered CLI agent
├── tests/test_toolkit.py           # 52 pytest tests
├── evals/eval_tools.py             # Arcade evals
└── pyproject.toml
```

---

## Design Notes

### Why a static song database

The current implementation uses a curated 100-song JSON database. This was a deliberate tradeoff for the POC:

- **Tests are deterministic** — assertions on exact outputs are possible
- **Scoring logic is transparent** — reviewers can see exactly what's being scored
- **No external API dependency** — `pytest tests/ -v` works with zero credentials

The limitation is obvious: you're constrained to 100 songs and the database needs manual maintenance.

### The production architecture

The right approach for production would flip the flow entirely:

```
Current:  our 100-song DB  →  score  →  search Spotify for titles
Future:   activity profile  →  Spotify /recommendations with audio_features  →  score  →  playlist
```

Spotify's API exposes `tempo`, `energy`, `valence`, and `danceability` as queryable audio features on their `/recommendations` endpoint. Combined with seed genres, this would give access to Spotify's full 100M+ song catalog with no local database to maintain.

> Note: Spotify restricted access to `audio-features` and `recommendations` for new apps in 2024, which is why the static database approach was used for this POC.

### Why mood exclusions are a hard override

Soft penalties don't solve the Daft Punk problem. A song that's *euphoric* is wrong for yard work even if it hits the right BPM. The hard 0.0 override on excluded moods captures this correctly — a 10-point BPM penalty would still let euphoric songs through.

### OAuth and local vs deployed

`create_spotify_playlist` reads `SPOTIFY_ACCESS_TOKEN` from `.env` for local development. In a deployed scenario (`arcade deploy`), this would use Arcade's built-in OAuth infrastructure — the `requires_auth=Spotify(scopes=[...])` decorator handles token injection automatically for any user without manual token management.

---

## External Resources

- [Arcade.dev docs](https://docs.arcade.dev) — MCP server architecture, `arcade new` scaffold, evals framework
- [Anthropic Python SDK](https://github.com/anthropics/anthropic-sdk-python) — agentic tool-use loop in `agent/main.py`
- [Spotify Web API](https://developer.spotify.com/documentation/web-api) — playlist creation and track search
- [Pydantic v2](https://docs.pydantic.dev) — models and validation
- Claude (claude-sonnet-4) assisted with code generation throughout; all architectural decisions, scoring logic, data design, and test assertions were authored and reviewed by hand

---

## License

MIT
