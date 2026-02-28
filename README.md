# hiresTI Music Player

![Python](https://img.shields.io/badge/Python-3.10%2B-blue)
![Rust](https://img.shields.io/badge/Rust-1.70%2B-orange?logo=rust)
![GTK4](https://img.shields.io/badge/UI-GTK4%20%2B%20Libadwaita-green)
![License](https://img.shields.io/badge/License-GPL--3.0-purple)
[![OpenClaw Integrated](https://img.shields.io/badge/OpenClaw-Integrated-1F6FEB)](./openclaw-mcp-guide-en.md)


`hiresTI` is an AI-ready native Linux desktop client for TIDAL, focused on stable playback, high-quality output paths, a responsive GTK4/Libadwaita user experience, and OpenClaw/MCP integration for AI-driven control.

## Highlights

- From `v1.2.0`, hiresTI uses a Rust audio engine core by default
- Native Linux UI with GTK4 + Libadwaita
- TIDAL OAuth login and account-scoped library access
- Bit-perfect playback flow with optional exclusive output controls
- Fast collection browsing (Albums, Liked Songs, Artists, Queue, History)
- Cloud playlist management with folder support and cover collage previews
- Built-in queue drawer, lyrics support, and visualizer modules
- MPRIS support (`org.mpris.MediaPlayer2.hiresti`) for desktop media controls
- Built-in remote control with HTTP JSON-RPC, MCP endpoint, and OpenClaw integration support

## Screenshots
### Main Window
![Main Window](screenshots/1.3.1-1.png)
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
cargo build --manifest-path src_rust/rust_audio_core/Cargo.toml --release
cargo build --manifest-path src_rust/rust_viz_core/Cargo.toml --release
python3 src/main.py
```

`hiresTI` loads the Rust audio and visualizer cores from `src_rust/*/target/release`, so the `--release` build step is required before running from source.

## Remote Control / MCP (OpenClaw)

Starting from `v1.4.0`, hiresTI includes a built-in remote control service with:

- HTTP JSON-RPC control endpoint
- MCP endpoint for OpenClaw / `mcporter`
- Bearer API key authentication
- `Local only` and `LAN` access modes

Typical OpenClaw setup:

1. In hiresTI, open `Settings > Remote Control`.
2. Enable Remote Control.
3. Leave it on `Local only` for same-machine use, or switch to `LAN` for another device.
4. Copy the MCP endpoint and API key shown in hiresTI.
5. Register the MCP service in OpenClaw:

```bash
cd ~/.openclaw/workspace
mcporter config add hires_ti http://127.0.0.1:18473/mcp \
  --header "Authorization=Bearer <YOUR_REMOTE_TOKEN>"
```

Then verify it:

```bash
mcporter list
mcporter list hires_ti --schema
mcporter call hires_ti.player_get_state
```

For a dedicated OpenClaw setup guide, see [openclaw-mcp-guide-en.md](./openclaw-mcp-guide-en.md).

## Install Prebuilt Packages
Please download prebuilt package from release page.

### Debian / Ubuntu (DEB)

```bash
sudo apt install ./hiresti_<version>_amd64.deb
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

### Flatpak

```bash
flatpak install ./hiresti-<version>.flatpak
```

Run:

```bash
flatpak run com.hiresti.player
```

> **Note:** Requires GNOME Platform runtime 48. If not already installed:
> ```bash
> flatpak install flathub org.gnome.Platform//48 org.gnome.Sdk//48
> ```
>
> User data is stored under `~/.var/app/com.hiresti.player/`.


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

## Acknowledgements

Special thanks to everyone who shares feedback. In particular, [ilijagosp](https://github.com/ilijagosp) has provided feedback and suggestions with every new release.

## License

GPL-3.0
