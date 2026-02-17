# ui_config.py

SIDEBAR_RATIO = 0.20  # <--- 修改这里：30% 宽度
VOLUME_RATIO  = 0.10 
SIDEBAR_MIN_WIDTH = 260 # 稍微调宽一点最小宽度
VOLUME_MIN_WIDTH = 150 
WINDOW_WIDTH = 1100
WINDOW_HEIGHT = 800
# ui_config.py

# ... 前面的变量定义保持不变 ...
# ui_config.py

# ... 前面的变量保持不变 ...
# --- ui_config.py ---

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
    background: rgba(10, 10, 10, 0.8);
    border-top: 1px solid rgba(255, 255, 255, 0.2);
    padding: 10px;
    border-radius: 12px;
    margin: 0px 35px 1px 35px;
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

    /* 2. 按钮本体 - 核心去背景 */
    .mini-switcher button {
        /* [关键] 必须清除 background-image，否则会有灰色渐变 */

        border: 1px solid alpha(currentColor, 0.1);
        box-shadow: none;
        text-shadow: none; /* 去掉文字阴影 */

        /* 尺寸与字体 */
        min-height: 22px;
        min-width: 0;
        padding: 2px 12px;
        margin-right: 5px; /* 独立胶囊间距 */

        font-weight: 800;
        font-size: 11px;
        color: rgba(255, 255, 255, 0.4);
        transition: all 0.2s;
    }

    .mini-switcher button:first-child {
        border-radius: 12px 0 0 0;
    }

    /* 4. 右边按钮：只圆右边 */
    .mini-switcher button:last-child {
        border-radius: 0 12px 0 0;
    }

    /* 3. 防止窗口失去焦点时变灰 (Inspector 里显示你是 backdrop 状态) */
    .mini-switcher button:backdrop {
        background-image: none;
        background-color: transparent;
        color: rgba(255, 255, 255, 0.3);
    }

    /* 4. 选中状态 (Spectrum 被选中时) */
    .mini-switcher button:checked {
        background-color: rgba(255, 255, 255, 0.15); /* 只有这里有淡淡的背景 */
        background-image: none;
        color: white;
        box-shadow: none;
    }

    /* 选中状态但在后台时 */
    .mini-switcher button:checked:backdrop {
        background-color: rgba(255, 255, 255, 0.15);
        color: white;
    }

    /* 5. 鼠标悬停 */
    .mini-switcher button:hover {
        background-color: rgba(255, 255, 255, 0.08);
        background-image: none;
        color: white;
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
    background: rgba(10, 10, 10, 0.98);  /* <--- 试着把这里改成 0.6 或 0.5 */
    border-top: 1px solid rgba(255, 255, 255, 0.2);
    border-top: 1px solid rgba(255, 255, 255, 0.15);
    border-bottom: 1px solid rgba(0, 0, 0, 0.3);

    /* 3. 玻璃内发光/阴影：增加立体感，不让它看起来像一张纸 */
    /* inset 0 0 20px 意味着在内部有一圈淡淡的黑晕 */
    box-shadow: inset 0 0 20px rgba(0, 0, 0, 0.2);

    padding: 10px;
    border-radius: 0px 12px 0 0;
    margin: 0px 32px 0px 32px;
    }

    .lyrics-scroller { background: transparent; }
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

/* 其他样式保持不变... */
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
.pill { margin: 10px; padding: 10px; min-width: 25px; min-height: 25px; border-radius: 99px; }
flowboxchild { background-color: transparent; padding: 0; margin: 0; }
.card { background-color: transparent; border: none; box-shadow: none; padding: 8px; min-width: 130px; transition: background-color 0.2s; }
.card:hover { background-color: alpha(currentColor, 0.06); }
.card:hover label { color: @accent_color; }
.album-cover-img { border-radius: 8px; -gtk-icon-transform: scale(1);}
.header-art { border-radius: 12px; }
.album-header-box { padding: 32px; margin-bottom: 10px; }
.album-title-large { font-size: 28px; font-weight: 800; margin-bottom: 4px; }
.album-artist-medium { font-size: 16px; font-weight: 600; color: @accent_color; margin-bottom: 8px; }
.album-meta { font-size: 13px; opacity: 0.7; }
.heart-btn { background: transparent; box-shadow: none; border: none; padding: 12px; min-width: 64px; min-height: 64px; border-radius: 99px; color: alpha(currentColor, 0.3); transition: all 0.3s; }
.heart-btn image { -gtk-icon-size: 32px; }
.heart-btn:hover { color: alpha(currentColor, 0.6); background-color: alpha(currentColor, 0.05); transform: scale(1.1); }
.heart-btn.active { color: #e91e63; opacity: 1; }
.section-title { font-size: 20px; font-weight: 700; margin: 12px; }
.tech-label { font-family: "Monospace"; font-size: 10px; font-weight: bold; color: @accent_color; background-color: alpha(@accent_bg_color, 0.12); padding: 3px; border-radius: 4px; margin-top: 0; }
.settings-container { padding: 40px; }
.settings-group { background-color: alpha(currentColor, 0.05); border-radius: 12px; padding: 6px; margin-bottom: 24px; }
.settings-row { padding: 12px 16px; border-bottom: 1px solid alpha(currentColor, 0.05); }
.settings-label { font-weight: 600; }
.player-title { font-size: 14px; font-weight: 800; margin-bottom: 10px; }
.player-artist { color: @accent_color; font-weight: 600; font-size: 12px; margin-bottom: 5px; }
.player-album { color: alpha(currentColor, 0.5); font-size: 12px; }
.bp-text-glow { color: #489A54; font-size: 10px; letter-spacing: 1px; margin-right: 3px; text-shadow: 0 0 2px alpha(#FFD700, 0.6), 0 0 5px alpha(#FFD700, 0.3); }
.signal-card { background-color: alpha(currentColor, 0.05); border-radius: 12px; padding: 16px; margin: 0 8px; border: 1px solid alpha(currentColor, 0.08); }
.signal-icon { color: @accent_color; -gtk-icon-size: 24px; }
.signal-connector { color: alpha(currentColor, 0.2); font-size: 24px; font-weight: 800; margin: -4px 0; }
.stat-value { font-family: "Monospace"; font-weight: bold; font-size: 13px; }
.success-text { color: #26a269; }
"""
