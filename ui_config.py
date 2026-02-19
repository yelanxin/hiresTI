SIDEBAR_RATIO = 0.20
VOLUME_RATIO  = 0.10 
SIDEBAR_MIN_WIDTH = 260
VOLUME_MIN_WIDTH = 150 
WINDOW_WIDTH = 1100
WINDOW_HEIGHT = 800

CSS_DATA = """
.circular-avatar { border-radius: 9999px; }

/* 侧边栏基础样式 */
.sidebar-header { font-size: 13px; font-weight: 800; opacity: 0.5; margin: 16px 12px 8px 12px; text-transform: uppercase; letter-spacing: 1px; }
.sidebar-row { padding: 8px 12px; border-radius: 6px; margin: 0 4px; }
.sidebar-row:hover { background-color: alpha(currentColor, 0.08); }
.sidebar-row:selected { background-color: alpha(@accent_bg_color, 0.8); color: white; }

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
    padding: 10px;
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

.viz-theme-dd {
    margin-right: 4px;
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
    min-height: 21px;
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
    min-width: 26px;
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

    /* 4. 右边按钮：只圆右边 */
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
        padding: 3px 14px;
        font-weight: 800;
        font-size: 12px;
        opacity: 1;
        transition: all 0.2s;
        border-radius: 0;
        border-bottom: none;
    }
    .viz-right-first button,
    .lyrics-font-dd button {
        border-radius: 12px 0 0 0;
    }
    .viz-right-last button,
    .lyrics-motion-dd button {
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
    }

    /* Box 也要透明 */
    .lyrics-scroller > box {
        background: transparent;
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
.card-bar.mini-state .player-ctrls-box button.flat { min-height: 32px; min-width: 32px; padding: 0; color: alpha(currentColor, 0.7); background: transparent; }
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
.pill { margin: 10px; padding: 10px; min-width: 25px; min-height: 25px; border-radius: 99px; }
flowboxchild { background-color: transparent; padding: 0; margin: 0; }
.card { background-color: transparent; border: none; box-shadow: none; padding: 8px; min-width: 130px; transition: background-color 0.2s; }
.card:hover { background-color: alpha(currentColor, 0.06); }
.card:hover label { color: @accent_color; }
.history-card-btn .card:hover { background-color: transparent; }
.album-cover-img { border-radius: 8px; -gtk-icon-transform: scale(1);}
.header-art { border-radius: 12px; }
.album-header-box { padding: 32px; margin-bottom: 10px; }
.album-title-large { font-size: 28px; font-weight: 800; margin-bottom: 4px; }
.album-artist-medium { font-size: 16px; font-weight: 600; color: @accent_color; margin-bottom: 8px; }
.album-meta { font-size: 13px; opacity: 0.7; }
.history-rank-badge {
    min-width: 20px;
    padding: 2px 8px;
    border-radius: 999px;
    font-size: 12px;
    font-weight: 700;
    color: alpha(currentColor, 0.92);
    background-color: alpha(currentColor, 0.16);
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

.track-heart-btn { background: transparent; box-shadow: none; border: none; padding: 2px; min-width: 18px; min-height: 18px; border-radius: 99px; color: alpha(currentColor, 0.36); transition: all 0.2s; }
.track-heart-btn image { -gtk-icon-size: 18px; }
.track-heart-btn:hover { color: alpha(currentColor, 0.7); background-color: alpha(currentColor, 0.05); transform: scale(1.06); }
.track-heart-btn.active { color: #e91e63; opacity: 1; }

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

/* Shortcut content style (keep system popover shell) */
.shortcuts-popover { min-width: 380px; }
.shortcuts-title { font-size: 18px; font-weight: 800; margin-bottom: 2px; }
.shortcuts-subtitle { font-size: 12px; color: alpha(currentColor, 0.72); margin-bottom: 10px; }
.shortcuts-list { margin-top: 2px; }
.shortcuts-row {
    padding: 10px 12px;
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
    padding: 4px 10px;
    border-radius: 8px;
    border: 1px solid alpha(currentColor, 0.25);
    background-color: alpha(currentColor, 0.10);
    font-family: "Monospace";
    font-size: 12px;
    font-weight: 700;
}

.liked-action-btn {
    min-height: 23px;
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

.liked-artist-scroll-btn {
    min-width: 28px;
    min-height: 28px;
    padding: 0;
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
    min-width: 54px;
    min-height: 54px;
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

"""
