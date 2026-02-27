#!/bin/bash
set -e

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
CONTAINER_NAME="hiresti-ui-test-$$"

echo "=== hiresTI UI Test Script ==="
echo "Running Ubuntu 24.04 UI test via Podman with X11 forwarding"
echo ""

# 检查 Podman
if ! command -v podman &> /dev/null; then
    echo "Error: Podman is not installed"
    exit 1
fi

# 允许容器访问 X11
echo "Setting up X11 forwarding..."
xhost +local:podman 2>/dev/null || true

# 检查是否已有可用的容器
EXISTING_CONTAINER=$(podman ps -a --format '{{.Names}}' | grep "^hiresti-ui-test-" | head -1)

if [ -n "$EXISTING_CONTAINER" ]; then
    CONTAINER_NAME="$EXISTING_CONTAINER"
    echo "Using existing container: $CONTAINER_NAME"
else
    # 启动新的 Ubuntu 24.04 容器
    echo "Starting new Ubuntu 24.04 container..."
    podman run -d \
        --name "$CONTAINER_NAME" \
        --device /dev/dri:/dev/dri \
        --userns=host \
        -e DISPLAY="$DISPLAY" \
        -v /tmp/.X11-unix:/tmp/.X11-unix \
        -v "$PROJECT_DIR:/hiresTI:Z" \
        -w /hiresTI \
        ubuntu:24.04 \
        sleep infinity

    # 安装依赖
    echo "Installing dependencies in container..."
    podman exec "$CONTAINER_NAME" bash -c "
        export DEBIAN_FRONTEND=noninteractive
        apt-get update
        apt-get install -y --no-install-recommends \
            python3 \
            python3-pip \
            python3-gi \
            python3-gi-cairo \
            python3-cairo \
            python3-dateutil \
            python3-typing-extensions \
            python3-isodate \
            gir1.2-gtk-4.0 \
            gir1.2-adw-1 \
            gir1.2-gtksource-4 \
            qrencode \
            python3-gst-1.0 \
            gstreamer1.0-plugins-base \
            gstreamer1.0-plugins-good \
            gstreamer1.0-plugins-bad \
            gstreamer1.0-plugins-ugly \
            libpipewire-0.3-0 \
            libpulse0 \
            gstreamer1.0-x \
            libgl1 \
            libgstreamer1.0-dev \
            gstreamer1.0-libav \
            libcairo2-dev \
            pkg-config \
            python3-dev \
            build-essential
    "

    # 安装 Python 依赖
    echo "Installing Python packages..."
    podman exec "$CONTAINER_NAME" bash -c "
        pip3 install --break-system-packages \
            --force-reinstall --ignore-installed typing-extensions \
            -r /hiresTI/requirements.txt
    "
fi

echo ""
echo "=== Container ready ==="
echo "Container name: $CONTAINER_NAME"
echo "To enter container: podman exec -it $CONTAINER_NAME bash"
echo "To run app: podman exec -e DISPLAY=$DISPLAY $CONTAINER_NAME python3 -m src.main"
echo ""

# 启动应用
echo "Starting hiresTI..."
podman exec -e DISPLAY="$DISPLAY" -e PYTHONPATH=/hiresTI "$CONTAINER_NAME" python3 src/main.py
