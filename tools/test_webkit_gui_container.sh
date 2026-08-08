#!/usr/bin/env bash
# Run hiresTI (or a minimal WebKit login probe) in a GUI container for
# manual issue #83 testing on Hyprland / wlroots hosts.
#
# Usage:
#   ./tools/test_webkit_gui_container.sh probe   # quick WebKit login page
#   ./tools/test_webkit_gui_container.sh app     # full hiresTI UI
#
# Requirements on host: Docker, running Wayland or X11 session, PipeWire.
set -euo pipefail

MODE="${1:-probe}"
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
IMAGE="${HIRESTI_GUI_TEST_IMAGE:-hiresti-gui-test-arch}"
CONTAINER="${HIRESTI_GUI_TEST_CONTAINER:-hiresti-gui-test-$$}"
UID_GID="$(id -u):$(id -g)"

if ! command -v docker >/dev/null; then
  echo "Error: docker not found" >&2
  exit 1
fi

if [[ -z "${XDG_RUNTIME_DIR:-}" ]]; then
  export XDG_RUNTIME_DIR="/run/user/$(id -u)"
fi

DISPLAY_FLAGS=()
if [[ "${XDG_SESSION_TYPE:-}" == "wayland" && -n "${WAYLAND_DISPLAY:-}" ]]; then
  echo "Using Wayland display: ${WAYLAND_DISPLAY} (${XDG_RUNTIME_DIR})"
  DISPLAY_FLAGS+=(
    -e "WAYLAND_DISPLAY=${WAYLAND_DISPLAY}"
    -e "XDG_SESSION_TYPE=wayland"
    -v "${XDG_RUNTIME_DIR}:${XDG_RUNTIME_DIR}"
  )
else
  echo "Using X11 display: ${DISPLAY:-:0}"
  if command -v xhost >/dev/null; then
    xhost +local:docker >/dev/null 2>&1 || true
  fi
  DISPLAY_FLAGS+=(
    -e "DISPLAY=${DISPLAY:-:0}"
    -v /tmp/.X11-unix:/tmp/.X11-unix
  )
fi

echo "Building GUI test image (${IMAGE}) if needed..."
docker build -t "${IMAGE}" -f - "${PROJECT_DIR}" <<'DOCKERFILE'
FROM archlinux:latest
RUN pacman -Syu --noconfirm \
    python python-pip python-gobject gtk4 libadwaita \
    webkitgtk-6.0 xdg-dbus-proxy bubblewrap \
    gstreamer gst-plugin-pipewire pipewire pipewire-pulse wireplumber \
    dbus mesa qrencode curl ca-certificates \
    && pacman -Scc --noconfirm
WORKDIR /hiresTI
DOCKERFILE

echo "Starting container (${CONTAINER})..."
docker run -it --rm \
  --name "${CONTAINER}" \
  --userns=host \
  --ipc=host \
  --network=host \
  --device /dev/dri:/dev/dri \
  -e "XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR}" \
  -e "HOME=/tmp/hiresti-home" \
  -u "${UID_GID}" \
  "${DISPLAY_FLAGS[@]}" \
  -v "${PROJECT_DIR}:/hiresTI" \
  -w /hiresTI \
  "${IMAGE}" \
  bash -lc '
    set -e
    mkdir -p "$HOME"
    export PYTHONPATH=/hiresTI/src
  if [[ ! -f src_rust/rust_audio_core/target/release/librust_audio_core.so ]]; then
    echo "Note: Rust audio core not built on host mount; app mode may fail."
    echo "      Build on host: (cd src_rust/rust_audio_core && cargo build --release)"
  fi
  if [[ -f requirements.txt ]]; then
    pip install --user -q -r requirements.txt || true
  fi
  case "'"${MODE}"'" in
    probe)
      echo "Launching WebKit login probe (close window to exit)..."
      exec python tools/webkit_login_probe.py
      ;;
    app)
      echo "Launching full hiresTI (close window to exit)..."
      exec python src/main.py
      ;;
    bash)
      echo "Interactive shell. Try:"
      echo "  python tools/webkit_login_probe.py"
      echo "  python src/main.py"
      exec bash
      ;;
    *)
      echo "Unknown mode: '"'"${MODE}"'"'" >&2
      exit 2
      ;;
  esac
'
