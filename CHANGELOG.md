# Changelog

## 1.2.3 - 2026-02-23
Code quality improvements: HTTP connection pool, cache path unification, and main.py refactoring.

### Added
- Added `core/http_session.py` for unified global HTTP session management with configurable connection pool (default: 64).
- Added `utils/paths.py` for unified cache/config/data path management (supports Flatpak XDG environment variables).
- Added `read_json()` / `write_json()` utility functions in `core/settings.py`.

### Changed
- Refactored HTTP connection pool: all HTTP requests now use a shared session with larger pool (64 connections by default).
  - `backend/tidal.py` - tidalapi session
  - `utils/helpers.py` - image/audio downloads
  - `viz/background_viz.py` - visualization images
- Refactored cache directory: unified to use `utils.get_cache_dir()` across all modules.
- Refactored image download: added `download_to_cache()` function for reusable download logic.
- Fixed Flatpak icon path: icons directory is now correctly resolved to project root.

### Fixed
- Fixed artist artwork cache memory leak: added `max_artist_artwork_cache = 500` limit with LRU eviction.
- Improved error handling: added warning logs to empty exception handlers in critical paths.

### Refactored
- Code organization: moved 9 frequently-used methods from `main.py` to new `app/app_handlers.py`.
- Created `app/` directory structure for better code organization.
- Reduced main.py from 4978 to 4812 lines (166 lines removed).

---

## 1.2.2 - 2026-02-23
Coverage: Flatpak storage path fixes.

### Fixed
- Fixed Flatpak cache/token storage: now uses XDG_CACHE_HOME (automatically set by Flatpak to `~/.var/app/com.hiresti.player/cache`).

---

## 1.2.1 - 2026-02-22
