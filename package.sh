#!/bin/bash
set -euo pipefail

# ================= 配置区域 =================
APP_NAME="hiresti"
APP_ID="com.hiresti.player"  # [新增] 必须与 main.py 中的 application_id 一致
DISPLAY_NAME="HiresTI"
MAINTAINER="Eason <yelanxin@gmail.com>"
DESCRIPTION="High-Res Tidal Player for Linux with Bit-Perfect support."
LICENSE="GPL-3.0"
URL="https://github.com/yourrepo/hiresti"
# ===========================================

TYPE="${1:-}"
VERSION="${2:-}"
USE_PY_BINARY="${HIRESTI_PY_BINARY:-0}"

# Compute DEB architecture string (e.g. amd64, arm64)
if command -v dpkg-deb &>/dev/null; then
    DEB_ARCH="$(dpkg --print-architecture)"
else
    DEB_ARCH="$(uname -m | sed 's/x86_64/amd64/;s/aarch64/arm64/')"
fi

if [ -z "$TYPE" ] || [ -z "$VERSION" ]; then
    echo "Usage: ./package.sh [deb|rpm|rpm-fedora|rpm-el9|arch|flatpak|all] [version]  (note: 'all' skips flatpak)"
    echo "Example: ./package.sh all 1.0.0"
    exit 1
fi

if [[ "$TYPE" == "deb" || "$TYPE" == "all" ]] && ! command -v dpkg-deb &> /dev/null; then
    echo "Error: 'dpkg-deb' is required."
    exit 1
fi

if [[ "$TYPE" == "rpm" || "$TYPE" == "rpm-fedora" || "$TYPE" == "rpm-el9" || "$TYPE" == "all" ]] && ! command -v rpmbuild &> /dev/null; then
    echo "Error: 'rpmbuild' is required."
    exit 1
fi

if [[ "$TYPE" == "arch" || "$TYPE" == "all" ]] && ! command -v zstd &> /dev/null; then
    echo "Error: 'zstd' is required for Arch package build."
    exit 1
fi

if [[ "$TYPE" == "flatpak" ]] && ! command -v flatpak-builder &> /dev/null; then
    echo "Error: 'flatpak-builder' is required for Flatpak build."
    exit 1
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

sync_flatpak_metainfo_release() {
    local meta_file="flatpak/com.hiresti.player.metainfo.xml"
    if [ ! -f "$meta_file" ]; then
        return 0
    fi

    local release_date
    release_date="$(
        sed -n "s/^##[[:space:]]\\+${VERSION//./\\.}[[:space:]]*-[[:space:]]*\\([0-9]\\{4\\}-[0-9]\\{2\\}-[0-9]\\{2\\}\\).*$/\\1/p" CHANGELOG.md | head -n 1
    )"
    if [ -z "$release_date" ]; then
        release_date="$(date -u +%F)"
    fi

    local tmp_file
    tmp_file="$(mktemp)"
    awk -v version="$VERSION" -v date="$release_date" '
        /<releases>/ && !inserted {
            print
            print "    <release version=\"" version "\" date=\"" date "\"/>"
            inserted = 1
            next
        }
        {
            if (index($0, "<release version=\"" version "\"") > 0) {
                next
            }
            print
        }
    ' "$meta_file" > "$tmp_file"
    mv "$tmp_file" "$meta_file"
    echo "🧾 Flatpak metainfo synced: $VERSION ($release_date)"
}

sync_flatpak_metainfo_release

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

mkdir -p "$INSTALL_DIR"
mkdir -p "$BIN_DIR"
mkdir -p "$APP_DIR"
mkdir -p "$SYSTEM_ICON_DIR"

# 2. 复制源文件
echo "📂 Copying source files..."
# Copy main.py and new directory structure (src/)
cp -r src/* "$INSTALL_DIR/"
# Note: Rust .so files are copied separately below (see sections 2.1 and 2.2)
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

# 2.1 构建并打包 Rust 可视化核心动态库（libviz_core.so）
if [ -f "src_rust/rust_viz_core/Cargo.toml" ]; then
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

# 2.2 构建并打包 Rust 音频核心动态库（librust_audio_core.so）
if [ -f "src_rust/rust_audio_core/Cargo.toml" ]; then
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

# 2.3 构建 Rust 启动器（/usr/bin/hiresti）
# 注意：EL9 和 DEB 使用 shell 脚本，因为 Rust launcher 编译环境 glibc 版本可能与目标系统不兼容
if [[ "$TYPE" == "rpm-el9" || "$TYPE" == "el9" || "$TYPE" == "deb" || "$TYPE" == "all" ]]; then
    # For EL9 and DEB, use a shell script wrapper for better compatibility
    cat <<'WRAPPER' > "$BIN_DIR/$APP_NAME"
#!/bin/bash
APP_DIR="/usr/share/hiresti"
cd "$APP_DIR"
PYTHONPATH="$APP_DIR/libs:$APP_DIR" python3 main.py "$@"
WRAPPER
    chmod +x "$BIN_DIR/$APP_NAME"
    echo "✅ Installed shell launcher: /usr/bin/$APP_NAME"
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
# 这里的逻辑是：把图标名字也统一改为 hiresti，方便 .desktop 引用
if [ -d "icons/hicolor" ]; then
    cp -r icons/hicolor "$SYSTEM_ICON_DIR/"
elif [ -f "icon.svg" ]; then
    mkdir -p "$SYSTEM_ICON_DIR/hicolor/scalable/apps"
    cp icon.svg "$SYSTEM_ICON_DIR/hicolor/scalable/apps/$APP_NAME.svg"
elif [ -f "icons/icon.png" ]; then
    mkdir -p "$SYSTEM_ICON_DIR/hicolor/256x256/apps"
    cp icons/icon.png "$SYSTEM_ICON_DIR/hicolor/256x256/apps/$APP_NAME.png"
else
    # Fallback
    if [ -f "icon.png" ]; then
         mkdir -p "$SYSTEM_ICON_DIR/hicolor/256x256/apps"
         cp icon.png "$SYSTEM_ICON_DIR/hicolor/256x256/apps/$APP_NAME.png"
    fi
fi

# 4. 捆绑依赖
echo "📦 Bundling Python dependencies..."
mkdir -p "$INSTALL_DIR/libs"
if ! pip3 install tidalapi requests urllib3 pystray pillow qrcode python-dateutil typing-extensions isodate mpegdash pyaes ratelimit six setproctitle -t "$INSTALL_DIR/libs" --no-cache-dir --upgrade; then
    echo "⚠️ Online dependency install failed, using local site-packages fallback..."
    python3 - "$INSTALL_DIR/libs" <<'PY'
import os
import shutil
import sys
import sysconfig
from importlib.util import find_spec

target = sys.argv[1]
modules = [
    "tidalapi",
    "requests",
    "urllib3",
    "qrcode",
    "PIL",
    "certifi",
    "idna",
    "charset_normalizer",
    "dateutil",
    "typing_extensions",
    "isodate",
    "mpegdash",
    "pyaes",
    "ratelimit",
    "six",
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

# 兼容 RPM shebang 严格检查：避免 /usr/bin/env python 触发 brp-mangle-shebangs 报错
while IFS= read -r f; do
    sed -i '1s|^#!/usr/bin/env python$|#!/usr/bin/env python3|' "$f"
done < <(grep -RIl '^#!/usr/bin/env python$' "$INSTALL_DIR/libs" || true)

# 5. [关键修改] 创建 .desktop 文件
# 文件名必须是 APP_ID.desktop (com.hiresti.player.desktop)
echo "🖥️ Creating desktop entry..."
cat <<EOF > "$APP_DIR/$APP_ID.desktop"
[Desktop Entry]
Name=$DISPLAY_NAME
Comment=$DESCRIPTION
Exec=/usr/bin/$APP_NAME
# 图标名称对应 /usr/share/icons/.../hiresti.png
Icon=$APP_NAME
Terminal=false
Type=Application
Categories=AudioVideo;Audio;Player;Music;
# 这里的 StartupWMClass 用于 X11 兼容，必须匹配 GLib.set_prgname 设置的值
StartupWMClass=$DISPLAY_NAME
EOF

# ================= 分支处理 =================

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
Version:        $VERSION
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

%files
/usr/share/$APP_NAME
/usr/bin/$APP_NAME
/usr/share/applications/$APP_ID.desktop
/usr/share/icons/*

%changelog
* $(date "+%a %b %d %Y") $MAINTAINER - $VERSION-1
- Automated ${variant} build
EOF

    rpmbuild -bb "$spec_file" \
        --define "_topdir $rpm_build_root" \
        --define "dist .${dist_tag}"

    mkdir -p dist
    mv "$rpm_build_root"/RPMS/"$arch"/${APP_NAME}-${VERSION}-1*.${arch}.rpm "dist/"
    echo "✅ RPM created (${variant})."
}

build_arch_package() {
    local arch pkg_rel pkg_ver_rel pkg_file pkg_root pkg_size build_ts
    arch="$(uname -m)"
    pkg_rel="1"
    pkg_ver_rel="${VERSION}-${pkg_rel}"
    pkg_file="dist/${APP_NAME}-${pkg_ver_rel}-${arch}.pkg.tar.zst"
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
depend = python-gobject
depend = python-cairo
depend = pipewire
depend = libpulse
EOF

    mkdir -p dist
    tar --sort=name --mtime="@$build_ts" --owner=0 --group=0 --numeric-owner \
        -C "$pkg_root" -I 'zstd -19 -T0' -cf "$pkg_file" .PKGINFO usr
    echo "✅ Arch package created."
}

build_flatpak_package() {
    local flatpak_builder_file="flatpak/com.hiresti.player.yml"
    local build_dir="build_flatpak"
    local repo_dir="flatpak/repo"

    if [ ! -f "$flatpak_builder_file" ]; then
        echo "Error: Flatpak manifest not found: $flatpak_builder_file"
        exit 1
    fi

    # Vendor Rust dependencies for offline Flatpak build.
    # flatpak-builder copies the source tree (type: dir) without network access, so the
    # vendor/ directory must exist before flatpak-builder is invoked.
    if [ -f "src_rust/rust_audio_core/Cargo.toml" ]; then
        if command -v cargo &>/dev/null; then
            echo "📦 Vendoring Rust audio core dependencies for Flatpak..."
            (cd src_rust/rust_audio_core && cargo vendor vendor)
        else
            echo "Error: 'cargo' not found. Cannot vendor Rust dependencies for Flatpak."
            exit 1
        fi
    fi

    # Clean previous build
    rm -rf "$build_dir"
    mkdir -p dist

    # Build the Flatpak using flatpak-builder
    # Note: runtime-version in manifest should match GNOME SDK version (e.g., 48), not app version
    flatpak-builder --force-clean --repo="$repo_dir" "$build_dir" "$flatpak_builder_file"

    # Export to a single .flatpak file
    flatpak build-bundle "$repo_dir" "dist/${APP_NAME}-${VERSION}.flatpak" "com.hiresti.player"

    echo "✅ Flatpak package created: dist/${APP_NAME}-${VERSION}.flatpak"
}

if [ "$TYPE" == "deb" ]; then
    echo "📦 Building .deb package..."
    mkdir -p "$BUILD_ROOT/DEBIAN"
    cat <<EOF > "$BUILD_ROOT/DEBIAN/control"
Package: $APP_NAME
Version: $VERSION
Section: sound
Priority: optional
Architecture: $DEB_ARCH
Depends: python3, python3-gi, python3-gi-cairo, python3-cairo, python3-dateutil, python3-typing-extensions, python3-isodate, python3-setproctitle, gir1.2-gtk-4.0, gir1.2-adw-1, gir1.2-gtksource-4, qrencode, python3-gst-1.0, gstreamer1.0-plugins-base, gstreamer1.0-plugins-good, gstreamer1.0-plugins-bad, gstreamer1.0-plugins-ugly, libpipewire-0.3-0, libpulse0
Maintainer: $MAINTAINER
Description: $DESCRIPTION
 $DISPLAY_NAME is a desktop client for Tidal focusing on High-Res audio.
EOF
    mkdir -p dist
    dpkg-deb --build "$BUILD_ROOT" "dist/${APP_NAME}_${VERSION}_${DEB_ARCH}.deb"
    echo "✅ DEB created."

elif [ "$TYPE" == "rpm" ]; then
    echo "📦 Building Fedora + EL9 RPM packages..."
    build_rpm_variant "fedora" "fedora" "python3, python3-gobject, python3-cairo, python3-setproctitle, gtk4, libadwaita, gstreamer1-plugins-base, gstreamer1-plugins-good, gstreamer1-plugins-bad-free, gstreamer1-plugins-ugly-free"
    build_rpm_variant "el9" "el9" "python3, python3-gobject, python3-cairo, python3-setproctitle, gtk4, libadwaita, gstreamer1-plugins-base, gstreamer1-plugins-good, gstreamer1-plugins-bad-free, gstreamer1-plugins-ugly-free"
elif [ "$TYPE" == "rpm-fedora" ]; then
    echo "📦 Building Fedora RPM package..."
    build_rpm_variant "fedora" "fedora" "python3, python3-gobject, python3-cairo, python3-setproctitle, gtk4, libadwaita, gstreamer1-plugins-base, gstreamer1-plugins-good, gstreamer1-plugins-bad-free, gstreamer1-plugins-ugly-free"
elif [ "$TYPE" == "rpm-el9" ]; then
    echo "📦 Building EL9 RPM package..."
    build_rpm_variant "el9" "el9" "python3, python3-gobject, python3-cairo, python3-setproctitle, gtk4, libadwaita, gstreamer1-plugins-base, gstreamer1-plugins-good, gstreamer1-plugins-bad-free, gstreamer1-plugins-ugly-free"
elif [ "$TYPE" == "arch" ]; then
    echo "📦 Building Arch package..."
    build_arch_package
elif [ "$TYPE" == "flatpak" ]; then
    echo "📦 Building Flatpak package..."
    build_flatpak_package
elif [ "$TYPE" == "all" ]; then
    echo "📦 Building DEB package..."
    mkdir -p "$BUILD_ROOT/DEBIAN"
    cat <<EOF > "$BUILD_ROOT/DEBIAN/control"
Package: $APP_NAME
Version: $VERSION
Section: sound
Priority: optional
Architecture: $DEB_ARCH
Depends: python3, python3-gi, python3-gi-cairo, python3-cairo, python3-dateutil, python3-typing-extensions, python3-isodate, python3-setproctitle, gir1.2-gtk-4.0, gir1.2-adw-1, gir1.2-gtksource-4, qrencode, python3-gst-1.0, gstreamer1.0-plugins-base, gstreamer1.0-plugins-good, gstreamer1.0-plugins-bad, gstreamer1.0-plugins-ugly, libpipewire-0.3-0, libpulse0
Maintainer: $MAINTAINER
Description: $DESCRIPTION
 $DISPLAY_NAME is a desktop client for Tidal focusing on High-Res audio.
EOF
    mkdir -p dist
    dpkg-deb --build "$BUILD_ROOT" "dist/${APP_NAME}_${VERSION}_${DEB_ARCH}.deb"
    echo "✅ DEB created."

    # Remove DEBIAN metadata before RPM build to avoid unpackaged-file errors.
    rm -rf "$BUILD_ROOT/DEBIAN"

    echo "📦 Building Fedora + EL9 RPM packages..."
    build_rpm_variant "fedora" "fedora" "python3, python3-gobject, python3-cairo, python3-setproctitle, gtk4, libadwaita, gstreamer1-plugins-base, gstreamer1-plugins-good, gstreamer1-plugins-bad-free, gstreamer1-plugins-ugly-free"
    build_rpm_variant "el9" "el9" "python3, python3-gobject, python3-cairo, python3-setproctitle, gtk4, libadwaita, gstreamer1-plugins-base, gstreamer1-plugins-good, gstreamer1-plugins-bad-free, gstreamer1-plugins-ugly-free"
    echo "📦 Building Arch package..."
    build_arch_package
else
    echo "Error: unsupported type '$TYPE'. Use deb | rpm | rpm-fedora | rpm-el9 | arch | flatpak | all"
    exit 1
fi

rm -rf "$BUILD_ROOT"
echo "🎉 Build Complete!"
