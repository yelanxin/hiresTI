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

CSS_DATA = """
.circular-avatar { border-radius: 9999px; }

/* 侧边栏基础样式 */
.sidebar-header { font-size: 13px; font-weight: 800; opacity: 0.5; margin: 16px 12px 8px 12px; text-transform: uppercase; letter-spacing: 1px; }
.sidebar-row { padding: 8px 12px; border-radius: 6px; margin: 0 4px; }
.sidebar-row:hover { background-color: alpha(currentColor, 0.08); }
.sidebar-row:selected { background-color: alpha(@accent_bg_color, 0.8); color: white; }

/* =================================================================== */
/* 核心播放栏样式修复 */
/* =================================================================== */

/* 1. 正常模式：悬浮、有边距、有圆角 */
.card-bar { 
    background-color: @headerbar_bg_color;
    border-top: 1px solid alpha(currentColor, 0.12); 
    padding: 5px 16px; 
    
    /* [正常模式] 四周有 25px 的悬浮空间 */
    margin: 0px 25px 25px 25px;
    
    border-radius: 12px;
    border: 1px solid alpha(currentColor, 0.1);
    transition: all 0.3s cubic-bezier(0.25, 0.8, 0.25, 1); /* 平滑过渡 */
}

/* 2. [迷你模式]：强制去边距、去圆角、填满 */
/* 注意：这里选择器是 .card-bar.mini-state，优先级很高 */
.card-bar.mini-state {
    margin: 0;       
    padding: 20px 0px 20px 20px;
    border-radius: 0;
    border: none;    
    background-color: @headerbar_bg_color;
}

/* 确保窗口背景透明，防止底下透出黑色 */
window.undecorated { background-color: transparent; }
.player-overlay-container { background-color: transparent; }

/* =================================================================== */

/* ================================================= */
/* Mini Mode 播放控件专属样式 */
/* ================================================= */

/* 1. 控制按钮容器的位置 (替代之前的 set_margin_top) */
.card-bar.mini-state .player-ctrls-box {
    margin-top: 12px;   /* 整体下移距离 */
    margin-right: 20px; /* 整体右移/左移微调 */
    border-spacing: 15px; /* 按钮之间的间距 (如果是 Box 可尝试此属性或 spacing) */
}

/* 2. 普通按钮 (上一首/下一首) 样式 */
.card-bar.mini-state .player-ctrls-box button.flat {
    min-height: 32px;  /* 按钮高度 */
    min-width: 32px;   /* 按钮宽度 */
    padding: 0;        /* 去掉内边距让它更紧凑 */
    color: alpha(currentColor, 0.7); /* 稍微调暗一点颜色 */
    background: transparent;
}

/* 3. 播放/暂停大按钮 (中间那个) 样式 */
.card-bar.mini-state .player-ctrls-box .pill {
    min-height: 42px;  /* 设置得比两边大一点 */
    min-width: 42px;
    padding: 0;
    background-color: @accent_color; /* 使用主题色 */
    color: white;      /* 图标白色 */
    border-radius: 99px; /* 圆形 */
    box-shadow: 0 2px 5px alpha(black, 0.2); /* 加点阴影更有质感 */
}
.card-bar.mini-state .player-ctrls-box .pill:hover {
    filter: brightness(1.1); /* 悬停变亮 */
    transform: scale(1.05);  /* 悬停微放大 */
}

/* 4. 控制图标的大小 */
.card-bar.mini-state .player-ctrls-box button image {
    -gtk-icon-size: 16px; /* 这里调整图标本身的大小 */
}
/* 单独放大播放按钮的图标 */
.card-bar.mini-state .player-ctrls-box .pill image {
    -gtk-icon-size: 20px;
}

/* 单独控制 EQ 按钮图标大小 */
.eq-btn image {
    -gtk-icon-size: 24px; /*在这里修改数值，默认通常是 16px */
}

/* 如果您想顺便调整按钮的内边距，让它看起来更大/更小 */
.eq-btn {
    min-width: 36px;
    min-height: 36px;
    padding: 0;
}

.viz-panel {
    background: rgba(10, 10, 10, 0.8);
    border-top: 1px solid rgba(255, 255, 255, 0.2);
    padding: 10px;
    border-radius: 12px 12px 0 0;
    margin: 0px 35px 1px 35px;
}

/* 其他通用样式 (保持不变) */
.card-bar scale.horizontal { margin: 0; padding: 0; }
.card-bar scale trough { min-height: 4px; }
.pill { margin: 10px; padding: 10px; min-width: 25px; min-height: 25px; border-radius: 99px; }
flowboxchild { background-color: transparent; padding: 0; margin: 0; }
.card { background-color: transparent; border: none; box-shadow: none; padding: 8px; min-width: 130px; transition: background-color 0.2s; }
.card:hover { background-color: alpha(currentColor, 0.06); }
.card:hover label { color: @accent_color; }
.album-cover-img { border-radius: 8px; }
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
