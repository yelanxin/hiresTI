# hiresTI Music Player

![Python](https://img.shields.io/badge/Python-3.10%2B-blue)
![GTK4](https://img.shields.io/badge/UI-GTK4%20%2B%20Libadwaita-green)
![License](https://img.shields.io/badge/License-MIT-purple)

`hiresTI` is a native Linux desktop client for TIDAL, focused on stable playback, high-quality output paths, and a responsive GTK4/Libadwaita user experience.

## Highlights

- Native Linux UI with GTK4 + Libadwaita
- TIDAL OAuth login and account-scoped library access
- Bit-perfect playback flow with optional exclusive output controls
- Fast collection browsing (Albums, Liked Songs, Artists, Queue, History)
- Local playlist management with cover collage generation
- Built-in queue drawer, lyrics support, and visualizer modules
- Linux package build pipeline for DEB and RPM targets

## Screenshots
### Main Window
![Main Window](screenshots/1.0.5-1.png)
![Visualizer](screenshots/1.0.5-2.png)
![Queue Playlist](screenshots/1.0.5-3.png)
![Settings](screenshots/1.0.5-4.png)
![Settings](screenshots/1.0.5-5.png)
![Settings](screenshots/1.0.5-6.png)
![Settings](screenshots/1.0.5-7.png)
![Settings](screenshots/1.0.5-8.png)
### Mini Mode
<img src="screenshots/1.0.4-5.png" width="400">

## Tech Stack

- Python 3.10+
- GTK4 + Libadwaita (PyGObject)
- GStreamer (playback pipeline)
- `tidalapi` (TIDAL integration)

## Runtime Requirements

Install these system packages first:

- Python 3.10+
- GTK4
- Libadwaita
- GStreamer core and plugins (`good` / `bad` / `ugly`)
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

## License

MIT
