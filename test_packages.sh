#!/bin/bash
set -e

# 测试 DEB 包 (Debian Bookworm)
echo "========== 测试 DEB 包 (Debian Bookworm) =========="
podman run --rm --privileged -v "$(pwd)/dist:/dist" debian:bookworm bash -c "
    apt-get update -qq
    # Install gstreamer first, then python3-gst
    apt-get install -y -qq python3-gi python3-gi-cairo python3-dateutil python3-typing-extensions python3-isodate gstreamer1.0-plugins-good gstreamer1.0-plugins-bad gstreamer1.0-plugins-ugly gstreamer1.0-plugins-base gir1.2-gtk-4.0 gir1.2-adw-1 python3-numpy libcairo2-dev pkg-config gir1.2-gst-plugins-base-1.0 2>&1 | tail -10
    dpkg -i /dist/hiresti_1.2.5_all.deb 2>&1 | tail -10 || apt-get install -f -y -qq 2>&1 | tail -5
    ls -la /usr/bin/hiresti
    /usr/bin/hiresti 2>&1 | head -10 || echo 'Binary test complete'
"

# 测试 DEB 包 (Ubuntu 24.04 Noble)
echo ""
echo "========== 测试 DEB 包 (Ubuntu 24.04 Noble) =========="
podman run --rm --privileged -v "$(pwd)/dist:/dist" ubuntu:24.04 bash -c "
    apt-get update -qq
    # Ubuntu 24.04 requires python3-gst-1.0 to be installed first
    apt-get install -y -qq python3-gst-1.0 2>&1 | tail -5
    apt-get install -y -qq python3-gi python3-gi-cairo python3-dateutil python3-typing-extensions python3-isodate gstreamer1.0-plugins-good gstreamer1.0-plugins-bad gstreamer1.0-plugins-ugly gstreamer1.0-plugins-base gir1.2-gtk-4.0 gir1.2-adw-1 python3-numpy libcairo2-dev pkg-config gir1.2-gst-plugins-base-1.0 2>&1 | tail -10
    dpkg -i /dist/hiresti_1.2.5_all.deb 2>&1 | tail -10 || apt-get install -f -y -qq 2>&1 | tail -5
    ls -la /usr/bin/hiresti
    /usr/bin/hiresti 2>&1 | head -10 || echo 'Binary test complete'
"

# 测试 DEB 包 (Ubuntu 22.04 Jammy)
echo ""
echo "========== 测试 DEB 包 (Ubuntu 22.04 Jammy) =========="
podman run --rm --privileged -v "$(pwd)/dist:/dist" ubuntu:22.04 bash -c "
    apt-get update -qq
    # Ubuntu 22.04 may require python3-gst-1.0 to be installed first
    apt-get install -y -qq python3-gst-1.0 2>&1 | tail -5
    apt-get install -y -qq python3-gi python3-gi-cairo python3-dateutil python3-typing-extensions python3-isodate gstreamer1.0-plugins-good gstreamer1.0-plugins-bad gstreamer1.0-plugins-ugly gstreamer1.0-plugins-base gir1.2-gtk-4.0 gir1.2-adw-1 python3-numpy libcairo2-dev pkg-config gir1.2-gst-plugins-base-1.0 2>&1 | tail -10
    dpkg -i /dist/hiresti_1.2.5_all.deb 2>&1 | tail -10 || apt-get install -f -y -qq 2>&1 | tail -5
    ls -la /usr/bin/hiresti
    /usr/bin/hiresti 2>&1 | head -10 || echo 'Binary test complete'
"

# 测试 RPM (Fedora) 包
echo ""
echo "========== 测试 RPM (Fedora) 包 =========="
podman run --rm --privileged -v "$(pwd)/dist:/dist" fedora:41 bash -c "
    dnf install -y -q /dist/hiresti-1.2.5-1.fedora.x86_64.rpm 2>&1 | tail -5
    ls -la /usr/bin/hiresti
    /usr/bin/hiresti 2>&1 | head -10 || echo 'Binary test complete'
"

# 测试 RPM (EL9) 包
echo ""
echo "========== 测试 RPM (EL9) 包 =========="
podman run --rm --privileged -v "$(pwd)/dist:/dist" rockylinux:9 bash -c "
    dnf install -y -q /dist/hiresti-1.2.5-1.el9.x86_64.rpm 2>&1 | tail -5
    ls -la /usr/bin/hiresti
    /usr/bin/hiresti 2>&1 | head -10 || echo 'Binary test complete'
"

# 测试 Arch 包
echo ""
echo "========== 测试 Arch 包 =========="
podman run --rm --privileged -v "$(pwd)/dist:/dist" archlinux:latest bash -c "
    pacman -Sy --noconfirm 2>&1 | tail -3
    tar -xf /dist/hiresti-1.2.5-1-x86_64.pkg.tar.zst -C /tmp 2>&1
    ls -la /tmp/usr/bin/hiresti 2>&1 || echo 'Binary check'
"

# 测试 Flatpak 包
echo ""
echo "========== 测试 Flatpak 包 =========="
podman run --rm --privileged -v "$(pwd)/dist:/dist" -u root fedora:41 bash -c "
    dnf install -y -q flatpak 2>&1 | tail -3
    flatpak remote-add --if-not-exists flathub /usr/share/flatpak/flathub.flatpakrepo 2>/dev/null || flatpak remote-add --if-not-exists flathub https://flathub.org/repo/flathub.flatpakrepo 2>&1 | tail -5
    flatpak install -y --user flathub org.gnome.Platform//48 org.gnome.Sdk//48 2>&1 | tail -10
    flatpak install -y --user /dist/hiresti-1.2.5.flatpak 2>&1 | tail -10
    flatpak list | grep hiresti
"

echo ""
echo "========== 所有测试完成 =========="
