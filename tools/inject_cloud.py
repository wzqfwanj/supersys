"""把云端服务器地址注入到客户端资源里（GitHub Actions 构建时用）。

环境变量 CLOUD_URL，例如 https://wkeeli.cn/supersys/；为空时写占位（开发版）。
生成：
  web/cloud.js       给网页（PC/移动端 WebView）用
  web/cloud.json     给桌面版选择窗口、Android 客户端用
"""

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
url = (os.environ.get("CLOUD_URL") or "").strip().rstrip("/")
if url and not url.startswith("http"):
    url = "https://" + url
if url:
    url += "/"

(ROOT / "web" / "cloud.js").write_text(
    '// 构建时注入的云端地址\n'
    f'window.SUPERSYS_CLOUD_URL = "{url}";\n',
    encoding="utf-8",
)
(ROOT / "web" / "cloud.json").write_text(
    json.dumps({"url": url}, ensure_ascii=False) + "\n",
    encoding="utf-8",
)
print("cloud url injected:", url or "(empty)")
