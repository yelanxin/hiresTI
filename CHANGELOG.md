# Changelog

## 1.4.5 - 2026-03-02
ALSA exclusive reliability + signal-path clarity release: one-shot D-Bus reservation retry, 32-bit container DAC support, and clearer bit-perfect diagnostics/UI.

### Added
- Added D-Bus `org.freedesktop.ReserveDevice1` ALSA reservation support via `src/services/alsa_reserve.py` so exclusive `hw:N,M` playback can politely ask PipeWire/WirePlumber to release the card only after a direct exclusive open fails.
- Added ALSA exclusive runtime diagnostics that log the container adapter format, source bit depth, and active kernel `hw_params` when a 32-bit container-only DAC is in use.
- Added regression coverage for:
  - one-shot ALSA reservation retry behavior,
  - active ALSA `hw_params` parsing and container-adapter diagnostic dedupe,
  - ALSA bit-perfect verdict rules that now allow lossless container widening such as `16-bit -> 32-bit`.

### Changed
- ALSA exclusive output now tries direct hardware open first and only falls back to D-Bus reservation on failure, instead of reserving the device preemptively.
- ALSA exclusive sink creation in the Rust audio core now detects `S32_LE` / `S24_32_LE`-only playback devices from `/proc/asound/cardN/stream*` and inserts `audioconvert + capsfilter` to widen source PCM into the required container format without resampling.
- `Audio Signal Path` bit-perfect rules now treat ALSA exclusive playback as valid when the sample rate matches, the system mixer is bypassed, and output bit depth is greater than or equal to source bit depth.
- `Bit-Perfect Mode` settings now include an explicit help popover explaining the difference between PipeWire source-rate following and true ALSA exclusive bit-perfect playback.
- `Audio Signal Path` now uses a dedicated terminal-style black/green presentation with tighter row spacing.

### Fixed
- Fixed an ALSA exclusive retry loop caused by scheduling `set_output()` directly with `GLib.idle_add`, which repeatedly re-applied output switching after reservation success.
- Fixed ALSA exclusive error classification so generic `rust-alsa-sink` messages no longer trigger false device-disconnect recovery loops.
- Fixed transport/output switch error reporting to include the last Rust/GStreamer error detail when available.
- Fixed GTK slider warnings in the Signal Path window by removing the custom scrollbar slider override that conflicted with GTK sizing.

### Tests
- Verified with:
  - `pytest -q tests/test_rust_audio_reservation_retry.py tests/test_signal_path_bitperfect.py tests/test_audio_output_state_transition.py`
  - `cargo test --lib`

---

## 1.4.1 - 2026-02-28
Remote control UI clarification release: clearer MCP/RPC endpoint presentation and better LAN endpoint display.

### Changed
- Remote Control settings now show `MCP Endpoint` and `RPC Endpoint` as separate rows instead of a single ambiguous endpoint field.
- Each endpoint row now has its own dedicated `Copy` action so OpenClaw/MCP setup uses the correct `/mcp` URL by default.
- In `LAN` mode, when the bind host is `0.0.0.0`, the displayed endpoints now prefer the detected local machine IPv4 address instead of showing the wildcard bind address.

### Fixed
- Fixed Remote Control settings misleading MCP users by showing the `/rpc` endpoint as the primary endpoint.
- Fixed `LAN` endpoint display showing `0.0.0.0`, which is valid for binding but not useful for clients connecting from another device.

### Tests
- Added regression coverage for endpoint display host selection with wildcard LAN bind addresses versus explicit bind hosts.

---

## 1.4.0 - 2026-02-28
Remote control + playback reliability release: LAN-capable remote API, MCP integration, queue/event automation, and immediate UI/state fixes.

### Added
- Added a built-in remote-control service with HTTP JSON-RPC transport:
  - supports playback control, queue inspection, queue replacement/append/insert/move/remove/clear, indexed queue playback, and structured `search.match_tracks`,
  - exposes `auth.status` with both RPC and MCP endpoints for client auto-configuration.
- Added native MCP support for OpenClaw-style integrations:
  - `/mcp` HTTP endpoint with MCP initialize/tools flow,
  - tool metadata for player, queue, and search operations,
  - structured MCP tool responses and notification handling.
- Added live remote event fanout:
  - `/events` SSE stream for playback/queue changes,
  - queue/playback event publishing from track start, pause/resume, seek, queue mutation, and playback error paths.
- Added a dedicated OpenClaw setup guide: `openclaw-mcp-guide-en.md`.
- Added remote-control secret storage with generated Bearer API keys saved separately from normal settings.

### Changed
- Remote Control settings expanded and polished:
  - dedicated section with enable toggle, access mode, port, endpoint, API key generation, and copy actions,
  - `Bind IP` and `Allowed Clients` now stay hidden in `Local only` mode and only appear in `LAN`,
  - endpoint row now includes a direct `Copy` action.
- App startup/shutdown now manages the remote-control service lifecycle automatically when the feature is enabled.
- Key regeneration now takes effect immediately:
  - restarting the remote service closes existing MCP/event/HTTP connections,
  - stale long-lived clients must reconnect with the new key.
- My Albums favorite toggles now update collection state immediately without requiring an app restart:
  - un-favoriting removes the album from the cached My Albums list right away,
  - adding a favorite invalidates the recent-albums cache so ordering reloads from TIDAL cleanly.
- Mini mode restore no longer leaves the global search box spuriously focused.
- ALSA exclusive-mode device enumeration is now more robust:
  - the Rust audio core enumerates real playback PCM devices from `/proc/asound/card*/pcm*p`,
  - ALSA output selection now uses the correct `hw:<card>,<pcm>` target instead of assuming PCM `0`.

### Security
- Remote control is disabled by default.
- LAN access requires a Bearer API key on every request.
- Optional IP/CIDR allowlists can restrict which local-network clients may connect.
- MCP requests now enforce host/origin checks in addition to Bearer auth.
- Remote API secrets are stored in a dedicated file with restricted permissions.

### Fixed
- Fixed stale My Albums UI after removing a TIDAL album favorite from the album page.
- Fixed remote-control key rotation not invalidating active long-lived MCP/event connections until full app restart.
- Fixed mini-mode restore activating the search box unexpectedly.
- Fixed ALSA exclusive-mode failures on hardware whose playback PCM index is not `0`.

### Tests
- Added regression coverage for:
  - remote API key generation, rotation, invalid-key rejection, loopback-only binding, and allowlist enforcement,
  - MCP HTTP initialize/notification handling and tool-call structured responses,
  - SSE event fanout and formatting,
  - JSON-RPC queue move/insert/append/replace behavior and public queue snapshots,
  - My Albums cache invalidation/synchronization after album favorite toggles,
  - ALSA playback PCM enumeration fallback and real-device selection in the Rust audio core.

---

## 1.3.2 - 2026-02-28
UI + packaging fix release: search suggestions polish, logout view reset, and icon reliability hardening.

### Changed
- Recent Searches popover polished:
  - clicking a recent search now closes the popover before navigating to results,
  - recent-search chips now wrap by available width instead of fixed columns,
  - chip spacing, padding, and top spacing were tightened for a denser layout.
- Non-header right-click now opens an app context menu with `Share...` and `Close`:
  - `Share...` copies the project's GitHub link and shows a copied notice,
  - `Close` follows the app's normal window close behavior.
- Search page structure simplified:
  - removed the in-page Recent Searches block in favor of the header popover flow,
  - removed the separate History Tracks search section,
  - search result sections now start hidden until they have content.
- Home card subtitles are now aligned with My Albums subtitle styling.
- Liked Songs artist filter avatars increased to `60x60`.
- Liked Songs artist filter labels now use lighter text weight (`300`).

### Fixed
- Logout now resets the right-side content stack back to the login/home surface even when triggered from `search_view`.
- Session restore no longer reopens stale `search_view`; it falls back to Home/grid state instead.
- Search focus handling is now more consistent:
  - dragging the header no longer leaves the search entry spuriously focused on release,
  - clicking non-interactive blank areas now clears search focus and closes suggestions more reliably.
- Header and non-header window interactions are now split correctly:
  - header right-click keeps the system default window menu,
  - non-header drag-to-move behavior was restored,
  - content layout stays expanded after the drag-handle restructuring.
- Bundled icon coverage improved:
  - Flatpak now installs the full `hicolor` icon set, not just the app icon,
  - runtime icon-theme search now checks bundled app paths more robustly,
  - all app-referenced symbolic icons are now shipped locally,
  - bundled symbolic icons now use theme-aware color (`currentColor`) for light/dark adaptation.
- Visualizer handle realignment is now more robust after layout changes and uses a more stable overlay-relative bounds calculation.
- Favorite-button refresh no longer traverses removed search history result widgets.

### Tests
- Added regression coverage for:
  - closing search suggestions when a search is executed,
  - clearing search focus on blank-area clicks and suppressing focus after header drag,
  - global share context-menu interactions and clipboard copy behavior,
  - resetting logout view state back to `grid_view`.

---

## 1.3.1 - 2026-02-27
Feature release: MPRIS remote-control integration for Linux desktop media controls.

### Added
- Added full MPRIS service (`org.mpris.MediaPlayer2.hiresti`) with:
  - `org.mpris.MediaPlayer2` interface (`Raise`, `Quit`),
  - `org.mpris.MediaPlayer2.Player` interface (`Play/Pause/PlayPause/Stop/Next/Previous/Seek/SetPosition`),
  - property exposure for `PlaybackStatus`, `Metadata`, `Position`, `LoopStatus`, `Shuffle`, and `Volume`.
- Added new MPRIS service module and app wrapper wiring:
  - `src/services/mpris.py`
  - `src/app/app_mpris.py`

### Changed
- MPRIS lifecycle is now managed by app bootstrap:
  - service starts after app activation,
  - service stops cleanly during app shutdown.
- Playback state is now synchronized to MPRIS from core runtime paths:
  - play/pause/stop and next/previous transitions,
  - queue mutation (remove/clear/set queue),
  - progress updates and user seek commits,
  - loop/shuffle mode toggles and volume changes.

### Tests
- Added MPRIS helper tests for:
  - track ID object-path mapping,
  - play-mode to loop/shuffle mapping,
  - metadata/playback status snapshot behavior,
  - loop/shuffle/volume property setter behavior.

---

## 1.3.0 - 2026-02-27
Refactor + sync release: main.py modular split, waveform/audio sync stabilization, and UI layout tuning.

### Refactored
- Included the `main.py` split work in this release: app lifecycle/bootstrap, visualizer control, runtime refs, and wiring are now handled in dedicated `app/` modules with centralized bind-map wiring.

### Added
- Added dedicated `New` page experience for release/fresh-track browsing.
- Added dedicated `Top` page experience for chart/top-content browsing.

### Changed
- Visualizer backend strategy simplified to a single Cairo path:
  - removed Performance/Quality backend policy switching from UI/runtime,
  - removed GL/GPU prewarm and policy handlers from visualizer wiring.
- Sidebar and window defaults updated:
  - `SIDEBAR_RATIO` set to `0.15`,
  - default window size set to `1250x800`.
- Queue drawer layout changed to adaptive height with vertical breathing room:
  - top and bottom margins are each `10%` of window/overlay height (drawer body follows remaining `80%`).
- Home page card layout adjusted:
  - Home `FlowBox` switched to non-homogeneous layout to keep card spacing stable across normal/fullscreen states,
  - home/top/new card width updated to `180`,
  - Home track card uses width `100` with cover `90`.
- History page UI optimized:
  - Top20 rows now use the same now-playing visual language as Top/New (active background + playing icon),
  - dashboard track-row cover sizing is unified for History/New/Top.
- Artist page avatar size increased to `150x150`.
- Unified dashboard track-cover size via `DASHBOARD_TRACK_COVER_SIZE = 70` for Top/History/New track rows.

### Fixed
- Waveform/audio sync offset no longer depends on ALSA buffer/latency profile:
  - removed buffer-based minimum offset clamp in Rust audio visual sync delay path,
  - latency profile changes/startup no longer overwrite visual sync offset,
  - visual sync now consistently uses dedicated `viz_sync_offset_ms`.
- Restored now-playing indicator consistency:
  - History Top20 rows now show playing icon and active background, aligned with Top/New behavior.

---

## 1.2.9 - 2026-02-25
Fix: logout now fully resets all UI and session state.

### Fixed
- Fixed logout: `on_logout_clicked` in `app_handlers.py` was a stripped-down stub that silently overrode the complete implementation in `main.py`. The active version was missing: closing the user popover, resetting the login-in-progress flag and attempt ID, cleaning up any open login dialogs, switching the account scope back to guest, clearing the stream prefetch cache, and refreshing favorite button states. All of these are now performed on logout.
- Removed the dead-code `on_login_clicked` and `on_logout_clicked` class methods from `main.py` that were never reached due to being overridden at class-binding time.
- Upgraded `_rounded_pixbuf` failure log level from `debug` to `warning` so rendering errors are visible in default log output.

### Build
- DEB `Depends`: added `python3-gi-cairo` (required for Cairo/GDK rendering), `gir1.2-gtksource-4` (GtkSourceView typelib), and `qrencode` (system fallback for QR login when the `qrcode` Python package is absent).

---

## 1.2.8 - 2026-02-25
UI: Home page adaptive layout; packaging and test script fixes.

### Changed
- Home page sections now use `FlowBox` adaptive layout instead of a fixed 2-row horizontal scrolling grid — items automatically wrap to fill available width at any window size.
- Removed "X items" count labels from Home section headers.

### Fixed
- DEB `Depends`: added `libpipewire-0.3-0` and `libpulse0`, which are required by the Rust audio core (`librust_audio_core.so` links against PipeWire and PulseAudio at runtime). Without these the app failed to start on clean Debian/Ubuntu installs.

### Build / Test
- `test_packages.sh` rewritten with `--version` / `-v` and `--os` / `-o` parameters; version auto-detected from `dist/` when not specified, systems can be tested individually or in any combination.
- Removed Ubuntu 22.04 test (container hangs without exit).
- Fixed EL9 test: enable EPEL and CRB repos before `dnf install` to satisfy `libadwaita`, `gstreamer1-plugins-bad-free`, and `gstreamer1-plugins-ugly-free` dependencies.
- Fixed Debian test: install `python3-gst-1.0` before other packages to prevent `dpkg` dependency errors.
- Fixed all DEB tests: pre-install `libpipewire-0.3-0` and `libpulse0`.
- Fixed Arch test: replaced bare `tar` extraction with proper `pacman -S` (deps) + `pacman -U` (package) + binary run, matching the behaviour of other distro tests.
- Fixed Flatpak test: use direct flathub URL for `remote-add`, switch from `--user` to `--system` install (root container), remove unnecessary SDK install, add `flatpak run` smoke test.
- Increased binary output capture from `head -10` to `head -30` across all tests to prevent error tracebacks from being truncated.

---

## 1.2.7 - 2026-02-24
Bug fix: login button now works correctly.

### Fixed
- Fixed `AttributeError` when clicking the login button: the `on_login_clicked` handler in `app_handlers.py` was incorrectly calling `ui_actions.on_login_clicked()` which does not exist. Implemented the login logic directly in the handler.

---

## 1.2.6 - 2026-02-24
Performance: Liked Songs and My Albums load speed improvements, config directory fixes, and packaging corrections.

### Added
- My Albums now shows a cached instant first paint on repeated visits — no more "Loading albums..." wait when returning to the page.
- Added in-memory album cache in the backend (`_cached_albums`) with a 5-minute TTL, shared across My Albums page loads and favorite ID refresh to eliminate duplicate API calls on login.

### Changed
- Liked Songs page no longer performs a redundant full UI rebuild when navigating back to the page; cached data is rendered exactly once via a new `_initial_render_done` flag.
- Liked Songs refresh now skips full widget reconstruction when the track list is unchanged (same count and boundary IDs), reusing existing artist filter chips and only re-running filters.
- Raised Liked Songs and My Albums cache TTL from 30 seconds to 5 minutes. Fav-toggle actions bypass the TTL via `force=True` to ensure immediate refresh after un-liking a track.
- Stage 1 head-fetch (limit=100) in Liked Songs refresh is now skipped when the local cache already has 100 or more tracks.
- `get_favorite_tracks` and `get_recent_albums` pagination increased from page size 100 to 1000, reducing TIDAL API round trips up to 10× for large libraries.
- `get_artwork_url()` in My Albums card rendering moved from the GTK main thread to a background worker thread; placeholder icon shown immediately.
- Image loading (`load_img`) now uses a bounded `ThreadPoolExecutor` (max 8 workers) instead of spawning one unbounded `Thread` per image, preventing thread explosion on large album/artist pages.
- `_refresh_track_fav_button` now performs the favorite state lookup synchronously (O(1) local set read) instead of submitting a daemon thread per track row.
- `requirements.txt` synced with the pip install list in `package.sh`: added `Pillow`, `python-dateutil`, `typing-extensions`, `isodate`, `mpegdash`, `pyaes`, `ratelimit`, `six`, `certifi`.

### Fixed
- Token files (`hiresti_token.json`) and `settings.json` are now stored in the XDG config directory (`~/.config/hiresti` / `~/.var/app/.../config/hiresti`) instead of the cache directory, so clearing the cache no longer logs users out or resets settings.
- One-time silent migration: on first launch after upgrade, existing token and settings files are automatically moved from the old cache path to the new config path — no manual action or re-login required.
- Removed leftover `[DEBUG] print()` statements from `save_session()` that were leaking to stderr in production builds.
- `_refresh_favorite_ids_sync` no longer issues a duplicate `get_recent_albums` API call on login when the album cache is already fresh from the UI load.
- DEB `Architecture` changed from `all` to the actual host architecture — packages contain arch-specific Rust `.so` files and must not be marked architecture-independent. Output filename updated accordingly (e.g. `hiresti_1.2.6_amd64.deb`).
- DEB `Depends`: added `gstreamer1.0-plugins-base` (provides `GstPbutils`, required by the audio pipeline).
- RPM `Requires` (both Fedora and EL9): added `python3-cairo` and `gstreamer1-plugins-base`.
- Arch `.PKGINFO`: corrected `libpipewire` → `pipewire`; removed `python-pillow` and `python-requests` (already bundled via pip install).
- Flatpak Rust module source paths fixed: `path: ../..` + `cd hiresTI/src_rust/…` → `path: ..` + `cd src_rust/…` — the old paths required the repo to be inside a directory named exactly `hiresTI`.
- Flatpak build now runs `cargo vendor` before invoking `flatpak-builder` so the `vendor/` directory is available for the offline `cargo build --release --offline` step inside the sandbox.
- Shell launcher: removed dead `if [ -f "$APP_DIR/src/main.py" ]` branch — source files are installed flat to `/usr/share/hiresti/`.

---

## 1.2.5 - 2026-02-24
Albums page refactor: search, sorting, pagination, and waveform performance improvements.

### Added
- Added search functionality to Favorites Albums page - users can now search through their favorite albums by title or artist.
- Added sorting options to Albums page - support sorting by Name (A-Z, Z-A), Artist, Date Added, and Release Date.
- Added pagination to Albums page - display albums in pages of 50 items for better performance with large collections.

### Fixed
- Fixed waveform visualization lag: optimized rendering pipeline to reduce CPU/GPU usage during playback.
- Fixed waveform performance: implemented lazy loading and frame rate limiting to prevent stuttering.

### Changed
- Improved UI responsiveness for list pages (Albums, Playlists, Artists): optimized scroll handling and item rendering.
- Updated Albums page layout: better handling of long album/artist names with ellipsis truncation.

---

## 1.2.4 - 2026-02-23
Code quality improvements: duplicate code reduction in utils/paths.py.

### Refactored
- Extracted `_get_xdg_dir()` helper function in `utils/paths.py` to reduce code duplication across `get_cache_dir()`, `get_config_dir()`, and `get_data_dir()`.

---

## 1.2.3 - 2026-02-23
Code quality improvements: HTTP connection pool optimization, cache path unification, and main.py refactoring.

### Added
- Added `core/http_session.py` for unified global HTTP session management with configurable connection pool (default: 64).
- Added `utils/paths.py` for unified cache/config/data path management (supports Flatpak XDG environment variables).
- Added `read_json()` / `write_json()` utility functions in `core/settings.py`.

### Changed
- Refactored HTTP connection pool: all HTTP requests now use a shared session with larger pool (default: 64 connections).
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
Coverage: login reliability hotfix for Linux distro TLS CA path differences.

### Fixed
- Fixed TIDAL OAuth/login failures on Ubuntu when inherited TLS env vars pointed to non-existent RHEL CA bundle paths (for example `/etc/pki/ca-trust/extracted/pem/tls-ca-bundle.pem`).
- Added runtime CA bundle normalization in `TidalBackend`:
  - validate `REQUESTS_CA_BUNDLE`, `CURL_CA_BUNDLE`, `SSL_CERT_FILE`,
  - auto-fallback to available bundle (`certifi` first, then common system paths),
  - clear invalid overrides if no valid bundle file is found.
- Added regression test coverage for invalid CA bundle env handling during OAuth startup.

## 1.2.0 - 2026-02-22
Coverage: major audio architecture refactor after 1.1.1, centered on Rust audio runtime.

### Added
- Added Rust launcher binary entrypoint (`hiresti`) via new `rust_launcher` crate.
- Added optional Python binary bundling path (PyInstaller onedir):
  - helper script: `tools/build_py_binary.sh`,
  - packaging switch: `HIRESTI_PY_BINARY=1`.

### Changed
- Audio runtime is now Rust-first:
  - playback transport, device routing, and output state transitions run through Rust core pipeline,
  - Python-side fallback paths were reduced/removed in core playback flow.
- PipeWire/ALSA path handling was refactored around Rust transport control:
  - output route application and rebind/recovery flow unified,
  - clearer behavior when target device is unavailable or route switch fails.
- Signal Path/Tech Info data sources were moved toward Rust-driven runtime values:
  - playback/session/output fields now align with live Rust pipeline state,
  - less dependence on ad-hoc Python-side estimations.
- Visualizer and audio timing integration was reworked around Rust spectrum pipeline:
  - better lifecycle control when drawers/tabs are shown or hidden,
  - reduced unnecessary background spectrum processing in inactive states.
- Packaging flow updated to build/install Rust launcher to `/usr/bin/hiresti` instead of generating a shell wrapper.
- Launcher flow updated:
  - Rust launcher prefers bundled binary (`/usr/share/hiresti/hiresti_app/hiresti_app`) when present,
  - otherwise falls back to `python3 main.py`.

### Fixed
- Improved output-device reliability in Rust playback path during route changes/hotplug scenarios.
- Improved observability of audio/login failures with clearer runtime diagnostics in logs/UI.

### Notes
- In source mode, seeing a `python` process is expected (Rust launcher starts Python app).
- To run with a bundled app binary entry, build with:
  - `HIRESTI_PY_BINARY=1 ./package.sh <type> <version>`

## 1.1.1 - 2026-02-21
Coverage: incremental fixes and performance refinements after 1.1.0.

### Changed
- Improved Queue drawer responsiveness:
  - open animation starts immediately before heavy list refresh work,
  - avoided redundant queue-drawer rebuild when queue data is unchanged.
- Added Rust-accelerated collection name-sort path for:
  - Favorite Artists page load,
  - Artist albums page load.
- Added logging for Rust/Python path visibility in collection and paging flows.
- Kept visualizer panel opening without content fade-in (fade disabled) for lower UI latency.

### Fixed
- Fixed queue drawer perceived "late start" behavior on toggle/hotkey in heavy UI scenarios.

### Packaging Output (1.1.1)
- `hiresti_1.1.1_all.deb`
- `hiresti-1.1.1-1.fedora.x86_64.rpm`
- `hiresti-1.1.1-1.el9.x86_64.rpm`
- `hiresti-1.1.1-1-x86_64.pkg.tar.zst`

## 1.1.0 - 2026-02-20
Coverage: changes after 1.0.10 on 2026-02-20.

### Warning
- Local playlists have been removed in this release.
- Only cloud playlists are supported now.
- If you used local playlists in previous versions, please migrate to cloud playlists before upgrading.

### Added
- Added cloud playlist-focused management flow.
- Added playlist folders:
  - create / rename / delete,
  - folder cover collage preview (up to 4 playlist covers),
  - folder item count badge.
- Added playlist/folder creation entry via unified `+` menu.
- Added Rust visualizer core bundling step to packaging output.

### Changed
- Reworked playlist pages to align with other list/detail pages.
- Moved playlist edit/delete actions from list cards to playlist detail header area.
- Updated visualizer rendering pipeline with broader GL path coverage and Rust preprocessing hooks.
- Refined visualizer transitions (fade-in and cache-to-live blending on enable).
- Updated About dialog content and removed author line.

### Fixed
- Fixed playlist/folder back navigation regressions in nested navigation paths.
- Fixed folder/playlist UI edge cases (menu placement, layout, warning-prone sizing).
- Fixed mini mode toggle crash (`is_mini_mode` attribute init issue).
- Fixed multiple GL shader/runtime regressions and fallback behavior.
- Fixed image-loading reliability issues and several GTK warnings.

### Performance
- Reduced CPU usage across common playback scenarios and multiple visualizer effects.
- Improved GL rendering stability and reduced CPU spikes in several modes.

### Packaging Output (1.1.0)
- `hiresti_1.1.0_all.deb`
- `hiresti-1.1.0-1.fedora.x86_64.rpm`
- `hiresti-1.1.0-1.el9.x86_64.rpm`
- `hiresti-1.1.0-1-x86_64.pkg.tar.zst`

## 1.0.10 - 2026-02-19
Coverage: changes after 1.0.9 on 2026-02-19.

### Added
- Added search tracks pagination controls with `50` items per page (`Prev` / `Next` / page indicator).
- Added search-page batch action button: `Like Selected`.
- Added progressive fallback for stream URL quality resolution:
  - Try selected quality first (e.g. `HI_RES_LOSSLESS`),
  - then fallback to `LOSSLESS`,
  - then `HIGH` when needed.

### Changed
- Improved compatibility for `tidalapi` quality enum variants (legacy and newer naming).
- Increased search API result fetch window for tracks to support pagination.
- Startup login-view rendering now avoids flashing logged-out UI for already logged-in users.

### Fixed
- Fixed incomplete liked-library fetch behavior by adding robust pagination for favorite artists/albums/tracks.
- Fixed search track row activation under pagination to play the correct absolute track index.
- Fixed logged-out UI state consistency:
  - hide search input,
  - hide overlay handles,
  - keep bottom player bar visible.
- Removed album-page header batch-like control after UX review (kept search batch-like flow only).

### Packaging Output (1.0.10)
- `hiresti_1.0.10_all.deb`
- `hiresti-1.0.10-1.fedora.x86_64.rpm`
- `hiresti-1.0.10-1.el9.x86_64.rpm`
- `hiresti-1.0.10-1-x86_64.pkg.tar.zst`

## 1.0.9 - 2026-02-19
Coverage: changes on 2026-02-19.

### Added
- Added `HIRES_DEBUG_BUTTONS=1` button metrics dump tooling for GTK size diagnostics around history click playback transitions.

### Changed
- Unified handle dimensions per latest UI adjustment:
  - Queue side handle width set to `23`.
  - Visualizer bottom handle height set to `23`.
- Updated handle-related CSS minimum sizes to match the runtime widget requests above.
- Adjusted player favorite button top margin from `-5` to `0` to avoid GTK button vertical min-size warnings.
- Refined back-navigation behavior to correctly re-select `home`/selected nav row state when returning to `grid_view`.

### Fixed
- Fixed GTK warning during history track click flow:
  - `GtkButton ... adjusted size vertical ... must not decrease below min ...`
  - Root cause was negative top margin on `player-heart-btn`.

### Packaging Output (1.0.9)
- `hiresti_1.0.9_all.deb`
- `hiresti-1.0.9-1.fedora.x86_64.rpm`
- `hiresti-1.0.9-1.el9.x86_64.rpm`
- `hiresti-1.0.9-1-x86_64.pkg.tar.zst`

## 1.0.4 - 2026-02-18
Coverage: changes from 2026-02-11 to 2026-02-18.

### Added
- 10-band EQ and related UI controls.
- Bit-perfect playback flow and status indicators.
- Lyrics page and lyrics background visualizer.
- Visualizer module and multiple new effects/themes, including:
  - `Pro Bars`
  - `Pro Line`
  - `Pro Fall`
  - `Stars`
  - `Infrared` theme
  - `Stars BWR` theme
- Home page improvements (custom mixes, sidebar updates, track time display).
- Added account-scoped local data isolation for history and playlists.
- Packaging support updates for DEB/RPM release workflow.

### Changed
- Visualizer naming refined to shorter effect labels:
  - `Wave`, `Fill`, `Mirror`, `Dots`, `Peak`, `Trail`, `Pulse`, `Stereo`, `Burst`, `Fall`, `Spiral`, `Pro Bars`, `Pro Line`, `Pro Fall`
- Improved `Pro Fall` performance by pre-binning spectrum history and reducing per-frame computation.
- Updated visualizer/theme integration so effects follow selected spectrum theme more consistently.
- Reworked `package.sh`:
  - Bundles required source folders (`ui/`, `actions/`, `icons/`).
  - Adds preflight checks.
  - Uses safer shell mode and quoting.
  - Produces dual RPM variants from one command:
    - Fedora (`.fedora`)
    - EL9 (`.el9`)
  - Keeps support for single-variant RPM builds (`rpm-fedora`, `rpm-el9`).
- Updated docs and README structure for releases.
- Multiple fixes in output device restore flow, exclusive mode latency/settings, search behavior, and UI polish.

### Removed
- Removed `IR Waterfall` effect (superseded by `Pro Fall`).
- Removed redundant legacy infrared-only rendering branch.

### Packaging Output (1.0.4)
- `hiresti_1.0.4_all.deb`
- `hiresti-1.0.4-1.fedora.x86_64.rpm`
- `hiresti-1.0.4-1.el9.x86_64.rpm`

### Notes
- Local cache root remains `~/.cache/hiresti`.
- Account-scoped files are now stored under per-user profile directories after login.
