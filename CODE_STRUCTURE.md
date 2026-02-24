# Code Structure

This document describes the project structure of hiresTI for developers and contributors.

## Overview

hiresTI is a native Linux desktop client for TIDAL, built with Python (GTK4/Libadwaita) for the UI layer and Rust for the audio engine core.

## Directory Structure

```
hiresTI/
├── src/                    # Main Python source code
│   ├── main.py            # Application entry point
│   ├── core/              # Core application modules
│   ├── backend/           # External service integrations
│   ├── models/            # Data models
│   ├── services/          # Business logic services
│   ├── ui/                # User interface components
│   ├── actions/           # User action handlers
│   ├── viz/               # Visualizer components
│   ├── utils/             # Utility functions
│   └── _rust/             # Rust bindings (FFI)
├── src_rust/              # Rust source code
│   ├── rust_audio_core/   # Audio playback engine
│   ├── rust_viz_core/     # Visualization processing
│   └── rust_launcher/     # Application launcher
├── tests/                 # Unit tests
├── flatpak/               # Flatpak packaging
└── icons/                 # Application icons
```

## Module Details

### `src/core/` - Core Application Modules

Low-level application infrastructure and configuration.

| File | Description |
|------|-------------|
| `constants.py` | Application constants (PlayMode, LyricsSettings, AudioLatency, VisualizerSettings, etc.) |
| `settings.py` | Settings management (load/save configuration) |
| `errors.py` | Error classification and user message handling |
| `logging.py` | Logging setup and configuration |
| `executor.py` | Task execution utilities (submit_task, submit_daemon) |

### `src/backend/` - External Service Integrations

Third-party service integrations.

| File | Description |
|------|-------------|
| `tidal.py` | TIDAL API client (OAuth, playlist management, search, streaming) |

### `src/models/` - Data Models

Data structures representing domain entities.

| File | Description |
|------|-------------|
| `local.py` | Local data models (LocalArtist, LocalAlbum, LocalTrack) |
| `playlist.py` | Playlist and history management (HistoryManager, PlaylistManager) |

### `src/services/` - Business Logic Services

Service layer handling core application functionality.

| File | Description |
|------|-------------|
| `lyrics.py` | Lyrics fetching and management |
| `signal_path.py` | Audio signal path window (PipeWire/PulseAudio monitoring) |

### `src/ui/` - User Interface Components

UI components and builders.

| File | Description |
|------|-------------|
| `builders.py` | Main UI builder functions |
| `views_builders.py` | View builder functions |
| `track_table.py` | Track table components |
| `config.py` | UI configuration constants |

### `src/actions/` - User Action Handlers

Event handlers for user interactions.

| File | Description |
|------|-------------|
| `playback_actions.py` | Play/pause, next/previous track handling |
| `audio_settings_actions.py` | Audio device, latency, driver settings |
| `lyrics_playback_actions.py` | Lyrics display and synchronization |
| `playback_stream_actions.py` | Stream quality, URL handling |
| `ui_actions.py` | UI rendering and updates |
| `ui_navigation.py` | Navigation and routing |

### `src/viz/` - Visualizer Components

Audio visualization modules.

| File | Description |
|------|-------------|
| `visualizer.py` | Base spectrum visualizer (Cairo) |
| `visualizer_gpu.py` | GPU-accelerated visualizer |
| `visualizer_glarea.py` | OpenGL-based visualizer |
| `background_viz.py` | Background visualizer for window |

### `src/utils/` - Utility Functions

Helper functions and utilities.

| File | Description |
|------|-------------|
| `helpers.py` | Image caching, cover art generation, audio caching, cursor utilities |

### `src/_rust/` - Rust Bindings (FFI)

Python bindings for Rust components.

| File | Description |
|------|-------------|
| `audio.py` | Rust audio engine wrapper (create_audio_engine, RustAudioPlayerAdapter) |
| `viz.py` | Rust visualizer processor (RustVizCore, RustBarsRenderer) |

### `src_rust/` - Rust Source Code

Native Rust implementations for performance-critical components.

| Directory | Description |
|-----------|-------------|
| `rust_audio_core/` | Audio playback engine (GStreamer-based) |
| `rust_viz_core/` | FFT and visualization processing |
| `rust_launcher/` | Application launcher |

## Key Dependencies

### Python Dependencies

- `gi` (PyGObject) - GTK4/Libadwaita bindings
- `tidalapi` - TIDAL API client
- `requests` - HTTP client
- `qrcode` - QR code generation for login
- `pystray` - System tray support
- `PIL` (Pillow) - Image processing

### Rust Dependencies (vendored)

- `gstreamer` - Audio pipeline
- `rubato` - Resampling
- `symphonia` - Audio decoding
- `anyhow` - Error handling

## Import Conventions

The project uses relative imports within the `src/` package:

```python
# Core modules
from core.settings import load_settings
from core.logging import setup_logging
from core.errors import classify_exception

# Backend
from backend import TidalBackend

# Models
from models import HistoryManager, PlaylistManager

# Services
from services.lyrics import LyricsManager
from services.signal_path import AudioSignalPathWindow

# UI
from ui import builders, views_builders
from ui.config import *

# Actions
from actions import playback_actions, ui_actions

# Utils
import utils.helpers as utils

# Rust bindings
from _rust.audio import create_audio_engine
from _rust.viz import RustVizCore
```

## Running the Application

```bash
# From project root
python src/main.py

# Or using the package script
./package.sh run
```

## Building Rust Components

```bash
# Build audio core
cd src_rust/rust_audio_core
cargo build --release

# Build viz core
cd src_rust/rust_viz_core
cargo build --release
```

## Testing

```bash
# Run all tests
pytest

# Run specific test file
pytest tests/test_playback_actions.py
```

## Architecture Notes

1. **Hybrid Python/Rust Design**: The application uses Python for UI and high-level logic, with Rust handling performance-critical audio processing.

2. **Event-Driven UI**: GTK4's signal system handles user interactions through action modules.

3. **Service Layer**: Business logic is encapsulated in services, keeping UI code clean.

4. **Model-View separation**: Models define data structures, UI modules handle rendering.

## Contributing

When adding new functionality:

1. Place new code in the appropriate module directory
2. Update imports in affected files
3. Add tests in `tests/`
4. Update this document if the structure changes
