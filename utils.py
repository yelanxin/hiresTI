import os
import requests
import hashlib
from threading import Thread
from gi.repository import GLib, GdkPixbuf, Gdk

def load_img(widget, url_provider, cache_dir, size=84):
    """
    HiDPI 最终修正版：
    1. 线程内生成 2x 高清图 (物理像素)。
    2. 主线程强制设定 1x 逻辑尺寸 (pixel_size)。
    这样 GTK 会自动用高清图填充逻辑区域，既清晰大小又对。
    """
    # 先清除旧图，避免复用时的视觉残留
    widget.set_from_pixbuf(None)
    
    def fetch():
        try:
            u = url_provider() if callable(url_provider) else url_provider
            if not u: return
            
            # 标记当前目标 URL，防止快速滚动时图片错乱
            widget._target_url = u
            
            f_name = hashlib.md5(u.encode()).hexdigest()
            f_path = os.path.join(cache_dir, f_name)
            
            # 1. 下载 (如果不存在)
            if not os.path.exists(f_path):
                try:
                    r = requests.get(u, timeout=10, verify=False)
                    if r.status_code == 200:
                        with open(f_path, 'wb') as f:
                            f.write(r.content)
                    else: return
                except: return

            # 2. 图片处理 (在后台线程完成，避免卡顿)
            try:
                pb = GdkPixbuf.Pixbuf.new_from_file(f_path)
                if pb:
                    # 【核心步骤 A】生成 2 倍大小的物理图片数据
                    # 例如：UI 需要 160，我们生成 320x320 的数据
                    target_phys_size = size * 2
                    scaled = pb.scale_simple(target_phys_size, target_phys_size, GdkPixbuf.InterpType.BILINEAR)
                else:
                    scaled = None
            except Exception as e:
                scaled = None

            # 3. 应用到 UI (回到主线程)
            def apply():
                # 检查控件是否还在请求这张图
                if hasattr(widget, '_target_url') and widget._target_url == u and scaled:
                    try:
                        # 【核心步骤 B】强制控件显示为逻辑尺寸 (例如 160)
                        # 如果不加这一行，GTK 可能会把 320 的图显示得巨大，或者依然显示得很小
                        widget.set_pixel_size(size)
                        
                        # 设置高清数据
                        widget.set_from_pixbuf(scaled)
                    except Exception as e:
                        print(f"[IMG Apply Error] {e}")
            
            GLib.idle_add(apply)
        except Exception as e: pass
            
    Thread(target=fetch, daemon=True).start()

def set_pointer_cursor(widget, enable):
    try:
        cursor_name = "pointer" if enable else "default"
        cursor = Gdk.Cursor.new_from_name(cursor_name, None)
        widget.set_cursor(cursor)
    except: pass
