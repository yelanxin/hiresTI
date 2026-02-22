# Changelog

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
