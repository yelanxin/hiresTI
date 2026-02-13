# ui_config.py

SIDEBAR_RATIO = 0.20  # <--- 修改这里：30% 宽度
VOLUME_RATIO  = 0.10 
SIDEBAR_MIN_WIDTH = 260 # 稍微调宽一点最小宽度
VOLUME_MIN_WIDTH = 150 
WINDOW_WIDTH = 1100
WINDOW_HEIGHT = 800

CSS_DATA = """
.circular-avatar { border-radius: 9999px; }

/* 侧边栏样式 */
.sidebar-header {
    font-size: 13px;
    font-weight: 800;
    opacity: 0.5;
    margin: 16px 12px 8px 12px;
    text-transform: uppercase;
    letter-spacing: 1px;
}
.sidebar-row { padding: 8px 12px; border-radius: 6px; margin: 0 4px; }
.sidebar-row:hover { background-color: alpha(currentColor, 0.08); }
.sidebar-row:selected { background-color: alpha(@accent_bg_color, 0.8); color: white; }

/* 底部播放栏 */
.card-bar { 
    background-color: @headerbar_bg_color; 
    border-top: 1px solid alpha(currentColor, 0.12); 
    padding: 5px 16px; 
    /* 添加以下代码 */
    margin: 0px 25px 25px 25px;
    border-radius: 12px;  /* 既然悬浮了，加个圆角会更好看 */
    border: 1px solid alpha(currentColor, 0.1); /* 增加四周边缘线 */
}


.card-bar scale.horizontal {
    margin-top: 0;
    margin-bottom: 0;
    padding-top: 0;
    padding-bottom: 0;
}

.card-bar scale trough {
    min-height: 4px;     /* 减小轨道高度 */
}



.pill { margin: 10px; padding: 10px; min-width: 25px; min-height: 25px; border-radius: 99px; }

/* 绝对扁平化卡片 */
flowboxchild { background-color: transparent; padding: 0; margin: 0; }
.card { 
    background-color: transparent;
    border: none;
    box-shadow: none;
    padding: 8px; 
    min-width: 130px; 
    transition: background-color 0.2s;
}
.card:hover { background-color: alpha(currentColor, 0.06); }
.card:hover label { color: @accent_color; }

.album-cover-img { border-radius: 8px; }
.header-art { border-radius: 12px; }

/* 详情页头部样式 */
.album-header-box { padding: 32px; margin-bottom: 10px; }
.album-title-large { font-size: 28px; font-weight: 800; margin-bottom: 4px; }
.album-artist-medium { font-size: 16px; font-weight: 600; color: @accent_color; margin-bottom: 8px; }
.album-meta { font-size: 13px; opacity: 0.7; }

/* 大爱心按钮样式 */
.heart-btn {
    background: transparent;
    box-shadow: none;
    border: none;
    padding: 12px;
    min-width: 64px;
    min-height: 64px;
    border-radius: 99px;
    color: alpha(currentColor, 0.3);
    transition: all 0.3s cubic-bezier(0.175, 0.885, 0.32, 1.275);
}
.heart-btn image { -gtk-icon-size: 32px; }
.heart-btn:hover {
    color: alpha(currentColor, 0.6);
    background-color: alpha(currentColor, 0.05);
    transform: scale(1.1);
}
.heart-btn.active { color: #e91e63; opacity: 1; }
.heart-btn.active:hover { color: #d81b60; transform: scale(1.15); }

/* 动态标题 */
.section-title { 
    font-size: 20px; 
    font-weight: 700; 
    margin: 12px 12px 12px 12px; 
}

.tech-label { 
    font-family: "Monospace"; 
    font-size: 10px; 
    font-weight: bold; 
    color: @accent_color; 
    background-color: alpha(@accent_bg_color, 0.12); 
    padding: 3px 3px; 
    border-radius: 4px; 
    margin-top: 0;
}

.card-bar box > box > image,
.card-bar box > box > label.tech-label {
    margin-top: 5px;
    margin-bottom: 5px;
}

.settings-container { padding: 40px; }
.settings-group {
    background-color: alpha(currentColor, 0.05);
    border-radius: 12px;
    padding: 6px;
    margin-bottom: 24px;
}
.settings-row {
    padding: 12px 16px;
    border-bottom: 1px solid alpha(currentColor, 0.05);
}
.settings-row:last-child { border-bottom: none; }
.settings-label { font-weight: 600; }
"""
