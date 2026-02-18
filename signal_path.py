import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, GLib, Pango, Gdk

class AudioSignalPathWindow(Adw.Window):
    def __init__(self, parent_app):
        super().__init__(transient_for=parent_app.win, modal=True)
        # [修复 1] 先初始化变量，防止 AttributeError
        self.timer_id = None 
        
        self.set_default_size(550, 760)
        self.set_title("Audio Signal Path")
        self.app = parent_app
        self.player = parent_app.player

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
        
        info = self.player.stream_info
        self._update_summary()
        self._update_recent_events()
        
        # --- 1. Source Data (保持不变) ---
        codec = info.get("codec", "-")
        fmt = info.get("fmt_str", "-") 
        bitrate = info.get("bitrate", 0)
        
        sample_rate = "Unknown"
        bit_depth = "Unknown"
        if "|" in fmt:
            parts = fmt.split("|")
            sample_rate = parts[0].strip()
            bit_depth = parts[1].strip()
        
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
        # [新增] 获取当前驱动名称
        current_driver = self.app.settings.get("driver", "Auto")
        
        engine_rows = []
        if is_exclusive:
            engine_rows.append(("Mode", "Hardware Exclusive 🔒", True))
            engine_rows.append(("Software Mixer", "Bypassed (Direct)", True))
            engine_rows.append(("Resampler", "Inactive (Bit-Perfect)", True))
        elif is_bp:
            engine_rows.append(("Mode", "Bit-Perfect Mode", True))
            engine_rows.append(("Software Mixer", "Bypassed", True))
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
        is_playing = self.player.is_playing()

        # 延迟数值显示
        if latency_sec > 0:
            latency_ms = latency_sec * 1000
            # [优化] 对于极低延迟 (<10ms) 显示绿色高亮
            lat_str = f"{latency_ms:.1f} ms"
        elif is_playing:
            if is_exclusive:
                lat_str = "< 5.0 ms (Direct)"
            elif current_driver == "PipeWire":
                # PipeWire 通常能拿到数值，万一拿不到，给个更有信心的估算
                lat_str = "~ 20 ms (PipeWire)" 
            else:
                lat_str = "~ 40 ms (Shared)"
        else:
            lat_str = "N/A"
            
        output_rows.append(("Latency", lat_str, latency_sec > 0 and latency_sec < 0.015)) # <15ms 高亮
        
        # 输出路径描述
        if is_exclusive:
            output_depth = bit_depth
            output_rate = sample_rate
            output_rows.append(("Output Depth", output_depth, True))
            output_rows.append(("Output Rate", output_rate, True))
            output_rows.append(("Output Path", "Direct ALSA Hardware", True))
        else:
            output_depth = "16/32 bit (Float)"
            output_rate = "Server Controlled"
            output_rows.append(("Session Depth", output_depth, False))
            output_rows.append(("Session Rate", output_rate, False))
            
            # [优化] 明确显示是通过哪个服务输出的
            if current_driver == "PipeWire":
                output_rows.append(("Output Path", "PipeWire Multimedia", True)) # 绿色高亮
            elif current_driver == "PulseAudio":
                output_rows.append(("Output Path", "PulseAudio Server", False))
            else:
                output_rows.append(("Output Path", "System Shared", False))
            output_rows.append(("Note", "Final hardware depth is managed by audio server", False))

        # Source vs Output compare.
        source_pair = f"{sample_rate} / {bit_depth}"
        output_pair = f"{output_rate} / {output_depth}"
        is_match = (
            self.player.output_state == "active"
            and is_exclusive
            and sample_rate != "Unknown"
            and bit_depth != "Unknown"
            and output_rate == sample_rate
            and output_depth == bit_depth
        )
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
        fmt = self.player.stream_info.get("fmt_str", "-")
        sample_rate = "Unknown"
        bit_depth = "Unknown"
        if "|" in fmt:
            parts = fmt.split("|")
            sample_rate = parts[0].strip()
            bit_depth = parts[1].strip()

        output_rate = sample_rate if exclusive else "Server Controlled"
        output_depth = bit_depth if exclusive else "16/32 bit (Float)"
        format_match = (
            state == "active"
            and exclusive
            and sample_rate != "Unknown"
            and bit_depth != "Unknown"
            and output_rate == sample_rate
            and output_depth == bit_depth
        )

        verdict_ok, reasons = self._compute_bitperfect_verdict(state)
        rows = [
            ("Bit-Perfect Verdict", "Yes" if verdict_ok else "No", verdict_ok),
            ("Format Match", "Yes" if format_match else "No", format_match),
            ("Bit-Perfect", "Yes" if bit_perfect else "No", bit_perfect),
            ("Exclusive", "Yes" if exclusive else "No", exclusive),
            ("Output State", state.capitalize(), state == "active"),
        ]
        if req_driver:
            target = f"{req_driver}" if not req_dev else f"{req_driver} / {req_dev}"
            rows.append(("Target Output", target, False))
        if err:
            rows.append(("Last Error", err, False))
        if not verdict_ok and reasons:
            rows.append(("Reasons", " | ".join(reasons), False))
        fixes = self._build_fix_suggestions(state, sample_rate, bit_depth)
        if fixes:
            rows.append(("How to Fix", " | ".join(fixes), False))

        for key, value, ok in rows:
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
            lbl_key = Gtk.Label(label=key, xalign=0, css_classes=["dim-label"])
            lbl_val = Gtk.Label(label=value, xalign=1, hexpand=True, css_classes=["stat-value"])
            lbl_val.set_wrap(True)
            if ok:
                lbl_val.add_css_class("success-text")
            row.append(lbl_key)
            row.append(lbl_val)
            self.summary_rows.append(row)

    def _compute_bitperfect_verdict(self, output_state):
        reasons = []
        if not self.player.bit_perfect_mode:
            reasons.append("Bit-Perfect mode disabled")
        if not self.player.exclusive_lock_mode:
            reasons.append("Not in exclusive mode")
        driver = self.app.settings.get("driver", "Auto")
        if driver != "ALSA":
            reasons.append(f"Driver is {driver}")
        if output_state in ("fallback", "error"):
            reasons.append(f"Output state is {output_state}")
        return (len(reasons) == 0), reasons

    def _build_diagnostics_text(self):
        info = self.player.stream_info
        fmt = info.get("fmt_str", "-")
        codec = info.get("codec", "-")
        bitrate = info.get("bitrate", 0)
        state = getattr(self.player, "output_state", "idle")
        err = getattr(self.player, "output_error", None)
        driver = self.app.settings.get("driver", "Auto")
        dev = getattr(self.app, "current_device_name", "Default")
        verdict_ok, reasons = self._compute_bitperfect_verdict(state)
        sample_rate = "Unknown"
        bit_depth = "Unknown"
        if "|" in fmt:
            parts = fmt.split("|")
            sample_rate = parts[0].strip()
            bit_depth = parts[1].strip()
        output_rate = sample_rate if self.player.exclusive_lock_mode else "Server Controlled"
        output_depth = bit_depth if self.player.exclusive_lock_mode else "16/32 bit (Float)"
        format_match = (
            state == "active"
            and self.player.exclusive_lock_mode
            and sample_rate != "Unknown"
            and bit_depth != "Unknown"
            and output_rate == sample_rate
            and output_depth == bit_depth
        )

        lines = [
            f"Bit-Perfect Verdict: {'Yes' if verdict_ok else 'No'}",
            f"Format Match: {'Yes' if format_match else 'No'}",
            f"Bit-Perfect Mode: {'On' if self.player.bit_perfect_mode else 'Off'}",
            f"Exclusive Mode: {'On' if self.player.exclusive_lock_mode else 'Off'}",
            f"Driver: {driver}",
            f"Device: {dev}",
            f"Output State: {state}",
            f"Source Codec: {codec}",
            f"Source Format: {fmt}",
            f"Source Bitrate: {bitrate // 1000 if bitrate else 0} kbps",
        ]
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
        driver = self.app.settings.get("driver", "Auto")
        if driver != "ALSA":
            suggestions.append("Switch driver to ALSA")
        if not self.player.bit_perfect_mode:
            suggestions.append("Enable Bit-Perfect mode")
        if not self.player.exclusive_lock_mode:
            suggestions.append("Enable Exclusive mode")
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
