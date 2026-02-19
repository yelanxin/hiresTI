# Changelog

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
