# Architecture Overview

This project now uses a modular UI/action layout to keep `main.py` focused on app wiring and lifecycle.

## High-Level Structure

- `main.py`
  - Application bootstrap (`Adw.Application`)
  - State ownership (player/backend/session/UI state)
  - Delegates UI build and interaction logic to modules below

- `ui/builders.py`
  - Top-level UI construction:
  - Header
  - Body shell (sidebar + stack + overlay)
  - Player bar

- `ui/views_builders.py`
  - View-specific builders:
  - Grid/home view
  - Tracks view
  - Settings view
  - Search view
  - Login-state view toggle logic

- `actions/ui_actions.py`
  - Search flow
  - Search result rendering
  - Album detail loading
  - Track list population

- `actions/ui_navigation.py`
  - Sidebar navigation handling
  - Back navigation
  - Artist navigation flow

- `actions/playback_actions.py`
  - Play/pause
  - Next/previous track behavior
  - Next-index calculation by play mode

- `actions/audio_settings_actions.py`
  - Latency profile change handling
  - Driver/device refresh and apply flow
  - Device selection handling

- `app_settings.py`
  - Centralized settings defaults and normalization
  - Settings versioning field (`settings_version`)
  - Atomic settings persistence

- `utils.py` cache maintenance
  - Cover cache pruning by age and size
  - Startup background cleanup task
  - Env controls:
  - `HIRESTI_COVER_CACHE_MAX_MB` (default `300`)
  - `HIRESTI_COVER_CACHE_MAX_DAYS` (default `30`)

## Call Flow (Typical)

1. `main.py` activates app and builds UI via `ui/builders.py`.
2. User interactions call `main.py` methods.
3. Methods delegate to `actions/*` modules.
4. Actions update app state/UI and invoke backend/player.

## Design Rule

Keep `main.py` as an orchestrator, and move new feature logic into:

- `ui/*` for widget construction/layout
- `actions/*` for interaction behavior and flow

## Logging

- Startup calls `setup_logging()` in `main.py`.
- Environment variables:
- `HIRESTI_LOG_LEVEL` global level (`INFO` by default)
- `HIRESTI_LOG_FILE` optional log file path
- `HIRESTI_LOG_ROTATE_BYTES` rotate threshold in bytes (default `5242880`)
- `HIRESTI_LOG_BACKUP_COUNT` rotated file count (default `3`)
- `HIRESTI_LOG_MODULE_LEVELS` per-module override, for example:
  `audio_player=DEBUG,tidal_backend=INFO`

## Testing

- Unit tests live under `tests/`.
- Current focus:
- playback next-index behavior
- lyrics parsing behavior
- settings normalization and persistence
- Run:
- `pytest -q tests`

## Troubleshooting

- No sound or output busy:
- switch driver/device in Settings and retry
- check logs for `busy` recovery and fallback sink messages
- Lyrics not shown:
- some tracks have no lyrics (backend returns 404/no object)
- check lyric status text in UI and backend logs
- Login expired:
- re-login from header login button
- logs classify this as `auth` errors in search/playback/lyrics flows
