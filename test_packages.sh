#!/bin/bash
set -e

# ---------- 参数解析 ----------
VERSION=""
TARGETS=()

usage() {
    echo "Usage: $0 [--version <x.y.z>] [--os <target>[,<target>...]]"
    echo ""
    echo "  -v, --version   指定要测试的版本号，例如 1.2.8"
    echo "                  未指定时自动从 dist/ 目录检测"
    echo "  -o, --os        指定要测试的系统，多个用逗号分隔，不指定则全部测试"
    echo ""
    echo "  可用的系统名称:"
    echo "    debian        Debian Bookworm (DEB)"
    echo "    ubuntu        Ubuntu 24.04 Noble (DEB)"
    echo "    fedora        Fedora 41 (RPM)"
    echo "    el9           Rocky Linux 9 / EL9 (RPM)"
    echo "    arch          Arch Linux (pkg.tar.zst)"
    echo "    flatpak       Flatpak (fedora:41 容器)"
    echo ""
    echo "  示例:"
    echo "    $0 --version 1.2.8 --os debian"
    echo "    $0 --version 1.2.8 --os debian,ubuntu"
    echo "    $0 -v 1.2.8 -o fedora,el9"
    echo "    $0  # 自动检测版本，测试全部"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        -v|--version)
            VERSION="$2"
            shift 2
            ;;
        -o|--os)
            IFS=',' read -ra TARGETS <<< "$2"
            shift 2
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "Unknown argument: $1"
            usage
            exit 1
            ;;
    esac
done

# 未指定版本时，从 dist/ 目录自动检测
if [[ -z "$VERSION" ]]; then
    VERSION=$(ls dist/hiresti_*.deb 2>/dev/null | head -1 | grep -oP '(?<=hiresti_)\d+\.\d+\.\d+')
fi
if [[ -z "$VERSION" ]]; then
    echo "Error: 无法自动检测版本号，请使用 --version 指定"
    echo "Usage: $0 --version <x.y.z>"
    exit 1
fi

# 未指定系统时，默认全部
ALL_TARGETS=(debian ubuntu fedora el9 arch flatpak)
if [[ ${#TARGETS[@]} -eq 0 ]]; then
    TARGETS=("${ALL_TARGETS[@]}")
fi

# 校验系统名称
for t in "${TARGETS[@]}"; do
    valid=0
    for a in "${ALL_TARGETS[@]}"; do
        [[ "$t" == "$a" ]] && valid=1 && break
    done
    if [[ $valid -eq 0 ]]; then
        echo "Error: 未知系统 '$t'"
        echo "可用: ${ALL_TARGETS[*]}"
        exit 1
    fi
done

echo "测试版本: ${VERSION}"
echo "测试系统: ${TARGETS[*]}"
echo ""

should_run() { for t in "${TARGETS[@]}"; do [[ "$t" == "$1" ]] && return 0; done; return 1; }

# ---------- 各系统测试函数 ----------

test_debian() {
    echo "========== 测试 DEB 包 (Debian Bookworm) =========="
    podman run --rm --privileged -v "$(pwd)/dist:/dist" debian:bookworm bash -c "
        apt-get update -qq
        apt-get install -y -qq python3-gst-1.0 2>&1 | tail -5
        apt-get install -y -qq python3-gi python3-gi-cairo python3-dateutil python3-typing-extensions python3-isodate gstreamer1.0-plugins-good gstreamer1.0-plugins-bad gstreamer1.0-plugins-ugly gstreamer1.0-plugins-base gir1.2-gtk-4.0 gir1.2-adw-1 python3-numpy libcairo2-dev pkg-config gir1.2-gst-plugins-base-1.0 libpipewire-0.3-0 libpulse0 2>&1 | tail -10
        dpkg -i /dist/hiresti_${VERSION}_amd64.deb 2>&1 | tail -10 || apt-get install -f -y -qq 2>&1 | tail -5
        ls -la /usr/bin/hiresti
        /usr/bin/hiresti 2>&1 | head -30 || echo 'Binary test complete'
    "
}

test_ubuntu() {
    echo "========== 测试 DEB 包 (Ubuntu 24.04 Noble) =========="
    podman run --rm --privileged -v "$(pwd)/dist:/dist" ubuntu:24.04 bash -c "
        apt-get update -qq
        apt-get install -y -qq python3-gst-1.0 2>&1 | tail -5
        apt-get install -y -qq python3-gi python3-gi-cairo python3-dateutil python3-typing-extensions python3-isodate gstreamer1.0-plugins-good gstreamer1.0-plugins-bad gstreamer1.0-plugins-ugly gstreamer1.0-plugins-base gir1.2-gtk-4.0 gir1.2-adw-1 python3-numpy libcairo2-dev pkg-config gir1.2-gst-plugins-base-1.0 libpipewire-0.3-0 libpulse0 2>&1 | tail -10
        dpkg -i /dist/hiresti_${VERSION}_amd64.deb 2>&1 | tail -10 || apt-get install -f -y -qq 2>&1 | tail -5
        ls -la /usr/bin/hiresti
        /usr/bin/hiresti 2>&1 | head -30 || echo 'Binary test complete'
    "
}

test_fedora() {
    echo "========== 测试 RPM (Fedora 41) 包 =========="
    podman run --rm --privileged -v "$(pwd)/dist:/dist" fedora:41 bash -c "
        dnf install -y -q /dist/hiresti-${VERSION}-1.fedora.x86_64.rpm 2>&1 | tail -5
        ls -la /usr/bin/hiresti
        /usr/bin/hiresti 2>&1 | head -30 || echo 'Binary test complete'
    "
}

test_el9() {
    echo "========== 测试 RPM (EL9 / Rocky Linux 9) 包 =========="
    podman run --rm --privileged -v "$(pwd)/dist:/dist" rockylinux:9 bash -c "
        # 启用 EPEL 和 CRB 仓库，提供 libadwaita / gstreamer1-plugins-bad-free / gstreamer1-plugins-ugly-free
        dnf install -y -q epel-release 2>&1 | tail -3
        dnf config-manager --set-enabled crb 2>&1 | tail -3
        dnf install -y -q /dist/hiresti-${VERSION}-1.el9.x86_64.rpm 2>&1 | tail -5
        ls -la /usr/bin/hiresti
        /usr/bin/hiresti 2>&1 | head -30 || echo 'Binary test complete'
    "
}

test_arch() {
    echo "========== 测试 Arch 包 =========="
    podman run --rm --privileged -v "$(pwd)/dist:/dist" archlinux:latest bash -c "
        pacman -Sy --noconfirm 2>&1 | tail -3
        pacman -S --noconfirm --needed python gtk4 libadwaita gstreamer gst-plugins-good gst-plugins-bad gst-plugins-ugly gst-python python-gobject python-cairo pipewire libpulse 2>&1 | tail -10
        pacman -U --noconfirm /dist/hiresti-${VERSION}-1-x86_64.pkg.tar.zst 2>&1 | tail -5
        ls -la /usr/bin/hiresti
        /usr/bin/hiresti 2>&1 | head -30 || echo 'Binary test complete'
    "
}

test_flatpak() {
    echo "========== 测试 Flatpak 包 =========="
    podman run --rm --privileged -v "$(pwd)/dist:/dist" -u root fedora:41 bash -c "
        dnf install -y -q flatpak 2>&1 | tail -3
        flatpak remote-add --if-not-exists --system flathub https://flathub.org/repo/flathub.flatpakrepo 2>&1 | tail -3
        flatpak install -y --system flathub org.gnome.Platform//48 2>&1 | tail -10
        flatpak install -y --system /dist/hiresti-${VERSION}.flatpak 2>&1 | tail -10
        flatpak list | grep hiresti
        flatpak run com.hiresti.player 2>&1 | head -30 || echo 'Flatpak test complete'
    "
}

# ---------- 按顺序执行选中的测试 ----------
first=1
for target in "${TARGETS[@]}"; do
    [[ $first -eq 0 ]] && echo ""
    first=0
    test_${target}
done

echo ""
echo "========== 所有测试完成 =========="
