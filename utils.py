# utils.py
import os
import requests
import hashlib
from threading import Thread
from gi.repository import GLib, GdkPixbuf, Gdk

def load_img(widget, url_provider, cache_dir, size=84):
    """
    通用异步图片加载器，带本地缓存
    """
    def fetch():
        try:
            # 获取 URL (支持 lambda 懒加载)
            u = url_provider() if callable(url_provider) else url_provider
            if not u: return
            
            # 生成缓存路径
            f_name = hashlib.md5(u.encode()).hexdigest()
            f_path = os.path.join(cache_dir, f_name)
            
            # 检查或下载
            if not os.path.exists(f_path):
                r = requests.get(u, timeout=10, verify=False)
                if r.status_code == 200:
                    with open(f_path, 'wb') as f:
                        f.write(r.content)
                else: return

            # 加载并显示
            pix = GdkPixbuf.Pixbuf.new_from_file_at_scale(f_path, size, size, True)
            GLib.idle_add(widget.set_from_pixbuf, pix)
        except:
            pass
            
    Thread(target=fetch, daemon=True).start()

def set_pointer_cursor(widget, enter=True):
    """切换手型光标"""
    cursor_name = "pointer" if enter else None
    widget.set_cursor(Gdk.Cursor.new_from_name(cursor_name, None) if cursor_name else None)
