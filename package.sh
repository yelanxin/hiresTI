#!/bin/bash
set -euo pipefail

# ================= 配置区域 =================
APP_NAME="hiresti"
APP_ID="com.hiresti.player"  # [新增] 必须与 main.py 中的 application_id 一致
DISPLAY_NAME="HiresTI"
MAINTAINER="Eason <yelanxin@gmail.com>"
DESCRIPTION="High-Res Tidal Player for Linux with Bit-Perfect support."
LICENSE="MIT"
URL="https://github.com/yourrepo/hiresti"
# ===========================================

TYPE=$1
VERSION=$2

if [ -z "$TYPE" ] || [ -z "$VERSION" ]; then
    echo "Usage: ./package.sh [deb|rpm|rpm-fedora|rpm-el9] [version]"
    echo "Example: ./package.sh rpm 1.0.0"
    exit 1
fi

if [ "$TYPE" == "deb" ] && ! command -v dpkg-deb &> /dev/null; then
    echo "Error: 'dpkg-deb' is required."
    exit 1
fi

if [[ "$TYPE" == "rpm" || "$TYPE" == "rpm-fedora" || "$TYPE" == "rpm-el9" ]] && ! command -v rpmbuild &> /dev/null; then
    echo "Error: 'rpmbuild' is required."
    exit 1
fi

echo "🚀 Starting build process for $APP_NAME v$VERSION ($TYPE)..."

# Preflight checks
for required in main.py ui actions icons/hicolor; do
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
cp ./*.py "$INSTALL_DIR/"
cp -r ui "$INSTALL_DIR/"
cp -r actions "$INSTALL_DIR/"
cp -r icons "$INSTALL_DIR/"
if [ -d "css" ]; then cp -r css "$INSTALL_DIR/"; fi

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
pip3 install tidalapi requests urllib3 pystray pillow -t "$INSTALL_DIR/libs" --no-cache-dir --upgrade

# 5. 创建启动脚本
echo "📜 Creating launcher script..."
LAUNCHER="$BIN_DIR/$APP_NAME"
cat <<EOF > "$LAUNCHER"
#!/bin/bash
export PYTHONPATH="/usr/share/$APP_NAME/libs:\$PYTHONPATH"
cd /usr/share/$APP_NAME
exec python3 main.py "\$@"
EOF
chmod +x "$LAUNCHER"

# 6. [关键修改] 创建 .desktop 文件
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

if [ "$TYPE" == "deb" ]; then
    echo "📦 Building .deb package..."
    mkdir -p "$BUILD_ROOT/DEBIAN"
    cat <<EOF > "$BUILD_ROOT/DEBIAN/control"
Package: $APP_NAME
Version: $VERSION
Section: sound
Priority: optional
Architecture: all
Depends: python3, python3-gi, gir1.2-gtk-4.0, gir1.2-adw-1, python3-gst-1.0, gstreamer1.0-plugins-good, gstreamer1.0-plugins-bad, gstreamer1.0-plugins-ugly
Maintainer: $MAINTAINER
Description: $DESCRIPTION
 $DISPLAY_NAME is a desktop client for Tidal focusing on High-Res audio.
EOF
    mkdir -p dist
    dpkg-deb --build "$BUILD_ROOT" "dist/${APP_NAME}_${VERSION}_all.deb"
    echo "✅ DEB created."

elif [ "$TYPE" == "rpm" ]; then
    echo "📦 Building Fedora + EL9 RPM packages..."
    build_rpm_variant "fedora" "fedora" "python3, python3-gobject, gtk4, libadwaita, gstreamer1-plugins-good, gstreamer1-plugins-bad-free, gstreamer1-plugins-ugly-free"
    build_rpm_variant "el9" "el9" "python3, python3-gobject, gtk4, libadwaita, gstreamer1-plugins-good, gstreamer1-plugins-bad-free, gstreamer1-plugins-ugly-free"
elif [ "$TYPE" == "rpm-fedora" ]; then
    echo "📦 Building Fedora RPM package..."
    build_rpm_variant "fedora" "fedora" "python3, python3-gobject, gtk4, libadwaita, gstreamer1-plugins-good, gstreamer1-plugins-bad-free, gstreamer1-plugins-ugly-free"
elif [ "$TYPE" == "rpm-el9" ]; then
    echo "📦 Building EL9 RPM package..."
    build_rpm_variant "el9" "el9" "python3, python3-gobject, gtk4, libadwaita, gstreamer1-plugins-good, gstreamer1-plugins-bad-free, gstreamer1-plugins-ugly-free"
else
    echo "Error: unsupported type '$TYPE'. Use deb | rpm | rpm-fedora | rpm-el9"
    exit 1
fi

rm -rf "$BUILD_ROOT"
echo "🎉 Build Complete!"
