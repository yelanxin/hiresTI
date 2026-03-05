# HiresTI Audio Quality Optimization Guide

This guide covers the low-latency and bit-perfect optimizations already built into HiresTI, as well as system- and hardware-level improvements you can make on your end.

---

## 1. What HiresTI Already Does Internally

### 1.1 ALSA mmap Direct-Write Path (Zero-Copy)

In exclusive mode, HiresTI bypasses GStreamer's standard audio output chain entirely. A dedicated Rust thread calls `snd_pcm_mmap_begin` / `snd_pcm_mmap_commit` directly, writing PCM frames straight into the kernel DMA ring buffer without a `copy_to_user` hop. Compared to the PulseAudio or PipeWire mixing path, this eliminates 1–2 intermediate copies and the associated cache pollution.

### 1.2 Real-Time Thread Scheduling (SCHED_FIFO)

The mmap write thread runs under the `SCHED_FIFO` policy (default priority 60, configurable in settings). A `SCHED_FIFO` thread cannot be preempted by ordinary `SCHED_OTHER` tasks, ensuring each ALSA period write completes before the hardware deadline.

### 1.3 Memory Locking (`mlockall`)

At thread startup, `mlockall(MCL_CURRENT)` is called to pin all currently mapped pages in physical RAM. After the ALSA device is opened for the first time, `mlockall` is called again to also lock the DMA mapping pages. The PCM accumulation buffer is pre-faulted (written end-to-end then cleared) before locking, so no page faults occur on the real-time path during playback.

### 1.4 CPU C-State Prevention

While the mmap thread is running, it holds an open file descriptor to `/dev/cpu_dma_latency` with the value `0` written to it (requesting a 0 µs DMA latency budget). This forces the kernel to keep the CPU in the shallow C0/C1 idle state. Deep C-states (C3/C6) carry wakeup latencies of 100–300 µs — significant relative to a 10 ms ALSA period. The guard is released automatically when the thread exits. This is the same mechanism used by PipeWire, JACK, and rtkit.

### 1.5 Decode Thread Priority Boost

A GStreamer bus sync handler intercepts `GST_MESSAGE_STREAM_STATUS / Enter` messages, which are posted by each streaming thread (FLAC/AAC/MQA decoder, demuxer, etc.) at the moment it starts. The sync handler calls `nice(-5)` from within that thread's context, giving decode threads a moderate priority advantage over ordinary system tasks without requiring root privileges. This reduces the chance of decode output stalls that would drain the PCM accumulation buffer and cause underruns.

### 1.6 Uniform Buffer Splitting (`audiobuffersplit`)

FLAC decoders typically output ~4096-frame blocks (~93 ms at 44100 Hz). The `audiobuffersplit` GStreamer plugin slices these into uniform 16 ms chunks matching the spectrum analyser's refresh interval. This makes waveform visualisation more detailed and ensures the mmap write thread receives data in a steady, evenly-spaced stream rather than in large bursts.

### 1.7 Early Write-Thread Wakeup (`avail_min = period/2`)

The ALSA software parameters set `avail_min` to half a period rather than one full period. The kernel wakes the write thread as soon as half a period of DMA space becomes free, giving it a head-start on the next write. This extra margin helps the thread meet its hardware deadline under scheduling jitter without any meaningful overhead (one additional `poll` wakeup per period).

### 1.8 Three-Period Pre-Fill Before Playback Start

`snd_pcm_start` is called only after three full periods of audio have been written into the DMA buffer (versus the more common two). The extra period absorbs network jitter or occasional decode latency spikes that would otherwise immediately cause an underrun at the start of playback. The cost is roughly one additional period (~10 ms) of startup latency.

### 1.9 Bit-Perfect Output Format

HiresTI supports S16LE, S24LE (24-in-32 container), and S32LE output, written directly to a `hw:` device with no ALSA dmix, softvol, or software resampling in the path. The format is selected in settings and negotiated with the hardware; the PCM stream from TIDAL reaches your DAC mathematically identical to the source.

---

## 2. System-Level Optimizations (User Side)

### 2.1 Kernel

#### Use a Real-Time Kernel (Strongly Recommended)

The standard Linux kernel contains non-preemptible critical sections protected by spinlocks. Even a `SCHED_FIFO` thread can be delayed by hundreds of microseconds while the kernel holds such a lock. The `PREEMPT_RT` patch converts nearly all of these to preemptible mutexes, dramatically reducing worst-case scheduling latency.

| Distribution | Installation |
|---|---|
| Arch Linux | `sudo pacman -S linux-rt linux-rt-headers` |
| Fedora | `sudo dnf install kernel-rt` |
| Ubuntu | `sudo apt install linux-image-lowlatency` or Ubuntu Studio |

After installation, boot into the RT kernel — no further configuration is required.

#### Threaded IRQs (`threadirqs`)

Add `threadirqs` to your kernel boot parameters to make hardware interrupt handlers run as kernel threads. You can then use `chrt` to assign RT priority to the audio IRQ thread:

```bash
# Add threadirqs to GRUB_CMDLINE_LINUX in /etc/default/grub, then update grub

# Find the audio IRQ thread PID
grep -i "snd\|usb-audio" /proc/interrupts

# Assign SCHED_FIFO priority 70 to it
chrt -f -p 70 <irq_thread_pid>
```

### 2.2 CPU Scheduling

#### Set the CPU Frequency Governor to `performance`

Frequency scaling transitions introduce latency. Pin the governor to `performance` to keep the CPU at its maximum clock:

```bash
# Temporary (lost on reboot)
echo performance | sudo tee /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor

# Permanent (using cpupower)
sudo cpupower frequency-set -g performance
```

#### IRQ and Process CPU Affinity

Binding the audio IRQ and the HiresTI process to the same CPU core eliminates cross-core communication overhead:

```bash
# Find the IRQ number for your audio device
cat /proc/interrupts | grep -i "snd\|usb-audio\|hdaudio"

# Bind that IRQ to CPU core 2 (affinity mask 4 = binary 100)
echo 4 | sudo tee /proc/irq/<IRQ_NUMBER>/smp_affinity

# Launch HiresTI pinned to the same core
taskset -c 2 hiresti
```

#### Disable Hyper-Threading (Optional)

SMT sibling cores share L1/L2 caches. A sibling thread's cache activity can displace the audio write thread's working set, causing extra latency spikes. In critical listening environments this can be disabled in the BIOS, or temporarily suppressed with the `nosmt` kernel parameter.

### 2.3 ALSA Configuration

HiresTI opens the device as `hw:X,Y`, bypassing dmix, softvol, and any plug/rate conversion plugins. However, a system-wide `/etc/asound.conf` that redirects `hw:` through dmix would intercept this. Verify your configuration contains no such redirection:

```bash
# Check for active ALSA configuration
cat ~/.asoundrc 2>/dev/null
cat /etc/asound.conf 2>/dev/null
# Neither file should contain 'pcm.!default' pointing to dmix
```

### 2.4 USB Audio Driver Parameters (USB DAC Users)

The `snd-usb-audio` kernel module parameter `nrpacks` controls how many isochronous packets are bundled per USB Request Block (URB). Reducing it lowers the USB scheduling granularity:

```bash
# Check the current value
cat /sys/module/snd_usb_audio/parameters/nrpacks

# Set to 1 for finest scheduling granularity (slight CPU overhead increase)
echo 1 | sudo tee /sys/module/snd_usb_audio/parameters/nrpacks

# Make it permanent
echo 'options snd-usb-audio nrpacks=1' | sudo tee /etc/modprobe.d/usb-audio.conf
```

### 2.5 Memory

#### Reduce Swap Pressure

Swapping causes unpredictable page faults that interrupt the real-time thread. Lower the kernel's tendency to swap:

```bash
# Temporary
echo 10 | sudo tee /proc/sys/vm/swappiness

# Permanent
echo 'vm.swappiness=10' | sudo tee -a /etc/sysctl.d/99-audio.conf
sysctl -p /etc/sysctl.d/99-audio.conf
```

#### Disable Transparent Huge Pages

The THP background compaction thread periodically consumes CPU time and triggers TLB flushes, adding latency spikes to real-time threads:

```bash
echo never | sudo tee /sys/kernel/mm/transparent_hugepage/enabled
```

### 2.6 PipeWire / PulseAudio

The exclusive ALSA mmap path opens the hardware device directly. If PipeWire or PulseAudio already holds the device open, `snd_pcm_open` will fail. Stop the audio daemon before switching to exclusive mode:

```bash
# Stop (session will restart services automatically on next login)
systemctl --user stop pipewire pipewire-pulse wireplumber

# Restore when done
systemctl --user start pipewire pipewire-pulse wireplumber
```

---

## 3. Hardware Recommendations

### 3.1 USB DAC Connection

- **Avoid USB hubs.** Connect your DAC directly to a rear-panel motherboard port. Hubs add electrical noise and an additional scheduling layer in the host controller.
- **Cable length.** Keep USB cables short (≤1 m) and well-shielded. Longer cables with poor ground conductors can couple high-frequency digital noise from the motherboard into the DAC's analog ground plane.
- **USB isolators.** For critical listening, a galvanic or optical USB isolator (e.g. Intona, JCAT USB Isolator) completely breaks the ground-noise conduction path between the PC and DAC.

### 3.2 DAC Clock Mode: Async vs. Adaptive

USB audio devices operating in **Asynchronous UAC2** mode use their own internal oscillator as the master clock; the host computer's scheduling jitter does not directly affect D/A conversion. Devices in **Adaptive** mode derive their clock from the USB Start-of-Frame signal, making them sensitive to Linux USB scheduling irregularities.

Verify your DAC's mode:

```bash
lsusb -v 2>/dev/null | grep -A2 -i "bRefresh"
# bRefresh = 0  → Asynchronous (preferred)
# bRefresh > 0  → Adaptive or Synchronous
```

### 3.3 Power Supply

- A **linear power supply (LPS)** for your DAC typically produces lower high-frequency ripple than a switching supply (SMPS), reducing the noise floor at the analog output stage.
- For desktop setups, a powered USB filter (e.g. iFi iPurifier, JCAT USB Card) on the DAC's USB port can attenuate noise carried on the USB 5 V rail without a full galvanic isolator.

### 3.4 Dedicated PCIe Audio Card vs. Onboard

Onboard audio shares a ground plane with GPUs, NVMe drives, and other high-frequency digital components. A dedicated PCIe sound card — particularly one with on-card power regulation and PCIe bus isolation — typically achieves a lower analog noise floor than integrated audio, independent of the USB path.

---

## 4. Diagnostics

During exclusive playback, the **Settings → Diagnostics** panel (developer option) displays the live state of the mmap write thread:

| Field | Description |
|---|---|
| `realtime` | Whether RT scheduling is active and the effective priority |
| `memlock` | Whether `mlockall` succeeded |
| `negotiated_rate` | Sample rate agreed with the ALSA device |
| `period_frames` | Actual period size in frames |
| `device_resets` | Number of device resets caused by underruns |
| `open_failures` | Number of failed device open attempts (indicates PipeWire/PulseAudio contention) |

If `realtime` shows a failure reason, the most common causes are:
- `RLIMIT_RTPRIO` is 0 for the user — add the user to the `audio` or `realtime` group, or configure `/etc/security/limits.d/`
- rtkit is not running — `systemctl --user status rtkit-daemon`
