import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, GLib, Pango, Gdk
import time
import subprocess
import re
import logging
import glob

logger = logging.getLogger("signal_path")

class AudioSignalPathWindow(Adw.Window):
    def __init__(self, parent_app):
        super().__init__(transient_for=parent_app.win, modal=True)
        # [修复 1] 先初始化变量，防止 AttributeError
        self.timer_id = None 
        
        self.set_default_size(550, 760)
        self.set_title("Audio Signal Path")
        self.app = parent_app
        self.player = parent_app.player
        self._pw_runtime_cache_ts = 0.0
        self._pw_runtime_cache = {}

        # 主界面容器
        content = Adw.ToolbarView()
        self.set_content(content)

        # 顶部栏
        header = Adw.HeaderBar()
        content.add_top_bar(header)

        # 滚动区域
        scroll = Gtk.ScrolledWindow()
        content.set_content(scroll)

        # 居中布局
        clamp = Adw.Clamp(maximum_size=550, margin_top=24, margin_bottom=24, margin_start=12, margin_end=12)
        scroll.set_child(clamp)

        # 垂直主盒子
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        main_box.add_css_class("signal-path-root")
        clamp.set_child(main_box)
        self.root_box = main_box
        self._sync_theme_from_app()

        # --- 标题区域 ---
        title_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, margin_bottom=12)
        lbl_title = Gtk.Label(label="Signal Path", css_classes=["title-2"])
        lbl_sub = Gtk.Label(label="Live Audio Processing Pipeline", css_classes=["dim-label"])
        title_box.append(lbl_title)
        title_box.append(lbl_sub)
        main_box.append(title_box)

        # --- 顶部状态摘要 ---
        self.summary_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, css_classes=["signal-card"], margin_bottom=8)
        summary_head = Gtk.Box(spacing=8, margin_bottom=8)
        summary_head.append(Gtk.Image.new_from_icon_name("dialog-information-symbolic"))
        summary_head.append(Gtk.Label(label="Output Summary", xalign=0, css_classes=["heading"], hexpand=True))
        self.copy_diag_btn = Gtk.Button(label="Copy", css_classes=["flat"])
        self.copy_diag_btn.set_tooltip_text("Copy diagnostics summary")
        self.copy_diag_btn.connect("clicked", self.on_copy_diagnostics_clicked)
        summary_head.append(self.copy_diag_btn)
        self.summary_card.append(summary_head)
        self.summary_rows = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.summary_card.append(self.summary_rows)
        main_box.append(self.summary_card)

        # --- 1. Source Stage (源文件) ---
        self.card_source = self.create_stage_card(
            "cloud-symbolic", "Source Media", "TIDAL Cloud"
        )
        main_box.append(self.card_source)

        # ↓ 连接箭头
        main_box.append(self.create_arrow())

        # --- 2. Player Engine (播放器处理) ---
        self.card_engine = self.create_stage_card(
            "preferences-system-symbolic", "HiresTI Engine", "Audio Processing"
        )
        main_box.append(self.card_engine)

        # ↓ 连接箭头
        main_box.append(self.create_arrow())

        # --- 3. Hardware Output (硬件输出) ---
        self.card_output = self.create_stage_card(
            "audio-card-symbolic", "Audio Device", "Hardware Output"
        )
        main_box.append(self.card_output)

        # --- 4. Recent Events ---
        self.card_events = self.create_stage_card(
            "view-list-symbolic", "Recent Events", "Playback / Output Timeline"
        )
        main_box.append(self.card_events)

        # 启动定时器刷新数据 (每秒刷新)
        self.update_info() # 现在调用它是安全的
        self.timer_id = GLib.timeout_add(1000, self.update_info)
        
        # 窗口关闭时清理定时器
        self.connect("close-request", self.on_close)

    def _sync_theme_from_app(self):
        root = getattr(self, "root_box", None)
        app_root = getattr(self.app, "main_vbox", None) if hasattr(self, "app") else None
        if root is None or app_root is None:
            return
        # Mirror app theme class so themed CSS selectors apply inside this window too.
        for cls in ("app-theme-dark", "app-theme-fresh", "app-theme-sunset", "app-theme-mint", "app-theme-retro"):
            root.remove_css_class(cls)
            if cls in app_root.get_css_classes():
                root.add_css_class(cls)

    def on_close(self, *args):
        # 这里的检查现在是安全的，因为 __init__ 里已经设为 None 了
        if self.timer_id:
            GLib.source_remove(self.timer_id)
            self.timer_id = None
        return False

    def create_stage_card(self, icon_name, title, subtitle):
        """创建每一级的卡片"""
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, css_classes=["signal-card"])
        
        # 头部：图标 + 标题
        header = Gtk.Box(spacing=12, margin_bottom=12)
        icon = Gtk.Image.new_from_icon_name(icon_name)
        icon.add_css_class("signal-icon")
        
        text_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        lbl_t = Gtk.Label(label=title, xalign=0, css_classes=["heading"])
        lbl_s = Gtk.Label(label=subtitle, xalign=0, css_classes=["caption", "dim-label"])
        text_box.append(lbl_t); text_box.append(lbl_s)
        
        header.append(icon)
        header.append(text_box)
        card.append(header)
        
        # 内容区域
        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        card.content_box = content_box 
        card.append(content_box)
        
        return card

    def create_arrow(self):
        """创建连接箭头"""
        lbl = Gtk.Label(label="↓", css_classes=["signal-connector"])
        return lbl

    def set_card_rows(self, card, rows):
        """更新卡片内的数据行"""
        while child := card.content_box.get_first_child():
            card.content_box.remove(child)
            
        for label, value, is_highlight in rows:
            value_text = str(value)
            is_long = len(value_text) > 44 or " | " in value_text
            row = Gtk.Box(
                orientation=Gtk.Orientation.VERTICAL if is_long else Gtk.Orientation.HORIZONTAL,
                spacing=4 if is_long else 0,
            )

            lbl_key = Gtk.Label(label=label, xalign=0, css_classes=["dim-label"])
            lbl_key.set_wrap(True)
            lbl_key.set_wrap_mode(Pango.WrapMode.WORD_CHAR)

            lbl_val = Gtk.Label(
                label=value_text,
                xalign=0 if is_long else 1,
                hexpand=True,
                css_classes=["stat-value"],
            )
            lbl_val.set_wrap(True)
            lbl_val.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
            
            if is_highlight:
                lbl_val.add_css_class("success-text")
                
            row.append(lbl_key)
            row.append(lbl_val)
            card.content_box.append(row)

    def update_info(self):
        # 确保定时器安全
        # if not self.timer_id: return True # (已由 on_close 处理，这里可省略)

        snap = self._read_runtime_snapshot_safe()
        snap_src = snap.get("source", {}) if isinstance(snap, dict) else {}
        if not isinstance(snap_src, dict):
            snap_src = {}
        snap_out = snap.get("output", {}) if isinstance(snap, dict) else {}
        if not isinstance(snap_out, dict):
            snap_out = {}
        self._update_summary()
        self._update_recent_events()

        # --- 1. Source Data (Rust snapshot only) ---
        codec = self._normalize_codec_display(str(snap_src.get("codec", "") or "-"))
        bitrate = int(snap_src.get("bitrate", 0) or 0)

        sample_rate = "Unknown"
        bit_depth = "Unknown"
        src_rate = int(snap_src.get("rate", 0) or 0)
        src_depth = int(snap_src.get("depth", 0) or 0)
        if src_rate > 0:
            sample_rate = f"{src_rate/1000.0:g}kHz"
        if src_depth > 0:
            bit_depth = f"{src_depth}-bit"

        source_rows = [
            ("Format", codec, False),
            ("Bit Depth", bit_depth, False),
            ("Sample Rate", sample_rate, False),
            ("Bitrate", f"{bitrate // 1000} kbps" if bitrate > 0 else "-", False),
        ]
        self.set_card_rows(self.card_source, source_rows)

        # --- 2. Engine Data (优化显示) ---
        is_exclusive = self.player.exclusive_lock_mode
        is_bp = self.player.bit_perfect_mode
        current_driver = self._get_current_driver()
        pw_force_rate, _pw_allowed = self._get_pipewire_clock_state()
        pw_runtime = self._get_pipewire_runtime_formats()
        if current_driver == "PipeWire":
            # Kernel-level fallback for final hardware params (e.g. S32_LE).
            hw_fallback = self._get_kernel_hw_runtime()
            if hw_fallback.get("hardware_depth") and not pw_runtime.get("hardware_depth"):
                pw_runtime["hardware_depth"] = hw_fallback.get("hardware_depth")
            if hw_fallback.get("hardware_rate") and not pw_runtime.get("hardware_rate"):
                pw_runtime["hardware_rate"] = hw_fallback.get("hardware_rate")
        
        engine_rows = []
        if is_exclusive:
            engine_rows.append(("Mode", "Hardware Exclusive 🔒", True))
            engine_rows.append(("Software Mixer", "Bypassed (Direct)", True))
            engine_rows.append(("Resampler", "Inactive (Bit-Perfect)", True))
        elif is_bp:
            engine_rows.append(("Mode", "Bit-Perfect Mode", True))
            engine_rows.append(("Software Mixer", "Bypassed", True))
            if current_driver == "PipeWire":
                engine_rows.append(("Clock Source", f"PipeWire Forced ({pw_force_rate} Hz)" if pw_force_rate > 0 else "PipeWire Auto", False))
            else:
                engine_rows.append(("Clock Source", "Auto-Adjusted", False))
        else:
            # [优化] 根据驱动显示不同文案
            if current_driver == "PipeWire":
                engine_rows.append(("Mode", "PipeWire Graph 🚀", False)) # 加个图标表示高性能
                engine_rows.append(("Scheduling", "Quantum Driven", False))
            else:
                engine_rows.append(("Mode", "Shared Mode", False))
                engine_rows.append(("Software Mixer", "Active", False))
                
            engine_rows.append(("Resampler", "System Default", False))
            
        self.set_card_rows(self.card_engine, engine_rows)

        # --- 3. Output Data (优化显示) ---
        output_rows = []
        
        dev_name = self.app.current_device_name
        # 截断过长的设备名
        display_dev = dev_name[:25]+".." if len(dev_name)>25 else dev_name
        output_rows.append(("Device", display_dev, False))

        latency_sec = self.player.get_latency()
        pw_latency_ms = self._get_pipewire_runtime_latency_ms()
        is_playing = self.player.is_playing()

        # 延迟数值显示
        if is_exclusive:
            # In exclusive mode, align UI with configured target buffer size.
            try:
                cfg_buf_us = int(getattr(self.player, "alsa_buffer_time", 0) or 0)
            except Exception:
                cfg_buf_us = 0
            if cfg_buf_us > 0:
                lat_str = f"{(cfg_buf_us / 1000.0):.1f} ms"
            else:
                lat_str = "N/A"
        elif current_driver == "PipeWire" and pw_latency_ms is not None:
            lat_str = f"{pw_latency_ms:.1f} ms (PipeWire Node)"
        elif current_driver == "PipeWire" and latency_sec > 0:
            # Fallback to real GStreamer-reported latency (no guessed value).
            latency_ms = latency_sec * 1000
            lat_str = f"{latency_ms:.1f} ms (GStreamer)"
        elif latency_sec > 0:
            latency_ms = latency_sec * 1000
            # [优化] 对于极低延迟 (<10ms) 显示绿色高亮
            lat_str = f"{latency_ms:.1f} ms"
        elif is_playing:
            if is_exclusive:
                lat_str = "< 5.0 ms (Direct)"
            elif current_driver == "PipeWire":
                # Do not show guessed values in PipeWire mode.
                lat_str = "N/A (PipeWire Node unavailable)"
            else:
                lat_str = "~ 40 ms (Shared)"
        else:
            lat_str = "N/A"
            
        output_rows.append(("Latency", lat_str, latency_sec > 0 and latency_sec < 0.015)) # <15ms 高亮

        # 输出路径描述
        if is_exclusive:
            # Exclusive mode should display hardware runtime values from Rust snapshot.
            output_depth = ""
            output_rate = ""
            hw_depth = int(snap_out.get("hardware_depth", 0) or 0)
            hw_rate = int(snap_out.get("hardware_rate", 0) or 0)
            if hw_depth > 0:
                output_depth = self._parse_pw_depth(f"S{hw_depth}LE")
            if hw_rate > 0:
                output_rate = self._format_rate_hz(hw_rate)
            if not output_depth:
                output_depth = "Unknown"
            if not output_rate:
                output_rate = "Unknown"
            output_rows.append(("Output Depth", output_depth, True))
            output_rows.append(("Output Rate", output_rate, True))
            output_rows.append(("Output Path", "Direct ALSA Hardware", True))
        else:
            output_depth = "16/32 bit (Float)"
            output_rate = "Server Controlled"
            if current_driver == "PipeWire" and pw_force_rate > 0:
                output_rate = f"{pw_force_rate/1000.0:g}kHz"
            if current_driver == "PipeWire":
                sess_depth = pw_runtime.get("session_depth")
                sess_rate = pw_runtime.get("session_rate")
                if sess_depth:
                    output_depth = sess_depth
                if sess_rate:
                    output_rate = sess_rate
            if current_driver == "PipeWire":
                hw_depth = pw_runtime.get("hardware_depth")
                hw_rate = pw_runtime.get("hardware_rate")
                # PipeWire card should emphasize final sink format (what DAC sees).
                if hw_depth:
                    output_depth = hw_depth
                if hw_rate:
                    output_rate = hw_rate
                # Keep stream format visible as secondary info.
                if sess_depth:
                    output_rows.append(("Stream Depth", sess_depth, False))
                if sess_rate:
                    output_rows.append(("Stream Rate", sess_rate, False))
            output_rows.append(("Output Depth", output_depth, current_driver == "PipeWire" and bool(pw_runtime.get("hardware_depth"))))
            output_rows.append(("Output Rate", output_rate, current_driver == "PipeWire" and bool(pw_runtime.get("hardware_rate"))))
            
            # [优化] 明确显示是通过哪个服务输出的
            if current_driver == "PipeWire":
                output_rows.append(("Output Path", "PipeWire Multimedia", True)) # 绿色高亮
            elif current_driver == "PulseAudio":
                output_rows.append(("Output Path", "PulseAudio Server", False))
            else:
                output_rows.append(("Output Path", "System Shared", False))

        # Source vs Output compare.
        source_pair = f"{sample_rate} / {bit_depth}"
        display_out_rate = output_rate
        display_out_depth = output_depth
        if current_driver == "PipeWire":
            display_out_rate = pw_runtime.get("hardware_rate") or output_rate
            display_out_depth = pw_runtime.get("hardware_depth") or output_depth
        output_pair = f"{display_out_rate} / {display_out_depth}"
        is_match = self._compute_format_match(current_driver, sample_rate, bit_depth, output_rate, output_depth)
        output_rows.append(("Source -> Output", f"{source_pair} -> {output_pair}", False))
        output_rows.append(("Format Match", "Yes" if is_match else "No", is_match))
            
        self.set_card_rows(self.card_output, output_rows)

        return True

    def _update_summary(self):
        while child := self.summary_rows.get_first_child():
            self.summary_rows.remove(child)

        state = getattr(self.player, "output_state", "idle")
        err = getattr(self.player, "output_error", None)
        req_driver = getattr(self.player, "requested_driver", None)
        req_dev = getattr(self.player, "requested_device_id", None)

        bit_perfect = self.player.bit_perfect_mode
        exclusive = self.player.exclusive_lock_mode
        driver = self._get_current_driver()
        pw_force_rate, _pw_allowed = self._get_pipewire_clock_state()
        snap = self._read_runtime_snapshot_safe()
        snap_src = snap.get("source", {}) if isinstance(snap, dict) else {}
        if not isinstance(snap_src, dict):
            snap_src = {}
        snap_out = snap.get("output", {}) if isinstance(snap, dict) else {}
        if not isinstance(snap_out, dict):
            snap_out = {}
        sample_rate = "Unknown"
        bit_depth = "Unknown"
        src_rate = int(snap_src.get("rate", 0) or 0)
        src_depth = int(snap_src.get("depth", 0) or 0)
        if src_rate > 0:
            sample_rate = f"{src_rate/1000.0:g}kHz"
        if src_depth > 0:
            bit_depth = f"{src_depth}-bit"

        output_rate = "Server Controlled"
        output_depth = "16/32 bit (Float)"
        if exclusive:
            hw_rate = int(snap_out.get("hardware_rate", 0) or 0)
            hw_depth = int(snap_out.get("hardware_depth", 0) or 0)
            output_rate = self._format_rate_hz(hw_rate) if hw_rate > 0 else "Unknown"
            output_depth = self._parse_pw_depth(f"S{hw_depth}LE") if hw_depth > 0 else "Unknown"
        if driver == "PipeWire" and pw_force_rate > 0 and not exclusive:
            output_rate = f"{pw_force_rate/1000.0:g}kHz"
        rate_match = self._rate_only_match(sample_rate, output_rate)
        format_match = self._compute_format_match(driver, sample_rate, bit_depth, output_rate, output_depth)

        verdict_ok, verdict_style, reasons = self._compute_bitperfect_verdict(state, sample_rate, bit_depth, output_rate, output_depth)
        rows = [
            ("Bit-Perfect Verdict", "Yes" if verdict_ok else "No", verdict_style),
            ("Rate Match", "Yes" if rate_match else "No", "ok" if rate_match else "warn"),
            ("Exclusive", "Yes" if exclusive else "No", "ok" if exclusive else "warn"),
            ("Output State", state.capitalize(), "ok" if state == "active" else "warn"),
        ]
        if req_driver:
            target = f"{req_driver}" if not req_dev else f"{req_driver} / {req_dev}"
            rows.append(("Target Output", target, False))
        if err:
            rows.append(("Last Error", err, False))
        if not verdict_ok and reasons:
            rows.append(("Reasons", " | ".join(reasons), False))
        # Keep summary concise: hide actionable suggestion row in UI.

        for key, value, style in rows:
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
            lbl_key = Gtk.Label(label=key, xalign=0, css_classes=["dim-label"])
            lbl_val = Gtk.Label(label=value, xalign=1, hexpand=True, css_classes=["stat-value"])
            lbl_val.set_wrap(True)
            if style == "ok":
                lbl_val.add_css_class("success-text")
            elif style == "warn":
                lbl_val.add_css_class("warning-text")
            row.append(lbl_key)
            row.append(lbl_val)
            self.summary_rows.append(row)

    def _compute_bitperfect_verdict(self, output_state, sample_rate="Unknown", bit_depth="Unknown", output_rate="Unknown", output_depth="Unknown"):
        reasons = []
        driver = self._get_current_driver()
        bit_perfect = bool(getattr(self.player, "bit_perfect_mode", False))
        exclusive = bool(getattr(self.player, "exclusive_lock_mode", False))

        if not bit_perfect:
            reasons.append("Bit-Perfect mode disabled")

        if output_state in ("fallback", "error"):
            reasons.append(f"Output state is {output_state}")

        rate_match = self._rate_only_match(sample_rate, output_rate)
        depth_match = self._depth_only_match(bit_depth, output_depth)
        format_match = bool(rate_match and depth_match)

        # ALSA path: requires exclusive for strict direct mode (rate+depth match).
        if driver == "ALSA":
            if not exclusive:
                reasons.append("Not in exclusive mode")
            if not format_match:
                reasons.append("Rate/depth mismatch")
        # PipeWire path: strict mode here also requires both rate and depth match.
        elif driver == "PipeWire":
            if bool(getattr(self.player, "_pipewire_rate_blocked", False)):
                reasons.append("PipeWire rate blocked")
            if not format_match:
                reasons.append("Rate/depth mismatch")
        else:
            reasons.append(f"Driver is {driver}")

        verdict_ok = bool(bit_perfect and output_state == "active" and format_match and (driver != "ALSA" or exclusive))
        return (verdict_ok, "ok" if verdict_ok else "warn", reasons)

    def _get_current_driver(self):
        drv = getattr(self.player, "current_driver", None) or self.app.settings.get("driver", "Auto")
        return str(drv or "Auto")

    def _read_runtime_snapshot_safe(self):
        fn = getattr(self.player, "_read_runtime_snapshot", None)
        if not callable(fn):
            return {}
        try:
            snap = fn() or {}
            if isinstance(snap, dict):
                return snap
        except Exception:
            return {}
        return {}

    def _get_pipewire_clock_state(self):
        force_rate = 0
        allowed_raw = ""
        fn = getattr(self.player, "_read_pipewire_clock_metadata", None)
        if callable(fn):
            try:
                meta = fn() or {}
                force_rate = int(meta.get("force_rate", 0) or 0)
                allowed_raw = str(meta.get("allowed_rates_raw", "") or "")
            except Exception:
                pass
        return force_rate, allowed_raw

    def _get_pipewire_runtime_latency_ms(self):
        fn = getattr(self.player, "_read_runtime_snapshot", None)
        if not callable(fn):
            return None
        try:
            snap = fn() or {}
            pw = snap.get("pipewire", {}) if isinstance(snap, dict) else {}
            if not isinstance(pw, dict):
                return None
            v = float(pw.get("latency_ms", -1.0) or -1.0)
            try:
                now = time.monotonic()
                last = float(getattr(self, "_pw_latency_log_ts", 0.0) or 0.0)
                if (now - last) >= 3.0:
                    self._pw_latency_log_ts = now
                    logger.info(
                        "SignalPath latency source: latency_ms=%s force_rate=%s allowed=%s",
                        pw.get("latency_ms", None),
                        pw.get("force_rate", None),
                        pw.get("allowed_rates_raw", None),
                    )
            except Exception:
                pass
            if v >= 0.0:
                return v
        except Exception:
            return None
        return None

    def _compute_format_match(self, driver, sample_rate, bit_depth, output_rate, output_depth):
        if self.player.output_state != "active":
            return False
        if sample_rate == "Unknown" or bit_depth == "Unknown":
            return False
        if driver == "ALSA" and self.player.exclusive_lock_mode:
            return self._rate_only_match(sample_rate, output_rate) and self._depth_only_match(bit_depth, output_depth)
        if driver == "PipeWire":
            return self._rate_only_match(sample_rate, output_rate) and self._depth_only_match(bit_depth, output_depth)
        return False

    @staticmethod
    def _rate_only_match(src_rate, out_rate):
        def _to_hz(v):
            s = str(v or "").strip().lower()
            if not s or s == "unknown":
                return 0
            try:
                if s.endswith("khz"):
                    return int(round(float(s.replace("khz", "").strip()) * 1000.0))
                if s.endswith("hz"):
                    return int(round(float(s.replace("hz", "").strip())))
                return int(round(float(s)))
            except Exception:
                return 0
        a = _to_hz(src_rate)
        b = _to_hz(out_rate)
        return a > 0 and b > 0 and a == b

    @staticmethod
    def _depth_only_match(src_depth, out_depth):
        def _to_bits(v):
            s = str(v or "").strip().lower()
            if not s or s == "unknown":
                return 0
            m = re.search(r"(\d+)\s*-?\s*bit", s)
            if m:
                try:
                    return int(m.group(1))
                except Exception:
                    return 0
            try:
                return int(s)
            except Exception:
                return 0
        a = _to_bits(src_depth)
        b = _to_bits(out_depth)
        return a > 0 and b > 0 and a == b

    @staticmethod
    def _parse_pw_depth(fmt):
        f = str(fmt or "").upper()
        if not f:
            return ""
        if "F32" in f:
            return "32-bit (Float)"
        if "F64" in f:
            return "64-bit (Float)"
        m = re.search(r"([SUF])(\d+)", f)
        if not m:
            return ""
        bits = int(m.group(2))
        if m.group(1) == "F":
            return f"{bits}-bit (Float)"
        return f"{bits}-bit"

    @staticmethod
    def _format_rate_hz(rate):
        try:
            r = int(rate or 0)
        except Exception:
            r = 0
        if r <= 0:
            return ""
        return f"{r/1000.0:g}kHz"

    @staticmethod
    def _normalize_codec_display(codec):
        s = str(codec or "").strip()
        if not s:
            return "-"
        # Clean escaped text from tag strings (e.g. "Free\\ Lossless\\ Audio\\ Codec\\ \\(FLAC\\)")
        s = s.replace("\\(", "(").replace("\\)", ")").replace("\\", " ")
        s = re.sub(r"\s+", " ", s).strip()
        up = s.upper()
        if "FLAC" in up or "FREE LOSSLESS AUDIO CODEC" in up:
            return "FLAC"
        if "ALAC" in up:
            return "ALAC"
        if "AAC" in up:
            return "AAC"
        if "MP3" in up:
            return "MP3"
        if "MQA" in up:
            return "MQA"
        return s

    def _parse_pw_top_line(self, line):
        s = str(line or "").strip()
        if not s or s.startswith("S ") or s.startswith("I "):
            return None
        parts = s.split()
        if len(parts) < 10:
            return None
        fmt_idx = -1
        fmt_re = re.compile(r"^(?:S|U|F)\d+(?:LE|BE)?$")
        for i, tok in enumerate(parts):
            if fmt_re.match(str(tok or "").upper()):
                if i + 2 < len(parts):
                    fmt_idx = i
                    break
        if fmt_idx < 0:
            return None
        fmt = parts[fmt_idx]
        channels = parts[fmt_idx + 1] if (fmt_idx + 1) < len(parts) else ""
        rate = parts[fmt_idx + 2] if (fmt_idx + 2) < len(parts) else ""
        name = " ".join(parts[(fmt_idx + 3):]).strip()
        if not name:
            return None
        return {
            "state": parts[0] if parts else "",
            "format": fmt,
            "channels": channels,
            "rate": rate,
            "name": name,
        }

    def _get_pipewire_runtime_formats(self):
        now = time.monotonic()
        if (now - float(self._pw_runtime_cache_ts or 0.0)) < 1.5:
            return dict(self._pw_runtime_cache or {})

        data = {}
        driver = self._get_current_driver()
        if driver != "PipeWire":
            self._pw_runtime_cache_ts = now
            self._pw_runtime_cache = data
            return data

        # Prefer Rust runtime snapshot (system/C API based).
        snap_reader = getattr(self.player, "_read_runtime_snapshot", None)
        if callable(snap_reader):
            try:
                snap = snap_reader() or {}
                out = snap.get("output", {}) if isinstance(snap, dict) else {}
                if isinstance(out, dict):
                    sr = self._format_rate_hz(out.get("session_rate", 0))
                    sd = self._parse_pw_depth(f"S{int(out.get('session_depth', 0) or 0)}LE") if int(out.get("session_depth", 0) or 0) > 0 else ""
                    hr = self._format_rate_hz(out.get("hardware_rate", 0))
                    hd = self._parse_pw_depth(f"S{int(out.get('hardware_depth', 0) or 0)}LE") if int(out.get("hardware_depth", 0) or 0) > 0 else ""
                    if sd:
                        data["session_depth"] = sd
                    if sr:
                        data["session_rate"] = sr
                    if hd:
                        data["hardware_depth"] = hd
                    if hr:
                        data["hardware_rate"] = hr
            except Exception:
                logger.debug("Rust runtime snapshot parse failed", exc_info=True)

        # Fallback: output_* fields from stream_info (still from Rust TAG path).
        if not data:
            try:
                info = dict(getattr(self.player, "stream_info", {}) or {})
                orate = int(info.get("output_rate", 0) or 0)
                odepth = int(info.get("output_depth", 0) or 0)
                if orate > 0:
                    data["session_rate"] = self._format_rate_hz(orate)
                if odepth > 0:
                    data["session_depth"] = self._parse_pw_depth(f"S{odepth}LE")
            except Exception:
                pass

        self._pw_runtime_cache_ts = now
        self._pw_runtime_cache = data
        return dict(data)

    def _get_kernel_hw_runtime(self):
        """
        Read active ALSA playback hw_params as a stable fallback.
        Useful when pw-top mapping is unavailable.
        """
        out = {}
        try:
            for status_path in sorted(glob.glob("/proc/asound/card*/pcm*p/sub*/status")):
                try:
                    with open(status_path, "r", encoding="utf-8", errors="ignore") as f:
                        status_txt = f.read()
                except Exception:
                    continue
                if "RUNNING" not in status_txt.upper():
                    continue
                hw_path = status_path.rsplit("/", 1)[0] + "/hw_params"
                try:
                    with open(hw_path, "r", encoding="utf-8", errors="ignore") as f:
                        hw_txt = f.read()
                except Exception:
                    continue
                fmt = ""
                rate = ""
                for ln in hw_txt.splitlines():
                    s = ln.strip()
                    if s.lower().startswith("format:"):
                        fmt = s.split(":", 1)[1].strip()
                    elif s.lower().startswith("rate:"):
                        rate = s.split(":", 1)[1].strip().split(" ", 1)[0]
                if fmt:
                    d = self._parse_pw_depth(fmt.replace("_", ""))
                    if d:
                        out["hardware_depth"] = d
                if rate:
                    r = self._format_rate_hz(rate)
                    if r:
                        out["hardware_rate"] = r
                if out:
                    return out
        except Exception:
            logger.debug("kernel hw_params parse failed", exc_info=True)
        return out

    def _build_diagnostics_text(self):
        snap = self._read_runtime_snapshot_safe()
        snap_src = snap.get("source", {}) if isinstance(snap, dict) else {}
        if not isinstance(snap_src, dict):
            snap_src = {}
        snap_out = snap.get("output", {}) if isinstance(snap, dict) else {}
        if not isinstance(snap_out, dict):
            snap_out = {}
        codec = self._normalize_codec_display(str(snap_src.get("codec", "") or "-"))
        bitrate = int(snap_src.get("bitrate", 0) or 0)
        state = getattr(self.player, "output_state", "idle")
        err = getattr(self.player, "output_error", None)
        driver = self._get_current_driver()
        dev = getattr(self.app, "current_device_name", "Default")
        format_match = self._compute_format_match(driver, sample_rate, bit_depth, output_rate, output_depth)
        verdict_ok, _verdict_style, reasons = self._compute_bitperfect_verdict(
            state, sample_rate, bit_depth, output_rate, output_depth
        )
        sample_rate = "Unknown"
        bit_depth = "Unknown"
        src_rate = int(snap_src.get("rate", 0) or 0)
        src_depth = int(snap_src.get("depth", 0) or 0)
        if src_rate > 0:
            sample_rate = f"{src_rate/1000.0:g}kHz"
        if src_depth > 0:
            bit_depth = f"{src_depth}-bit"
        output_rate = "Server Controlled"
        output_depth = "16/32 bit (Float)"
        if self.player.exclusive_lock_mode:
            hw_rate = int(snap_out.get("hardware_rate", 0) or 0)
            hw_depth = int(snap_out.get("hardware_depth", 0) or 0)
            output_rate = self._format_rate_hz(hw_rate) if hw_rate > 0 else "Unknown"
            output_depth = self._parse_pw_depth(f"S{hw_depth}LE") if hw_depth > 0 else "Unknown"
        if driver == "PipeWire":
            force_rate, allowed_raw = self._get_pipewire_clock_state()
            if force_rate > 0 and not self.player.exclusive_lock_mode:
                output_rate = f"{force_rate/1000.0:g}kHz"
        else:
            force_rate, allowed_raw = (0, "")
        format_match = self._compute_format_match(driver, sample_rate, bit_depth, output_rate, output_depth)

        lines = [
            f"Bit-Perfect Verdict: {'Yes' if verdict_ok else 'No'}",
            f"Rate Match: {'Yes' if format_match else 'No'}",
            f"Bit-Perfect Mode: {'On' if self.player.bit_perfect_mode else 'Off'}",
            f"Exclusive Mode: {'On' if self.player.exclusive_lock_mode else 'Off'}",
            f"Driver: {driver}",
            f"Device: {dev}",
            f"Output State: {state}",
            f"Source Codec: {codec}",
            f"Source Format: {codec}",
            f"Source Bitrate: {bitrate // 1000 if bitrate else 0} kbps",
        ]
        if driver == "PipeWire":
            lines.append(f"PipeWire Force Rate: {force_rate if force_rate else '0'} Hz")
            if allowed_raw:
                lines.append(f"PipeWire Allowed Rates: {allowed_raw}")
        if reasons:
            lines.append(f"Reasons: {' | '.join(reasons)}")
        fixes = self._build_fix_suggestions(state, sample_rate, bit_depth)
        if fixes:
            lines.append(f"How to Fix: {' | '.join(fixes)}")
        if err:
            lines.append(f"Last Error: {err}")
        events = getattr(self.player, "event_log", [])
        if events:
            lines.append("Recent Events:")
            for ev in events[-8:]:
                lines.append(f"- {ev}")
        return "\n".join(lines)

    def on_copy_diagnostics_clicked(self, _btn):
        text = self._build_diagnostics_text()
        display = Gdk.Display.get_default()
        if not display:
            return
        clipboard = display.get_clipboard()
        clipboard.set(text)

    def _build_fix_suggestions(self, output_state, sample_rate, bit_depth):
        suggestions = []
        driver = self._get_current_driver()
        if not self.player.bit_perfect_mode:
            suggestions.append("Enable Bit-Perfect mode")
        if driver == "ALSA" and not self.player.exclusive_lock_mode:
            suggestions.append("Enable Exclusive mode")
        if driver == "PipeWire":
            force_rate, _allowed = self._get_pipewire_clock_state()
            if force_rate <= 0:
                suggestions.append("Restart playback to apply PipeWire force-rate")
        if output_state in ("fallback", "error"):
            suggestions.append("Click Recover in Settings")
        if sample_rate == "Unknown" or bit_depth == "Unknown":
            suggestions.append("Play a track for a few seconds to detect format")

        # Keep summary concise.
        return suggestions[:3]

    def _update_recent_events(self):
        events = list(getattr(self.player, "event_log", []))
        if not events:
            self.set_card_rows(self.card_events, [("Event", "No recent events", False)])
            return

        rows = []
        for ev in reversed(events[-6:]):
            if "|" in ev:
                ts, msg = ev.split("|", 1)
                rows.append((ts.strip(), msg.strip(), False))
            else:
                rows.append(("Event", ev, False))
        self.set_card_rows(self.card_events, rows)
