#!/usr/bin/env bash
# Launch a Garuda Hyprland live VM (QEMU/KVM) to manually reproduce/verify
# issue #83 (WebKit PKCE login crash on Hyprland/wlroots).
#
# Garuda Hyprland is Arch-based and boots a *live* Hyprland session, closely
# matching the bug reporter's environment (Arch + Hyprland + pipewire +
# xdg-desktop-portal-hyprland).
#
# Usage:
#   ./tools/hyprland_vm.sh            # boot live VM with a GUI window
#   HIRESTI_VM_RAM=8192 ./tools/hyprland_vm.sh
#
# Inside the VM (live user/pass is garuda/garuda):
#   The hiresTI repo is shared read-only at mount tag "hiresti".
#   Mount it and run the WebKit probe:
#     mkdir -p ~/hiresti && sudo mount -t 9p -o trans=virtio,version=9p2000.L,ro hiresti ~/hiresti
#     cd ~/hiresti
#     # Garuda Hyprland live already ships webkit/gtk/pipewire — do NOT run
#     # `pacman -Sy` + partial gstreamer installs (breaks live ISO versions).
#     pacman -Q webkitgtk-6.0 python-gobject gtk4 libadwaita 2>&1
#     # If anything is missing only:
#     sudo pacman -S --needed --noconfirm python python-gobject gtk4 libadwaita webkitgtk-6.0
#     python3 tools/webkit_login_probe.py
set -euo pipefail

VM_DIR="${HIRESTI_VM_DIR:-/var/tmp/hyprland-vm}"
ISO="${HIRESTI_VM_ISO:-${VM_DIR}/garuda-hyprland.iso}"
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
RAM="${HIRESTI_VM_RAM:-6144}"
CPUS="${HIRESTI_VM_CPUS:-4}"
OVMF_CODE="${HIRESTI_OVMF_CODE:-/usr/share/OVMF/OVMF_CODE_4M.fd}"
OVMF_VARS_SRC="${HIRESTI_OVMF_VARS:-/usr/share/OVMF/OVMF_VARS_4M.fd}"
OVMF_VARS="${VM_DIR}/OVMF_VARS.fd"

if [[ ! -f "$ISO" ]]; then
  echo "Error: ISO not found at $ISO" >&2
  echo "Download: curl -fL -o '$ISO' https://iso.builds.garudalinux.org/iso/latest/garuda/hyprland/latest.iso" >&2
  exit 1
fi

if [[ ! -e /dev/kvm ]]; then
  echo "Error: /dev/kvm missing — KVM acceleration unavailable." >&2
  exit 1
fi

mkdir -p "$VM_DIR"
# Per-VM writable UEFI vars copy.
if [[ ! -f "$OVMF_VARS" ]]; then
  cp "$OVMF_VARS_SRC" "$OVMF_VARS"
fi

# GTK display works on both Wayland and X11 hosts. virtio-vga-gl enables
# virgl 3D so Hyprland (needs GL) renders in the window.
echo "Launching Garuda Hyprland VM (RAM=${RAM}MB, CPUS=${CPUS})."
echo "Live login: garuda / garuda. Close the window to stop the VM."
echo "hiresTI repo shared via 9p mount tag: hiresti (read-only)."

exec qemu-system-x86_64 \
  -name "hiresti-hyprland-test" \
  -enable-kvm \
  -machine q35,accel=kvm \
  -cpu host \
  -smp "$CPUS" \
  -m "$RAM" \
  -drive if=pflash,format=raw,readonly=on,file="$OVMF_CODE" \
  -drive if=pflash,format=raw,file="$OVMF_VARS" \
  -cdrom "$ISO" \
  -boot d \
  -device virtio-vga-gl \
  -display gtk,gl=on \
  -device intel-hda -device hda-duplex \
  -device qemu-xhci -device usb-tablet \
  -netdev user,id=net0 -device virtio-net-pci,netdev=net0 \
  -virtfs "local,path=${PROJECT_DIR},mount_tag=hiresti,security_model=mapped-xattr,readonly=on" \
  -rtc base=localtime
