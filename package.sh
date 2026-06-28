#!/bin/bash
set -euo pipefail

# ================= 配置区域 =================
APP_NAME="hiresti"
APP_ID="com.hiresti.player"
DISPLAY_NAME="HiresTI"
MAINTAINER="Eason <yelanxin@gmail.com>"
DESCRIPTION="High-Res Tidal Player for Linux with Bit-Perfect support."
LICENSE="GPL-3.0"
URL="https://github.com/yourrepo/hiresti"
# ===========================================

# ---- Supported targets ----
# Each entry: TARGET_NAME  BASE_IMAGE  DISTRO_FAMILY  PKG_TYPE  SUFFIX
TARGETS=(
    "ubuntu2404             ubuntu:24.04                deb   deb          ubuntu2404"
    "ubuntu2604             ubuntu:26.04                deb   deb          ubuntu2604"
    "debian12               debian:12                   deb   deb          debian12"
    "debian13               debian:13                   deb   deb          debian13"
    "fedora43               fedora:43                   rpm   rpm-fedora   fedora43"
    "fedora44               fedora:44                   rpm   rpm-fedora   fedora44"
    "archlinux              archlinux:latest            arch  arch         archlinux"
    "opensuse-tumbleweed    opensuse/tumbleweed:latest  suse  rpm-opensuse opensuse_tumbleweed"
)

TYPE="${1:-}"
VERSION="${2:-}"
USE_PY_BINARY="${HIRESTI_PY_BINARY:-0}"
PKG_JOBS="${HIRESTI_PKG_JOBS:-1}"
if ! [[ "$PKG_JOBS" =~ ^[0-9]+$ ]] || [ "$PKG_JOBS" -lt 1 ]; then
    PKG_JOBS=1
fi

# ---- Usage ----
print_usage() {
    echo "Usage: ./package.sh <target> <version>"
    echo ""
    echo "Local targets (build on this machine):"
    echo "  deb             Build .deb using host toolchain"
    echo "  rpm-fedora      Build Fedora .rpm using host toolchain"
    echo "  arch            Build Arch .pkg.tar.zst using host toolchain"
    echo ""
    echo "Docker targets (build inside container for correct GLIBC):"
    echo "  ubuntu2404      Ubuntu 24.04 .deb"
    echo "  ubuntu2604      Ubuntu 26.04 .deb"
    echo "  debian12        Debian 12 .deb"
    echo "  debian13        Debian 13 .deb"
    echo "  fedora43        Fedora 43 .rpm"
    echo "  fedora44        Fedora 44 .rpm"
    echo "  archlinux              Arch Linux .pkg.tar.zst"
    echo "  opensuse-tumbleweed    openSUSE Tumbleweed .rpm"
    echo "  all                    Build all Docker targets"
    echo ""
    echo "Example: ./package.sh ubuntu2404 1.9.0beta1"
    echo "         ./package.sh all 1.9.0beta1"
    echo ""
    echo "Env:"
    echo "  HIRESTI_PKG_JOBS=N   parallel 'all' builds (default 1)"
    echo "  HIRESTI_PY_BINARY=1  bundle Python via PyInstaller"
}

if [ -z "$TYPE" ] || [ -z "$VERSION" ]; then
    print_usage
    exit 1
fi

# Compute DEB architecture string
if command -v dpkg-deb &>/dev/null; then
    DEB_ARCH="$(dpkg --print-architecture)"
else
    DEB_ARCH="$(uname -m | sed 's/x86_64/amd64/;s/aarch64/arm64/')"
fi

echo "🚀 Starting build process for $APP_NAME v$VERSION ($TYPE)..."
if [ "$USE_PY_BINARY" == "1" ]; then
    echo "🧱 Python app bundling: enabled (PyInstaller)"
else
    echo "🧱 Python app bundling: disabled (source mode)"
fi

# Keep a canonical version file in repo root based on build argument.
echo "$VERSION" > version.txt
echo "🧾 Version file updated: version.txt -> $VERSION"

# Package version must not contain '-' (pacman parses '-' as pkgver/pkgrel
# boundary; rpm disallows it in Version; historic deb releases used the
# stripped form too). Keep $VERSION as-is for the in-app version string.
PKG_VERSION="${VERSION//-/}"
if [ "$PKG_VERSION" != "$VERSION" ]; then
    echo "🧾 Packaging version normalized: $VERSION -> $PKG_VERSION"
fi


# ====================================================================
#  Docker-based builds
# ====================================================================

find_target() {
    local name="$1"
    for t in "${TARGETS[@]}"; do
        local fields=($t)
        if [ "${fields[0]}" = "$name" ]; then
            echo "$t"
            return 0
        fi
    done
    return 1
}

docker_build_target() {
    local target_name="$1"
    local target_line
    target_line="$(find_target "$target_name")" || {
        echo "Error: unknown target '$target_name'"
        exit 1
    }
    local fields=($target_line)
    local base_image="${fields[1]}"
    local distro_family="${fields[2]}"
    local pkg_type="${fields[3]}"
    local suffix="${fields[4]}"
    local image_tag="hiresti-builder-${target_name}"

    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "  Building: $target_name ($base_image)"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

    docker build -t "$image_tag" \
        --build-arg BASE_IMAGE="$base_image" \
        --build-arg DISTRO_FAMILY="$distro_family" \
        --build-arg DISTRO_ID="$target_name" \
        -f Dockerfile.build . || {
        echo "❌ Docker image build failed for $target_name"
        return 1
    }

    mkdir -p dist

    docker run --rm \
        -v "$(pwd)/dist:/output" \
        -e VERSION="$VERSION" \
        -e PKG_TYPE="$pkg_type" \
        -e PKG_SUFFIX="$suffix" \
        "$image_tag" || {
        echo "❌ Package build failed for $target_name"
        return 1
    }

    echo "✅ $target_name build complete"
}

# Handle Docker targets
case "$TYPE" in
    ubuntu2404|ubuntu2604|debian12|debian13|fedora43|fedora44|archlinux|opensuse-tumbleweed)
        docker_build_target "$TYPE"
        echo ""
        echo "🎉 Build Complete! Packages in dist/:"
        ls -lh dist/ 2>/dev/null
        exit 0
        ;;
    all)
        mkdir -p dist
        failed=()
        if [ "$PKG_JOBS" -le 1 ]; then
            for t in "${TARGETS[@]}"; do
                local_fields=($t)
                target_name="${local_fields[0]}"
                docker_build_target "$target_name" || failed+=("$target_name")
            done
        else
            echo "🔀 Parallel multi-target build (HIRESTI_PKG_JOBS=$PKG_JOBS)"
            echo "   Per-target output streamed to dist/build-<target>.log"
            faildir="$(mktemp -d)"
            trap 'rm -rf "$faildir"' EXIT
            for t in "${TARGETS[@]}"; do
                local_fields=($t)
                target_name="${local_fields[0]}"
                while [ "$(jobs -rp | wc -l)" -ge "$PKG_JOBS" ]; do
                    wait -n 2>/dev/null || true
                done
                (
                    log="dist/build-${target_name}.log"
                    echo "[start] ${target_name}  → ${log}"
                    if docker_build_target "${target_name}" >"$log" 2>&1; then
                        echo "[ok]    ${target_name}"
                    else
                        echo "[FAIL]  ${target_name}  → ${log}"
                        touch "$faildir/${target_name}"
                    fi
                ) &
            done
            wait
            for f in "$faildir"/*; do
                [ -e "$f" ] || continue
                failed+=("$(basename "$f")")
            done
        fi
        echo ""
        echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        if [ ${#failed[@]} -eq 0 ]; then
            echo "🎉 All builds complete! Packages in dist/:"
        else
            echo "⚠️  Builds complete with failures: ${failed[*]}"
            echo "Successful packages in dist/:"
        fi
        ls -lh dist/ 2>/dev/null
        exit 0
        ;;
esac


# ====================================================================
#  Local builds (deb / rpm-fedora / arch) — no Docker
# ====================================================================

# Preflight checks
for required in src/main.py src/ui src/actions src/viz icons/hicolor; do
    if [ ! -e "$required" ]; then
        echo "Error: required path missing: $required"
        exit 1
    fi
done

# 1. 创建临时构建目录
BUILD_ROOT="build_tmp"
rm -rf "$BUILD_ROOT"
mkdir -p "$BUILD_ROOT"

INSTALL_DIR="$BUILD_ROOT/usr/share/$APP_NAME"
BIN_DIR="$BUILD_ROOT/usr/bin"
APP_DIR="$BUILD_ROOT/usr/share/applications"
SYSTEM_ICON_DIR="$BUILD_ROOT/usr/share/icons"
UDEV_DIR="$BUILD_ROOT/usr/lib/udev/rules.d"

mkdir -p "$INSTALL_DIR"
mkdir -p "$BIN_DIR"
mkdir -p "$APP_DIR"
mkdir -p "$SYSTEM_ICON_DIR"
mkdir -p "$UDEV_DIR"

# udev rule
cat <<'UDEV_EOF' > "$UDEV_DIR/99-hiresti-usb-audio.rules"
# HiresTI USB Rawlink - grant logged-in user access to USB audio devices
SUBSYSTEM=="usb", ENV{DEVTYPE}=="usb_device", ENV{ID_USB_INTERFACES}=="*:01????:*", TAG+="uaccess"
UDEV_EOF

# 2. 复制源文件
echo "📂 Copying source files..."
cp -r src/* "$INSTALL_DIR/"
if [ -f "version.txt" ]; then cp version.txt "$INSTALL_DIR/"; fi
cp -r icons "$INSTALL_DIR/"
if [ -d "css" ]; then cp -r css "$INSTALL_DIR/"; fi
if [ -f "LICENSE" ]; then cp LICENSE "$INSTALL_DIR/"; fi

# 2.0 可选：把 Python 主程序打成独立二进制（PyInstaller onedir）
if [ "$USE_PY_BINARY" == "1" ]; then
    if [ ! -x "tools/build_py_binary.sh" ]; then
        echo "Error: tools/build_py_binary.sh not found or not executable."
        exit 1
    fi
    echo "📦 Building bundled Python binary (PyInstaller)..."
    PYI_DIST_DIR="$BUILD_ROOT/pyi-dist"
    PYI_WORK_DIR="$BUILD_ROOT/pyi-work"
    PYI_SPEC_DIR="$BUILD_ROOT/pyi-spec"
    ./tools/build_py_binary.sh "$PYI_DIST_DIR" "$PYI_WORK_DIR" "$PYI_SPEC_DIR"
    if [ ! -x "$PYI_DIST_DIR/hiresti_app/hiresti_app" ]; then
        echo "Error: PyInstaller bundle missing executable: $PYI_DIST_DIR/hiresti_app/hiresti_app"
        exit 1
    fi
    rm -rf "$INSTALL_DIR/hiresti_app"
    cp -a "$PYI_DIST_DIR/hiresti_app" "$INSTALL_DIR/"
    echo "✅ Bundled Python binary: $INSTALL_DIR/hiresti_app/hiresti_app"
fi

# 2.1 构建并打包 Rust 可视化核心动态库
# Docker builds pre-compile Rust into rust_out/; use those if available.
PREBUILT_DIR="rust_out"
RUST_SO="${PREBUILT_DIR}/libviz_core.so"
if [ -f "$RUST_SO" ]; then
    echo "✅ Using pre-built Rust visualizer core"
    mkdir -p "$INSTALL_DIR/src_rust/rust_viz_core/target/release"
    cp "$RUST_SO" "$INSTALL_DIR/src_rust/rust_viz_core/target/release/"
elif [ -f "src_rust/rust_viz_core/Cargo.toml" ]; then
    if command -v cargo &> /dev/null; then
        echo "🦀 Building Rust visualizer core..."
        cargo build --manifest-path src_rust/rust_viz_core/Cargo.toml --release
        RUST_SO="src_rust/rust_viz_core/target/release/libviz_core.so"
        if [ ! -f "$RUST_SO" ]; then
            echo "Error: Rust build finished but $RUST_SO not found."
            exit 1
        fi
        mkdir -p "$INSTALL_DIR/src_rust/rust_viz_core/target/release"
        cp "$RUST_SO" "$INSTALL_DIR/src_rust/rust_viz_core/target/release/"
        echo "✅ Bundled Rust core: $RUST_SO"
    else
        echo "⚠️ 'cargo' not found. Rust core will not be bundled."
    fi
fi

# 2.2 构建并打包 Rust 音频核心动态库
RUST_AUDIO_SO="${PREBUILT_DIR}/librust_audio_core.so"
if [ -f "$RUST_AUDIO_SO" ]; then
    echo "✅ Using pre-built Rust audio core"
    mkdir -p "$INSTALL_DIR/src_rust/rust_audio_core/target/release"
    cp "$RUST_AUDIO_SO" "$INSTALL_DIR/src_rust/rust_audio_core/target/release/"
elif [ -f "src_rust/rust_audio_core/Cargo.toml" ]; then
    if command -v cargo &> /dev/null; then
        echo "🦀 Building Rust audio core..."
        cargo build --manifest-path src_rust/rust_audio_core/Cargo.toml --release
        RUST_AUDIO_SO="src_rust/rust_audio_core/target/release/librust_audio_core.so"
        if [ ! -f "$RUST_AUDIO_SO" ]; then
            echo "Error: Rust audio build finished but $RUST_AUDIO_SO not found."
            exit 1
        fi
        mkdir -p "$INSTALL_DIR/src_rust/rust_audio_core/target/release"
        cp "$RUST_AUDIO_SO" "$INSTALL_DIR/src_rust/rust_audio_core/target/release/"
        echo "✅ Bundled Rust audio core: $RUST_AUDIO_SO"
    else
        echo "⚠️ 'cargo' not found. Rust audio core will not be bundled."
    fi
fi

# 2.3 构建启动器
RUST_LAUNCHER="${PREBUILT_DIR}/${APP_NAME}"
if [[ "$TYPE" == "deb" ]]; then
    cat <<'WRAPPER' > "$BIN_DIR/$APP_NAME"
#!/bin/bash
APP_DIR="/usr/share/hiresti"
cd "$APP_DIR"
PYTHONPATH="$APP_DIR/libs:$APP_DIR" python3 main.py "$@"
WRAPPER
    chmod +x "$BIN_DIR/$APP_NAME"
    echo "✅ Installed shell launcher: /usr/bin/$APP_NAME"
elif [ -f "$RUST_LAUNCHER" ]; then
    echo "✅ Using pre-built Rust launcher"
    cp "$RUST_LAUNCHER" "$BIN_DIR/$APP_NAME"
    chmod +x "$BIN_DIR/$APP_NAME"
elif [ -f "src_rust/rust_launcher/Cargo.toml" ]; then
    if command -v cargo &> /dev/null; then
        echo "🦀 Building Rust launcher..."
        cargo build --manifest-path src_rust/rust_launcher/Cargo.toml --release
        RUST_LAUNCHER_BIN="src_rust/rust_launcher/target/release/$APP_NAME"
        if [ ! -f "$RUST_LAUNCHER_BIN" ]; then
            echo "Error: Rust launcher build finished but $RUST_LAUNCHER_BIN not found."
            exit 1
        fi
        cp "$RUST_LAUNCHER_BIN" "$BIN_DIR/$APP_NAME"
        chmod +x "$BIN_DIR/$APP_NAME"
        echo "✅ Installed Rust launcher: /usr/bin/$APP_NAME"
    else
        echo "Error: 'cargo' not found. Rust launcher is required."
        exit 1
    fi
else
    echo "Error: src_rust/rust_launcher/Cargo.toml not found."
    exit 1
fi

# 3. 处理图标
echo "🎨 Installing icons..."
if [ -d "icons/hicolor" ]; then
    cp -r icons/hicolor "$SYSTEM_ICON_DIR/"
elif [ -f "icon.svg" ]; then
    mkdir -p "$SYSTEM_ICON_DIR/hicolor/scalable/apps"
    cp icon.svg "$SYSTEM_ICON_DIR/hicolor/scalable/apps/$APP_NAME.svg"
elif [ -f "icons/icon.png" ]; then
    mkdir -p "$SYSTEM_ICON_DIR/hicolor/256x256/apps"
    cp icons/icon.png "$SYSTEM_ICON_DIR/hicolor/256x256/apps/$APP_NAME.png"
else
    if [ -f "icon.png" ]; then
         mkdir -p "$SYSTEM_ICON_DIR/hicolor/256x256/apps"
         cp icon.png "$SYSTEM_ICON_DIR/hicolor/256x256/apps/$APP_NAME.png"
    fi
fi

# 4. 捆绑依赖
echo "📦 Bundling Python dependencies..."
mkdir -p "$INSTALL_DIR/libs"
if ! pip3 install tidalapi requests urllib3 PyOpenGL pystray pillow qrcode python-dateutil typing-extensions isodate mpegdash pyaes ratelimit six setproctitle -t "$INSTALL_DIR/libs" --no-cache-dir --upgrade 2>/dev/null; then
    # Try with --break-system-packages for newer pip
    if ! pip3 install --break-system-packages tidalapi requests urllib3 PyOpenGL pystray pillow qrcode python-dateutil typing-extensions isodate mpegdash pyaes ratelimit six setproctitle -t "$INSTALL_DIR/libs" --no-cache-dir --upgrade 2>/dev/null; then
        echo "⚠️ Online dependency install failed, using local site-packages fallback..."
        python3 - "$INSTALL_DIR/libs" <<'PY'
import os
import shutil
import sys
from importlib.util import find_spec

target = sys.argv[1]
modules = [
    "tidalapi", "requests", "urllib3", "OpenGL", "qrcode", "PIL",
    "certifi", "idna", "charset_normalizer", "dateutil",
    "typing_extensions", "isodate", "mpegdash", "pyaes", "ratelimit", "six",
]

def copy_path(src, dst_root):
    if not src or not os.path.exists(src):
        return False
    base = os.path.basename(src)
    dst = os.path.join(dst_root, base)
    if os.path.isdir(src):
        if os.path.exists(dst):
            shutil.rmtree(dst)
        shutil.copytree(src, dst)
    else:
        shutil.copy2(src, dst)
    return True

copied = []
for mod in modules:
    spec = find_spec(mod)
    if spec is None:
        continue
    if spec.submodule_search_locations:
        src = list(spec.submodule_search_locations)[0]
    else:
        src = spec.origin
    if copy_path(src, target):
        copied.append(mod)
print("Copied local modules:", ", ".join(copied) if copied else "(none)")
PY
    fi
fi

# 兼容 RPM shebang 严格检查
while IFS= read -r f; do
    sed -i '1s|^#!/usr/bin/env python$|#!/usr/bin/env python3|' "$f"
done < <(grep -RIl '^#!/usr/bin/env python$' "$INSTALL_DIR/libs" || true)

# 5. 创建 .desktop 文件
echo "🖥️ Creating desktop entry..."
cat <<EOF > "$APP_DIR/$APP_ID.desktop"
[Desktop Entry]
Name=$DISPLAY_NAME
Comment=$DESCRIPTION
Exec=/usr/bin/$APP_NAME
Icon=$APP_NAME
Terminal=false
Type=Application
Categories=AudioVideo;Audio;Player;Music;
StartupWMClass=$DISPLAY_NAME
EOF


# ================= 输出包名后缀 =================
# 容器内构建时，PKG_SUFFIX 从环境变量传入
PKG_SUFFIX="${PKG_SUFFIX:-}"

# ================= 分支处理 =================

build_deb() {
    echo "📦 Building .deb package..."
    mkdir -p "$BUILD_ROOT/DEBIAN"
    cat <<EOF > "$BUILD_ROOT/DEBIAN/control"
Package: $APP_NAME
Version: $PKG_VERSION
Section: sound
Priority: optional
Architecture: $DEB_ARCH
Depends: python3, python3-gi, python3-gi-cairo, python3-cairo, python3-opengl, python3-dateutil, python3-typing-extensions, python3-isodate, python3-setproctitle, gir1.2-gtk-4.0, gir1.2-adw-1, gir1.2-gtksource-4, gir1.2-webkit-6.0, xdg-dbus-proxy, qrencode, python3-gst-1.0, gstreamer1.0-plugins-base, gstreamer1.0-plugins-good, gstreamer1.0-plugins-bad, gstreamer1.0-plugins-ugly, gstreamer1.0-pipewire, libpipewire-0.3-0, libpulse0, libasound2, libusb-1.0-0, libgl1, libegl1, libgl1-mesa-dri, pkexec | policykit-1, acl, udev
Maintainer: $MAINTAINER
Description: $DESCRIPTION
 $DISPLAY_NAME is a desktop client for Tidal focusing on High-Res audio.
EOF
    cat <<'POSTINST_EOF' > "$BUILD_ROOT/DEBIAN/postinst"
#!/bin/sh
set -e
if [ "$1" = "configure" ]; then
    udevadm control --reload-rules 2>/dev/null || true
    udevadm trigger --subsystem-match=usb 2>/dev/null || true
fi
exit 0
POSTINST_EOF
    chmod 755 "$BUILD_ROOT/DEBIAN/postinst"
    mkdir -p dist

    if [ -n "$PKG_SUFFIX" ]; then
        local deb_name="${APP_NAME}_${PKG_VERSION}_${DEB_ARCH}_${PKG_SUFFIX}.deb"
    else
        local deb_name="${APP_NAME}_${PKG_VERSION}_${DEB_ARCH}.deb"
    fi
    dpkg-deb --build "$BUILD_ROOT" "dist/${deb_name}"
    echo "✅ DEB created: dist/${deb_name}"
}

build_rpm_variant() {
    local variant="$1"
    local dist_tag="$2"
    local requires="$3"
    local arch spec_file rpm_build_root

    arch="$(uname -m)"
    rpm_build_root="$(pwd)/build_rpmbuild_${variant}"
    rm -rf "$rpm_build_root"
    mkdir -p "$rpm_build_root"/{BUILD,RPMS,SOURCES,SPECS,SRPMS}
    spec_file="$rpm_build_root/SPECS/$APP_NAME-${variant}.spec"

    cat <<EOF > "$spec_file"
Name:           $APP_NAME
Version:        $PKG_VERSION
Release:        1%{?dist}
Summary:        $DESCRIPTION (${variant})
License:        $LICENSE
BuildArch:      $arch
AutoReq:        no
AutoProv:       no
Requires:       $requires

%description
$DISPLAY_NAME is a desktop client for Tidal (${variant} build).

%prep
%build
%install
cp -r $(pwd)/$BUILD_ROOT/* %{buildroot}

%post
udevadm control --reload-rules 2>/dev/null || true
udevadm trigger --subsystem-match=usb 2>/dev/null || true

%files
/usr/share/$APP_NAME
/usr/bin/$APP_NAME
/usr/share/applications/$APP_ID.desktop
/usr/share/icons/*
/usr/lib/udev/rules.d/99-hiresti-usb-audio.rules

%changelog
* $(date "+%a %b %d %Y") $MAINTAINER - $PKG_VERSION-1
- Automated ${variant} build
EOF

    rpmbuild -bb "$spec_file" \
        --define "_topdir $rpm_build_root" \
        --define "dist .${dist_tag}"

    mkdir -p dist
    if [ -n "$PKG_SUFFIX" ]; then
        for rpm_file in "$rpm_build_root"/RPMS/"$arch"/${APP_NAME}-${PKG_VERSION}-1*.${arch}.rpm; do
            local base
            base="$(basename "$rpm_file")"
            local newname="${base%.rpm}_${PKG_SUFFIX}.rpm"
            mv "$rpm_file" "dist/${newname}"
            echo "✅ RPM created: dist/${newname}"
        done
    else
        mv "$rpm_build_root"/RPMS/"$arch"/${APP_NAME}-${PKG_VERSION}-1*.${arch}.rpm "dist/"
        echo "✅ RPM created (${variant})."
    fi
}

build_arch_package() {
    local arch pkg_rel pkg_ver_rel pkg_file pkg_root pkg_size build_ts
    arch="$(uname -m)"
    pkg_rel="1"
    pkg_ver_rel="${PKG_VERSION}-${pkg_rel}"
    pkg_root="$(pwd)/build_archpkg/pkgroot"

    rm -rf "$(pwd)/build_archpkg"
    mkdir -p "$pkg_root"
    cp -a "$BUILD_ROOT"/. "$pkg_root"/

    pkg_size="$(du -sb "$pkg_root" | awk '{print $1}')"
    build_ts="$(date +%s)"

    cat <<EOF > "$pkg_root/.PKGINFO"
pkgname = $APP_NAME
pkgbase = $APP_NAME
pkgver = $pkg_ver_rel
pkgdesc = $DESCRIPTION
url = $URL
builddate = $build_ts
packager = $MAINTAINER
size = $pkg_size
arch = $arch
license = $LICENSE
depend = python
depend = gtk4
depend = libadwaita
depend = gstreamer
depend = gst-plugins-good
depend = gst-plugins-bad
depend = gst-plugins-ugly
depend = gst-python
depend = gst-plugin-pipewire
depend = python-gobject
depend = python-cairo
depend = python-opengl
depend = python-setproctitle
depend = pipewire
depend = libpulse
depend = alsa-lib
depend = libusb
depend = mesa
depend = libglvnd
depend = webkitgtk-6.0
depend = xdg-dbus-proxy
depend = polkit
depend = acl
EOF

    cat <<'INSTALL_EOF' > "$pkg_root/.INSTALL"
post_install() {
    udevadm control --reload-rules 2>/dev/null || true
    udevadm trigger --subsystem-match=usb 2>/dev/null || true
}
post_upgrade() {
    post_install
}
INSTALL_EOF

    if [ -n "$PKG_SUFFIX" ]; then
        pkg_file="dist/${APP_NAME}-${pkg_ver_rel}-${arch}_${PKG_SUFFIX}.pkg.tar.zst"
    else
        pkg_file="dist/${APP_NAME}-${pkg_ver_rel}-${arch}.pkg.tar.zst"
    fi

    mkdir -p dist
    tar --sort=name --mtime="@$build_ts" --owner=0 --group=0 --numeric-owner \
        -C "$pkg_root" -I 'zstd -19 -T0' -cf "$pkg_file" .PKGINFO .INSTALL usr
    echo "✅ Arch package created: $pkg_file"
}


# ---- Dispatch local builds ----
FEDORA_REQUIRES="python3, python3-gobject, python3-cairo, python3-pyopengl, python3-setproctitle, gtk4, libadwaita, webkitgtk6.0, xdg-dbus-proxy, gstreamer1-plugins-base, gstreamer1-plugins-good, gstreamer1-plugins-bad-free, gstreamer1-plugins-ugly-free, pipewire, pipewire-gstreamer, pulseaudio-libs, alsa-lib, libusb1, mesa-libGL, mesa-libEGL, mesa-dri-drivers, libglvnd-glx, libglvnd-egl, polkit, acl"

OPENSUSE_REQUIRES="python3, python3-gobject, python3-gobject-Gdk, python3-gobject-cairo, python3-cairo, python3-opengl, python3-setproctitle, python3-python-dateutil, python3-typing_extensions, python3-isodate, typelib-1_0-Gtk-4_0, typelib-1_0-Adw-1, typelib-1_0-GtkSource-5, typelib-1_0-WebKit-6_0, xdg-dbus-proxy, gstreamer, gstreamer-plugins-base, gstreamer-plugins-good, gstreamer-plugins-bad, gstreamer-plugins-ugly, gstreamer-plugin-pipewire, pipewire, libpulse0, alsa, libasound2, libusb-1_0-0, Mesa-libGL1, Mesa-libEGL1, Mesa-dri, libglvnd, polkit, acl"

case "$TYPE" in
    deb)
        build_deb
        ;;
    rpm-fedora)
        build_rpm_variant "fedora" "fedora" "$FEDORA_REQUIRES"
        ;;
    rpm-opensuse)
        build_rpm_variant "opensuse" "opensuse" "$OPENSUSE_REQUIRES"
        ;;
    arch)
        build_arch_package
        ;;
    *)
        echo "Error: unsupported local type '$TYPE'. Use deb | rpm-fedora | rpm-opensuse | arch"
        echo "  Or use a Docker target: ubuntu2404 | ubuntu2604 | debian12 | debian13 | fedora43 | fedora44 | archlinux | opensuse-tumbleweed | all"
        exit 1
        ;;
esac

rm -rf "$BUILD_ROOT"
echo "🎉 Build Complete!"
