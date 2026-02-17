import os
import requests
import hashlib
from threading import Thread
from gi.repository import GLib, GdkPixbuf, Gdk

def load_img(widget, url_provider, cache_dir, size=84):
    """
    [混合修复版]
    - Gtk.Picture: 使用 Texture，自适应 (适合大图)。
    - Gtk.Image: 使用 set_pixel_size 强力锁死尺寸 (适合图标/封面)。
    """
    # 预设尺寸请求 (作为保底)
    widget.set_size_request(size, size)
    
    # 清空内容
    if hasattr(widget, 'set_paintable'): widget.set_paintable(None)
    elif hasattr(widget, 'set_from_pixbuf'): widget.set_from_pixbuf(None)
    
    def fetch():
        try:
            u = url_provider() if callable(url_provider) else url_provider
            if not u: return
            
            widget._target_url = u
            f_name = hashlib.md5(u.encode()).hexdigest()
            f_path = os.path.join(cache_dir, f_name)
            
            # 下载
            if not os.path.exists(f_path):
                try:
                    r = requests.get(u, timeout=10, verify=False)
                    if r.status_code == 200:
                        with open(f_path, 'wb') as f:
                            f.write(r.content)
                    else: return
                except: return

            # 判断控件类型
            w_type = type(widget).__name__
            
            # --- 情况 A: Gtk.Picture (用于详情页大图) ---
            if w_type == 'Picture':
                try:
                    pb = GdkPixbuf.Pixbuf.new_from_file(f_path)
                    texture = Gdk.Texture.new_for_pixbuf(pb)
                    def apply_pic():
                        if hasattr(widget, '_target_url') and widget._target_url == u:
                            widget.set_size_request(size, size)
                            widget.set_paintable(texture)
                    GLib.idle_add(apply_pic)
                except: pass

            # --- 情况 B: Gtk.Image (用于播放栏/列表) ---
            else:
                try:
                    pb = GdkPixbuf.Pixbuf.new_from_file(f_path)
                    if pb:
                        # 1. 生成 2倍 高清图数据 (例如 144x144)
                        target_phys = size * 2
                        scaled = pb.scale_simple(target_phys, target_phys, GdkPixbuf.InterpType.BILINEAR)
                        
                        def apply_img():
                            if hasattr(widget, '_target_url') and widget._target_url == u:
                                # [关键修复] 强制锁定逻辑显示尺寸！
                                # 这句代码是防止图片变大的绝对防线
                                widget.set_pixel_size(size) 
                                widget.set_from_pixbuf(scaled)
                        GLib.idle_add(apply_img)
                except: pass

        except Exception as e: pass
            
    Thread(target=fetch, daemon=True).start()

def set_pointer_cursor(widget, enable):
    try:
        cursor_name = "pointer" if enable else "default"
        cursor = Gdk.Cursor.new_from_name(cursor_name, None)
        widget.set_cursor(cursor)
    except: pass
