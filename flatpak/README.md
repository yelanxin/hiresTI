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

## Python dependency lock file

`python3-requirements.json` is generated from `flatpak/requirements-flatpak.txt` using:

```bash
python3 -m flatpak_pip_generator -r flatpak/requirements-flatpak.txt -o flatpak/python3-requirements
```

Re-run the command when Python dependency versions change.

## Submission checklist before opening a Flathub PR

1. Run `flatpak-builder --user --install --force-clean build-dir flatpak/com.hiresti.player.yml` locally.
2. Validate AppStream metadata and screenshots.
3. Verify runtime behavior in sandbox (login, playback, device switch, rate switching).
