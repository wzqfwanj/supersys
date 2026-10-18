"""supersys 后端：静态页面 + 规划 / 状态数据 + 智能体列表。

数据存 SQLite（Python 标准库 sqlite3），表结构是常见的「一条记录一行」：
每条约束条件、每个勾选、每个金额都是一行，增删改都是单行语句，
所以多个窗口同时操作也只会改到自己那一行，不会互相覆盖。

接口（REST 风格）：
  GET    /api/sections            分区 / 智能体列表
  GET    /api/plan                规划数据
  GET    /api/status              状态数据
  POST   /api/plan/items          新增条件   {field, name}
  PATCH  /api/plan/items/<id>     修改条件   {name}
  DELETE /api/plan/items/<id>     删除条件
  POST   /api/plan/batch          一次提交多条改动 {field, ops:{create, rename, delete}}
  POST   /api/plan/funds          保存金额   {amount}
  （/api/status/... 同理）
"""

import json
import mimetypes
import os
import re
import secrets
import socket
import sqlite3
import sys
import time
from datetime import datetime
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

# 手机端 PWA 的 manifest 要正确的 MIME 类型，浏览器才认。
mimetypes.add_type("application/manifest+json", ".webmanifest")

if getattr(sys, "frozen", False):
    # PyInstaller 打包后：网页资源在临时解压目录，数据放在 exe 旁边
    ROOT = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(sys.executable)))
    DATA_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    ROOT = os.path.dirname(os.path.abspath(__file__))
    DATA_DIR = ROOT

WEB_DIR = os.path.join(ROOT, "web")
# 数据文件可用环境变量指定，便于测试时不碰真实数据。
DB_FILE = (
    os.environ.get("SUPERSYS_DB")
    or os.environ.get("SUPERSYS_DATA")
    or os.path.join(DATA_DIR, "data.db")
)
# 旧的 data.json（上一版用的），启动时如果新库是空的就迁移进来。
LEGACY_JSON = os.environ.get("SUPERSYS_LEGACY") or os.path.join(DATA_DIR, "data.json")

# 部署到公网时设置 SUPERSYS_PASSWORD，没设置就是本地模式（不用登录）。
AUTH_PASSWORD = os.environ.get("SUPERSYS_PASSWORD", "")
SESSION_COOKIE = "supersys_session"
SESSION_DAYS = 30
SESSIONS = {}  # token -> 过期时间戳

LOGIN_PAGE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#121212">
<title>supersys 登录</title>
</head>
<body>
<form id="login-form">
  <h1>supersys</h1>
  <p class="hint">输入访问密码</p>
  <input id="password" type="password" autocomplete="current-password" placeholder="密码">
  <button type="submit">进入</button>
  <p id="msg" class="msg"></p>
</form>
<script>
const form = document.getElementById("login-form");
const msg = document.getElementById("msg");
form.addEventListener("submit", async (event) => {
  event.preventDefault();
  msg.textContent = "";
  try {
    const res = await fetch("api/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password: document.getElementById("password").value }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || "登录失败");
    location.replace("./");
  } catch (err) {
    msg.textContent = err.message;
  }
});
</script>
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; }
  body {
    margin: 0; min-height: 100vh; display: flex; align-items: center; justify-content: center;
    padding: 24px; background: #121212; color: #e8e8e8;
    font: 16px/1.7 -apple-system, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
  }
  form { width: min(340px, 100%); }
  h1 { margin: 0 0 8px; font-size: 22px; letter-spacing: .5px; }
  .hint { margin: 0 0 20px; color: #8f8f8f; font-size: 14px; }
  input {
    width: 100%; padding: 12px 14px; border: 1px solid #2e2e2e; border-radius: 8px;
    background: #1c1c1c; color: #e8e8e8; font-size: 16px;
  }
  input:focus { outline: none; border-color: #e8e8e8; }
  button {
    width: 100%; margin-top: 12px; padding: 12px; border: 1px solid #e8e8e8; border-radius: 8px;
    background: #e8e8e8; color: #121212; font-size: 15px; cursor: pointer;
  }
  .msg { margin: 12px 0 0; min-height: 20px; color: #ff8f8f; font-size: 13px; }
</style>
</body>
</html>
"""

SEPARATORS = re.compile(r"[，,、；;]+")
AMOUNT = re.compile(r"-?\d+(?:\.\d+)?")

SECTIONS = [
    {"id": "status", "name": "状态"},
    {"id": "plan", "name": "规划"},
    {"id": "agent", "name": "智能体"},
]

# 智能体：基础看身高体重，财务看资金和收入，饮食看饮食，运动看运动，监管目前只看今日。
AGENTS = [
    {"id": "base", "name": "基础智能体"},
    {"id": "finance", "name": "财务智能体"},
    {"id": "diet", "name": "饮食智能体"},
    {"id": "sport", "name": "运动智能体"},
    {"id": "supervisor", "name": "监管智能体"},
]

LIST_FIELDS = ("height", "weight", "meals", "sport", "today")
# 数字类型的字段（弹窗输入数字）
AMOUNT_FIELDS = ("funds", "income")
MAX_NAME = 200
MAX_ITEMS = 200

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    section    TEXT    NOT NULL,
    field      TEXT    NOT NULL,
    name       TEXT    NOT NULL,
    position   INTEGER NOT NULL DEFAULT 0,
    days       TEXT,
    checked_on TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS items_unique ON items (section, field, name);
CREATE TABLE IF NOT EXISTS amounts (
    section TEXT NOT NULL,
    field   TEXT NOT NULL,
    value   TEXT,
    PRIMARY KEY (section, field)
);
CREATE TABLE IF NOT EXISTS runs (
    date    TEXT PRIMARY KEY,
    ok      INTEGER NOT NULL DEFAULT 0,
    total   INTEGER NOT NULL DEFAULT 0,
    detail  TEXT
);
"""


class ApiError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


# ---------- 数据库 ----------

def init_db():
    """建库 + 打开 WAL（一次即可）；每个请求再各自拿连接。"""
    conn = sqlite3.connect(DB_FILE, timeout=5)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(SCHEMA)
        # 旧库补列：运动条件可以按周几安排，状态里的运动勾选带日期。
        columns = {row[1] for row in conn.execute("PRAGMA table_info(items)").fetchall()}
        if "days" not in columns:
            conn.execute("ALTER TABLE items ADD COLUMN days TEXT")
        if "checked_on" not in columns:
            conn.execute("ALTER TABLE items ADD COLUMN checked_on TEXT")
        # 旧的 funds 表迁移到 amounts 表（amounts 里还放「收入」等其它数字字段）
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        if "funds" in tables:
            has_amounts = conn.execute("SELECT COUNT(*) FROM amounts").fetchone()[0]
            if not has_amounts:
                for section, amount in conn.execute("SELECT section, amount FROM funds").fetchall():
                    if amount is not None:
                        conn.execute(
                            "INSERT OR REPLACE INTO amounts (section, field, value) VALUES (?, 'funds', ?)",
                            (section, amount),
                        )
        conn.commit()
    finally:
        conn.close()


def db():
    """每个请求一个连接：并发写时靠 WAL + busy_timeout 排队，不互相打断。"""
    conn = sqlite3.connect(DB_FILE, timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


# ---------- 数据整理 ----------

def clean_name(value):
    """一条条件就是用户输入的那段文字：原样保留（标点、空格都不拆），只去掉首尾空白。"""
    if value is None or isinstance(value, bool):
        return ""
    if isinstance(value, (int, float)):
        value = str(int(value)) if float(value).is_integer() else str(value)
    return str(value).strip()[:MAX_NAME]


def split_legacy_list(value):
    """把旧 data.json 里「a；b，c」这种用分隔符连起来的文本拆成条件列表（只在迁移时用）。"""
    if value is None or isinstance(value, bool):
        return []
    if isinstance(value, (int, float)):
        return [str(int(value)) if float(value).is_integer() else str(value)]
    names = []
    for part in SEPARATORS.split(str(value)):
        name = part.strip()[:MAX_NAME]
        if name:
            names.append(name)
    return names


def clean_amount(value):
    """金额只保留数字（旧文本「每月…20000元」也能取出数字）。"""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return str(int(value)) if float(value).is_integer() else str(value)
    match = AMOUNT.search(str(value))
    return match.group(0) if match else None


def to_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def parse_days(value):
    """运动按周几安排：1=周一 … 7=周日，空表示每天。"""
    if value is None or value == "" or isinstance(value, bool):
        return []
    if isinstance(value, (int, float)):
        numbers = [int(value)]
    elif isinstance(value, (list, tuple)):
        numbers = []
        for part in value:
            number = to_int(part)
            if number is not None:
                numbers.append(number)
    else:
        numbers = [int(match) for match in re.findall(r"[1-7]", str(value))]
    return sorted({number for number in numbers if 1 <= number <= 7})


def format_days(days):
    """存成 "1,3,5" 这种；空列表（每天）存 NULL。"""
    return ",".join(str(day) for day in days) or None


WEEKDAY_MAP = {
    "一": 1,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "日": 7,
    "天": 7,
    "七": 7,
}
WEEKDAY_SPEC = re.compile(
    r"^(?P<name>.+?)[，,、；;]"
    r"(?P<spec>[一二三四五六日七天周星期礼拜每0-9、，,；;\s\-~—和及与末作工到至]+)$"
)


def weekday_value(char):
    if char in WEEKDAY_MAP:
        return WEEKDAY_MAP[char]
    if char.isdigit() and 1 <= int(char) <= 7:
        return int(char)
    return None


def parse_weekday_spec(spec):
    """解析「一、三、五、七」「周一三五」「每天」「周末」「周一到周五」「1357」这些写法。"""
    text = (spec or "").strip()
    if not text:
        return None
    if text in ("每天", "每日", "天天"):
        return []
    if text == "周末":
        return [6, 7]
    if text in ("工作日", "周中"):
        return [1, 2, 3, 4, 5]
    cleaned = re.sub(r"[周星期礼拜每、，,；;\s和及与]", "", text)
    if not cleaned:
        return None
    range_match = re.fullmatch(
        r"([一二三四五六日天1-7])[到至~\-—]([一二三四五六日天1-7])", cleaned
    )
    if range_match:
        start = weekday_value(range_match.group(1))
        end = weekday_value(range_match.group(2))
        if start is not None and end is not None:
            low, high = sorted((start, end))
            return list(range(low, high + 1))
    days = []
    for char in cleaned:
        value = weekday_value(char)
        if value is None:
            return None
        days.append(value)
    return sorted(set(days)) or None


def split_sport_text(value):
    """「高脚杯深蹲，一、三、五、七」→ ("高脚杯深蹲", [1,3,5,7])；没有周几就是每天。"""
    text = clean_name(value)
    if not text:
        return "", []
    match = WEEKDAY_SPEC.match(text)
    if match:
        days = parse_weekday_spec(match.group("spec"))
        name = match.group("name").strip().rstrip("，,、；; ").strip()
        if days is not None and name:
            return name, days
    return text, []


def today_key():
    return datetime.now().strftime("%Y-%m-%d")


# ---------- 查询 / 写入（都在一个连接里） ----------

def load_section(conn, section):
    data = {field: None for field in AMOUNT_FIELDS}
    for field in AMOUNT_FIELDS:
        row = conn.execute(
            "SELECT value FROM amounts WHERE section = ? AND field = ?", (section, field)
        ).fetchone()
        if row is not None:
            data[field] = row["value"]
    for field in LIST_FIELDS:
        sql = "SELECT id, name, days, checked_on FROM items WHERE section = ? AND field = ?"
        params = [section, field]
        if section == "status" and field == "sport":
            # 运动勾选只算今天的
            sql += " AND checked_on = ?"
            params.append(today_key())
        sql += " ORDER BY position, id"
        rows = conn.execute(sql, params).fetchall()
        data[field] = [
            {
                "id": row["id"],
                "name": row["name"],
                "days": parse_days(row["days"]),
                "checkedOn": row["checked_on"],
            }
            for row in rows
        ]
    return data


def add_items(conn, section, field, entries):
    """entries: [{"name": 条件, "days": [周几]}]（运动的周几也可以直接写在文字里）"""
    normalized = []
    for entry in entries:
        name = entry.get("name") or ""
        days = entry.get("days") or []
        if field == "sport":
            name, parsed_days = split_sport_text(name)
            days = parsed_days if section == "plan" else []
        if not name:
            raise ApiError("条件不能为空")
        normalized.append({"name": name, "days": days})
    if section == "status":
        for entry in normalized:
            exists = conn.execute(
                "SELECT 1 FROM items WHERE section = 'plan' AND field = ? AND name = ?",
                (field, entry["name"]),
            ).fetchone()
            if exists is None:
                raise ApiError("「规划」里没有这个条件，先在那里定义")
        if field == "sport":
            # 运动只记今天的勾选，顺手清掉以前日期的记录
            conn.execute(
                "DELETE FROM items WHERE section = 'status' AND field = 'sport' "
                "AND (checked_on IS NULL OR checked_on != ?)",
                (today_key(),),
            )
    count = conn.execute(
        "SELECT COUNT(*) FROM items WHERE section = ? AND field = ?", (section, field)
    ).fetchone()[0]
    if count + len(normalized) > MAX_ITEMS:
        raise ApiError("条件太多了")
    position = conn.execute(
        "SELECT COALESCE(MAX(position), -1) + 1 FROM items WHERE section = ? AND field = ?",
        (section, field),
    ).fetchone()[0]
    for entry in normalized:
        days = None
        if field == "sport" and section == "plan":
            days = format_days(entry["days"])
        checked_on = today_key() if section == "status" and field == "sport" else None
        conn.execute(
            "INSERT OR IGNORE INTO items (section, field, name, position, days, checked_on) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (section, field, entry["name"], position, days, checked_on),
        )
        position += 1


def rename_item(conn, section, field, item_id, name, days=None):
    if field == "sport":
        name, parsed_days = split_sport_text(name)
        if section == "plan" and days is None:
            days = parsed_days
    row = conn.execute(
        "SELECT name, days FROM items WHERE id = ? AND section = ? AND field = ?",
        (item_id, section, field),
    ).fetchone()
    if row is None:
        raise ApiError("这条条件不存在", 404)
    old = row["name"]
    new_days = row["days"]
    if days is not None and field == "sport" and section == "plan":
        new_days = format_days(days)
    if name == old and new_days == row["days"]:
        return
    conn.execute("UPDATE items SET name = ?, days = ? WHERE id = ?", (name, new_days, item_id))
    # 规划里改名时，状态里的同名勾选跟着改名，勾选不会丢。
    if section == "plan" and name != old:
        conn.execute(
            "UPDATE items SET name = ? WHERE section = 'status' AND field = ? AND name = ?",
            (name, field, old),
        )


def delete_item(conn, section, field, item_id):
    row = conn.execute(
        "SELECT name FROM items WHERE id = ? AND section = ? AND field = ?",
        (item_id, section, field),
    ).fetchone()
    if row is None:
        raise ApiError("这条条件不存在", 404)
    conn.execute("DELETE FROM items WHERE id = ?", (item_id,))
    # 规划里删掉时，状态里的同名勾选也一起清掉。
    if section == "plan":
        conn.execute(
            "DELETE FROM items WHERE section = 'status' AND field = ? AND name = ?",
            (field, row["name"]),
        )


def set_amount(conn, section, field, amount):
    conn.execute(
        "INSERT OR REPLACE INTO amounts (section, field, value) VALUES (?, ?, ?)",
        (section, field, amount),
    )


def apply_batch(conn, section, field, ops):
    """点「确定」时一次提交：删除 / 改名 / 新增，全在同一个事务里完成。"""
    for raw_id in ops.get("delete") or []:
        item_id = to_int(raw_id)
        if item_id is None:
            continue
        row = conn.execute(
            "SELECT field FROM items WHERE id = ? AND section = ?", (item_id, section)
        ).fetchone()
        if row is not None:
            delete_item(conn, section, row["field"], item_id)

    for pair in ops.get("rename") or []:
        if not isinstance(pair, dict):
            continue
        item_id = to_int(pair.get("id"))
        if item_id is None:
            continue
        row = conn.execute(
            "SELECT field FROM items WHERE id = ? AND section = ?", (item_id, section)
        ).fetchone()
        if row is None:
            raise ApiError("有一条条件已经被删掉了，请刷新后重试", 409)
        name = clean_name(pair.get("name"))
        days = parse_days(pair.get("days")) if "days" in pair else None
        if name:
            rename_item(conn, section, row["field"], item_id, name, days)
        else:
            delete_item(conn, section, row["field"], item_id)

    for entry in ops.get("create") or []:
        if isinstance(entry, dict):
            name = clean_name(entry.get("name"))
            days = parse_days(entry.get("days"))
        else:
            name = clean_name(entry)
            days = []
        if name:
            add_items(conn, section, field, [{"name": name, "days": days}])


# ---------- 迁移旧 data.json ----------

def migrate_legacy_json():
    if not os.path.exists(LEGACY_JSON):
        return
    conn = sqlite3.connect(DB_FILE, timeout=5)
    try:
        with conn:
            has_data = conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
            if has_data:
                return
            try:
                with open(LEGACY_JSON, encoding="utf-8") as file:
                    data = json.load(file)
            except (OSError, json.JSONDecodeError):
                return
            for section in ("plan", "status"):
                block = data.get(section)
                if not isinstance(block, dict):
                    continue
                for field in LIST_FIELDS:
                    for index, name in enumerate(split_legacy_list(block.get(field))):
                        conn.execute(
                            "INSERT OR IGNORE INTO items (section, field, name, position) VALUES (?, ?, ?, ?)",
                            (section, field, name, index),
                        )
                amount = clean_amount(block.get("funds"))
                if amount is not None:
                    conn.execute(
                        "INSERT OR REPLACE INTO amounts (section, field, value) VALUES (?, 'funds', ?)",
                        (section, amount),
                    )
        print(f"已从 {os.path.basename(LEGACY_JSON)} 迁移数据到 {os.path.basename(DB_FILE)}", flush=True)
    finally:
        conn.close()


# ---------- HTTP ----------

ITEM_ROUTE = re.compile(r"^/api/(plan|status)/(items|funds|income|amounts)(?:/(\d+))?$")
BATCH_ROUTE = re.compile(r"^/api/(plan|status)/batch$")


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=WEB_DIR, **kwargs)

    # ---------- 读 ----------

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/login":
            self._send_login_page()
            return
        if path == "/api/session":
            self._json({"auth": bool(AUTH_PASSWORD), "loggedIn": self._is_authed()})
            return
        if not self._is_authed():
            if path.startswith("/api/"):
                self._json({"error": "请先登录"}, 401)
            else:
                self._redirect("login")
            return
        if path == "/api/sections":
            self._json({"app": "supersys", "sections": SECTIONS, "agents": AGENTS})
        elif path in ("/api/plan", "/api/status"):
            section = path.rsplit("/", 1)[1]
            conn = db()
            try:
                self._json(load_section(conn, section))
            finally:
                conn.close()
        elif path == "/api/runs":
            conn = db()
            try:
                rows = conn.execute(
                    "SELECT date, ok, total, detail FROM runs ORDER BY date DESC LIMIT 180"
                ).fetchall()
                runs = []
                for row in rows:
                    try:
                        results = json.loads(row["detail"]) if row["detail"] else []
                    except json.JSONDecodeError:
                        results = []
                    runs.append(
                        {
                            "date": row["date"],
                            "ok": row["ok"],
                            "total": row["total"],
                            "results": results,
                        }
                    )
                runs.reverse()
                self._json({"runs": runs})
            finally:
                conn.close()
        elif path == "/api/health":
            self._json({"ok": True})
        elif path.startswith("/api/"):
            self._json({"error": "接口不存在"}, 404)
        else:
            super().do_GET()

    # ---------- 写 ----------

    def do_POST(self):
        self._handle_write("POST")

    def do_PATCH(self):
        self._handle_write("PATCH")

    def do_DELETE(self):
        self._handle_write("DELETE")

    def _handle_write(self, method):
        path = self.path.split("?")[0]
        if path == "/api/login":
            if method != "POST":
                self._json({"error": "接口不存在"}, 404)
                return
            payload = self._read_json()
            password = str((payload or {}).get("password") or "")
            if not AUTH_PASSWORD or secrets.compare_digest(password, AUTH_PASSWORD):
                token = secrets.token_urlsafe(32)
                SESSIONS[token] = time.time() + SESSION_DAYS * 86400
                self._json({"ok": True}, cookie=self._session_cookie(token))
            else:
                self._json({"error": "密码不对"}, 401)
            return
        if path == "/api/logout":
            token = self._session_token()
            if token:
                SESSIONS.pop(token, None)
            self._json({"ok": True}, cookie=self._session_cookie("", expire=True))
            return
        if not self._is_authed():
            self._json({"error": "请先登录"}, 401)
            return
        batch_match = BATCH_ROUTE.match(path)
        item_match = ITEM_ROUTE.match(path)
        if batch_match is None and item_match is None and path != "/api/runs":
            self._json({"error": "接口不存在"}, 404)
            return
        payload = self._read_json()
        if payload is None:
            self._json({"error": "请求内容不是合法 JSON"}, 400)
            return
        print(f"[save] {method} {path} {json.dumps(payload, ensure_ascii=False)}", flush=True)

        conn = db()
        try:
            if path == "/api/runs":
                if method != "POST":
                    raise ApiError("接口不存在", 404)
                results = payload.get("results")
                if not isinstance(results, list) or not results:
                    raise ApiError("没有检查结果")
                clean_results = []
                for item in results[:20]:
                    if not isinstance(item, dict):
                        continue
                    clean_results.append(
                        {
                            "agent": str(item.get("agent") or "")[:40],
                            "name": str(item.get("name") or "")[:40],
                            "ok": bool(item.get("ok")),
                            "text": str(item.get("text") or "")[:500],
                        }
                    )
                ok_count = sum(1 for item in clean_results if item["ok"])
                with conn:
                    conn.execute(
                        "INSERT OR REPLACE INTO runs (date, ok, total, detail) VALUES (?, ?, ?, ?)",
                        (
                            today_key(),
                            ok_count,
                            len(clean_results),
                            json.dumps(clean_results, ensure_ascii=False),
                        ),
                    )
                self._json({"ok": True, "date": today_key(), "okCount": ok_count, "total": len(clean_results)})
                return
            if batch_match is not None:
                if method != "POST":
                    raise ApiError("接口不存在", 404)
                section = batch_match.group(1)
                field = payload.get("field")
                if field not in LIST_FIELDS:
                    raise ApiError("字段不存在")
                with conn:
                    apply_batch(conn, section, field, payload.get("ops") or {})
                self._json(load_section(conn, section))
                return

            section, resource, raw_id = item_match.group(1), item_match.group(2), item_match.group(3)
            item_id = int(raw_id) if raw_id else None
            if method == "POST" and resource == "items" and item_id is None:
                field = payload.get("field")
                if field not in LIST_FIELDS:
                    raise ApiError("字段不存在")
                name = clean_name(payload.get("name"))
                if not name:
                    raise ApiError("条件不能为空")
                days = parse_days(payload.get("days"))
                with conn:
                    add_items(conn, section, field, [{"name": name, "days": days}])
            elif method == "PATCH" and resource == "items" and item_id is not None:
                row = conn.execute(
                    "SELECT field FROM items WHERE id = ? AND section = ?", (item_id, section)
                ).fetchone()
                if row is None:
                    raise ApiError("这条条件不存在", 404)
                name = clean_name(payload.get("name"))
                if not name:
                    raise ApiError("条件不能为空")
                days = parse_days(payload.get("days")) if "days" in payload else None
                with conn:
                    rename_item(conn, section, row["field"], item_id, name, days)
            elif method == "DELETE" and resource == "items" and item_id is not None:
                row = conn.execute(
                    "SELECT field FROM items WHERE id = ? AND section = ?", (item_id, section)
                ).fetchone()
                if row is None:
                    raise ApiError("这条条件不存在", 404)
                with conn:
                    delete_item(conn, section, row["field"], item_id)
            elif method == "POST" and resource in ("funds", "income", "amounts") and item_id is None:
                field = resource if resource in AMOUNT_FIELDS else payload.get("field")
                if field not in AMOUNT_FIELDS:
                    raise ApiError("字段不存在")
                amount = clean_amount(payload.get("amount"))
                with conn:
                    set_amount(conn, section, field, amount)
            else:
                raise ApiError("接口不存在", 404)
            self._json(load_section(conn, section))
        except ApiError as error:
            self._json({"error": str(error)}, error.status)
        except sqlite3.IntegrityError:
            self._json({"error": "这个条件已经存在"}, 409)
        except sqlite3.Error:
            self._json({"error": "数据库错误，请重试"}, 500)
        finally:
            conn.close()

    # ---------- 工具 ----------

    def _read_json(self):
        try:
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b"{}"
            return json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return None

    # ---------- 登录 / 会话 ----------

    def _session_token(self):
        cookie = self.headers.get("Cookie") or ""
        for part in cookie.split(";"):
            name, _, value = part.strip().partition("=")
            if name == SESSION_COOKIE:
                return value
        return None

    def _is_authed(self):
        if not AUTH_PASSWORD:
            return True
        token = self._session_token()
        if not token:
            return False
        expiry = SESSIONS.get(token)
        if expiry is None or expiry < time.time():
            SESSIONS.pop(token, None)
            return False
        return True

    def _session_cookie(self, token, expire=False):
        cookie = f"{SESSION_COOKIE}={token}; Path=/; HttpOnly; SameSite=Lax"
        if expire:
            cookie += "; Max-Age=0"
        else:
            cookie += f"; Max-Age={SESSION_DAYS * 86400}"
        if (self.headers.get("X-Forwarded-Proto") or "").lower() == "https":
            cookie += "; Secure"
        return cookie

    def _redirect(self, location):
        self.send_response(302)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _send_login_page(self):
        body = LOGIN_PAGE.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, data, status=200, cookie=None):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(body)

    def end_headers(self):
        # 静态文件也禁用缓存，避免改了代码浏览器还跑旧版本。
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


class Server(ThreadingHTTPServer):
    request_queue_size = 128
    daemon_threads = True

    def handle_error(self, request, client_address):
        """浏览器提前关连接时不用刷一堆 traceback。"""
        error = sys.exc_info()[1]
        if isinstance(error, (ConnectionResetError, BrokenPipeError)):
            return
        super().handle_error(request, client_address)


def lan_addresses():
    """列出本机局域网 IPv4 地址（手机访问用）。"""
    addresses = set()
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            ip = info[4][0]
            if not ip.startswith("127."):
                addresses.add(ip)
    except OSError:
        pass
    if not addresses:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.connect(("8.8.8.8", 80))
                addresses.add(sock.getsockname()[0])
        except OSError:
            pass
    return sorted(addresses)


def main():
    init_db()
    migrate_legacy_json()
    argv = sys.argv[1:]
    flags = {item for item in argv if item.startswith("--")}
    positional = [item for item in argv if not item.startswith("--")]
    port = int(positional[0]) if positional else int(os.environ.get("SUPERSYS_PORT", "8000"))
    host = os.environ.get("SUPERSYS_HOST") or ("0.0.0.0" if "--lan" in flags else "127.0.0.1")
    server = Server((host, port), Handler)
    print(f"supersys 已启动：http://127.0.0.1:{port}", flush=True)
    print("登录保护：已开启（SUPERSYS_PASSWORD）" if AUTH_PASSWORD else "登录保护：未开启（本地模式）", flush=True)
    if host == "0.0.0.0":
        for ip in lan_addresses():
            print(f"手机（同一 Wi-Fi）访问：http://{ip}:{port}", flush=True)
        print("提示：这是局域网访问，公共 Wi-Fi 下请不要用 --lan。", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
