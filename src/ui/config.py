SIDEBAR_RATIO = 0.15
VOLUME_RATIO  = 0.10 
SIDEBAR_MIN_WIDTH = 260
VOLUME_MIN_WIDTH = 150 
WINDOW_WIDTH = 1250
WINDOW_HEIGHT = 800

CSS_DATA = """
.circular-avatar { border-radius: 9999px; }
button.flat,
button.circular {
    min-height: 28px;
}

/* 侧边栏基础样式 */
.sidebar-header { font-size: 13px; font-weight: 800; opacity: 0.5; margin: 16px 12px 8px 12px; text-transform: uppercase; letter-spacing: 1px; }
.sidebar-row { padding: 8px 12px; border-radius: 6px; margin: 0 4px; }
.sidebar-row:hover { background-color: alpha(currentColor, 0.08); }
.sidebar-row:selected { background-color: alpha(@accent_bg_color, 0.8); color: white; }
.sidebar-group-row,
.sidebar-group-row:hover,
.sidebar-group-row:selected {
    background: transparent;
    background-color: transparent;
    box-shadow: none;
}

/* 核心播放栏样式 */
.card-bar { 
    background-color: @headerbar_bg_color;
    border-top: 1px solid alpha(currentColor, 0.12); 
    padding: 5px 16px; 
    margin: 0px 25px 25px 25px;
    border-radius: 12px;
    border: 1px solid alpha(currentColor, 0.1);
    transition: all 0.3s cubic-bezier(0.25, 0.8, 0.25, 1);
}

.card-bar.mini-state {
    margin: 0;       
    padding: 20px 0px 20px 20px;
    border-radius: 0;
    border: none;    
    background-color: @headerbar_bg_color;
}

/* 波形面板黑框 */
.viz-panel {
    background: rgba(10, 10, 10, 0.98);
    background-color: rgba(10, 10, 10, 0.98);
    background-image: none;
    border-top: 1px solid rgba(255, 255, 255, 0.2);
    padding: 14px;
    border-radius: 12px;
    margin: 0px 35px 1px 35px;
}

.viz-panel-dark {
    background-color: rgba(10, 10, 10, 0.98);
    background-image: none;
}

.viz-panel-light {
    background-color: rgba(246, 248, 251, 0.98);
    background-image: none;
    border-top: 1px solid rgba(20, 24, 32, 0.12);
    border-bottom: 1px solid rgba(20, 24, 32, 0.10);
}

.viz-theme-row {
    margin-bottom: 0;
}

.viz-right-controls {
    border-spacing: 0;
}

.dsp-workspace {
    min-height: 0;
}

.dsp-workspace-switcher {
    margin-bottom: 4px;
}

.dsp-workspace-switcher,
.dsp-workspace-switcher > box {
    background: none;
    background-color: transparent;
    box-shadow: none;
    padding: 0;
}

.dsp-workspace-switcher button {
    min-height: 32px;
    min-width: 0;
    padding: 5px 10px 7px 10px;
    margin-right: 14px;
    border-radius: 0;
    border: none;
    border-bottom: 2px solid transparent;
    background-image: none;
    background-color: transparent;
    box-shadow: none;
    text-shadow: none;
    color: rgba(245, 248, 252, 0.70);
    font-size: 12px;
    font-weight: 800;
}

.dsp-workspace-switcher button:last-child {
    margin-right: 0;
}

.dsp-workspace-switcher button:hover {
    background-color: transparent;
    color: rgba(255, 255, 255, 0.94);
}

.dsp-workspace-switcher button:checked {
    background-color: transparent;
    border-bottom-color: alpha(@accent_bg_color, 0.95);
    color: alpha(@accent_fg_color, 0.98);
}

.dsp-workspace-switcher button:backdrop {
    background-image: none;
}

.viz-surface-light .dsp-workspace-switcher button {
    background-color: transparent;
    color: rgba(18, 22, 30, 0.68);
}

.viz-surface-light .dsp-workspace-switcher button:hover {
    background-color: transparent;
    color: rgba(18, 22, 30, 0.94);
}

.viz-surface-light .dsp-workspace-switcher button:checked {
    background-color: transparent;
    border-bottom-color: alpha(@accent_bg_color, 0.90);
    color: rgba(18, 22, 30, 0.98);
}

.dsp-sidebar {
    min-width: 250px;
}

.dsp-master-card,
.dsp-detail-card,
.dsp-module-list row {
    border-radius: 12px;
}

.dsp-master-card,
.dsp-detail-card {
    padding: 16px;
}

.dsp-master-card,
.dsp-detail-card,
.dsp-module-list row {
    background-color: alpha(white, 0.04);
    border: 1px solid alpha(white, 0.08);
}

.viz-surface-light .dsp-master-card,
.viz-surface-light .dsp-detail-card,
.viz-surface-light .dsp-module-list row {
    background-color: rgba(255, 255, 255, 0.88);
    border-color: rgba(24, 28, 36, 0.08);
}

.dsp-module-list {
    background: transparent;
}

.dsp-module-list row:selected {
    background-color: alpha(@accent_bg_color, 0.18);
    border-color: alpha(@accent_bg_color, 0.35);
}

.dsp-chain-card {
    background-color: rgba(10, 14, 24, 0.88);
    background-image:
        radial-gradient(circle at 20% 18%, rgba(90, 150, 255, 0.05) 0%, rgba(90, 150, 255, 0.00) 26%),
        linear-gradient(180deg, rgba(26, 34, 54, 0.36) 0%, rgba(8, 12, 20, 0.90) 100%);
    border-color: rgba(150, 174, 220, 0.12);
    box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.03);
}

.viz-surface-light .dsp-chain-card {
    background-color: rgba(244, 248, 255, 0.94);
    background-image:
        radial-gradient(circle at 18% 16%, rgba(110, 170, 255, 0.08) 0%, rgba(110, 170, 255, 0.00) 24%),
        linear-gradient(180deg, rgba(255, 255, 255, 0.98) 0%, rgba(234, 241, 252, 0.92) 100%);
    border-color: rgba(90, 116, 156, 0.10);
}

.dsp-chain-button {
    min-width: 136px;
    min-height: 50px;
    padding: 0;
    border-radius: 10px;
    border: 1px solid rgba(154, 170, 208, 0.18);
    border-bottom: 1px solid rgba(214, 223, 245, 0.08);
    background-color: rgba(39, 43, 62, 0.95);
    background-image:
        linear-gradient(180deg, rgba(255, 255, 255, 0.035) 0%, rgba(255, 255, 255, 0.00) 28%),
        linear-gradient(
            180deg,
            rgba(70, 76, 100, 0.94) 0%,
            rgba(37, 41, 58, 0.98) 100%
        );
    box-shadow:
        inset 0 1px 0 rgba(255, 255, 255, 0.05),
        0 10px 22px rgba(0, 0, 0, 0.24),
        0 2px 6px rgba(0, 0, 0, 0.16);
}

.dsp-chain-button:hover {
    border-color: rgba(164, 184, 228, 0.26);
    border-bottom-color: rgba(214, 223, 245, 0.10);
    background-color: rgba(44, 49, 72, 0.98);
    background-image:
        linear-gradient(180deg, rgba(255, 255, 255, 0.06) 0%, rgba(255, 255, 255, 0.00) 30%),
        linear-gradient(
            180deg,
            rgba(78, 88, 116, 0.96) 0%,
            rgba(42, 47, 68, 0.99) 100%
        );
}

.viz-surface-light .dsp-chain-button {
    border-color: rgba(70, 92, 130, 0.12);
    border-bottom-color: rgba(70, 92, 130, 0.10);
    background-color: rgba(255, 255, 255, 0.98);
    background-image:
        linear-gradient(180deg, rgba(255, 255, 255, 0.86) 0%, rgba(255, 255, 255, 0.00) 28%),
        linear-gradient(
            180deg,
            rgba(246, 249, 255, 0.98) 0%,
            rgba(226, 233, 246, 0.96) 100%
        );
    box-shadow:
        inset 0 1px 0 rgba(255, 255, 255, 0.82),
        0 10px 22px rgba(36, 48, 74, 0.10),
        0 2px 6px rgba(36, 48, 74, 0.06);
}

.viz-surface-light .dsp-chain-button:hover {
    border-color: rgba(110, 134, 176, 0.20);
    border-bottom-color: rgba(70, 92, 130, 0.10);
    background-color: rgba(250, 252, 255, 0.99);
    background-image:
        linear-gradient(180deg, rgba(255, 255, 255, 0.92) 0%, rgba(255, 255, 255, 0.00) 30%),
        linear-gradient(
            180deg,
            rgba(250, 252, 255, 0.98) 0%,
            rgba(232, 239, 250, 0.98) 100%
        );
}

.dsp-chain-button-active {
    border-color: rgba(184, 198, 230, 0.20);
    border-bottom-color: rgba(214, 223, 245, 0.10);
}

.dsp-chain-button-inactive {
    border-color: rgba(124, 136, 166, 0.10);
    border-bottom-color: rgba(124, 136, 166, 0.26);
    background-image:
        linear-gradient(180deg, rgba(255, 255, 255, 0.03) 0%, rgba(255, 255, 255, 0.00) 28%),
        linear-gradient(
            180deg,
            rgba(64, 70, 94, 0.92) 0%,
            rgba(35, 39, 56, 0.98) 100%
        );
}

.dsp-chain-button-io {
    border-color: rgba(184, 198, 230, 0.20);
    border-bottom-color: rgba(214, 223, 245, 0.10);
}

.viz-surface-light .dsp-chain-button-active {
    border-color: rgba(110, 134, 176, 0.20);
    border-bottom-color: rgba(70, 92, 130, 0.10);
}

.viz-surface-light .dsp-chain-button-inactive {
    border-color: rgba(70, 84, 104, 0.12);
    border-bottom-color: rgba(120, 128, 144, 0.28);
    background-image:
        linear-gradient(180deg, rgba(255, 255, 255, 0.92) 0%, rgba(255, 255, 255, 0.00) 28%),
        linear-gradient(
            180deg,
            rgba(238, 242, 250, 0.98) 0%,
            rgba(224, 231, 244, 0.96) 100%
        );
}

.viz-surface-light .dsp-chain-button-io {
    border-color: rgba(110, 134, 176, 0.20);
    border-bottom-color: rgba(70, 92, 130, 0.10);
}

.dsp-chain-order,
.dsp-chain-state {
    font-weight: 800;
    letter-spacing: 0.04em;
}

.dsp-chain-title {
    min-height: 20px;
    font-size: 13px;
    font-weight: 800;
    letter-spacing: 0.02em;
    color: rgba(245, 248, 252, 0.96);
}

.dsp-chain-lamp {
    min-width: 16px;
    min-height: 8px;
    border-radius: 999px;
    background-color: rgba(152, 160, 184, 0.28);
    box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.08);
}

.dsp-chain-button-active .dsp-chain-lamp,
.dsp-chain-button-io .dsp-chain-lamp {
    background-color: @accent_bg_color;
    box-shadow:
        0 0 10px alpha(@accent_bg_color, 0.55),
        0 0 18px alpha(@accent_bg_color, 0.28);
}

.viz-surface-light .dsp-chain-lamp {
    background-color: rgba(126, 136, 160, 0.30);
}

.viz-surface-light .dsp-chain-button-active .dsp-chain-lamp,
.viz-surface-light .dsp-chain-button-io .dsp-chain-lamp {
    background-color: @accent_bg_color;
    box-shadow:
        0 0 10px alpha(@accent_bg_color, 0.34),
        0 0 16px alpha(@accent_bg_color, 0.16);
}

.dsp-chain-button-inactive .dsp-chain-title {
    color: rgba(226, 232, 245, 0.78);
}

.viz-surface-light .dsp-chain-title {
    color: rgba(18, 22, 30, 0.96);
}

.viz-surface-light .dsp-chain-button-inactive .dsp-chain-title {
    color: rgba(18, 22, 30, 0.66);
}

.dsp-chain-arrow {
    font-size: 26px;
    font-weight: 800;
    opacity: 0.72;
    color: rgba(132, 182, 255, 0.72);
}

.dsp-chain-connector {
    color: alpha(@accent_bg_color, 0.92);
}

.dsp-chain-connector-line {
    min-height: 1px;
    border-radius: 999px;
    background-color: alpha(@accent_bg_color, 0.72);
}

.dsp-chain-connector-line-vertical {
    min-width: 1px;
    min-height: 8px;
    border-radius: 999px;
    background-color: alpha(@accent_bg_color, 0.72);
}

.dsp-chain-connector-head {
    font-size: 9px;
    font-weight: 900;
    color: alpha(@accent_bg_color, 0.96);
    margin-top: -1px;
}

.viz-surface-light .dsp-chain-connector {
    color: alpha(@accent_bg_color, 0.88);
}

.viz-surface-light .dsp-chain-connector-line {
    background-color: alpha(@accent_bg_color, 0.64);
}

.viz-surface-light .dsp-chain-connector-line-vertical {
    background-color: alpha(@accent_bg_color, 0.64);
}

.viz-surface-light .dsp-chain-connector-head {
    color: alpha(@accent_bg_color, 0.90);
}

.dsp-chain-handle {
    opacity: 0.88;
    color: rgba(212, 220, 240, 0.82);
}

.viz-theme-dd {
    margin-right: 0;
}

.dsp-preset-dd button {
    border: 1px solid alpha(currentColor, 0.12);
    box-shadow: none;
    text-shadow: none;
    background-image: none;
    background-color: alpha(white, 0.04);
    min-height: 30px;
    min-width: 0;
    padding: 4px 12px;
    font-weight: 700;
    font-size: 12px;
    color: rgba(245, 248, 252, 0.90);
    border-radius: 10px;
}

.dsp-preset-dd button:hover {
    background-color: alpha(white, 0.08);
}

.viz-surface-light .dsp-preset-dd button {
    background-color: rgba(255, 255, 255, 0.92);
    border-color: rgba(24, 28, 36, 0.12);
    color: rgba(18, 22, 30, 0.92);
}

.viz-surface-light .dsp-preset-dd button:hover {
    background-color: rgba(244, 247, 251, 0.98);
}

.viz-toolbar-btn {
    min-width: 35px;
    min-height: 35px;
    padding: 0;
    margin-left: 0;
    border-radius: 0;
    background-color: rgba(34, 38, 48, 0.98);
    border: 1px solid rgba(255, 255, 255, 0.24);
    border-bottom: none;
    box-shadow: none;
    text-shadow: none;
    color: rgba(245, 248, 252, 0.88);
    font-weight: 800;
    font-size: 12px;
}

.viz-toolbar-btn:hover {
    background-color: rgba(50, 56, 70, 0.98);
    color: rgba(255, 255, 255, 0.98);
}

.viz-toolbar-btn.viz-right-last {
    border-radius: 0 12px 0 0;
}

.viz-toolbar-btn.viz-floating-corner-btn {
    border-radius: 12px 12px 0 0;
}

.viz-overlay-btn {
    min-width: 28px;
    min-height: 28px;
    padding: 0;
    border: none;
    border-radius: 10px;
    background: transparent;
    background-color: transparent;
    background-image: none;
    box-shadow: none;
    text-shadow: none;
    color: rgba(245, 248, 252, 0.88);
}

.viz-overlay-btn:hover {
    background-color: rgba(255, 255, 255, 0.08);
    color: rgba(255, 255, 255, 0.98);
}

.viz-surface-light .viz-overlay-btn {
    color: rgba(18, 22, 30, 0.86);
}

.viz-surface-light .viz-overlay-btn:hover {
    background-color: rgba(20, 24, 32, 0.06);
    color: rgba(18, 22, 30, 0.96);
}

.viz-surface-light .viz-toolbar-btn {
    color: rgba(18, 22, 30, 0.86);
    background-color: rgba(247, 249, 252, 0.98);
    border-color: rgba(30, 35, 45, 0.20);
}

.viz-surface-light .viz-toolbar-btn:hover {
    color: rgba(18, 22, 30, 0.96);
    background-color: rgba(233, 238, 246, 0.98);
}

.viz-right-last,
.lyrics-motion-dd {
    margin-right: 0;
}

.viz-surface-dark .mini-switcher button,
.viz-surface-dark .viz-theme-dd button {
    color: rgba(245, 248, 252, 0.88);
    background-color: rgba(34, 38, 48, 0.98);
    border-color: rgba(255, 255, 255, 0.24);
    opacity: 1;
}

.viz-surface-light .mini-switcher button,
.viz-surface-light .viz-theme-dd button {
    color: rgba(18, 22, 30, 0.86);
    background-color: rgba(247, 249, 252, 0.98);
    border-color: rgba(30, 35, 45, 0.20);
    opacity: 1;
}

.viz-surface-light .mini-switcher button:hover,
.viz-surface-light .viz-theme-dd button:hover {
    color: rgba(18, 22, 30, 0.96);
    background-color: rgba(233, 238, 246, 0.98);
}

.viz-surface-light .mini-switcher button:checked,
.viz-surface-light .viz-theme-dd button:checked {
    color: rgba(18, 22, 30, 0.98);
    background-color: rgba(219, 228, 242, 0.98);
}

.viz-surface-dark .mini-switcher button:hover,
.viz-surface-dark .viz-theme-dd button:hover {
    background-color: rgba(50, 56, 70, 0.98);
    color: rgba(255, 255, 255, 0.98);
}

.viz-surface-dark .mini-switcher button:checked,
.viz-surface-dark .viz-theme-dd button:checked {
    background-color: alpha(@accent_bg_color, 0.90);
    color: alpha(@accent_fg_color, 0.98);
}

.viz-handle-floating .viz-handle-btn {
    border-radius: 10px 10px 0 0;
    border: 1px solid rgba(255, 255, 255, 0.20);
    border-bottom: none;
    background-image: none;
    box-shadow: none;
    min-height: 23px;
    min-width: 50px;
    padding: 0;
}

.viz-handle-dark .viz-handle-btn {
    background-color: rgba(34, 38, 48, 0.98);
    color: rgba(245, 248, 252, 0.96);
}

.viz-handle-dark .viz-handle-btn:hover {
    background-color: rgba(50, 56, 70, 0.98);
    color: white;
}

.viz-handle-dark .viz-handle-btn:active,
.viz-handle-dark .viz-handle-btn.active {
    background-color: rgba(50, 56, 70, 0.98);
    color: white;
}

.viz-handle-light .viz-handle-btn {
    background-color: rgba(247, 249, 252, 0.98);
    color: rgba(18, 22, 30, 0.96);
    border-color: rgba(30, 35, 45, 0.24);
}

.viz-handle-light .viz-handle-btn:hover {
    background-color: rgba(233, 238, 246, 0.98);
    color: rgba(12, 16, 24, 0.98);
}

.viz-handle-light .viz-handle-btn:active,
.viz-handle-light .viz-handle-btn.active {
    background-color: rgba(233, 238, 246, 0.98);
    color: rgba(12, 16, 24, 0.98);
}

.queue-backdrop {
    background-color: rgba(0, 0, 0, 0.14);
}

.queue-anchor .queue-handle-shell {
    border-radius: 12px 0 0 12px;
    border: 1px solid rgb(142, 150, 164);
    border-right: none;
    background-color: rgb(247, 249, 252);
    min-height: 50px;
}

.queue-anchor button.queue-handle-btn {
    border: none;
    background: transparent;
    background-image: none;
    box-shadow: none;
    min-width: 23px;
    min-height: 50px;
    padding: 0;
    color: rgba(18, 22, 30, 0.96);
}

.queue-anchor button.queue-handle-btn:backdrop,
.queue-anchor button.queue-handle-btn:hover,
.queue-anchor button.queue-handle-btn:active,
.queue-anchor button.queue-handle-btn.active {
    border: none;
    background: transparent;
    background-image: none;
    box-shadow: none;
}

.queue-anchor .queue-drawer {
    background-color: rgb(247, 249, 252);
    border: 1px solid rgb(142, 150, 164);
    border-right: none;
    border-radius: 12px 0 0 12px;
}

.queue-anchor .queue-drawer .home-section-title {
    font-weight: 800;
}

.queue-anchor .queue-drawer .home-section-count {
    border-radius: 999px;
    padding: 2px 8px;
}

.queue-anchor .queue-drawer-scroll,
.queue-anchor .queue-drawer-scroll viewport {
    background-color: rgb(247, 249, 252);
}

.queue-anchor .queue-drawer-list {
    background-color: rgb(247, 249, 252);
}

.queue-anchor .queue-drawer-list row {
    border-radius: 8px;
    margin: 2px 0;
    box-shadow: none;
}

.queue-anchor .queue-drawer-list row:hover {
    background-color: rgba(26, 33, 46, 0.08);
}

.queue-anchor .queue-drawer-list row:selected {
    background-color: rgba(26, 33, 46, 0.14);
}

.queue-handle-dark .queue-handle-shell {
    background-color: rgb(34, 38, 48);
    border-color: rgba(255, 255, 255, 0.24);
}

.queue-handle-dark button.queue-handle-btn {
    color: rgba(245, 248, 252, 0.96);
}

.queue-handle-dark button.queue-handle-btn:hover {
    color: white;
}

.queue-handle-dark .queue-drawer {
    background-color: @window_bg_color;
    border-color: rgba(255, 255, 255, 0.24);
}

.queue-handle-dark .queue-drawer-scroll,
.queue-handle-dark .queue-drawer-scroll viewport,
.queue-handle-dark .queue-drawer-list {
    background-color: @window_bg_color;
}

.queue-handle-dark .queue-drawer .home-section-title {
    color: rgba(245, 248, 252, 0.94);
}

.queue-handle-dark .queue-drawer .home-section-count {
    color: rgba(245, 248, 252, 0.88);
    background-color: rgba(255, 255, 255, 0.10);
}

.queue-handle-light .queue-handle-shell {
    background-color: rgb(247, 249, 252);
    border-color: rgb(142, 150, 164);
}

.queue-handle-light button.queue-handle-btn {
    color: rgba(18, 22, 30, 0.96);
}

.queue-handle-light button.queue-handle-btn:hover {
    color: rgba(12, 16, 24, 0.98);
}

.queue-handle-light .queue-drawer {
    background-color: rgb(247, 249, 252);
    border-color: rgb(142, 150, 164);
}

.queue-handle-light .queue-drawer .home-section-title {
    color: rgba(18, 22, 30, 0.94);
}

.queue-handle-light .queue-drawer .home-section-count {
    color: rgba(18, 22, 30, 0.82);
    background-color: rgba(26, 33, 46, 0.10);
}

.lyrics-theme-light .lyric-line {
    color: rgba(18, 22, 30, 0.62);
    text-shadow: none;
}

.lyrics-theme-light .lyric-line.active {
    color: rgba(12, 16, 24, 0.98);
    text-shadow: 0 0 10px rgba(255, 255, 255, 0.45);
}

/* ===================================
   Mini Switcher 独立胶囊版 (修复版)
   =================================== */

/* 1. 容器清理 */
    .mini-switcher,
    .mini-switcher > box {
        background: none;
        background-color: transparent;
        box-shadow: none;
        margin: 0 0 0px 0px;
        padding: 0;
    }

    /* 2. 按钮本体 */
    .mini-switcher button {
        border: 1px solid alpha(currentColor, 0.2);
        box-shadow: none;
        text-shadow: none; /* 去掉文字阴影 */
        background-image: none;
        background-color: rgba(34, 38, 48, 0.98);

        /* 尺寸与字体 */
        min-height: 28px;
        min-width: 0;
        padding: 3px 14px;
        margin-right: 4px;

        font-weight: 800;
        font-size: 12px;
        color: rgba(255, 255, 255, 0.88);
        opacity: 1;
        transition: all 0.2s;
        border-radius: 0;
        border-bottom: none;
    }

    .mini-switcher button:first-child {
        border-radius: 12px 0 0 0;
    }

    .mini-switcher button:last-child {
        border-radius: 0 12px 0 0;
        margin-right: 0;
    }

    /* 3. 防止窗口失去焦点时变灰 (Inspector 里显示你是 backdrop 状态) */
    .mini-switcher button:backdrop {
        background-image: none;
        background-color: rgba(34, 38, 48, 0.98);
        color: alpha(currentColor, 0.75);
    }

    /* 4. 选中状态 (Spectrum 被选中时) */
    .mini-switcher button:checked {
        background-color: alpha(@accent_bg_color, 0.90); /* 只有这里有淡淡的背景 */
        background-image: none;
        color: alpha(@accent_fg_color, 0.98);
        box-shadow: none;
    }

    /* 选中状态但在后台时 */
    .mini-switcher button:checked:backdrop {
        background-color: alpha(@accent_bg_color, 0.86);
        color: alpha(@accent_fg_color, 0.95);
    }

    /* 5. 鼠标悬停 */
    .mini-switcher button:hover {
        background-color: rgba(50, 56, 70, 0.98);
        background-image: none;
        color: alpha(currentColor, 0.98);
    }
    .viz-theme-dd button {
        border: 1px solid alpha(currentColor, 0.2);
        box-shadow: none;
        text-shadow: none;
        background-image: none;
        background-color: rgba(34, 38, 48, 0.98);
        min-height: 28px;
        min-width: 0;
        padding: 3px 8px;
        font-weight: 800;
        font-size: 12px;
        opacity: 1;
        transition: all 0.2s;
        border-radius: 0;
        border-bottom: none;
    }
    .viz-theme-dd button label {
        min-width: 0;
    }
    .viz-right-first button,
    .lyrics-font-dd button {
        border-radius: 12px 0 0 0;
    }
    .viz-right-last button {
        border-radius: 0 12px 0 0;
    }

    .viz-panel {
    /* rgba(红, 绿, 蓝, 透明度)
       最后一个数字控制透明度：范围是 0.0 到 1.0

       0.95 = 几乎不透明 (很深)
       0.8  = 默认值 (深色玻璃感)
       0.5  = 半透明
       0.2  = 非常透
       0.0  = 完全透明 (看不见背景，只有波形)
    */
    /* Theme-specific background is controlled by .viz-panel-dark / .viz-panel-light */
    background-image: none;
    border-top: 1px solid alpha(currentColor, 0.18);
    border-bottom: 1px solid rgba(0, 0, 0, 0.3);

    /* 3. 玻璃内发光/阴影：增加立体感，不让它看起来像一张纸 */
    /* inset 0 0 20px 意味着在内部有一圈淡淡的黑晕 */
    box-shadow: inset 0 0 20px rgba(0, 0, 0, 0.2);

    padding: 0px;
    border-radius: 0;
    margin: 0px 32px 0px 32px;
    }

    .lyrics-scroller {
        background: transparent;
        background-color: transparent;
        border-radius: 0;
    }

    /* Box 也要透明 */
    .lyrics-scroller > box,
    .lyrics-scroller viewport {
        background: transparent;
        border-radius: 0;
    }
    .lyric-line {
        font-size: 16px; 
        font-weight: 200; 
        color: rgba(255, 255, 255, 0.35);
        margin-bottom: 0px; 
        padding: 4px 10px; 
        transition: all 0.4s cubic-bezier(0.25, 0.8, 0.25, 1);
    }
    .lyric-line.active {
        font-size: 20px; font-weight: 800; color: #ffffff; opacity: 1;
        margin-bottom: 24px; margin-top: 8px; text-shadow: 0 0 15px rgba(255, 255, 255, 0.2);
    }

window.undecorated { background-color: transparent; }
.player-overlay-container { background-color: transparent; }
.card-bar.mini-state .player-ctrls-box { margin-top: 12px; margin-right: 20px; border-spacing: 15px; }
.card-bar.mini-state .player-ctrls-box button.flat { min-height: 28px; min-width: 28px; padding: 0; color: alpha(currentColor, 0.7); background: transparent; }
.card-bar.mini-state .player-ctrls-box .pill { min-height: 42px; min-width: 42px; padding: 0; background-color: @accent_color; color: white; border-radius: 99px; box-shadow: 0 2px 5px alpha(black, 0.2); }
.card-bar.mini-state .player-ctrls-box .pill:hover { filter: brightness(1.1); transform: scale(1.05); }
.card-bar.mini-state .player-ctrls-box button image { -gtk-icon-size: 16px; }
.card-bar.mini-state .player-ctrls-box .pill image { -gtk-icon-size: 20px; }
.eq-btn image { -gtk-icon-size: 24px; }
.eq-btn { min-width: 36px; min-height: 36px; padding: 0; }
.card-bar scale.horizontal { margin: 0; padding: 0; }
.card-bar scale trough { min-height: 4px; }
.player-ctrls-box .transport-main-btn {
    min-width: 40px;
    min-height: 40px;
    margin: 0;
    padding: 0;
    border-radius: 999px;
    border: none;
    background-image: none;
    background-color: @accent_bg_color;
    color: @accent_fg_color;
    box-shadow: none;
}
.player-ctrls-box .transport-main-btn:hover {
    background-image: none;
    background-color: shade(@accent_bg_color, 1.08);
}
.player-ctrls-box .transport-main-btn:active {
    background-image: none;
    background-color: shade(@accent_bg_color, 0.92);
}
.player-ctrls-box .transport-main-btn image {
    -gtk-icon-size: 18px;
}
.pill { margin: 10px; padding: 10px; min-width: 28px; min-height: 28px; border-radius: 99px; }
flowboxchild { background-color: transparent; padding: 0; margin: 0; }
.card { background-color: transparent; border: none; box-shadow: none; padding: 8px; min-width: 130px; transition: background-color 0.2s; }
.home-feed-card { padding: 6px 0; min-width: 0; border-radius: 12px; transition: background-color 0.2s; }
.home-feed-btn { padding: 0; min-width: 0; min-height: 0; background: transparent; box-shadow: none; }
.home-feed-media { transition: filter 0.2s; }
.home-feed-tint { background-color: transparent; transition: background-color 0.2s; }
.playlist-folder-shape { border-radius: 16px; }
.home-feed-btn:hover,
.home-feed-btn:active,
.home-feed-btn:checked {
    background: transparent;
    background-color: transparent;
    box-shadow: none;
}
.home-feed-btn:hover .home-feed-card,
.home-feed-btn:active .home-feed-card,
.home-feed-btn:checked .home-feed-card {
    background-color: alpha(currentColor, 0.06);
}
.home-feed-btn:hover .home-feed-tint,
.home-feed-btn:active .home-feed-tint,
.home-feed-btn:checked .home-feed-tint,
.card:hover .home-feed-tint {
    background-color: alpha(@accent_bg_color, 0.16);
}
.home-feed-btn:hover label,
.home-feed-btn:active label,
.home-feed-btn:checked label {
    color: @accent_color;
}
.card:hover { background-color: alpha(currentColor, 0.06); }
.card:hover label { color: @accent_color; }
.artist-feed-card:hover { background-color: transparent; }
.history-card-btn .card:hover { background-color: transparent; }
.playlist-folder-cover {
    min-width: 130px;
    min-height: 130px;
    border-radius: 16px;
    border: 1px solid alpha(currentColor, 0.14);
    background:
        linear-gradient(160deg, alpha(@accent_bg_color, 0.22), alpha(@accent_bg_color, 0.06)),
        linear-gradient(0deg, alpha(currentColor, 0.05), alpha(currentColor, 0.05));
    box-shadow: inset 0 1px 0 alpha(white, 0.04);
    padding: 4px;
}
.playlist-folder-collage {
    min-width: 120px;
    min-height: 120px;
}
.playlist-folder-cell {
    border-radius: 10px;
    background-color: alpha(currentColor, 0.06);
}
.playlist-folder-preview-img {
    border-radius: 10px;
}
.playlist-folder-badge {
    min-width: 16px;
    padding: 1px 6px;
    border-radius: 999px;
    font-size: 10px;
    font-weight: 700;
    color: alpha(currentColor, 0.92);
    background-color: alpha(currentColor, 0.62);
}
.history-scroll-btn {
    min-width: 28px;
    min-height: 28px;
    padding: 2px;
}
.history-card-btn {
    min-height: 28px;
    padding: 0;
}
.dashboard-track-row-btn {
    background: transparent;
    background-color: transparent;
    box-shadow: none;
}
.dashboard-track-row-btn:hover,
.dashboard-track-row-btn:active,
.dashboard-track-row-btn:checked {
    background: transparent;
    background-color: transparent;
    box-shadow: none;
}
.dashboard-track-row-btn:hover .home-feed-tint,
.dashboard-track-row-btn:active .home-feed-tint,
.dashboard-track-row-btn:checked .home-feed-tint {
    background-color: alpha(@accent_bg_color, 0.16);
}
.dashboard-track-row-btn:hover .home-card-title,
.dashboard-track-row-btn:active .home-card-title,
.dashboard-track-row-btn:checked .home-card-title,
.dashboard-track-row-btn:hover .home-card-subtitle,
.dashboard-track-row-btn:active .home-card-subtitle,
.dashboard-track-row-btn:checked .home-card-subtitle {
    color: @accent_color;
}
.history-card-btn.track-row-playing {
    border-radius: 10px;
    background-color: alpha(@accent_bg_color, 0.16);
}
.history-card-btn.track-row-playing:hover {
    background-color: alpha(@accent_bg_color, 0.22);
}
.track-row-playing-icon {
    color: @accent_bg_color;
    margin-right: 4px;
}
.home-scroll-btn,
.playlist-tool-btn,
.player-side-btn,
.transport-btn {
    min-width: 28px;
    min-height: 28px;
    padding: 2px;
}
.player-side-btn.eq-btn image {
    -gtk-icon-size: 20px;
}
.album-cover-img { border-radius: 8px; -gtk-icon-transform: scale(1);}
.header-art { border-radius: 12px; }
.album-header-box { padding: 32px 6px 32px 32px; margin-bottom: 10px; }
.album-title-large { font-size: 28px; font-weight: 800; margin-bottom: 4px; }
.album-artist-medium { font-size: 16px; font-weight: 600; color: @accent_color; margin-bottom: 8px; }
.album-meta { font-size: 13px; opacity: 0.7; }
.artist-detail-hero {
    margin: 0 0 18px 0;
}
.artist-detail-hero-image,
.artist-detail-hero-scrim {
    border-radius: 0;
}
.artist-detail-hero-strip,
.artist-detail-hero-panel,
.artist-detail-hero-side-image,
.artist-detail-hero-center-image,
.artist-detail-hero-side-dim,
.artist-detail-hero-center-fade {
    border-radius: 0;
}
.artist-detail-hero-side-image {
    opacity: 0.72;
}
.artist-detail-hero-side-dim {
    background-image:
        linear-gradient(90deg, alpha(black, 0.48), alpha(black, 0.34));
}
.artist-detail-hero-center-image {
    opacity: 1.0;
}
.artist-detail-hero-center-fade {
    background-image:
        linear-gradient(90deg,
            alpha(black, 0.20) 0%,
            transparent 12%,
            transparent 88%,
            alpha(black, 0.20) 100%);
}
.artist-detail-hero-scrim {
    background-image:
        linear-gradient(180deg, alpha(black, 0.18), alpha(black, 0.42) 42%, alpha(black, 0.68) 100%);
}
.artist-detail-hero-top {
    padding: 0 18px 18px 18px;
}
.artist-detail-fav-btn {
    min-width: 38px;
    min-height: 38px;
    padding: 0;
    border-radius: 999px;
    border: 1px solid alpha(white, 0.12);
    background-color: alpha(black, 0.28);
    color: alpha(white, 0.96);
}
.artist-detail-fav-btn:hover {
    background-color: alpha(black, 0.36);
}
.artist-detail-fav-btn.active {
    color: #ff3f7f;
}
.artist-detail-hero-content {
    padding: 28px;
}
.artist-detail-kicker {
    font-size: 12px;
    font-weight: 800;
    letter-spacing: 0.08em;
    color: alpha(white, 0.84);
    text-transform: uppercase;
    text-shadow: 0 2px 12px alpha(black, 0.38);
}
.artist-detail-title {
    font-size: 34px;
    font-weight: 900;
    color: white;
    text-shadow: 0 3px 18px alpha(black, 0.42);
}
.artist-detail-meta {
    font-size: 14px;
    font-weight: 600;
    color: alpha(white, 0.82);
    text-shadow: 0 2px 12px alpha(black, 0.36);
}
.artist-detail-section {
    margin-bottom: 12px;
}
.home-subtitle,
.album-artist-medium,
.album-meta,
.home-card-title,
.home-card-subtitle,
.home-section-subtitle {
    padding-top: 1px;
    padding-bottom: 1px;
}
.home-section-title-btn {
    padding: 0;
    min-height: 0;
    min-width: 0;
    background: transparent;
    box-shadow: none;
    border-radius: 4px;
}
.home-section-title-btn:hover,
.home-section-title-btn:active {
    background: transparent;
    box-shadow: none;
}
.home-section-title-btn:hover .home-section-title-link {
    text-decoration: underline;
}
.history-rank-badge {
    min-width: 20px;
    padding: 2px 8px;
    border-radius: 999px;
    font-size: 12px;
    font-weight: 700;
    color: alpha(currentColor, 0.92);
    background-color: alpha(currentColor, 0.16);
}
.history-rank-chip {
    min-width: 24px;
    min-height: 24px;
    padding: 0;
    border-radius: 999px;
    font-size: 9px;
    font-weight: 800;
    color: alpha(currentColor, 0.95);
    background-color: alpha(currentColor, 0.14);
}
.history-rank-top1 {
    color: #1f1f1f;
    background-color: #ffd54f;
}
.history-rank-top2 {
    color: #1f1f1f;
    background-color: #cfd8dc;
}
.history-rank-top3 {
    color: #1f1f1f;
    background-color: #ffcc80;
}
.history-play-count-badge {
    padding: 2px 8px;
    border-radius: 999px;
    font-size: 11px;
    font-weight: 600;
    color: alpha(currentColor, 0.82);
    background-color: alpha(currentColor, 0.10);
}
.heart-btn { background: transparent; box-shadow: none; border: none; padding: 12px; min-width: 64px; min-height: 64px; border-radius: 99px; color: alpha(currentColor, 0.3); transition: all 0.3s; }
.heart-btn image { -gtk-icon-size: 32px; }
.heart-btn:hover { color: alpha(currentColor, 0.6); background-color: alpha(currentColor, 0.05); transform: scale(1.1); }
.heart-btn.active { color: #e91e63; opacity: 1; }

.now-playing-shell {
    background: none;
    background-color: transparent;
}
.now-playing-surface {
    border-radius: 24px 24px 0 0;
    border: 1px solid alpha(currentColor, 0.08);
    background-color: black;
    background-image:
        linear-gradient(145deg, alpha(@accent_bg_color, 0.14), transparent 32%);
    box-shadow: 0 18px 42px alpha(black, 0.20);
    padding: 0;
}
.now-playing-layout {
    min-height: 0;
}
.now-playing-left {
    min-width: 0;
    border-radius: 24px 0 0 0;
    border: none;
    background-color: transparent;
}
.now-playing-right {
    min-width: 0;
    border-radius: 0 24px 0 0;
    background: transparent;
}
.now-playing-cover {
    background: transparent;
}
.now-playing-left-scrim {
    border-radius: 24px 0 0 0;
}
.now-playing-left-top {
    min-width: 0;
}
.now-playing-kicker {
    font-size: 15px;
    font-weight: 800;
    color: alpha(white, 0.96);
    text-shadow: 0 2px 12px alpha(black, 0.30);
}
.now-playing-meta-panel {
    padding: 0 0 12px 0;
    min-width: 0;
}
.now-playing-info-card {
    background-color: rgba(0, 0, 0, 0.20);
    background-image: none;
    border: 1px solid alpha(white, 0.10);
    border-radius: 16px;
    box-shadow: none;
    padding: 20px;
}
.now-playing-title {
    font-size: 30px;
    font-weight: 800;
    line-height: 1.08;
    margin-top: 0;
    color: white;
    text-shadow: 0 2px 14px alpha(black, 0.30);
}
.now-playing-artist {
    font-size: 16px;
    font-weight: 700;
    color: #f1c76a;
    text-shadow: 0 2px 12px alpha(black, 0.30);
}
.now-playing-album {
    font-size: 13px;
    color: alpha(white, 0.78);
    text-shadow: 0 2px 12px alpha(black, 0.30);
}
.now-playing-tool-row {
    margin-top: 0;
    margin-bottom: 0;
}
.now-playing-tool-btn {
    min-width: 34px;
    min-height: 34px;
    padding: 0;
    border: 1px solid alpha(currentColor, 0.10);
    border-radius: 999px;
    background-image: none;
    background-color: alpha(currentColor, 0.10);
    box-shadow: none;
}
.now-playing-tool-btn:hover {
    background-image: none;
    background-color: alpha(currentColor, 0.14);
}
.now-playing-tool-btn:active {
    background-image: none;
    background-color: alpha(currentColor, 0.08);
}
.now-playing-tool-btn image {
    -gtk-icon-size: 18px;
}
.now-playing-track-fav-btn.active {
    color: #e91e63;
    opacity: 1;
}
.now-playing-tool-btn.eq-btn image {
    -gtk-icon-size: 20px;
}
.now-playing-progress-box {
    margin-top: 0;
}
.now-playing-progress-box label {
    color: alpha(white, 0.82);
}
.now-playing-progress trough {
    min-height: 6px;
    border-radius: 999px;
    background-color: alpha(white, 0.18);
}
.now-playing-progress progress {
    min-height: 6px;
    border-radius: 999px;
    background-color: #f1c76a;
}
.now-playing-controls {
    margin-top: 0;
}
.now-playing-controls .transport-btn {
    min-width: 42px;
    min-height: 42px;
    margin: 0;
    padding: 0;
}
.now-playing-controls .transport-btn image {
    -gtk-icon-size: 22px;
}
.now-playing-controls .transport-main-btn {
    min-width: 56px;
    min-height: 56px;
    margin: 0;
    padding: 0;
    border-radius: 999px;
    background-image: none;
    background-color: alpha(currentColor, 0.10);
    border: 1px solid alpha(currentColor, 0.10);
    box-shadow: none;
}
.now-playing-controls .transport-main-btn image {
    -gtk-icon-size: 26px;
}
.now-playing-collapse-btn {
    color: alpha(white, 0.75);
    min-width: 32px;
    min-height: 32px;
}
.now-playing-collapse-btn:hover {
    color: white;
    background-color: alpha(white, 0.12);
}
.now-playing-switcher {
    background: none;
    background-color: transparent;
    box-shadow: none;
    margin: -2px 0 0 0;
    padding: 0;
}
.now-playing-switcher > box {
    background: none;
    background-color: transparent;
    box-shadow: none;
    margin: 0;
    padding: 0;
}
.now-playing-switcher button {
    min-height: 32px;
    margin: 0;
    padding: 4px 16px;
    border: 1px solid alpha(currentColor, 0.10);
    border-radius: 0;
    background-image: none;
    background-color: alpha(currentColor, 0.10);
    box-shadow: none;
    text-shadow: none;
}
.now-playing-switcher button:first-child,
.now-playing-switcher button:last-child {
    border-radius: 0;
}
.now-playing-switcher button:first-child {
    border-radius: 0 0 0 14px;
}
.now-playing-switcher button:last-child {
    border-radius: 0 0 14px 0;
}
.now-playing-switcher button:checked {
    background-image: none;
    background-color: alpha(currentColor, 0.10);
    box-shadow: inset 0 -2px 0 alpha(white, 0.24);
}
.now-playing-switcher button:hover {
    background-image: none;
    background-color: alpha(currentColor, 0.14);
}
.now-playing-stack,
.now-playing-stack-page,
.now-playing-track-scroll,
.now-playing-track-scroll viewport {
    background: transparent;
    background-color: transparent;
    background-image: none;
    box-shadow: none;
    border: none;
}
.now-playing-list-shell {
    background: transparent;
    background-color: transparent;
    background-image: none;
    border: none;
    box-shadow: none;
    padding: 0;
}
.now-playing-list-shell .now-playing-track-scroll,
.now-playing-list-shell .now-playing-track-scroll viewport {
    background: transparent;
    background-color: transparent;
    background-image: none;
    border: none;
    box-shadow: none;
}
.now-playing-open-album-btn image {
    -gtk-icon-size: 18px;
}
.now-playing-lyrics-page {
    border-radius: 18px;
}
.now-playing-track-list row {
    border-radius: 14px;
}
.now-playing-track-row {
    margin-bottom: 2px;
}
.now-playing-lyrics-box {
    min-width: 0;
}

.track-heart-btn { background: transparent; box-shadow: none; border: none; padding: 2px; min-width: 18px; min-height: 18px; border-radius: 99px; color: alpha(currentColor, 0.36); transition: all 0.2s; }
.track-heart-btn image { -gtk-icon-size: 18px; }
.track-heart-btn:hover { color: alpha(currentColor, 0.7); background-color: alpha(currentColor, 0.05); transform: scale(1.06); }
.track-heart-btn.active { color: #e91e63; opacity: 1; }

.album-fav-btn { border-radius: 9999px; color: alpha(currentColor, 0.5); transition: all 0.2s; }
.album-fav-btn image { -gtk-icon-size: 28px; }
.album-fav-btn.active { color: #e91e63; }

.album-action-btns button {
    min-width: 50px;
    min-height: 50px;
    padding: 6px;
}
.album-action-btns button image {
    -gtk-icon-size: 24px;
}

.playlist-more-menu button {
    padding: 12px 16px;
    min-height: 0;
}
.playlist-more-menu button image {
    -gtk-icon-size: 16px;
}

.player-heart-btn { background: transparent; box-shadow: none; border: none; padding: 2px; min-width: 24px; min-height: 24px; border-radius: 99px; color: alpha(currentColor, 0.34); margin-top: 0; transition: all 0.2s; }
.player-heart-btn image { -gtk-icon-size: 20px; }
.player-heart-btn:hover { color: alpha(currentColor, 0.7); background-color: alpha(currentColor, 0.05); transform: scale(1.05); }
.player-heart-btn.active { color: #e91e63; opacity: 1; }
.section-title { font-size: 20px; font-weight: 700; margin: 12px; }
.login-hero-card {
    background-color: alpha(currentColor, 0.045);
    border: 1px solid alpha(currentColor, 0.09);
    border-radius: 18px;
    padding: 22px;
}
.login-hero-icon { opacity: 0.78; margin-bottom: 6px; }
.login-hero-title { font-size: 20px; font-weight: 760; margin-bottom: 2px; }
.login-hero-subtitle { font-size: 13px; margin-bottom: 8px; }
.login-hero-btn { min-width: 220px; min-height: 46px; padding: 0 16px; }
.tech-label { font-family: "Monospace"; font-size: 10px; font-weight: bold; color: @accent_color; background-color: alpha(@accent_bg_color, 0.12); padding: 3px; border-radius: 4px; margin-top: 0; }
.settings-container { padding: 40px; }
.settings-group { background-color: alpha(currentColor, 0.05); border-radius: 12px; padding: 6px; margin-bottom: 24px; }
.settings-row { padding: 12px 16px; border-bottom: 1px solid alpha(currentColor, 0.05); }
.settings-label { font-weight: 600; }
.diag-chip {
    padding: 2px 8px;
    border-radius: 999px;
    font-size: 11px;
    font-weight: 700;
    background-color: alpha(currentColor, 0.10);
}
.status-idle {
    color: alpha(currentColor, 0.70);
}
.status-switching {
    color: #9a6700;
}
.status-active {
    color: #1a7f37;
}
.status-fallback {
    color: #b35900;
}
.status-error {
    color: #cf222e;
}
.player-title { font-size: 14px; font-weight: 800; margin-bottom: 10px; }
.player-artist { color: @accent_color; font-weight: 600; font-size: 12px; margin-bottom: 5px; }
.player-album { color: alpha(currentColor, 0.5); font-size: 12px; }
.bp-text-glow { color: #489A54; font-size: 10px; letter-spacing: 1px; margin-right: 3px; text-shadow: 0 0 2px alpha(#FFD700, 0.6), 0 0 5px alpha(#FFD700, 0.3); }
.signal-card { background-color: alpha(currentColor, 0.05); border-radius: 12px; padding: 16px; margin: 0 8px; border: 1px solid alpha(currentColor, 0.08); }
.signal-icon { color: @accent_color; -gtk-icon-size: 24px; }
.signal-connector { color: alpha(currentColor, 0.2); font-size: 24px; font-weight: 800; margin: -4px 0; }
.stat-value { font-family: "Monospace"; font-weight: bold; font-size: 13px; }
.success-text { color: #26a269; }
.warning-text { color: #f6d32d; }

/* Shortcut content style (keep system popover shell) */
.shortcuts-popover { min-width: 260px; }
.shortcuts-title { font-size: 18px; font-weight: 800; margin-bottom: 2px; }
.shortcuts-subtitle { font-size: 12px; color: alpha(currentColor, 0.72); margin-bottom: 6px; }
.shortcuts-list { margin-top: 0; }
.shortcuts-row {
    padding: 7px 8px;
    border-radius: 10px;
    border: 1px solid alpha(currentColor, 0.14);
    background-color: alpha(currentColor, 0.04);
}
.shortcuts-row:hover {
    background-color: alpha(currentColor, 0.07);
    border-color: alpha(@accent_bg_color, 0.40);
}
.shortcuts-action { font-size: 13px; font-weight: 600; }
.shortcuts-keycap {
    padding: 3px 7px;
    border-radius: 8px;
    border: 1px solid alpha(currentColor, 0.25);
    background-color: alpha(currentColor, 0.10);
    font-family: "Monospace";
    font-size: 12px;
    font-weight: 700;
}

.liked-action-btn {
    min-height: 28px;
    padding: 0 12px;
    border-radius: 999px;
    border: 1px solid alpha(currentColor, 0.24);
    background-color: alpha(currentColor, 0.04);
    color: alpha(currentColor, 0.90);
    box-shadow: none;
}

.liked-action-btn:hover {
    background-color: alpha(currentColor, 0.08);
    border-color: alpha(@accent_bg_color, 0.45);
}

.liked-action-btn:active {
    background-color: alpha(currentColor, 0.12);
}

.liked-action-btn-primary {
    min-height: 28px;
    padding: 0 12px;
    border-radius: 999px;
    background-color: alpha(@accent_bg_color, 0.20);
    border-color: alpha(@accent_bg_color, 0.58);
    color: @accent_fg_color;
}

.liked-action-btn-primary:hover {
    background-color: alpha(@accent_bg_color, 0.28);
    border-color: alpha(@accent_bg_color, 0.72);
}

.liked-artist-filter-scroll,
.liked-artist-filter-scroll viewport,
.liked-artist-filter-flow {
    background: transparent;
}

.genres-tabs-scroll,
.genres-tabs-scroll viewport,
.genres-tabs-scroll stackswitcher {
    background: transparent;
}

.genres-show-more-row {
    margin-top: 6px;
}

.genres-show-more-btn {
    min-height: 28px;
    padding: 0 12px;
    border-radius: 999px;
    background-color: alpha(@accent_bg_color, 0.12);
    border-color: alpha(@accent_bg_color, 0.34);
    box-shadow: none;
}

.genres-show-more-btn:hover {
    background-color: alpha(@accent_bg_color, 0.18);
    border-color: alpha(@accent_bg_color, 0.48);
}

.liked-artist-scroll-btn {
    min-width: 28px;
    min-height: 28px;
    padding: 2px 0;
    margin-top: 2px;
}

.liked-artist-filter-btn {
    border-radius: 10px;
    border: 1px solid transparent;
    padding: 4px 6px;
    box-shadow: none;
}

.liked-artist-filter-btn:hover {
    border-color: alpha(@accent_bg_color, 0.35);
    background-color: alpha(currentColor, 0.04);
}

.liked-artist-filter-btn.active {
    border-color: alpha(@accent_bg_color, 0.65);
    background-color: alpha(@accent_bg_color, 0.14);
}

.liked-artist-filter-img {
    min-width: 60px;
    min-height: 60px;
}

.liked-artist-filter-name {
    font-weight: 300;
}

.liked-artist-count-badge {
    min-width: 16px;
    padding: 1px 6px;
    border-radius: 999px;
    font-size: 10px;
    font-weight: 700;
    color: alpha(currentColor, 0.92);
    background-color: alpha(currentColor, 0.62);
    margin-right: 0;
    margin-bottom: 0;
}

/* Unified rounded list surfaces across list pages */
.tracks-list,
.boxed-list {
    background-color: alpha(currentColor, 0.04);
    border: 1px solid alpha(currentColor, 0.10);
    border-radius: 12px;
    padding: 6px;
}

.tracks-list.now-playing-track-list {
    background-image: none;
    background-color: rgba(24, 26, 34, 0.30);
    border: 1px solid alpha(currentColor, 0.10);
    border-radius: 18px;
    box-shadow: none;
    padding: 6px;
}

.tracks-list row,
.boxed-list row {
    border-radius: 10px;
    margin: 2px 0;
}

.tracks-list row:hover,
.boxed-list row:hover {
    background-color: alpha(currentColor, 0.06);
}

.search-suggest-popover {
    padding: 0;
}

.search-suggest-scroll,
.search-suggest-scroll viewport {
    background: transparent;
}

.search-suggest-content {
    min-width: 600px;
}

.search-suggest-title {
    font-size: 16px;
    font-weight: 800;
}

.search-suggest-chip {
    min-height: 42px;
    padding: 0 10px;
    border-radius: 14px;
    border: 1px solid alpha(currentColor, 0.16);
    background-image: none;
    background-color: alpha(currentColor, 0.10);
    box-shadow: none;
}

.search-suggest-chip:hover {
    border-color: alpha(@accent_bg_color, 0.50);
    background-color: alpha(@accent_bg_color, 0.20);
}

.search-suggest-chip:active {
    background-color: alpha(@accent_bg_color, 0.28);
}

.home-card-subtitle {
    font-weight: 300;
}

"""


def get_scale_css_overrides(font_scale: float) -> str:
    """Return additional CSS that enlarges text for low-DPI (1x) displays.

    At scale ≥ 2 GTK's HiDPI path already doubles every logical pixel, so the
    base sizes in CSS_DATA are correct.  At 1x we inject overrides so the same
    physical-size feel is preserved.

    font_scale is typically 1.4 at scale=1 and 1.0 at scale≥2.
    Returns an empty string when no override is needed (font_scale ≤ 1.05).
    """
    if font_scale <= 1.05:
        return ""

    def fs(px: int) -> str:
        return f"{round(px * font_scale)}px"

    return f"""
/* DPI-adaptive font overrides (font_scale={font_scale:.2f}) */
.sidebar-header {{ font-size: {fs(13)}; }}
.section-title {{ font-size: {fs(20)}; }}
.album-title-large {{ font-size: {fs(28)}; }}
.album-artist-medium {{ font-size: {fs(16)}; }}
.album-meta {{ font-size: {fs(13)}; }}
.player-title {{ font-size: {fs(14)}; }}
.player-artist {{ font-size: {fs(12)}; }}
.player-album {{ font-size: {fs(12)}; }}
.now-playing-kicker {{ font-size: {fs(15)}; }}
.shortcuts-title {{ font-size: {fs(18)}; }}
.shortcuts-subtitle {{ font-size: {fs(12)}; }}
.shortcuts-action {{ font-size: {fs(13)}; }}
.login-hero-title {{ font-size: {fs(20)}; }}
.login-hero-subtitle {{ font-size: {fs(13)}; }}
"""
