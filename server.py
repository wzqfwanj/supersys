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
import threading
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

# 云端模式（邮箱验证码登录 + 每用户独立数据库）；不设置就是本地单机模式。
CLOUD_MODE = os.environ.get("SUPERSYS_CLOUD", "") == "1"
SESSION_COOKIE = "supersys_session"
SESSION_DAYS = 30
CODE_TTL = 300  # 验证码 5 分钟有效
CODE_RESEND = 60  # 同一邮箱 60 秒内不重复发
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
# 发信配置（QQ 邮箱等 SMTP）；没配就是测试模式（验证码写日志并回显）
SMTP_HOST = os.environ.get("SUPERSYS_SMTP_HOST", "")
SMTP_PORT = int(os.environ.get("SUPERSYS_SMTP_PORT", "465"))
SMTP_USER = os.environ.get("SUPERSYS_SMTP_USER", "")
SMTP_PASS = os.environ.get("SUPERSYS_SMTP_PASS", "")
SMTP_FROM = os.environ.get("SUPERSYS_SMTP_FROM", "") or SMTP_USER
EMAIL_MODE = "smtp" if SMTP_HOST and SMTP_USER and SMTP_PASS else "test"
# 防刷：同一邮箱 60 秒一条；全站每天发送上限（防短信/邮件轰炸）
CODE_DAILY_CAP = int(os.environ.get("SUPERSYS_CODE_DAILY_CAP", "200"))
_CODE_SENT = {}  # (ip, 日期) -> 当天已发次数
_CODE_LOCK = threading.Lock()

LOGIN_PAGE = r"""<!DOCTYPE html>
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
  <p class="hint">邮箱验证码登录</p>
  <input id="email" type="email" inputmode="email" autocomplete="email" placeholder="邮箱">
  <div class="code-row">
    <input id="code" type="text" inputmode="numeric" autocomplete="one-time-code" placeholder="验证码" maxlength="6">
    <button id="send" type="button">获取验证码</button>
  </div>
  <button type="submit">登录</button>
  <p id="msg" class="msg"></p>
</form>
<script>
const form = document.getElementById("login-form");
const msg = document.getElementById("msg");
const sendButton = document.getElementById("send");
const emailInput = document.getElementById("email");
const codeInput = document.getElementById("code");
let countdown = null;

async function post(path, body) {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || "请求失败");
  return data;
}

sendButton.addEventListener("click", async () => {
  const email = emailInput.value.trim();
  msg.textContent = "";
  if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) { msg.textContent = "请输入正确的邮箱"; return; }
  try {
    const data = await post("api/auth/request-code", { email });
    if (data.devCode) {
      codeInput.value = data.devCode;
      msg.textContent = "测试模式验证码：" + data.devCode;
    } else {
      msg.textContent = "验证码已发送，请查收邮箱（含垃圾箱）";
    }
    let left = 60;
    sendButton.disabled = true;
    sendButton.textContent = left + "s";
    clearInterval(countdown);
    countdown = setInterval(() => {
      left -= 1;
      if (left <= 0) {
        clearInterval(countdown);
        sendButton.disabled = false;
        sendButton.textContent = "获取验证码";
      } else {
        sendButton.textContent = left + "s";
      }
    }, 1000);
  } catch (err) {
    msg.textContent = err.message;
  }
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  msg.textContent = "";
  try {
    await post("api/auth/verify", { email: emailInput.value.trim(), code: codeInput.value.trim() });
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
  .code-row { display: flex; gap: 8px; margin-top: 10px; }
  .code-row input { flex: 1; }
  .code-row button { width: auto; margin-top: 0; white-space: nowrap; padding: 12px 14px; font-size: 14px; }
  button {
    width: 100%; margin-top: 10px; padding: 12px; border: 1px solid #e8e8e8; border-radius: 8px;
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


# ---------- 账号 / 会话 / 短信（云端模式） ----------

USERS_DIR = os.path.join(os.path.dirname(os.path.abspath(DB_FILE)), "users")
AUTH_DB = os.path.join(os.path.dirname(os.path.abspath(DB_FILE)), "auth.db")


def auth_db():
    conn = sqlite3.connect(AUTH_DB, timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def init_auth_db():
    """用户、验证码、会话都存在 auth.db；每个用户的数据单独一个 users/<id>.db。"""
    os.makedirs(USERS_DIR, exist_ok=True)
    conn = auth_db()
    try:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(users)").fetchall()}
        if columns and "email" not in columns:
            # 旧版是按手机号注册的，补一列 email 兼容（旧手机号账号数据保留）
            conn.executescript(
                """
                CREATE TABLE users_new (
                    id      INTEGER PRIMARY KEY AUTOINCREMENT,
                    phone   TEXT,
                    email   TEXT,
                    created TEXT NOT NULL
                );
                INSERT INTO users_new (id, phone, created)
                    SELECT id, phone, created FROM users;
                DROP TABLE users;
                ALTER TABLE users_new RENAME TO users;
                """
            )
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id      INTEGER PRIMARY KEY AUTOINCREMENT,
                phone   TEXT,
                email   TEXT,
                created TEXT NOT NULL
            );
            DROP TABLE IF EXISTS codes;
            CREATE TABLE IF NOT EXISTS codes (
                email    TEXT PRIMARY KEY,
                code     TEXT NOT NULL,
                expires  REAL NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0,
                sent_at  REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sessions (
                token   TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                expires REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS email_limits (
                email     TEXT PRIMARY KEY,
                last_sent REAL NOT NULL
            );
            CREATE UNIQUE INDEX IF NOT EXISTS users_email_unique
                ON users (email) WHERE email IS NOT NULL;
            CREATE UNIQUE INDEX IF NOT EXISTS users_phone_unique
                ON users (phone) WHERE phone IS NOT NULL;
            """
        )
        conn.commit()
    finally:
        conn.close()


def user_db_path(user_id):
    return os.path.join(USERS_DIR, f"{user_id}.db")


def init_user_db(user_id, email=None):
    """给用户建独立数据库；现有数据带过去（只带一次，归属指定邮箱）。"""
    path = user_db_path(user_id)
    if os.path.exists(path):
        return path
    os.makedirs(USERS_DIR, exist_ok=True)
    owner_email = os.environ.get("SUPERSYS_OWNER_EMAIL", "").strip().lower()
    claim_legacy = bool(owner_email) and (email or "").strip().lower() == owner_email
    conn = sqlite3.connect(path, timeout=5)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(SCHEMA)
        if claim_legacy:
            # 优先接管之前手机号账号的数据（users/1.db），否则用本地 data.db
            source = user_db_path(1) if os.path.exists(user_db_path(1)) else DB_FILE
            if os.path.exists(source):
                src = sqlite3.connect(source)
                try:
                    src.backup(conn)
                finally:
                    src.close()
        conn.commit()
    finally:
        conn.close()
    return path


def db_for_user(user_id):
    """云端模式按用户开库；本地模式还是直接用 data.db。"""
    if not CLOUD_MODE or user_id is None:
        return db()
    init_user_db(user_id)
    conn = sqlite3.connect(user_db_path(user_id), timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def check_daily_cap(client_ip):
    """全站每天最多发多少条验证码，防止被刷。"""
    day = datetime.now().strftime("%Y-%m-%d")
    with _CODE_LOCK:
        count = _CODE_SENT.get("all", 0)
        if count >= CODE_DAILY_CAP:
            raise ApiError("今天的验证码发送次数已达上限，请明天再试", 429)
        _CODE_SENT["all"] = count + 1
        _CODE_SENT.setdefault("day", day)


def gen_code():
    return f"{secrets.randbelow(1000000):06d}"


def save_code(email, code):
    conn = auth_db()
    try:
        with conn:
            conn.execute(
                "INSERT OR REPLACE INTO codes (email, code, expires, attempts, sent_at) VALUES (?, ?, ?, 0, ?)",
                (email, code, time.time() + CODE_TTL, time.time()),
            )
    finally:
        conn.close()


def send_email(email, code):
    """测试模式：验证码写到服务器日志；配了 SMTP 就发真邮件。"""
    if EMAIL_MODE != "smtp":
        print(f"[email-test] {email} 验证码 {code}", flush=True)
        return
    try:
        import smtplib
        from email.header import Header
        from email.mime.text import MIMEText
        from email.utils import formataddr

        body = (
            f"你的 supersys 验证码是：{code}\n"
            f"5 分钟内有效。如果不是你本人操作，请忽略这封邮件。"
        )
        message = MIMEText(body, "plain", "utf-8")
        message["Subject"] = Header("supersys 验证码", "utf-8")
        message["From"] = formataddr(("supersys", SMTP_FROM))
        message["To"] = email
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=20) as smtp:
            smtp.login(SMTP_USER, SMTP_PASS)
            smtp.sendmail(SMTP_FROM, [email], message.as_string())
    except Exception:
        raise ApiError("验证码邮件发送失败，请稍后再试")


def session_user(token):
    if not token:
        return None
    conn = auth_db()
    try:
        row = conn.execute(
            "SELECT user_id, expires FROM sessions WHERE token = ?", (token,)
        ).fetchone()
        if row is None or row["expires"] < time.time():
            with conn:
                conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
            return None
        return row["user_id"]
    finally:
        conn.close()


def session_email(user_id):
    conn = auth_db()
    try:
        row = conn.execute("SELECT email FROM users WHERE id = ?", (user_id,)).fetchone()
        return row["email"] if row else None
    finally:
        conn.close()



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
        self.user_id = None
        if CLOUD_MODE:
            if path == "/login":
                self._send_login_page()
                return
            if path == "/api/session":
                user_id = self._authed_user()
                self._json(
                    {
                        "auth": True,
                        "loggedIn": user_id is not None,
                        "email": session_email(user_id) if user_id else None,
                    }
                )
                return
            if path.startswith("/api/auth/"):
                self._json({"error": "接口不存在"}, 404)
                return
            user_id = self._authed_user()
            if user_id is None:
                if path.startswith("/api/"):
                    self._json({"error": "请先登录"}, 401)
                else:
                    self._redirect("login")
                return
            self.user_id = user_id
        elif path == "/api/session":
            self._json({"auth": False, "loggedIn": True, "mode": "local"})
            return
        if path == "/api/sections":
            self._json({"app": "supersys", "sections": SECTIONS, "agents": AGENTS})
        elif path in ("/api/plan", "/api/status"):
            section = path.rsplit("/", 1)[1]
            conn = db_for_user(self.user_id)
            try:
                self._json(load_section(conn, section))
            finally:
                conn.close()
        elif path == "/api/runs":
            conn = db_for_user(self.user_id)
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
        self.user_id = None
        if CLOUD_MODE:
            if path.startswith("/api/auth/"):
                self._handle_auth_write(path, method)
                return
            if path == "/api/logout":
                self._clear_session()
                return
            user_id = self._authed_user()
            if user_id is None:
                self._json({"error": "请先登录"}, 401)
                return
            self.user_id = user_id
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

        conn = db_for_user(self.user_id)
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

    def _authed_user(self):
        return session_user(self._session_token())

    def _clear_session(self):
        token = self._session_token()
        if token:
            conn = auth_db()
            try:
                with conn:
                    conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
            finally:
                conn.close()
        self._json({"ok": True}, cookie=self._session_cookie("", expire=True))

    def _handle_auth_write(self, path, method):
        if method != "POST":
            self._json({"error": "接口不存在"}, 404)
            return
        payload = self._read_json() or {}
        if path == "/api/auth/request-code":
            self._request_code(payload)
        elif path == "/api/auth/verify":
            self._verify_code(payload)
        elif path == "/api/auth/logout":
            self._clear_session()
        else:
            self._json({"error": "接口不存在"}, 404)

    def _request_code(self, payload):
        email = str(payload.get("email") or "").strip().lower()
        if not EMAIL_RE.match(email):
            self._json({"error": "邮箱格式不对"}, 400)
            return
        conn = auth_db()
        try:
            row = conn.execute(
                "SELECT last_sent FROM email_limits WHERE email = ?", (email,)
            ).fetchone()
            if row and time.time() - row["last_sent"] < CODE_RESEND:
                self._json({"error": "验证码刚发过，请稍后再试"}, 429)
                return
        finally:
            conn.close()
        try:
            check_daily_cap(self.client_address[0])
        except ApiError as error:
            self._json({"error": str(error)}, error.status)
            return
        code = gen_code()
        save_code(email, code)
        try:
            send_email(email, code)
        except ApiError as error:
            self._json({"error": str(error)}, 500)
            return
        conn = auth_db()
        try:
            with conn:
                conn.execute(
                    "INSERT OR REPLACE INTO email_limits (email, last_sent) VALUES (?, ?)",
                    (email, time.time()),
                )
        finally:
            conn.close()
        if EMAIL_MODE == "smtp":
            self._json({"ok": True})
        else:
            self._json({"ok": True, "testMode": True, "devCode": code})

    def _verify_code(self, payload):
        email = str(payload.get("email") or "").strip().lower()
        code = str(payload.get("code") or "").strip()
        if not EMAIL_RE.match(email) or not code:
            self._json({"error": "邮箱或验证码不对"}, 400)
            return
        conn = auth_db()
        try:
            row = conn.execute(
                "SELECT code, expires, attempts FROM codes WHERE email = ?", (email,)
            ).fetchone()
            if row is None:
                self._json({"error": "请先获取验证码"}, 400)
                return
            if row["expires"] < time.time():
                self._json({"error": "验证码已过期，请重新获取"}, 400)
                return
            if row["attempts"] >= 5:
                self._json({"error": "尝试次数太多，请重新获取验证码"}, 429)
                return
            if not secrets.compare_digest(row["code"], code):
                with conn:
                    conn.execute("UPDATE codes SET attempts = attempts + 1 WHERE email = ?", (email,))
                self._json({"error": "验证码不对"}, 400)
                return
            is_new = conn.execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone() is None
            with conn:
                conn.execute("DELETE FROM codes WHERE email = ?", (email,))
                if is_new:
                    conn.execute(
                        "INSERT INTO users (email, created) VALUES (?, ?)",
                        (email, today_key()),
                    )
                user_row = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
                user_id = user_row["id"]
                token = secrets.token_urlsafe(32)
                conn.execute(
                    "INSERT INTO sessions (token, user_id, expires) VALUES (?, ?, ?)",
                    (token, user_id, time.time() + SESSION_DAYS * 86400),
                )
        finally:
            conn.close()
        try:
            init_user_db(user_id, email)
        except Exception:
            self._json({"error": "初始化用户数据失败"}, 500)
            return
        owner_email = os.environ.get("SUPERSYS_OWNER_EMAIL", "").strip().lower()
        if is_new and owner_email and email == owner_email:
            # 旧数据已经交接给这个邮箱账号，清掉之前的手机号占位账号
            conn = auth_db()
            try:
                with conn:
                    conn.execute("DELETE FROM users WHERE email IS NULL")
            finally:
                conn.close()
        self._json({"ok": True, "email": email}, cookie=self._session_cookie(token))

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
    if CLOUD_MODE:
        init_auth_db()
    argv = sys.argv[1:]
    flags = {item for item in argv if item.startswith("--")}
    positional = [item for item in argv if not item.startswith("--")]
    port = int(positional[0]) if positional else int(os.environ.get("SUPERSYS_PORT", "8000"))
    host = os.environ.get("SUPERSYS_HOST") or ("0.0.0.0" if "--lan" in flags else "127.0.0.1")
    server = Server((host, port), Handler)
    print(f"supersys 已启动：http://127.0.0.1:{port}", flush=True)
    if CLOUD_MODE:
        print(
            "云端模式：邮箱验证码登录（" + ("SMTP 已配置" if EMAIL_MODE == "smtp" else "测试模式，验证码写日志") + "）",
            flush=True,
        )
    else:
        print("本地模式：无需登录", flush=True)
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
