# hiresTI Desktop 🎵

![Python](https://img.shields.io/badge/Python-3.10%2B-blue)
![GTK4](https://img.shields.io/badge/UI-GTK4%20%2B%20Libadwaita-green)
![License](https://img.shields.io/badge/License-MIT-purple)
![Status](https://img.shields.io/badge/Status-v1.0-orange)

**hiresTI** is a modern, high-fidelity TIDAL client for Linux, built with **GTK4**, **Libadwaita**, and **GStreamer**. 

Designed for audiophiles, it prioritizes sound quality above all else, featuring a dedicated **Bit-Perfect Mode** and **Hardware Exclusive Locking** to bypass the OS mixer and deliver pure, unaltered audio to your DAC.

![Main Interface](screenshots/1.png)

## ✨ Key Features

* **🎧 Audiophile-Grade Audio Engine**
    * **Bit-Perfect Playback**: Automatically switches your DAC's sample rate to match the source track (44.1kHz, 96kHz, etc.) using PipeWire metadata.
    * **Hardware Exclusive Mode**: Completely bypasses the system sound server (PulseAudio/PipeWire) and locks the ALSA hardware device for the purest signal path.
    * **Glowing "BIT PERFECT" Indicator**: Visual confirmation when the audio path is uncompromised.
    * **10-Band Equalizer**: Built-in DSP for sound tuning (automatically disabled in Bit-Perfect mode).

* **🎨 Modern Linux UI**
    * Native **GTK4 + Libadwaita** interface that feels right at home on GNOME/Fedora/Ubuntu.
    * **HiDPI Support**: Crisp, high-resolution album art rendering.
    * **Adaptive Player Bar**: Three-line layout (Title, Artist, Album) with a floating, translucent glass-morphism effect.
    * **Interactive Elements**: Clickable artist names, hover effects, and animated favorite (heart) icons.

* **🚀 Tidal Integration**
    * **OAuth Login**: Secure login via the official Tidal web flow.
    * **Master/Hi-Res Support**: Supports FLAC streaming up to 24-bit/192kHz.
    * **My Collection**: Access your Playlists, Favorite Artists, and Albums.
    * **Search**: Unified search for Artists, Albums, and Tracks.

## 📸 Screenshots

| Album Detai | Setting |
|:---:|:---:|
| ![Detail](screenshots/2.png) | ![Search](screenshots/3.png) |

## 🛠️ Installation

### Prerequisites

**Fedora 43 (Recommended)**
```bash
sudo dnf install python3-gobject gtk4 libadwaita gstreamer1 \
    gstreamer1-plugins-base gstreamer1-plugins-good \
    gstreamer1-plugins-bad-free gstreamer1-plugins-ugly-free \
    gstreamer1-libav pipewire-utils pulseaudio-utils psmisc \
    python3-pip python3-devel gcc
