# utils.py
import os
import requests
import hashlib
from threading import Thread
from gi.repository import GLib, GdkPixbuf, Gdk

def load_img(widget, url_provider, cache_dir, size=84):
    """
    带详细日志的异步图片加载器
    """
    # 1. 标记初始状态
    widget.set_from_pixbuf(None)
    widget_id = hex(id(widget))
    
    def fetch():
        try:
            # 解析 URL
            print(f"[DEBUG] {widget_id} 开始解析 URL...")
            u = url_provider() if callable(url_provider) else url_provider
            
            if not u:
                print(f"[DEBUG] {widget_id} 错误：解析到的 URL 为空")
                return
            
            print(f"[DEBUG] {widget_id} 目标 URL: {u[:60]}...")
            widget._target_url = u 
            
            # 缓存逻辑
            f_name = hashlib.md5(u.encode()).hexdigest()
            f_path = os.path.join(cache_dir, f_name)
            
            if not os.path.exists(f_path):
                print(f"[DEBUG] {widget_id} 缓存未命中，开始下载...")
                r = requests.get(u, timeout=10, verify=False)
                if r.status_code == 200:
                    with open(f_path, 'wb') as f:
                        f.write(r.content)
                    print(f"[DEBUG] {widget_id} 下载完成并保存到: {f_name}")
                else:
                    print(f"[DEBUG] {widget_id} 下载失败，状态码: {r.status_code}")
                    return
            else:
                print(f"[DEBUG] {widget_id} 命中本地缓存: {f_name}")

            def apply():
                # 时序校验
                if hasattr(widget, '_target_url') and widget._target_url == u:
                    try:
                        pix = GdkPixbuf.Pixbuf.new_from_file_at_scale(f_path, size, size, True)
                        widget.set_from_pixbuf(pix)
                        print(f"[DEBUG] {widget_id} 渲染成功！")
                    except Exception as e:
                        print(f"[DEBUG] {widget_id} 渲染异常: {e}")
                else:
                    print(f"[DEBUG] {widget_id} 渲染跳过：由于 widget 已发起新请求")
            
            GLib.idle_add(apply)
        except Exception as e:
            print(f"[DEBUG] {widget_id} 线程崩溃: {e}")
            
    Thread(target=fetch, daemon=True).start()

def set_pointer_cursor(widget, enter=True):
    cursor_name = "pointer" if enter else None
    try:
        widget.set_cursor(Gdk.Cursor.new_from_name(cursor_name, None) if cursor_name else None)
    except: pass
