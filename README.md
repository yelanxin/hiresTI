# hiresTI Music Player

![Python](https://img.shields.io/badge/Python-3.10%2B-blue)
![GTK4](https://img.shields.io/badge/UI-GTK4%20%2B%20Libadwaita-green)
![License](https://img.shields.io/badge/License-GPL--3.0-purple)

`hiresTI` is a native Linux desktop client for TIDAL, focused on stable playback, high-quality output paths, and a responsive GTK4/Libadwaita user experience.

## Highlights

- From `v1.2.0`, hiresTI uses a Rust audio engine core by default
- Native Linux UI with GTK4 + Libadwaita
- TIDAL OAuth login and account-scoped library access
- Bit-perfect playback flow with optional exclusive output controls
- Fast collection browsing (Albums, Liked Songs, Artists, Queue, History)
- Cloud playlist management with folder support and cover collage previews
- Built-in queue drawer, lyrics support, and visualizer modules

## Screenshots
### Main Window
![Main Window](screenshots/1.0.5-1.png)
![Visualizer](screenshots/1.0.5-2.png)
![Queue Playlist](screenshots/1.0.5-3.png)
![Settings](screenshots/1.0.5-4.png)
![Settings](screenshots/1.0.5-5.png)
![Settings](screenshots/1.0.5-7.png)
![Settings](screenshots/1.0.5-8.png)
### Mini Mode
<img src="screenshots/1.0.4-5.png" width="400">
<img src="screenshots/1.0.5-6.png" width="500">


## Tech Stack

- Python 3.10+
- GTK4 + Libadwaita (PyGObject)
- Rust audio engine core (`rust_audio_core`)
- GStreamer (audio pipeline runtime via Rust core)
- `tidalapi` (TIDAL integration)

## Audio Engine Note

Starting from `v1.2.0`, playback is driven by the Rust audio engine core by default.
Python remains the UI/application layer, while transport/output routing and core playback runtime run through Rust.

## Runtime Requirements

Install these system packages first:

- Python 3.10+
- GTK4
- Libadwaita
- GStreamer core and plugins
- PyGObject bindings

Bundled Python dependencies used by packaging:

- `tidalapi`
- `requests`
- `urllib3`
- `pystray`
- `pillow`

## Quick Start (Source)

```bash
python3 -m pip install -r requirements.txt
python3 main.py
```

## Install Prebuilt Packages

### Debian / Ubuntu (DEB)

```bash
sudo apt install ./hiresti_<version>_all.deb
```

### Fedora (RPM)

```bash
sudo dnf install ./hiresti-<version>-1.fedora.<arch>.rpm
```

### EL9 (Rocky / Alma / RHEL 9)

```bash
sudo dnf install ./hiresti-<version>-1.el9.<arch>.rpm
```

### Arch Linux

```bash
sudo pacman -U ./hiresti-<version>-1-<arch>.pkg.tar.zst
```

## Upgrade Guide

### Playlist migration note

Starting from `v1.1.0`, local playlists are removed.
Only cloud playlists are supported.

### Fedora / EL9 RPM upgrades

Use upgrade mode when moving to a newer version:

```bash
sudo dnf upgrade ./hiresti-<version>-1.fedora.<arch>.rpm
```

or:

```bash
sudo rpm -Uvh ./hiresti-<version>-1.fedora.<arch>.rpm
```

For EL9 packages, replace `fedora` with `el9`.

Do not use `rpm -i` for upgrades, because it installs side-by-side and can cause file conflict errors.

## Support

If you run into issues, have feature requests, or want to report bugs, please open a GitHub issue:

- https://github.com/yelanxin/hiresTI/issues

## Troubleshooting With Logs

If you hit a problem, please start the app from terminal and attach logs in your issue:

```bash
hiresti 2>&1 | tee /tmp/hiresti.log
```

For GTK debug output:

```bash
G_MESSAGES_DEBUG=all hiresti 2>&1 | tee /tmp/hiresti-gtk.log
```

When reporting, include:

- your distro and desktop environment
- app version
- steps to reproduce
- relevant log snippets (or the full log file path above)

## License

GPL-3.0
