"""supersys 桌面版：原生窗口 + 右下角托盘图标 + 本地/云端存储选择。

第一次打开先选「本地存储」还是「云端存储」，之后记住（desktop_config.json）；
关窗口缩到托盘，右键托盘图标可以打开或退出。
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
CONFIG_FILE = os.path.join(APP_DIR, "desktop_config.json")

CHOOSER_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>supersys</title>
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; }
  body {
    margin: 0; min-height: 100vh; padding: 36px 32px; background: #121212; color: #e8e8e8;
    font: 15px/1.6 -apple-system, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
  }
  h1 { margin: 0 0 6px; font-size: 22px; letter-spacing: .5px; }
  .hint { margin: 0 0 24px; color: #8f8f8f; font-size: 13px; }
  .section { margin-bottom: 20px; }
  .section h2 { margin: 0 0 8px; font-size: 14px; font-weight: 500; color: #cfcfcf; }
  button {
    padding: 10px 18px; border: 1px solid #e8e8e8; border-radius: 6px;
    background: #e8e8e8; color: #121212; font-size: 14px; cursor: pointer;
  }
  button.secondary { background: none; color: #e8e8e8; }
  button:hover { opacity: .85; }
  input {
    width: 100%; margin-top: 8px; padding: 9px 12px; border: 1px solid #2e2e2e; border-radius: 6px;
    background: #1c1c1c; color: #e8e8e8; font-size: 14px;
  }
  input:focus { outline: none; border-color: #e8e8e8; }
  .msg { margin: 10px 0 0; min-height: 18px; color: #ff8f8f; font-size: 12px; }
  .row { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
</style>
</head>
<body>
<h1>supersys</h1>
<p class="hint">选择数据存在哪里：本地存储只在这台电脑上；云端存储登录手机号后多设备同步。</p>

<div class="section">
  <h2>本地存储</h2>
  <button id="local">使用本地存储</button>
</div>

<div class="section">
  <h2>云端存储</h2>
  <div class="row">
    <input id="url" placeholder="https://你的域名/supersys/" value="https://你的域名/supersys/">
    <button class="secondary" id="cloud">连接云端</button>
  </div>
</div>

<p class="msg" id="msg"></p>

<script>
const msg = document.getElementById("msg");
document.getElementById("local").addEventListener("click", async () => {
  msg.textContent = "";
  try {
    const result = await pywebview.api.choose_local();
    location.href = result.url;
  } catch (err) {
    msg.textContent = String(err);
  }
});
document.getElementById("cloud").addEventListener("click", async () => {
  msg.textContent = "";
  try {
    const result = await pywebview.api.choose_cloud(document.getElementById("url").value);
    location.href = result.url;
  } catch (err) {
    msg.textContent = String(err);
  }
});
</script>
</body>
</html>
"""


class Chooser:
    """首次启动的选择窗口：选完把配置写到 exe 旁边。"""

    def __init__(self):
        self.httpd = None

    def choose_local(self):
        port = pick_port()
        self.httpd, url = start_server(port)
        save_config({"mode": "local"})
        return {"url": url}

    def choose_cloud(self, url):
        url = str(url or "").strip()
        if not url.startswith("http://") and not url.startswith("https://"):
            raise ValueError("请输入以 http:// 或 https:// 开头的地址")
        save_config({"mode": "cloud", "url": url})
        return {"url": url}


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


def load_config():
    """读取 exe 旁边的 desktop_config.json；没有就返回 None（表示第一次启动）。"""
    try:
        with open(CONFIG_FILE, encoding="utf-8") as file:
            data = json.load(file)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    url = str(data.get("url") or "").strip()
    mode = data.get("mode")
    if mode not in ("local", "cloud"):
        mode = "cloud" if url else "local"
    return {"mode": mode, "url": url}


def save_config(config):
    with open(CONFIG_FILE, "w", encoding="utf-8") as file:
        json.dump(config, file, ensure_ascii=False)


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
    config = load_config()
    httpd = None
    chooser = None

    if config is None:
        chooser = Chooser()
        window = webview.create_window(
            "supersys",
            html=CHOOSER_HTML,
            js_api=chooser,
            width=560,
            height=470,
            min_size=(520, 420),
            background_color="#121212",
            hidden=testing,
        )
    else:
        if config.get("mode") == "cloud" and config.get("url"):
            url = config["url"]
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
        for item in (httpd, chooser.httpd if chooser is not None else None):
            if item is not None:
                item.shutdown()
                item.server_close()


if __name__ == "__main__":
    main()
