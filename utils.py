import os
import requests
import hashlib
from threading import Thread
from gi.repository import GLib, GdkPixbuf, Gdk

def load_img(widget, url_provider, cache_dir, size=84):
    """
    图片加载器：
    读取图片后，强制缩放为 size x size 的正方形。
    解决因原图非正方形导致留白、进而导致 CSS 圆角裁剪失效的问题。
    """
    # 先清空旧图
    widget.set_from_pixbuf(None)
    
    def fetch():
        try:
            # 1. 获取 URL
            u = url_provider() if callable(url_provider) else url_provider
            if not u: return
            
            # 标记当前目标 URL，防止复用错乱
            widget._target_url = u
            
            # 2. 缓存检查
            f_name = hashlib.md5(u.encode()).hexdigest()
            f_path = os.path.join(cache_dir, f_name)
            
            if not os.path.exists(f_path):
                try:
                    # 下载 (Tidal 图片通常是 JPG)
                    r = requests.get(u, timeout=10, verify=False)
                    if r.status_code == 200:
                        with open(f_path, 'wb') as f:
                            f.write(r.content)
                    else: return
                except: return

            # 3. 应用图片
            def apply():
                # 检查控件是否还在请求这张图
                if hasattr(widget, '_target_url') and widget._target_url == u:
                    try:
                        # [核心修改]
                        # 1. 读取原始图片 (不缩放)
                        pb = GdkPixbuf.Pixbuf.new_from_file(f_path)
                        if pb:
                            # 2. 强制缩放到指定尺寸 (忽略宽高比，填满正方形)
                            # InterpType.BILINEAR: 双线性插值，速度快且质量尚可
                            scaled = pb.scale_simple(size, size, GdkPixbuf.InterpType.BILINEAR)
                            widget.set_from_pixbuf(scaled)
                    except Exception as e:
                        print(f"[IMG] Error: {e}")
            
            GLib.idle_add(apply)
        except Exception as e: pass
            
    Thread(target=fetch, daemon=True).start()

def set_pointer_cursor(widget, enable):
    try:
        cursor_name = "pointer" if enable else "default"
        cursor = Gdk.Cursor.new_from_name(cursor_name, None)
        widget.set_cursor(cursor)
    except: pass
