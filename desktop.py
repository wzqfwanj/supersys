"""supersys 桌面版：本地起服务 + 原生窗口 + 右下角托盘图标。

双击桌面上的 supersys 图标（或「启动supersys.bat」）打开，独立窗口、没有浏览器地址栏；
关掉窗口不会退出，会缩到右下角托盘；右键托盘图标可以「打开 supersys」或「退出」。
数据仍然存在本目录的 data.db。
"""

import json
import os
import socket
import sys
import threading
import time
import traceback
import urllib.request

# 从桌面快捷方式启动时当前目录可能不是项目目录，这里保证能 import server
ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import pystray  # noqa: E402
import webview  # noqa: E402
from PIL import Image  # noqa: E402

import server  # noqa: E402

# 打包成 exe 后，配置 / 日志 / 数据都放在 exe 旁边（ROOT 是临时解压目录，不能用）
if getattr(sys, "frozen", False):
    APP_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    APP_DIR = ROOT

ICON = os.path.join(server.WEB_DIR, "icon.ico")
LOG_FILE = os.path.join(APP_DIR, "desktop.log")


def pick_port():
    """优先用 8000，被占用就换一个空闲端口。"""
    for port in (8000, 0):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind(("127.0.0.1", port))
                return sock.getsockname()[1]
            except OSError:
                continue
    raise RuntimeError("没有可用端口")


def start_server(port):
    server.init_db()
    server.migrate_legacy_json()
    host = os.environ.get("SUPERSYS_HOST", "127.0.0.1")
    httpd = server.Server((host, port), server.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{port}"
    for _ in range(80):
        try:
            with urllib.request.urlopen(url + "/api/health", timeout=1) as response:
                if response.status == 200:
                    return httpd, url
        except OSError:
            time.sleep(0.1)
    raise RuntimeError("服务启动失败")


def load_icon():
    try:
        return Image.open(ICON).convert("RGBA")
    except OSError:
        return Image.new("RGBA", (64, 64), (18, 18, 18, 255))


def remote_url():
    """exe 旁边放 desktop_config.json（{"url": "https://..."}）就连接云端服务。"""
    config = os.path.join(APP_DIR, "desktop_config.json")
    try:
        with open(config, encoding="utf-8") as file:
            data = json.load(file)
        url = str(data.get("url") or "").strip()
        return url or None
    except (OSError, ValueError):
        return None


def main():
    try:
        run()
    except Exception:
        with open(LOG_FILE, "a", encoding="utf-8") as log:
            log.write(traceback.format_exc())
            log.write("\n")
        raise


def run():
    testing = bool(os.environ.get("SUPERSYS_DESKTOP_TEST"))
    remote = remote_url()
    httpd = None
    if remote:
        url = remote
    else:
        port = pick_port()
        httpd, url = start_server(port)
    window = webview.create_window(
        "supersys",
        url,
        width=1080,
        height=820,
        min_size=(720, 560),
        background_color="#121212",
        hidden=testing,
    )

    state = {"force_quit": False}
    tray = None

    def show_window():
        try:
            window.show()
            window.restore()
        except Exception:
            pass

    def quit_app():
        state["force_quit"] = True
        if tray is not None:
            try:
                tray.stop()
            except Exception:
                pass
        for item in list(webview.windows):
            try:
                item.destroy()
            except Exception:
                pass

    # 点窗口右上角关闭：缩到托盘，不退出
    def on_closing():
        if state["force_quit"]:
            return True
        try:
            window.hide()
        except Exception:
            pass
        return False

    try:
        window.events.closing += on_closing
    except Exception:
        pass

    # 右下角托盘图标：双击 / 「打开」显示窗口，「退出」结束程序
    tray = pystray.Icon(
        "supersys",
        load_icon(),
        "supersys（双击打开）",
        pystray.Menu(
            pystray.MenuItem("打开 supersys", lambda icon, item: show_window(), default=True),
            pystray.MenuItem("退出", lambda icon, item: quit_app()),
        ),
    )
    threading.Thread(target=tray.run, daemon=True).start()

    def close_for_test():
        time.sleep(4)
        print(f"[test] tray.visible={getattr(tray, 'visible', None)}", flush=True)
        quit_app()

    try:
        webview.start(close_for_test if testing else None, icon=ICON)
    finally:
        try:
            tray.stop()
        except Exception:
            pass
        if httpd is not None:
            httpd.shutdown()
            httpd.server_close()


if __name__ == "__main__":
    main()
