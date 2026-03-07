# Changelog

## 1.6.0 - 2026-03-07
Visualizer overhaul + playback-scrubbing stability release: stereo-aware spectrum data, fullscreen waveform viewing, a redesigned waterfall/waveform presentation, and a critical ALSA mmap seek recovery fix.

### Added
- Added fullscreen mode for the visualizer/lyrics drawer, including dedicated expand/restore controls and window-height-aware resizing.
- Added stereo spectrum transport from the Rust audio core to Python/UI (`mono`, `left`, `right` channels), enabling true stereo visual effects instead of mono-only fallback data.
- Added new stereo-focused visualizer effects and rendering paths, including `Stereo Mirror`, `Stereo Scope`, `Balance Wave`, `Center Side`, `Phase Flower`, and `Stereo Meter`.
- Added settings migrations and regression coverage for the revised visualizer effect/profile lists and supported bar-count options.

### Changed
- Reworked the visualizer runtime to use a single Cairo-based rendering path instead of switching between legacy backend variants, simplifying behavior across effects and reducing backend-specific divergence.
- Visualizer spectrum preprocessing now uses denser upstream spectrum data and stereo channel parsing, improving high-frequency motion and channel separation.
- The waterfall/analyzer presentation has been redesigned into a smoother scrolling waveform-style renderer with clearer center-line and envelope shaping.
- Visualizer profile defaults and migrations now insert the new `Gentle` profile at the low-intensity end of the range.
- Supported visualizer bar counts have been narrowed to `4, 8, 16, 32, 48, 64`, removing oversized density options that did not scale cleanly with the new renderer.
- Home view content no longer uses the previous fixed-width clamp, so fullscreen windows can use the available horizontal space instead of forcing a centered narrow column.

### Fixed
- **[Critical] Fixed seek/scrubbing failure on `ALSA（mmap）`**: after a flush-seek, ALSA XRUN/stream-recovery paths could leave the mmap device in `PREPARED` state without re-priming/restarting playback, causing the progress bar to move while audio failed to resume. The mmap start sequence is now reset correctly after recoverable errors.
- Fixed spectrum frame interpolation and queue sampling so stereo-aware frames remain stable across timeline jumps, visual warmup, and backward seeks.
- Fixed fullscreen/reveal resize jitter in the visualizer drawer by resynchronizing overlay height after window-state transitions.
- Fixed legacy visualizer settings values (`viz_effect`, `viz_profile`, `viz_bar_count`) landing on invalid or removed options after upgrade.

### Tests
- Verified with:
  - `CCACHE_DISABLE=1 cargo test --manifest-path src_rust/rust_audio_core/Cargo.toml`
  - `python -m py_compile src/ui/views_builders.py`
  - `pytest -q tests/test_viz_bar_options.py tests/test_viz_effect_settings_migration.py tests/test_viz_profile_settings_migration.py`

---

## 1.5.3 - 2026-03-05
**Critical audio quality fix**: streaming now correctly delivers Hi-Res Lossless (up to 24-bit/192kHz) and source format is accurately reported throughout the UI.

### Fixed
- **[Critical] Fixed TIDAL streaming capped at CD quality (16-bit/44.1kHz)**: The player was using a legacy API endpoint (`urlpostpaywall`) that does not support HI_RES_LOSSLESS. Switched to the `playbackinfopostpaywall` endpoint (`get_stream()`) which correctly delivers TIDAL Max Hi-Res Lossless streams. Added support for both BTS (direct URL) and MPD (MPEG-DASH manifest) stream formats returned by the new endpoint.
- **[Critical] Fixed source format display always showing 32-bit/192kHz**: The audio engine's internal mmap container format (S32LE) was being reported as the source bit depth/sample rate instead of the actual TIDAL stream metadata. Source format is now injected directly from the TIDAL API (`Stream.bit_depth` / `Stream.sample_rate`) before each load, bypassing the unreliable GStreamer TAG text parser.
- Fixed Signal Path page showing incorrect source bit depth and sample rate: now reads from stream metadata (set by TIDAL API) rather than the Rust audio engine snapshot, which only reflects the internal PCM container format.
- Fixed ALSA mmap "device busy" error when switching from PipeWire to ALSA mmap driver: the mmap writer thread now pre-warms the ALSA device handle during idle, avoiding a race condition where the device was still held by PipeWire when the first audio frame arrived.

---

## 1.5.2 - 2026-03-05
PipeWire device visibility, pro-audio auto-switching, and audio settings layout polish.

### Added
- Added informational dialog when selecting a PipeWire device that is not in Pro-Audio mode: notifies the user that the device will be automatically switched to Pro-Audio to enable adaptive sample rate.
- After confirming the pro-audio dialog, the device dropdown now automatically selects the new pro-audio node without requiring manual re-selection.

### Changed
- `Realtime Audio Priority` setting is now only enabled when the `ALSA（mmap）` driver is selected; it is grayed out for all other drivers.
- Moved `Realtime Audio Priority` below `Output Bit Depth` in Audio settings for a more logical output-configuration flow.

### Fixed
- Fixed MUSILAND Monitor 09 (and similar USB audio devices) not appearing in the PipeWire device list: the card fallback logic incorrectly skipped cards whose active profile matched the chosen profile even when no PipeWire sink node existed.
- Fixed pro-audio profile switch always failing for devices listed via the `pwcardprofile:` fallback path: the Rust API and Python wrapper now both handle the `pwcardprofile:card|profile` device-id format.
- Fixed device display name showing only the manufacturer name (e.g. "MUSILAND Monitor") instead of the full model name (e.g. "Monitor 09") in non-pro-audio mode: USB index suffix stripping now only removes the trailing bus-index segment (`-NN`) rather than all trailing digits and dashes, and the node `nick` field is preferred when the description ends with "Analog Stereo".
- Fixed pro-audio target resolution after profile switch for `pwcardprofile:` devices: the resolver now extracts the card base name and locates the corresponding pro-audio node (`alsa_output.*pro-output-*`) in the refreshed device list.

---

## 1.5.0 - 2026-03-05
ALSA mmap control and now-playing/layout polish release: explicit `ALSA（auto）` vs `ALSA（mmap）` behavior, mmap realtime-thread tuning, clearer driver guidance, and stronger overlay/list stability with long metadata.

### Added
- Added dedicated ALSA driver variants in UI/runtime: `ALSA（auto）` and `ALSA（mmap）`.
- Added `Realtime Audio Priority` setting for the ALSA mmap writer thread (`Off`, `Low (40)`, `Recommended (60)`, `High (70)`, `Very High (80)`), including persistence and startup restore.
- Added Rust FFI control for mmap RT priority (`rac_set_mmap_realtime_priority`) and Python adapter wiring.
- Added mmap runtime diagnostics to Rust snapshots under `mmap_thread` (running state, realtime attempted/enabled/policy/priority/error, memlock status/mode, reset count).
- Added Audio Driver inline help/popover copy to explain `ALSA（auto）` vs forced `ALSA（mmap）` and MMAP jitter/copy tradeoffs.

### Changed
- Exclusive mode driver behavior changed from forcing a single ALSA option to allowing switching between `ALSA（auto）` and `ALSA（mmap）` only.
- Output Bit Depth copy and driver-family checks now treat both ALSA variants as explicit ALSA output paths.
- Now Playing left-cover rendering now uses full-height cover fill with a dynamic backdrop pipeline, improving visual consistency across artwork aspect/content.
- Now Playing right-side track rows now keep album/duration columns aligned under long titles via stricter label truncation and column ordering.
- Home/search feed card presentation now uses tighter feed-specific media overlays/tints and more stable subtitle/title sizing behavior.
- GTK icon-theme search-path setup now prefers bundled app icon paths ahead of inherited system paths.

### Fixed
- Fixed ALSA mmap startup/idle busy-spin risk by adding backoff when `try-pull-sample` returns no sample, preventing 100% CPU loops in no-flow states.
- Fixed ALSA naming mismatches in Signal Path verdict/help logic so `ALSA（auto）` / `ALSA（mmap）` are evaluated consistently with ALSA-exclusive rules.
- Fixed ALSA mmap spectrum path/state handling to keep spectrum pipeline behavior consistent across output switches and URI/timeline transitions.
- Fixed settings-driver dropdown state transitions around exclusive-mode toggles and persisted driver restoration.

### Tests
- Added/updated regression coverage for:
  - `tests/test_audio_settings_actions.py`
  - `tests/test_app_init_runtime.py`
  - `tests/test_now_playing_overlay_perf.py`
  - `tests/test_home_section_header.py`

---

## 1.4.9 - 2026-03-03
Display-scaling and output-format control release: better 1x readability, device-aware ALSA bit-depth selection, and clearer PipeWire behavior.

### Added
- Added an `Output Bit Depth` selector in Audio settings that reads the selected device's advertised PCM formats and only shows supported ALSA bit depths instead of a fixed `16/24/32-bit` list.

### Changed
- `Output Bit Depth` now appears above `Output Device` in Audio settings for a tighter output-configuration flow.
- `Output Bit Depth` is now ALSA-only. In `PipeWire` mode it stays on disabled `Auto`, because the final hardware bit depth is controlled by the PipeWire graph rather than directly by the player.
- Home-page card sizing now follows a DPI-adaptive shared cover size so album and track tiles keep a more consistent physical size across 1x and HiDPI displays.

### Fixed
- Fixed low-DPI layouts rendering text and artwork too small by detecting the primary display scale at startup and applying matching font/cover-size overrides.
- Fixed output-format control UI showing unsupported bit depths for the selected device and passing misleading format requests through PipeWire.

### Tests
- Verified with:
  - `pytest -q tests/test_audio_settings_actions.py`
  - `CCACHE_DISABLE=1 cargo test --manifest-path src_rust/rust_audio_core/Cargo.toml --lib`

---

## 1.4.8 - 2026-03-03
Navigation and session-recovery stability release: smoother first-open `New` page rendering, better post-sleep page recovery, and a more reliable Signal Path help popover.

### Fixed
- Fixed the `New` page occasionally flashing on first entry because prefetched sections were rendered and then immediately refreshed again instead of being treated as fresh cache data.
- Fixed cases where parts of the app could fail to display after system sleep/resume by resetting stale global HTTP connections before TIDAL session recovery and classifying broken SSL/TCP disconnects as recoverable network failures.
- Fixed the `Audio Signal Path` `Bit-Perfect Verdict` help button occasionally failing to open because the summary area was rebuilding the button every second even when the diagnostics had not changed.

### Tests
- Verified with:
  - `pytest -q tests/test_signal_path_bitperfect.py`
  - `pytest -q tests/test_tidal_session_recovery.py`

---

## 1.4.7 - 2026-03-03
Now Playing album-navigation follow-up release: easier album return flow, correct artist drill-down from overlay-opened albums, and reduced GTK label sizing warnings.

### Added
- The `Now Playing` album tab now includes a floating quick-open action that jumps straight to the current album in the main library view.

### Changed
- Returning from `Now Playing` to an album now synchronizes the left sidebar selection to `My Albums`, so the main shell context matches the page being shown.

### Fixed
- Fixed album header artist navigation for albums opened from `Now Playing` by carrying forward artist context even when the playback track's album object has incomplete artist metadata.
- Reduced repeated GTK `GtkLabel ... natural size must be >= min size` warnings by relaxing vertical sizing for the compact secondary/card label styles used in album and home grids.

### Tests
- Verified with:
  - `pytest -q tests/test_album_artist_navigation.py tests/test_now_playing_overlay_perf.py`
  - `pytest -q tests/test_home_section_header.py tests/test_tidal_home_page.py`

---

## 1.4.6 - 2026-03-03
Signal-path + home-page polish release: terminal-style bit-perfect help, clearer PipeWire verdict rules, quieter runtime diagnostics, and better TIDAL home context headers.

### Changed
- `Audio Signal Path` now shows the `Bit-Perfect Verdict` help as a terminal-style black/green popover that matches the Signal Path page, with a straight-edge shell instead of the default rounded GNOME bubble.
- The `Bit-Perfect Verdict` help copy now explains the exact pass criteria and makes the PipeWire system-mixer limitation explicit alongside the ALSA exclusive-mode requirement.
- PipeWire bit-perfect checks now use the same lossless container-widening rule as ALSA exclusive mode, so `16-bit -> 32-bit` container output is treated as valid when the playback path is otherwise lossless.
- PipeWire verdict failures now report narrower output-depth and sample-rate mismatches separately instead of collapsing them into a generic combined mismatch reason.
- PipeWire pro-audio profile activation now ignores `pwcardprofile:` pseudo-device ids instead of trying to treat them as real output targets.
- TIDAL home-page section headers now preserve official recommendation context more accurately by promoting the feed context title to the main line, rendering the recommendation reason as a smaller kicker, and showing context artwork when the feed provides it.
- TIDAL home-page subtitle handling now keeps upstream `subtitle` text when present and falls back to `description` only when needed, so shelves with contextual recommendations do not lose their intended wording.

### Fixed
- Fixed noisy repeated `Rust runtime snapshot` and `SignalPath latency source` logs by downgrading them to deduped `DEBUG` diagnostics that only emit when the observed runtime state changes.
- Fixed the Signal Path summary refresh loop so the `Bit-Perfect Verdict` help popover stays stable while it is open.
- Fixed failed ALSA exclusive retry paths so the previous active output selection is restored if the post-reservation switch still cannot be completed.

### Tests
- Verified with:
  - `pytest -q tests/test_signal_path_bitperfect.py`
  - `pytest -q tests/test_rust_audio_reservation_retry.py`
  - `pytest -q tests/test_home_section_header.py tests/test_tidal_home_page.py`

---

## 1.4.5 - 2026-03-02
ALSA exclusive reliability + signal-path clarity release: one-shot D-Bus reservation retry, 32-bit container DAC support, and clearer bit-perfect diagnostics/UI.

### Added
- Added D-Bus `org.freedesktop.ReserveDevice1` ALSA reservation support via `src/services/alsa_reserve.py` so exclusive `hw:N,M` playback can politely ask PipeWire/WirePlumber to release the card only after a direct exclusive open fails.
- Added ALSA exclusive runtime diagnostics that log the container adapter format, source bit depth, and active kernel `hw_params` when a 32-bit container-only DAC is in use.
- Added a dedicated `Now Playing` overlay with synchronized playback progress, queue/track panels, lyrics view, and dynamic cover-driven visuals.
- Added regression coverage for:
  - one-shot ALSA reservation retry behavior,
  - active ALSA `hw_params` parsing and container-adapter diagnostic dedupe,
  - ALSA bit-perfect verdict rules that now allow lossless container widening such as `16-bit -> 32-bit`,
  - now-playing overlay state/lyrics sync, favorites sync, and shortcut behavior.

### Changed
- ALSA exclusive output now tries direct hardware open first and only falls back to D-Bus reservation on failure, instead of reserving the device preemptively.
- ALSA exclusive sink creation in the Rust audio core now detects `S32_LE` / `S24_32_LE`-only playback devices from `/proc/asound/cardN/stream*` and inserts `audioconvert + capsfilter` to widen source PCM into the required container format without resampling.
- `Audio Signal Path` bit-perfect rules now treat ALSA exclusive playback as valid when the sample rate matches, the system mixer is bypassed, and output bit depth is greater than or equal to source bit depth.
- `Bit-Perfect Mode` settings now include an explicit help popover explaining the difference between PipeWire source-rate following and true ALSA exclusive bit-perfect playback.
- `Audio Signal Path` now uses a dedicated terminal-style black/green presentation with tighter row spacing.
- Main player, queue, favorites, lyrics, and transport state now mirror into the `Now Playing` overlay so overlay controls stay in sync with the primary UI.

### Fixed
- Fixed an ALSA exclusive retry loop caused by scheduling `set_output()` directly with `GLib.idle_add`, which repeatedly re-applied output switching after reservation success.
- Fixed ALSA exclusive error classification so generic `rust-alsa-sink` messages no longer trigger false device-disconnect recovery loops.
- Fixed transport/output switch error reporting to include the last Rust/GStreamer error detail when available.
- Fixed GTK slider warnings in the Signal Path window by removing the custom scrollbar slider override that conflicted with GTK sizing.
- Fixed album favorite updates not appearing in time in the UI after toggling favorite state.
- Fixed stale active lyric rows and delayed favorite/queue state refresh inside the `Now Playing` overlay.

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
