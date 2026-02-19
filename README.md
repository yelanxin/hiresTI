# hiresTI Music Player

![Python](https://img.shields.io/badge/Python-3.10%2B-blue)
![GTK4](https://img.shields.io/badge/UI-GTK4%20%2B%20Libadwaita-green)
![License](https://img.shields.io/badge/License-MIT-purple)

Native Linux TIDAL desktop player built with GTK4 + Libadwaita + GStreamer.

- Bit-perfect playback flow
- Exclusive output mode support
- Rich visualizer effects and themes
- Local playlists/history
- TIDAL OAuth login

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


## Requirements

Runtime (system packages):

- Python 3.10+
- GTK4
- Libadwaita
- GStreamer + good/bad/ugly plugins
- PyGObject bindings

Python packages (bundled in package script):

- tidalapi
- requests
- urllib3
- pystray
- pillow

## Install

1. Downloading the binary App from release page.

### Debian / Ubuntu (DEB)

```bash
sudo dpkg -i hiresti_<version>_all.deb
sudo apt -f install
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


## Notes

- Local data is stored under `~/.cache/hiresti`.
- History and playlists are account-scoped after login (per TIDAL user id).

## License

MIT
