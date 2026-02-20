# HiresTI - Linux 平台的高保真 Tidal 播放器

![Python](https://img.shields.io/badge/Python-3.10%2B-blue)
![GTK4](https://img.shields.io/badge/UI-GTK4%20%2B%20Libadwaita-green)
![License](https://img.shields.io/badge/License-GPL--3.0-purple)
![Status](https://img.shields.io/badge/Status-v1.0-orange)

![Logo](icons/hicolor/64x64/apps/hiresti.png)

HiresTI 是一款专为发烧友设计的原生、现代 Linux Tidal 桌面客户端。与 Electron 套壳应用不同，HiresTI 基于 Python 3 和 GTK4/Libadwaita 构建，资源占用极低，并能与 GNOME 桌面环境无缝集成。


![Main Interface](screenshots/1.png)

✨ 核心功能
🎧 高解析度音频: 支持 Tidal 的 Max（最高 24-bit/192kHz）、High 和 Low 音质流媒体。

⚡ 位完美模式 (Bit-Perfect): 绕过软件混音器和 EQ，将原始音频流精确传输至您的 DAC。

🔒 独占模式: 直接接管设备的硬件控制权 (ALSA)，防止其他应用干扰。

🎨 现代 UI: 基于 Libadwaita 构建的美观、自适应界面。

🛠️ 原生性能: 快速且资源高效（非 Electron）。

🎹 媒体键: 原生支持播放/暂停、下一曲和上一曲媒体键。

☁️ 云端歌单与文件夹: 支持云端 Playlist 管理与 Folder 分组，支持封面拼贴预览。

📌 版本说明: 从 v1.1.0 开始已移除本地 Playlist，仅保留云端 Playlist。

## 📸 Screenshots

| Album Detail | Setting |
|:---:|:---:|
| ![Detail](screenshots/2.png) | ![Search](screenshots/3.png) |

📥 安装
我们为主流 Linux 发行版提供预构建的安装包。无需手动安装 Python 库！

🐧 Debian / Ubuntu / Linux Mint / Deepin
从  [Releases Page](../../releases). 页面 下载最新的 .deb 版本。

Bash
# 安装安装包
```bash
sudo dpkg -i hiresti_1.0.0_all.deb
```

🎩 Fedora / RedHat / CentOS / openSUSE
从  [Releases Page](../../releases). 页面 下载最新的 .rpm 版本。

```Bash
# 使用 dnf 安装（推荐，自动处理依赖）
sudo dnf install ./hiresti-1.0.0-1.x86_64.rpm
```

## License

GPL-3.0

## 问题排查与日志反馈

如果遇到问题，请优先通过命令行启动并采集日志，然后在 Issue 中反馈：

```bash
hiresti 2>&1 | tee /tmp/hiresti.log
```

如果需要 GTK 调试日志：

```bash
G_MESSAGES_DEBUG=all hiresti 2>&1 | tee /tmp/hiresti-gtk.log
```

提交 Issue 时建议附带：

- 发行版与桌面环境（例如 Ubuntu 24.04 + KDE）
- 软件版本号
- 复现步骤
- 关键日志片段（或上述完整日志文件）
