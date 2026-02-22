# Flatpak/Flathub Packaging Notes

This directory contains a starter manifest for `com.hiresti.player` with a minimal permission set.

## Permission policy

The manifest intentionally keeps only the required permissions:

- `--share=network` for TIDAL API and stream access
- `--socket=wayland` and `--socket=fallback-x11` for desktop UI
- `--socket=pulseaudio` for audio output
- `--device=dri` for GPU acceleration/visualizer rendering

Not requested:

- `--filesystem=home` / `--filesystem=host`
- broad D-Bus talk names
- `--device=all`

## Submission checklist before opening a Flathub PR

1. Replace the `python-deps` module with pinned, auditable Python sources (no network-time pip install in build).
2. Run `flatpak-builder --user --install --force-clean build-dir flatpak/com.hiresti.player.yml` locally.
3. Validate AppStream metadata and screenshots.
4. Verify runtime behavior in sandbox (login, playback, device switch, rate switching).
