# Changelog

## 1.0.4 - 2026-02-18

### Added
- Added account-scoped local data isolation for history and playlists.
- Added new visualizer effects:
  - `Pro Bars`
  - `Pro Line`
  - `Pro Fall`
  - `Stars`
- Added `Infrared` spectrum theme.
- Added `Stars BWR` theme for `Stars` effect (pure black background + blue/white/red stars).
- Added richer `Burst` particle rendering (denser particles, layered glow, bass shockwave).

### Changed
- Refined visualizer naming to shorter effect labels:
  - `Wave`, `Fill`, `Mirror`, `Dots`, `Peak`, `Trail`, `Pulse`, `Stereo`, `Burst`, `Fall`, `Spiral`, `Pro Bars`, `Pro Line`, `Pro Fall`
- Improved `Pro Fall` performance by pre-binning spectrum history and reducing per-frame computation.
- Updated default visualizer behavior and theme integration so effects follow selected spectrum theme more consistently.
- Reworked packaging script (`package.sh`):
  - Bundles required source folders (`ui/`, `actions/`, `icons/`).
  - Adds preflight checks.
  - Uses safer shell options and quoting.
  - Produces dual RPM variants from one command:
    - Fedora (`.fedora`)
    - EL9 (`.el9`)
  - Keeps support for single-variant RPM builds (`rpm-fedora`, `rpm-el9`).
- Updated README with packaging/install instructions and screenshot placeholders.

### Removed
- Removed `IR Waterfall` effect (superseded by `Pro Fall`).
- Removed legacy redundant infrared-only branch no longer used.

### Packaging Output (1.0.4)
- `hiresti_1.0.4_all.deb`
- `hiresti-1.0.4-1.fedora.x86_64.rpm`
- `hiresti-1.0.4-1.el9.x86_64.rpm`

### Notes
- Local cache root remains `~/.cache/hiresti`.
- Account-scoped files are now stored under per-user profile directories after login.
