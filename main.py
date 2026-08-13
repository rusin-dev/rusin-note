#!/usr/bin/env python3
"""
rusin-note - 极简在线笔记服务 (支持匿名公开笔记 /world/ 和私有用户笔记 /user/)
- 公开笔记无需登录，直接访问 /world/<id> 即可编辑
- 私有笔记需注册登录，路径 /user/<username>/<note_id>
- 顶部导航栏，登录/注册/登出
- 密码强度要求可配置
- 支持纯数字ID自动重定向到公开笔记
- 统计页面 /count
- 免责声明 /disclaimer，支持Markdown渲染
- Cookie使用SHA-256哈希存储，会话支持超时清除
- 支持将公开笔记渲染为 Markdown（只读）：/world/<id>/md
- 支持将私有笔记渲染为 Markdown（仅本人）：/user/<用户名>/<笔记ID>/md
- 分享功能：私有笔记可生成 64 位分享链接 /share/<token>（支持只读/可编辑）
- 分享管理：/user/<用户名>/shares/（创建/删除/查看次数）
- XSS防护：使用bleach清洗Markdown渲染后的HTML
- GET请求独立限流（45次/分钟）
- 编辑区 Tab 键插入 4 个空格
"""

import os
import re
import json
import time
import html
import random
import string
import urllib.parse
import hashlib
import secrets
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from collections import defaultdict
from threading import Lock, Thread

# ---------- 尝试导入 Markdown 和 Bleach（用于安全渲染） ----------
try:
    import markdown
    MARKDOWN_AVAILABLE = True
except ImportError:
    markdown = None
    MARKDOWN_AVAILABLE = False

try:
    import bleach
    BLEACH_AVAILABLE = True
except ImportError:
    bleach = None
    BLEACH_AVAILABLE = False

# ---------- 加载配置 ----------
CONFIG_FILE = "config.json"
DEFAULT_CONFIG = {
    "max_note_size_mb": 5,
    "sitename": "如形の笔记",
    "rate_limit": {
        "window_seconds": 60,
        "max_requests": 30
    },
    "get_rate_limit": {                     # ADDED: GET请求独立限流
        "window_seconds": 60,
        "max_requests": 45
    },
    "id_generation": {
        "length": 6,
        "use_uppercase": True,
        "use_lowercase": True,
        "use_digits": True
    },
    "session_timeout": {
        "enabled": False,
        "minutes": 60
    },
    "password_policy": {
        "min_length": 8,
        "require_uppercase": True,
        "require_lowercase": True,
        "require_digits": True,
        "require_special": True
    }
}

def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"[警告] 读取配置文件失败，使用默认配置: {e}")
    return DEFAULT_CONFIG

config = load_config()
SITE_NAME = config.get("sitename", "") 
MAX_CONTENT_BYTES = config.get("max_note_size_mb", 5) * 1024 * 1024
RATE_WINDOW = config.get("rate_limit", {}).get("window_seconds", 60)
RATE_MAX = config.get("rate_limit", {}).get("max_requests", 30)

# GET限流配置
GET_RATE_CFG = config.get("get_rate_limit", DEFAULT_CONFIG["get_rate_limit"])
GET_RATE_WINDOW = GET_RATE_CFG.get("window_seconds", 60)
GET_RATE_MAX = GET_RATE_CFG.get("max_requests", 45)

# 会话超时配置
SESSION_TIMEOUT_ENABLED = config.get("session_timeout", {}).get("enabled", False)
SESSION_TIMEOUT_MINUTES = config.get("session_timeout", {}).get("minutes", 60)
SESSION_TIMEOUT_SECONDS = SESSION_TIMEOUT_MINUTES * 60

# socket 超时（秒）：防止慢速连接长期占用线程（BUG-008）
SOCKET_TIMEOUT = 60
# 后台会话清理线程的间隔（秒）（BUG-013）
SESSION_CLEANUP_INTERVAL = 300

# ---------- ID生成配置 ----------
ID_CFG = config.get("id_generation", DEFAULT_CONFIG["id_generation"])
ID_LENGTH = ID_CFG.get("length", 6)
USE_UPPER = ID_CFG.get("use_uppercase", True)
USE_LOWER = ID_CFG.get("use_lowercase", True)
USE_DIGIT = ID_CFG.get("use_digits", True)

_charset_parts = []
if USE_UPPER:
    _charset_parts.append(string.ascii_uppercase)
if USE_LOWER:
    _charset_parts.append(string.ascii_lowercase)
if USE_DIGIT:
    _charset_parts.append(string.digits)
if not _charset_parts:
    _charset_parts = [string.ascii_lowercase, string.digits]
ID_CHARSET = ''.join(_charset_parts)

# ---------- 密码策略配置 ----------
PW_POLICY = config.get("password_policy", DEFAULT_CONFIG["password_policy"])
PW_MIN_LENGTH = PW_POLICY.get("min_length", 8)
PW_REQUIRE_UPPER = PW_POLICY.get("require_uppercase", True)
PW_REQUIRE_LOWER = PW_POLICY.get("require_lowercase", True)
PW_REQUIRE_DIGIT = PW_POLICY.get("require_digits", True)
PW_REQUIRE_SPECIAL = PW_POLICY.get("require_special", True)

def get_password_requirements_description():
    parts = []
    parts.append(f"至少 {PW_MIN_LENGTH} 位")
    if PW_REQUIRE_UPPER:
        parts.append("大写字母")
    if PW_REQUIRE_LOWER:
        parts.append("小写字母")
    if PW_REQUIRE_DIGIT:
        parts.append("数字")
    if PW_REQUIRE_SPECIAL:
        parts.append("特殊符号 (不含 / \\ ( ) \" ' )")
    return "、".join(parts)

# ---------- 用户与会话存储 ----------
USER_FILE = "users.json"
SESSION_FILE = "sessions.json"
NOTES_BASE = "notes"
os.makedirs(NOTES_BASE, exist_ok=True)

users = {}
sessions = {}  # 格式: {sha256(token): {"username": str, "created_at": float}}
users_lock = Lock()
sessions_lock = Lock()

# 禁止的笔记ID（与路由冲突）
FORBIDDEN_NOTE_IDS = {"user", "world", "shares"}

def load_users():
    global users
    if os.path.exists(USER_FILE):
        try:
            with open(USER_FILE, "r", encoding="utf-8") as f:
                users = json.load(f)
        except Exception:
            users = {}
    else:
        users = {}

def save_users():
    with users_lock:
        try:
            with open(USER_FILE, "w", encoding="utf-8") as f:
                json.dump(users, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"[错误] 保存用户数据失败: {e}")

def load_sessions():
    global sessions
    if os.path.exists(SESSION_FILE):
        try:
            with open(SESSION_FILE, "r", encoding="utf-8") as f:
                sessions = json.load(f)
        except Exception:
            sessions = {}
    else:
        sessions = {}

def save_sessions():
    with sessions_lock:
        try:
            with open(SESSION_FILE, "w", encoding="utf-8") as f:
                json.dump(sessions, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"[错误] 保存会话数据失败: {e}")

load_users()
load_sessions()

# ---------- 分享存储 ----------
SHARE_FILE = "shares.json"
# 分享链接 token：64 位大小写字母+数字（防爆破）
SHARE_TOKEN_LENGTH = 64
SHARE_TOKEN_CHARSET = string.ascii_letters + string.digits

shares = {}  # 格式: {token: {"owner": str, "note_id": str, "created_at": float, "editable": bool, "views": int}}
shares_lock = Lock()

def load_shares():
    global shares
    if os.path.exists(SHARE_FILE):
        try:
            with open(SHARE_FILE, "r", encoding="utf-8") as f:
                shares = json.load(f)
        except Exception:
            shares = {}
    else:
        shares = {}

def save_shares():
    with shares_lock:
        try:
            with open(SHARE_FILE, "w", encoding="utf-8") as f:
                json.dump(shares, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"[错误] 保存分享数据失败: {e}")

def generate_share_token() -> str:
    return ''.join(secrets.choice(SHARE_TOKEN_CHARSET) for _ in range(SHARE_TOKEN_LENGTH))

def create_share(username: str, note_id: str, editable: bool) -> str:
    """创建分享，返回 64 位分享 token"""
    token = generate_share_token()
    with shares_lock:
        shares[token] = {
            "owner": username,
            "note_id": note_id,
            "created_at": time.time(),
            "editable": bool(editable),
            "views": 0,
        }
    save_shares()
    return token

def get_share(token: str) -> dict | None:
    with shares_lock:
        return shares.get(token)

def delete_share(username: str, token: str) -> bool:
    """仅分享者本人可删除，返回是否删除成功"""
    with shares_lock:
        share = shares.get(token)
        if share is None or share["owner"] != username:
            return False
        del shares[token]
    save_shares()
    return True

def increment_share_views(token: str):
    """每次访问分享链接时计数（持久化到 shares.json）"""
    with shares_lock:
        share = shares.get(token)
        if share is None:
            return
        share["views"] = share.get("views", 0) + 1
    save_shares()

def list_user_shares(username: str) -> list:
    """返回该用户创建的所有分享 [(token, share), ...]"""
    with shares_lock:
        return [(tok, dict(s)) for tok, s in shares.items() if s.get("owner") == username]

load_shares()

# ---------- 密码与认证工具 ----------
def generate_salt():
    return secrets.token_hex(8)

def hash_password(password: str, salt: str) -> str:
    return hashlib.sha256((salt + password).encode()).hexdigest()

def verify_password(password: str, salt: str, hashed: str) -> bool:
    return hash_password(password, salt) == hashed

def generate_session_token():
    return secrets.token_hex(32)

def hash_token(token: str) -> str:
    """对token进行SHA-256哈希"""
    return hashlib.sha256(token.encode()).hexdigest()

def create_session(username: str) -> str:
    """创建会话，返回原始token，存储时使用哈希作为键"""
    token = generate_session_token()
    token_hash = hash_token(token)
    with sessions_lock:
        sessions[token_hash] = {
            "username": username,
            "created_at": time.time()
        }
    save_sessions()
    return token

def delete_session(token: str):
    token_hash = hash_token(token)
    with sessions_lock:
        if token_hash in sessions:
            del sessions[token_hash]
    save_sessions()

def get_session_user(token: str) -> str | None:
    """验证token，返回用户名，若超时或不存在则返回None"""
    token_hash = hash_token(token)
    with sessions_lock:
        session = sessions.get(token_hash)
        if not session:
            return None
        # 检查超时
        if SESSION_TIMEOUT_ENABLED:
            elapsed = time.time() - session["created_at"]
            if elapsed > SESSION_TIMEOUT_SECONDS:
                # 删除过期会话
                del sessions[token_hash]
                save_sessions()
                return None
        return session["username"]

# ---------- 过期会话清理（BUG-013） ----------
def purge_expired_sessions() -> int:
    """删除已过期的会话，返回删除数量（仅在启用会话超时时生效）"""
    if not SESSION_TIMEOUT_ENABLED:
        return 0
    now = time.time()
    cutoff = now - SESSION_TIMEOUT_SECONDS
    expired = []
    with sessions_lock:
        for token_hash, sess in sessions.items():
            if sess["created_at"] < cutoff:
                expired.append(token_hash)
        for token_hash in expired:
            del sessions[token_hash]
    if expired:
        save_sessions()
        print(f"[清理] 已清除 {len(expired)} 个过期会话")
    return len(expired)

def session_cleanup_loop():
    """后台线程：定时清除过期会话"""
    while True:
        time.sleep(SESSION_CLEANUP_INTERVAL)
        try:
            purge_expired_sessions()
        except Exception as e:
            print(f"[错误] 会话清理失败: {e}")

# ---------- 密码复杂度检查（根据配置） ----------
def check_password_complexity(password: str) -> bool:
    if len(password) < PW_MIN_LENGTH:
        return False
    if PW_REQUIRE_UPPER and not re.search(r'[A-Z]', password):
        return False
    if PW_REQUIRE_LOWER and not re.search(r'[a-z]', password):
        return False
    if PW_REQUIRE_DIGIT and not re.search(r'[0-9]', password):
        return False
    if PW_REQUIRE_SPECIAL:
        # 特殊字符：排除 / \ ( ) " '
        excluded = r'\/\(\)"\''
        special_pattern = r'[^A-Za-z0-9' + re.escape(excluded) + r']'
        if not re.search(special_pattern, password):
            return False
    return True

# ---------- IP限流（POST） ----------
ip_requests = defaultdict(list)
ip_lock = Lock()
MAX_RECORDS_PER_IP = RATE_MAX * 2
IP_SWEEP_INTERVAL = 500  # 每 N 次请求清理一次已空的 IP 键，防止字典无限增长（BUG-011）

def cleanup_old_records(records, cutoff):
    i = 0
    while i < len(records):
        if records[i] <= cutoff:
            records.pop(i)
        else:
            i += 1

def _sweep_rate_limit_entries(records_dict, window_seconds):
    """清理所有 IP 的过期记录，并删除已无记录的键（调用方须已持有对应锁）"""
    cutoff = time.time() - window_seconds
    for key in list(records_dict.keys()):
        records = records_dict[key]
        cleanup_old_records(records, cutoff)
        if not records:
            del records_dict[key]

_ip_post_sweep_counter = 0

def is_rate_limited(ip: str) -> bool:
    global _ip_post_sweep_counter
    now = time.time()
    with ip_lock:
        records = ip_requests[ip]
        cutoff = now - RATE_WINDOW
        cleanup_old_records(records, cutoff)
        if len(records) >= RATE_MAX:
            return True
        records.append(now)
        if len(records) > MAX_RECORDS_PER_IP:
            del records[:len(records) - MAX_RECORDS_PER_IP]
        _ip_post_sweep_counter += 1
        if _ip_post_sweep_counter >= IP_SWEEP_INTERVAL:
            _ip_post_sweep_counter = 0
            _sweep_rate_limit_entries(ip_requests, RATE_WINDOW)
        return False

# ---------- IP限流（GET） ----------
ip_get_requests = defaultdict(list)
ip_get_lock = Lock()
MAX_GET_RECORDS_PER_IP = GET_RATE_MAX * 2
GET_SWEEP_INTERVAL = 500  # 每 N 次请求清理一次已空的 IP 键（BUG-011）

_ip_get_sweep_counter = 0

def is_get_rate_limited(ip: str) -> bool:
    global _ip_get_sweep_counter
    now = time.time()
    with ip_get_lock:
        records = ip_get_requests[ip]
        cutoff = now - GET_RATE_WINDOW
        cleanup_old_records(records, cutoff)  # 复用清理函数
        if len(records) >= GET_RATE_MAX:
            return True
        records.append(now)
        if len(records) > MAX_GET_RECORDS_PER_IP:
            del records[:len(records) - MAX_GET_RECORDS_PER_IP]
        _ip_get_sweep_counter += 1
        if _ip_get_sweep_counter >= GET_SWEEP_INTERVAL:
            _ip_get_sweep_counter = 0
            _sweep_rate_limit_entries(ip_get_requests, GET_RATE_WINDOW)
        return False

# ---------- 笔记文件操作 ----------
def validate_username(username: str) -> bool:
    return bool(re.match(r'^[a-zA-Z0-9_\-]+$', username))

def validate_note_id(note_id: str) -> bool:
    if note_id in FORBIDDEN_NOTE_IDS:
        return False
    return bool(re.match(r'^[a-zA-Z0-9_\-]+$', note_id))

def get_user_note_dir(username: str) -> str:
    path = os.path.join(NOTES_BASE, username)
    os.makedirs(path, exist_ok=True)
    return path

def get_note_path(username: str, note_id: str) -> str | None:
    if not validate_username(username) or not validate_note_id(note_id):
        return None
    user_dir = get_user_note_dir(username)
    safe_id = os.path.basename(note_id)
    return os.path.join(user_dir, f"{safe_id}.txt")

def read_note(username: str, note_id: str) -> str:
    path = get_note_path(username, note_id)
    if path is None:
        return ""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return ""
    except (IOError, OSError):
        return ""

def write_note(username: str, note_id: str, content: str) -> bool:
    path = get_note_path(username, note_id)
    if path is None:
        return False
    if content == "":
        try:
            if os.path.exists(path):
                os.remove(path)
            return True
        except OSError:
            return False
    try:
        temp_path = path + ".tmp"
        with open(temp_path, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path, path)
        return True
    except (IOError, OSError):
        try:
            if os.path.exists(temp_path):
                os.remove(temp_path)
        except:
            pass
        return False

def list_user_notes(username: str) -> list[str]:
    user_dir = get_user_note_dir(username)
    notes = []
    for fname in os.listdir(user_dir):
        if fname.endswith(".txt"):
            note_id = fname[:-4]
            if validate_note_id(note_id):
                notes.append(note_id)
    return notes

# ---------- 统计函数 ----------
def get_stats():
    """返回 (public_count, public_size, private_count, private_size, user_count)"""
    public_count = 0
    public_size = 0
    private_count = 0
    private_size = 0
    user_count = len(users)

    if not os.path.exists(NOTES_BASE):
        return (0, 0, 0, 0, user_count)

    for item in os.listdir(NOTES_BASE):
        item_path = os.path.join(NOTES_BASE, item)
        if not os.path.isdir(item_path):
            continue
        if item == "public":
            for fname in os.listdir(item_path):
                if fname.endswith(".txt"):
                    public_count += 1
                    try:
                        public_size += os.path.getsize(os.path.join(item_path, fname))
                    except:
                        pass
        else:
            for fname in os.listdir(item_path):
                if fname.endswith(".txt"):
                    private_count += 1
                    try:
                        private_size += os.path.getsize(os.path.join(item_path, fname))
                    except:
                        pass
    return (public_count, public_size, private_count, private_size, user_count)

# ---------- 随机ID生成 ----------
def generate_random_id() -> str:
    while True:
        rid = ''.join(random.choices(ID_CHARSET, k=ID_LENGTH))
        if rid not in FORBIDDEN_NOTE_IDS:
            return rid

# ---------- HTTP 处理器 ----------
class NoteHandler(BaseHTTPRequestHandler):
    _HTML_HEADER = "text/html; charset=utf-8"

    def log_request(self, code='-', size='-'):
        if code != 200:
            super().log_request(code, size)

    def get_client_ip(self) -> str:
        forwarded = self.headers.get("X-Forwarded-For")
        if forwarded:
            ip = forwarded.split(",", 1)[0].strip()
            return ip
        real_ip = self.headers.get("X-Real-IP")
        if real_ip:
            return real_ip.strip()
        return self.client_address[0]

    def get_session_cookie(self) -> str | None:
        cookie = self.headers.get("Cookie")
        if cookie:
            for pair in cookie.split(";"):
                pair = pair.strip()
                if pair.startswith("session="):
                    return pair[len("session="):]
        return None

    def get_current_user(self) -> str | None:
        token = self.get_session_cookie()
        if token:
            return get_session_user(token)
        return None

    def is_authenticated(self, username: str) -> bool:
        return self.get_current_user() == username

    # ---------- 导航栏 ----------
    def _get_navbar(self, current_user=None) -> str:
        if current_user is None:
            current_user = self.get_current_user()
        if current_user:
            return f"""
                <div class="navbar">
                    <span class="user-info">用户: {html.escape(current_user)}</span>
                    <span class="nav-links">
                        <a href="/user/{html.escape(current_user)}/">我的笔记</a>
                        <a href="/user/{html.escape(current_user)}/new">新建笔记</a>
                        <a href="/user/{html.escape(current_user)}/shares/">分享管理</a>
                        <a href="/logout">登出</a>
                    </span>
                </div>
            """
        else:
            return """
                <div class="navbar">
                    <span class="user-info">匿名</span>
                    <span class="nav-links">
                        <a href="/register">注册</a>
                        <a href="/login">登录</a>
                        <a href="/count">统计</a>
                        <a href="/disclaimer">免责声明</a>
                    </span>
                </div>
            """

    # ---------- 辅助响应 ----------
    def _send_redirect(self, location):
        self.send_response(302)
        self.send_header("Location", location)
        self.end_headers()

    def _set_session_cookie(self, token: str):
        self.send_header("Set-Cookie", f"session={token}; Path=/; HttpOnly; SameSite=Lax")

    def _clear_session_cookie(self):
        self.send_header("Set-Cookie", "session=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax")

    # ---------- 通用 HTML 渲染 ----------
    def _render_base(self, body: str, title="rusin-note", navbar=None, extra_head=""):
        if SITE_NAME:
            full_title = f"{title} | {SITE_NAME}"
        else:
            full_title = title
        if navbar is None:
            navbar = self._get_navbar()
        return f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{html.escape(full_title)}</title>
    <link rel="icon" href="/favicon.ico" type="image/x-icon">
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }}
        .navbar {{
            background: #f8f9fa;
            padding: 10px 24px;
            border-bottom: 1px solid #ddd;
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            font-size: 14px;
        }}
        .navbar .user-info {{
            font-weight: 500;
        }}
        .navbar .nav-links a {{
            margin-left: 16px;
            color: #0366d6;
            text-decoration: none;
        }}
        .navbar .nav-links a:hover {{
            text-decoration: underline;
        }}
        .container {{
            max-width: 900px;
            margin: 20px auto;
            padding: 0 20px;
        }}
        h1 {{ font-weight: 400; border-bottom: 1px solid #eee; padding-bottom: 10px; }}
        .form-group {{ margin-bottom: 16px; }}
        label {{ display: block; margin-bottom: 4px; font-weight: 500; }}
        input, button, textarea {{
            width: 100%;
            padding: 10px;
            font-size: 16px;
            box-sizing: border-box;
            border: 1px solid #ccc;
            border-radius: 4px;
        }}
        button {{
            background: #f0f0f0;
            cursor: pointer;
        }}
        button:hover {{ background: #e0e0e0; }}
        .error {{ color: #c00; }}
        .note-list {{ list-style: none; padding: 0; }}
        .note-list li {{ padding: 8px 0; border-bottom: 1px solid #eee; }}
        .note-list a {{ color: #0366d6; text-decoration: none; }}
        .note-list a:hover {{ text-decoration: underline; }}
        .empty {{ color: #888; }}
        .stat-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
            margin-top: 20px;
        }}
        .stat-card {{
            border: 1px solid #ddd;
            border-radius: 8px;
            padding: 16px 20px;
            background: #fafafa;
        }}
        .stat-card h3 {{
            margin-bottom: 8px;
            font-weight: 400;
            color: #333;
        }}
        .stat-card .number {{
            font-size: 28px;
            font-weight: 500;
        }}
        .stat-card .detail {{
            color: #666;
            font-size: 14px;
            margin-top: 4px;
        }}
        .disclaimer {{
            background: #f9f9f9;
            padding: 20px;
            border-radius: 8px;
            border: 1px solid #eee;
        }}
        .markdown-body {{
            font-size: 16px;
            line-height: 1.6;
        }}
        .markdown-body h1, .markdown-body h2, .markdown-body h3 {{
            border-bottom: 1px solid #eee;
            padding-bottom: 6px;
        }}
        .markdown-body ul, .markdown-body ol {{
            padding-left: 2em;
        }}
        .markdown-body code {{
            background: #f4f4f4;
            padding: 2px 6px;
            border-radius: 4px;
        }}
        .markdown-body pre {{
            background: #f4f4f4;
            padding: 12px;
            border-radius: 4px;
            overflow-x: auto;
        }}
        .markdown-body blockquote {{
            border-left: 4px solid #ddd;
            padding-left: 16px;
            color: #666;
        }}
        .markdown-body a {{
            color: #0366d6;
        }}
        .home-links {{
            list-style: none;
            padding: 0;
            margin-top: 24px;
        }}
        .home-links li {{
            margin: 12px 0;
        }}
        .home-links a {{
            font-size: 18px;
            color: #0366d6;
            text-decoration: none;
        }}
        .home-links a:hover {{
            text-decoration: underline;
        }}
    </style>
    {extra_head}
</head>
<body>
    {navbar}
    <div class="container">
        {body}
    </div>
</body>
</html>"""

    # ---------- 页面渲染 ----------
    def _render_home(self):
        body = """
            <h1>rusin-note</h1>
            <ul class="home-links">
                <li><a href="/world/">公开笔记（匿名）</a></li>
                <li><a href="/register">注册账号</a></li>
                <li><a href="/login">登录</a></li>
                <li><a href="/count">统计</a></li>
                <li><a href="/disclaimer">免责声明</a></li>
            </ul>
        """
        return self._render_base(body, "首页")

    def _render_register_form(self, error=""):
        req_desc = get_password_requirements_description()
        body = f"""
            <h1>注册</h1>
            {f'<p class="error">{html.escape(error)}</p>' if error else ''}
            <form method="POST" action="/register">
                <div class="form-group">
                    <label>用户名 (字母数字下划线连字符)</label>
                    <input type="text" name="username" required pattern="[a-zA-Z0-9_\\-]+">
                </div>
                <div class="form-group">
                    <label>密码 (要求: {req_desc})</label>
                    <input type="password" name="password" required>
                </div>
                <div class="form-group">
                    <label>确认密码</label>
                    <input type="password" name="confirm" required>
                </div>
                <button type="submit">注册</button>
            </form>
            <p style="margin-top:12px;"><a href="/login">已有账号？登录</a></p>
        """
        return self._render_base(body, "注册")

    def _render_login_form(self, error=""):
        body = f"""
            <h1>登录</h1>
            {f'<p class="error">{html.escape(error)}</p>' if error else ''}
            <form method="POST" action="/login">
                <div class="form-group">
                    <label>用户名</label>
                    <input type="text" name="username" required>
                </div>
                <div class="form-group">
                    <label>密码</label>
                    <input type="password" name="password" required>
                </div>
                <button type="submit">登录</button>
            </form>
            <p style="margin-top:12px;"><a href="/register">没有账号？注册</a></p>
        """
        return self._render_base(body, "登录")

    def _render_user_list(self, username: str, notes: list[str]):
        note_items = ""
        if notes:
            for nid in notes:
                note_items += f'<li><a href="/user/{html.escape(username)}/{html.escape(nid)}">{html.escape(nid)}</a></li>'
        else:
            note_items = '<li class="empty">还没有笔记，创建一个吧</li>'
        body = f"""
            <h1>{html.escape(username)} 的笔记</h1>
            <div style="margin-bottom: 16px;">
                <a href="/user/{html.escape(username)}/new">+ 新建笔记</a>
            </div>
            <ul class="note-list">
                {note_items}
            </ul>
        """
        navbar = self._get_navbar(username)
        return self._render_base(body, f"{username} 的笔记", navbar)

    def _render_count_page(self):
        pub_cnt, pub_size, priv_cnt, priv_size, user_cnt = get_stats()
        def fmt_size(sz):
            if sz < 1024:
                return f"{sz} B"
            elif sz < 1024*1024:
                return f"{sz/1024:.2f} KB"
            elif sz < 1024*1024*1024:
                return f"{sz/(1024*1024):.2f} MB"
            else:
                return f"{sz/(1024*1024*1024):.2f} GB"

        body = f"""
            <h1>笔记统计</h1>
            <div class="stat-grid">
                <div class="stat-card">
                    <h3>公开笔记</h3>
                    <div class="number">{pub_cnt}</div>
                    <div class="detail">总大小: {fmt_size(pub_size)}</div>
                </div>
                <div class="stat-card">
                    <h3>私有笔记</h3>
                    <div class="number">{priv_cnt}</div>
                    <div class="detail">总大小: {fmt_size(priv_size)}</div>
                </div>
                <div class="stat-card">
                    <h3>注册用户</h3>
                    <div class="number">{user_cnt}</div>
                    <div class="detail">已注册账号</div>
                </div>
            </div>
            <p style="margin-top: 24px;"><a href="/">返回首页</a></p>
        """
        return self._render_base(body, "统计信息")

    def _render_disclaimer(self):
        """读取 Disclaimer.md 并渲染为 HTML（支持 Markdown）"""
        disclaimer_file = "Disclaimer.md"
        if os.path.exists(disclaimer_file):
            try:
                with open(disclaimer_file, "r", encoding="utf-8") as f:
                    content = f.read()
            except Exception as e:
                content = f"读取免责声明文件失败: {e}"
        else:
            content = "免责声明文件 (Disclaimer.md) 未找到。"

        # 尝试使用 markdown 库渲染（同样需要安全清洗，但此处内容由管理员控制，风险较低，不过仍建议统一使用安全渲染）
        if MARKDOWN_AVAILABLE and BLEACH_AVAILABLE:
            try:
                raw_html = markdown.markdown(content, extensions=['extra', 'codehilite'])
                ALLOWED_TAGS = ['p', 'br', 'strong', 'em', 'u', 'strike', 'a', 'ul', 'ol', 'li', 'blockquote', 'pre', 'code', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'hr', 'table', 'thead', 'tbody', 'tr', 'th', 'td', 'div', 'span']
                ALLOWED_ATTRS = {'*': ['class'], 'a': ['href', 'title', 'target']}
                html_content = bleach.clean(raw_html, tags=ALLOWED_TAGS, attributes=ALLOWED_ATTRS, strip=True)
                body = f"""
                    <h1>免责声明</h1>
                    <div class="disclaimer markdown-body">{html_content}</div>
                    <p style="margin-top: 20px;"><a href="/">返回首页</a></p>
                """
                return self._render_base(body, "免责声明", extra_head="")
            except Exception:
                pass  # 降级到纯文本

        # 降级：纯文本（安全）
        body = f"""
            <h1>免责声明</h1>
            <div class="disclaimer">{html.escape(content)}</div>
            <p style="margin-top: 20px;"><a href="/">返回首页</a></p>
            <p style="color: #888; font-size: 14px;">提示: 安装 markdown 和 bleach 库以支持安全 Markdown 渲染 (pip install markdown bleach)</p>
        """
        return self._render_base(body, "免责声明")

    def _render_note_page(self, note_id: str, content: str, username: str = None, is_world: bool = False,
                          action_url: str = None, navbar: str = None, title_prefix: str = None,
                          hint_text: str = None):
        escaped_id = html.escape(note_id)
        escaped_content = html.escape(content)

        # ---- 生成标题 ----
        if title_prefix is None:
            title_prefix = "公开笔记" if is_world else "私有笔记"
        if SITE_NAME:
            full_title = f"{title_prefix} {escaped_id} | {SITE_NAME}"
        else:
            full_title = f"{title_prefix} {escaped_id}"
        # -----------------

        if action_url is None:
            action_url = f"/world/{escaped_id}" if is_world else f"/user/{html.escape(username)}/{escaped_id}"
        if navbar is None:
            navbar = self._get_navbar() if is_world else self._get_navbar(username)
        if hint_text is None:
            hint_text = ' 按 <kbd>Ctrl</kbd> + <kbd>S</kbd> 快速保存'

        page = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{html.escape(full_title)}</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            background: #ffffff;
            height: 100vh;
            overflow: hidden;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", sans-serif;
        }}
        .navbar {{
            background: #f8f9fa;
            padding: 8px 24px;
            border-bottom: 1px solid #ddd;
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            font-size: 14px;
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            z-index: 30;
        }}
        .navbar .user-info {{
            font-weight: 500;
        }}
        .navbar .nav-links a {{
            margin-left: 16px;
            color: #0366d6;
            text-decoration: none;
        }}
        .navbar .nav-links a:hover {{
            text-decoration: underline;
        }}
        form {{
            height: 100vh;
            display: flex;
            flex-direction: column;
            padding-top: 50px;
        }}
        textarea {{
            flex: 1;
            width: 100%;
            border: none;
            padding: 20px 24px;
            font-size: 16px;
            line-height: 1.7;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", sans-serif;
            resize: none;
            outline: none;
            background: #ffffff;
            color: #111;
        }}
        .save-btn {{
            position: fixed;
            bottom: 24px;
            right: 24px;
            background: rgba(240, 240, 240, 0.85);
            border: 1px solid #ddd;
            padding: 8px 20px;
            border-radius: 20px;
            font-size: 14px;
            color: #333;
            cursor: pointer;
            backdrop-filter: blur(4px);
            transition: all 0.2s;
            z-index: 10;
            font-weight: 500;
        }}
        .save-btn:hover {{
            background: rgba(220, 220, 220, 0.95);
            transform: scale(1.02);
        }}
        .save-btn:active {{
            background: #ccc;
            transform: scale(0.98);
        }}
        .save-hint {{
            position: fixed;
            bottom: 80px;
            left: 50%;
            transform: translateX(-50%);
            background: rgba(0, 0, 0, 0.75);
            color: #fff;
            padding: 10px 24px;
            border-radius: 24px;
            font-size: 14px;
            letter-spacing: 0.5px;
            backdrop-filter: blur(8px);
            opacity: 0;
            transition: opacity 0.4s ease, transform 0.4s ease;
            pointer-events: none;
            z-index: 20;
            font-weight: 400;
            box-shadow: 0 4px 20px rgba(0,0,0,0.2);
        }}
        .save-hint.show {{
            opacity: 1;
            transform: translateX(-50%) translateY(0);
        }}
        .save-hint kbd {{
            background: rgba(255, 255, 255, 0.2);
            padding: 2px 12px;
            border-radius: 6px;
            margin: 0 4px;
            font-size: 13px;
            border: 1px solid rgba(255, 255, 255, 0.15);
            font-family: inherit;
        }}
        .save-status {{
            position: fixed;
            bottom: 80px;
            right: 24px;
            font-size: 14px;
            color: #4CAF50;
            opacity: 0;
            transition: opacity 0.3s ease, transform 0.3s ease;
            pointer-events: none;
            z-index: 15;
            background: rgba(255, 255, 255, 0.95);
            padding: 6px 18px;
            border-radius: 16px;
            border: 1px solid #4CAF50;
            box-shadow: 0 2px 12px rgba(0,0,0,0.08);
            transform: translateY(10px);
        }}
        .save-status.show {{
            opacity: 1;
            transform: translateY(0);
        }}
        .save-status.saving {{
            color: #ff9800;
            border-color: #ff9800;
        }}
        .save-status.error {{
            color: #f44336;
            border-color: #f44336;
        }}
        @media (max-width: 640px) {{
            textarea {{
                padding: 16px 18px;
                font-size: 15px;
            }}
            .save-btn {{
                bottom: 16px;
                right: 16px;
                padding: 6px 16px;
                font-size: 13px;
            }}
            .save-hint {{
                bottom: 70px;
                padding: 8px 16px;
                font-size: 12px;
                white-space: nowrap;
            }}
            .save-status {{
                bottom: 70px;
                right: 16px;
                font-size: 12px;
                padding: 4px 14px;
            }}
        }}
    </style>
</head>
<body>
    {navbar}
    <form method="POST" action="{action_url}" id="noteForm">
        <textarea name="content" id="noteContent" autofocus spellcheck="true">{escaped_content}</textarea>
        <button type="button" class="save-btn" id="saveBtn"> 保存</button>
    </form>
    <div class="save-hint" id="saveHint">
         按 <kbd>Ctrl</kbd> + <kbd>S</kbd> 快速保存
    </div>
    <div class="save-status" id="saveStatus"></div>

    <script>
        (function() {{
            const form = document.getElementById('noteForm');
            const textarea = document.getElementById('noteContent');
            const saveBtn = document.getElementById('saveBtn');
            const saveHint = document.getElementById('saveHint');
            const saveStatus = document.getElementById('saveStatus');
            let saveTimeout = null;
            let statusTimeout = null;
            let hintTimeout = null;
            let isSaving = false;
            const DEFAULT_HINT = '{hint_text}';

            // ADDED: Tab键插入4个空格
            textarea.addEventListener('keydown', function(e) {{
                if (e.key === 'Tab') {{
                    e.preventDefault();
                    const start = this.selectionStart;
                    const end = this.selectionEnd;
                    this.value = this.value.substring(0, start) + '    ' + this.value.substring(end);
                    this.selectionStart = this.selectionEnd = start + 4;
                }}
            }});

            function showHint(message) {{
                if (message) {{
                    saveHint.innerHTML = message;
                }}
                saveHint.classList.add('show');
                clearTimeout(hintTimeout);
                hintTimeout = setTimeout(function() {{
                    saveHint.classList.remove('show');
                }}, 4000);
            }}

            function showStatus(message, type = '') {{
                saveStatus.textContent = message;
                saveStatus.className = 'save-status show';
                if (type) {{
                    saveStatus.classList.add(type);
                }}
                clearTimeout(statusTimeout);
                statusTimeout = setTimeout(function() {{
                    saveStatus.classList.remove('show');
                }}, 2500);
            }}

            setTimeout(function() {{
                showHint(DEFAULT_HINT);
            }}, 600);

            let inputTimer = null;
            textarea.addEventListener('input', function() {{
                clearTimeout(inputTimer);
                inputTimer = setTimeout(function() {{
                    showHint(DEFAULT_HINT);
                }}, 3000);
            }});

            textarea.addEventListener('focus', function() {{
                showHint(DEFAULT_HINT);
            }});

            document.addEventListener('keydown', function(e) {{
                if ((e.ctrlKey || e.metaKey) && e.key === 's') {{
                    e.preventDefault();
                    saveNote();
                }}
                if (e.key === 'Escape') {{
                    saveHint.classList.remove('show');
                    saveStatus.classList.remove('show');
                }}
            }});

            saveBtn.addEventListener('click', function(e) {{
                e.preventDefault();
                saveNote();
            }});

            function saveNote() {{
                if (isSaving) return;
                isSaving = true;
                showStatus(' 保存中...', 'saving');
                const content = textarea.value;
                fetch(window.location.href, {{
                    method: 'POST',
                    headers: {{
                        'Content-Type': 'application/x-www-form-urlencoded',
                    }},
                    body: 'content=' + encodeURIComponent(content)
                }})
                .then(response => {{
                    isSaving = false;
                    if (response.ok) {{
                        showStatus('已保存', '');
                        showHint(' 已保存！按 <kbd>Ctrl</kbd> + <kbd>S</kbd> 再次保存');
                    }} else {{
                        showStatus(' 保存失败 (' + response.status + ')', 'error');
                        showHint(' 保存失败，请重试');
                    }}
                }})
                .catch(error => {{
                    isSaving = false;
                    showStatus(' 网络错误', 'error');
                    showHint(' 保存失败：' + error.message);
                }});
            }}

            function autoResize() {{
                textarea.style.height = 'auto';
                textarea.style.height = textarea.scrollHeight + 'px';
            }}
            setTimeout(autoResize, 100);
            textarea.addEventListener('input', autoResize);
        }})();
    </script>
</body>
</html>"""
        return page

    # ---------- 只读 Markdown 渲染页面（安全清洗） ----------
    def _render_markdown_page(self, note_id: str, content: str, title_label: str = "公开笔记",
                              back_url: str = None, back_label: str = "返回编辑", navbar: str = None):
        """
        渲染笔记为 Markdown 只读页面（公开/私有/分享通用）。
        使用 bleach 清洗 HTML，防止 XSS。
        """
        # 如果 markdown 和 bleach 都可用，则安全渲染
        if MARKDOWN_AVAILABLE and BLEACH_AVAILABLE:
            try:
                raw_html = markdown.markdown(content, extensions=['extra', 'codehilite'])
                # 定义白名单标签和属性
                ALLOWED_TAGS = [
                    'p', 'br', 'strong', 'em', 'u', 'strike', 'a',
                    'ul', 'ol', 'li', 'blockquote', 'pre', 'code',
                    'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'hr',
                    'table', 'thead', 'tbody', 'tr', 'th', 'td',
                    'div', 'span'  # 允许容器标签
                ]
                ALLOWED_ATTRS = {
                    '*': ['class'],          # 允许 class（用于代码高亮等）
                    'a': ['href', 'title', 'target']
                }
                html_content = bleach.clean(raw_html, tags=ALLOWED_TAGS, attributes=ALLOWED_ATTRS, strip=True)
            except Exception:
                # 渲染失败，降级为纯文本
                html_content = f"<pre>{html.escape(content)}</pre>"
        else:
            # 缺少依赖，降级为纯文本（安全）
            html_content = f"<pre>{html.escape(content)}</pre>"

        if back_url is None:
            back_url = f"/world/{note_id}"
        if navbar is None:
            navbar = self._get_navbar()  # 匿名导航
        body = f"""
            <h1>{html.escape(title_label)} · {html.escape(note_id)} <span style="font-size:0.6em; font-weight:400; color:#888;">只读</span></h1>
            <div class="markdown-body" style="margin-top:20px; padding-bottom:40px;">
                {html_content}
            </div>
            <p style="margin-top: 20px;"><a href="{html.escape(back_url)}">{html.escape(back_label)}</a> · <a href="/">首页</a></p>
        """
        return self._render_base(body, f"Markdown - {note_id}", navbar)

    # ---------- 分享管理页面 ----------
    def _render_shares_page(self, username: str, error=""):
        my_shares = list_user_shares(username)
        notes = list_user_notes(username)

        note_options = ""
        if notes:
            for nid in notes:
                note_options += f'<option value="{html.escape(nid)}">{html.escape(nid)}</option>'
        else:
            note_options = '<option value="">（暂无笔记，请先创建笔记）</option>'

        rows = ""
        if my_shares:
            for tok, s in sorted(my_shares, key=lambda kv: kv[1].get("created_at", 0), reverse=True):
                nid = s.get("note_id", "")
                editable = "可编辑" if s.get("editable") else "只读"
                rows += f"""
                    <tr>
                        <td>{html.escape(nid)}</td>
                        <td><a class="share-link" href="/share/{tok}" target="_blank">/share/{tok}</a></td>
                        <td>{editable}</td>
                        <td>{s.get("views", 0)}</td>
                        <td>
                            <form method="POST" action="/user/{html.escape(username)}/shares/delete" style="display:inline;">
                                <input type="hidden" name="token" value="{tok}">
                                <button type="submit" class="btn-sm">删除</button>
                            </form>
                        </td>
                    </tr>"""
        else:
            rows = '<tr><td colspan="5" class="empty">还没有分享链接，创建第一个吧</td></tr>'

        body = f"""
            <h1>分享管理</h1>
            {f'<p class="error">{html.escape(error)}</p>' if error else ''}
            <div style="margin: 20px 0;">
                <h2 style="border:none; margin-bottom: 12px;">创建分享</h2>
                <form method="POST" action="/user/{html.escape(username)}/shares/" style="max-width: 420px;">
                    <div class="form-group">
                        <label>选择要分享的笔记</label>
                        <select name="note_id">{note_options}</select>
                    </div>
                    <div class="form-group" style="display:flex; align-items:center; gap:8px;">
                        <input type="checkbox" name="editable" value="1" id="editable_cb" style="width:auto;">
                        <label for="editable_cb" style="margin:0;">允许编辑（访客保存将修改我的原笔记）</label>
                    </div>
                    <button type="submit">创建分享</button>
                </form>
            </div>
            <h2 style="border:none; margin-bottom: 12px;">我的分享（{len(my_shares)}）</h2>
            <table class="share-table">
                <thead>
                    <tr><th>笔记</th><th>分享链接</th><th>权限</th><th>查看次数</th><th>操作</th></tr>
                </thead>
                <tbody>{rows}</tbody>
            </table>
            <p style="margin-top: 24px;"><a href="/user/{html.escape(username)}/">返回我的笔记</a></p>
        """
        # 分享页专用样式
        share_css = """
            <style>
                .share-table { width: 100%; border-collapse: collapse; margin-top: 8px; }
                .share-table th, .share-table td { border: 1px solid #ddd; padding: 8px 10px; text-align: left; font-size: 14px; word-break: break-all; }
                .share-table th { background: #f8f9fa; font-weight: 500; }
                .share-link { font-family: Consolas, monospace; font-size: 12px; color: #0366d6; }
                .btn-sm { width: auto; padding: 4px 14px; font-size: 13px; }
                select { width: 100%; padding: 10px; font-size: 16px; border: 1px solid #ccc; border-radius: 4px; }
            </style>
        """
        navbar = self._get_navbar(username)
        return self._render_base(body, "分享管理", navbar, extra_head=share_css)

    # ---------- 可编辑分享页面 ----------
    def _render_share_edit_page(self, token: str, note_id: str, content: str, owner: str):
        return self._render_note_page(
            note_id, content,
            action_url=f"/share/{token}",
            navbar=self._get_navbar(),
            title_prefix="分享笔记",
            hint_text=' 可编辑分享：保存后将写入分享者原笔记',
        )

    # ---------- GET 请求 ----------
    def do_GET(self):
        client_ip = self.get_client_ip()
        # ADDED: GET独立限流
        if is_get_rate_limited(client_ip):
            self.send_error(429, f"Too many GET requests (max {GET_RATE_MAX} per {GET_RATE_WINDOW}s)")
            return

        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        # 首页
        if path == "/" or path == "":
            self.send_response(200)
            self.send_header("Content-Type", self._HTML_HEADER)
            self.end_headers()
            self.wfile.write(self._render_home().encode("utf-8"))
            return

        # 统计页面
        if path == "/count":
            self.send_response(200)
            self.send_header("Content-Type", self._HTML_HEADER)
            self.end_headers()
            self.wfile.write(self._render_count_page().encode("utf-8"))
            return

        # 免责声明
        if path == "/disclaimer":
            self.send_response(200)
            self.send_header("Content-Type", self._HTML_HEADER)
            self.end_headers()
            self.wfile.write(self._render_disclaimer().encode("utf-8"))
            return

        # 纯数字路径 -> 重定向到 /world/<数字>
        digit_match = re.match(r'^/(\d+)$', path)
        if digit_match:
            note_id = digit_match.group(1)
            self._send_redirect(f"/world/{note_id}")
            return

        # 注册页面
        if path == "/register":
            self.send_response(200)
            self.send_header("Content-Type", self._HTML_HEADER)
            self.end_headers()
            self.wfile.write(self._render_register_form().encode("utf-8"))
            return

        # 登录页面
        if path == "/login":
            self.send_response(200)
            self.send_header("Content-Type", self._HTML_HEADER)
            self.end_headers()
            self.wfile.write(self._render_login_form().encode("utf-8"))
            return

        # 登出
        if path == "/logout":
            token = self.get_session_cookie()
            if token:
                delete_session(token)
            self.send_response(302)
            self._clear_session_cookie()
            self.send_header("Location", "/")
            self.end_headers()
            return
        
        # 处理 favicon.ico
        if path == "/favicon.ico":
            ico_path = "favicon.ico"  # 根目录下的 .ico 文件
            if os.path.exists(ico_path):
                with open(ico_path, "rb") as f:
                    data = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "image/x-icon")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            else:
                self.send_error(404, "Favicon not found")
            return

        # ---------- 新增：公开笔记 Markdown 渲染 /world/<id>/md ----------
        world_md_match = re.match(r'^/world/([^/]+)/md$', path)
        if world_md_match:
            note_id = world_md_match.group(1)
            if not validate_note_id(note_id):
                self.send_error(400, "Invalid note ID")
                return
            content = read_note("public", note_id)
            # 即使内容为空也渲染（显示空白）
            page = self._render_markdown_page(note_id, content)
            self.send_response(200)
            self.send_header("Content-Type", self._HTML_HEADER)
            self.end_headers()
            self.wfile.write(page.encode("utf-8"))
            return

        # ---------- 分享只读 Markdown：/share/<token>/md ----------
        share_md_match = re.match(r'^/share/([A-Za-z0-9]{64})/md$', path)
        if share_md_match:
            token = share_md_match.group(1)
            share = get_share(token)
            if share is None:
                self.send_error(404, "Share not found")
                return
            increment_share_views(token)
            note_id = share["note_id"]
            content = read_note(share["owner"], note_id)
            page = self._render_markdown_page(
                note_id, content,
                title_label="分享笔记",
                back_url=f"/share/{token}",
                back_label="返回分享",
                navbar=self._get_navbar(),
            )
            self.send_response(200)
            self.send_header("Content-Type", self._HTML_HEADER)
            self.end_headers()
            self.wfile.write(page.encode("utf-8"))
            return

        # ---------- 分享查看/编辑：/share/<token> ----------
        share_match = re.match(r'^/share/([A-Za-z0-9]{64})$', path)
        if share_match:
            token = share_match.group(1)
            share = get_share(token)
            if share is None:
                self.send_error(404, "Share not found")
                return
            increment_share_views(token)
            note_id = share["note_id"]
            content = read_note(share["owner"], note_id)
            if share.get("editable"):
                page = self._render_share_edit_page(token, note_id, content, share["owner"])
            else:
                page = self._render_markdown_page(
                    note_id, content,
                    title_label="分享笔记",
                    back_url=f"/share/{token}",
                    back_label="刷新",
                    navbar=self._get_navbar(),
                )
            self.send_response(200)
            self.send_header("Content-Type", self._HTML_HEADER)
            self.end_headers()
            self.wfile.write(page.encode("utf-8"))
            return

        # 公开笔记路径：/world/ 或 /world/<note_id>
        world_match = re.match(r'^/world/([^/]+)?$', path)
        if world_match:
            note_id = world_match.group(1)
            if note_id is None:
                new_id = generate_random_id()
                self._send_redirect(f"/world/{new_id}")
                return

            if not validate_note_id(note_id):
                self.send_error(400, "Invalid note ID")
                return

            content = read_note("public", note_id)
            page = self._render_note_page(note_id, content, is_world=True)
            self.send_response(200)
            self.send_header("Content-Type", self._HTML_HEADER)
            self.end_headers()
            self.wfile.write(page.encode("utf-8"))
            return

        # ---------- 私有笔记 Markdown：/user/<用户名>/<笔记ID>/md（需登录） ----------
        user_md_match = re.match(r'^/user/([^/]+)/([^/]+)/md$', path)
        if user_md_match:
            username = user_md_match.group(1)
            note_id = user_md_match.group(2)
            if not validate_username(username) or not validate_note_id(note_id):
                self.send_error(400, "Invalid username or note ID")
                return
            if not self.is_authenticated(username):
                self.send_response(401)
                self.send_header("Content-Type", self._HTML_HEADER)
                self.end_headers()
                body = "<h1>需要登录</h1><p>请先 <a href=\"/login\">登录</a> 或 <a href=\"/register\">注册</a> 以访问您的私有笔记。</p>"
                self.wfile.write(self._render_base(body, "请先登录").encode("utf-8"))
                return
            content = read_note(username, note_id)
            page = self._render_markdown_page(
                note_id, content,
                title_label="私有笔记",
                back_url=f"/user/{username}/{note_id}",
                back_label="返回编辑",
                navbar=self._get_navbar(username),
            )
            self.send_response(200)
            self.send_header("Content-Type", self._HTML_HEADER)
            self.end_headers()
            self.wfile.write(page.encode("utf-8"))
            return

        # ---------- 分享管理页面：/user/<用户名>/shares/（需登录） ----------
        shares_page_match = re.match(r'^/user/([^/]+)/shares/?$', path)
        if shares_page_match:
            username = shares_page_match.group(1)
            if not validate_username(username):
                self.send_error(400, "Invalid username")
                return
            if not self.is_authenticated(username):
                self.send_response(401)
                self.send_header("Content-Type", self._HTML_HEADER)
                self.end_headers()
                body = "<h1>需要登录</h1><p>请先 <a href=\"/login\">登录</a> 或 <a href=\"/register\">注册</a> 以访问您的分享管理。</p>"
                self.wfile.write(self._render_base(body, "请先登录").encode("utf-8"))
                return
            page = self._render_shares_page(username)
            self.send_response(200)
            self.send_header("Content-Type", self._HTML_HEADER)
            self.end_headers()
            self.wfile.write(page.encode("utf-8"))
            return

        # 私有用户路径：/user/<username>[/<note_id>] 或 /user/<username>/new
        # MODIFIED: 允许尾部斜杠
        user_match = re.match(r'^/user/([^/]+)(?:/([^/]+))?/?$', path)
        if user_match:
            username = user_match.group(1)
            note_id = user_match.group(2)

            if not validate_username(username):
                self.send_error(400, "Invalid username")
                return

            # 认证检查
            current_user = self.get_current_user()
            if current_user != username:
                self.send_response(401)
                self.send_header("Content-Type", self._HTML_HEADER)
                self.end_headers()
                body = "<h1>需要登录</h1><p>请先 <a href=\"/login\">登录</a> 或 <a href=\"/register\">注册</a> 以访问您的私有笔记。</p>"
                self.wfile.write(self._render_base(body, "请先登录").encode("utf-8"))
                return

            if note_id == "new":
                new_id = generate_random_id()
                self._send_redirect(f"/user/{username}/{new_id}")
                return

            if note_id is None:
                notes = list_user_notes(username)
                self.send_response(200)
                self.send_header("Content-Type", self._HTML_HEADER)
                self.end_headers()
                self.wfile.write(self._render_user_list(username, notes).encode("utf-8"))
                return

            if not validate_note_id(note_id):
                self.send_error(400, "Invalid note ID")
                return

            content = read_note(username, note_id)
            page = self._render_note_page(note_id, content, username=username, is_world=False)
            self.send_response(200)
            self.send_header("Content-Type", self._HTML_HEADER)
            self.end_headers()
            self.wfile.write(page.encode("utf-8"))
            return

        # 其他路径 -> 404
        self.send_error(404, "Not found")

    # ---------- POST 请求 ----------
    def do_POST(self):
        client_ip = self.get_client_ip()
        if is_rate_limited(client_ip):
            self.send_error(429, f"Too many requests (max {RATE_MAX} per {RATE_WINDOW}s)")
            return

        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        # 处理注册
        if path == "/register":
            content_length = int(self.headers.get("Content-Length", 0))
            if content_length > 1024 * 10:
                self.send_error(413, "Form too large")
                return
            post_data = self.rfile.read(content_length).decode("utf-8")
            form = urllib.parse.parse_qs(post_data, max_num_fields=5)
            username = form.get("username", [""])[0].strip()
            password = form.get("password", [""])[0]
            confirm = form.get("confirm", [""])[0]

            if not validate_username(username):
                self.send_response(200)
                self.send_header("Content-Type", self._HTML_HEADER)
                self.end_headers()
                self.wfile.write(self._render_register_form("用户名只能包含字母、数字、下划线、连字符").encode("utf-8"))
                return

            with users_lock:
                if username in users:
                    self.send_response(200)
                    self.send_header("Content-Type", self._HTML_HEADER)
                    self.end_headers()
                    self.wfile.write(self._render_register_form("用户名已存在").encode("utf-8"))
                    return

            if password != confirm:
                self.send_response(200)
                self.send_header("Content-Type", self._HTML_HEADER)
                self.end_headers()
                self.wfile.write(self._render_register_form("两次密码不一致").encode("utf-8"))
                return

            if not check_password_complexity(password):
                req_desc = get_password_requirements_description()
                self.send_response(200)
                self.send_header("Content-Type", self._HTML_HEADER)
                self.end_headers()
                self.wfile.write(self._render_register_form(
                    f"密码不符合要求：{req_desc}"
                ).encode("utf-8"))
                return

            salt = generate_salt()
            hashed = hash_password(password, salt)
            with users_lock:
                users[username] = {"salt": salt, "hash": hashed}
            save_users()

            token = create_session(username)
            self.send_response(302)
            self._set_session_cookie(token)
            self.send_header("Location", f"/user/{username}/new")
            self.end_headers()
            return

        # 处理登录
        if path == "/login":
            content_length = int(self.headers.get("Content-Length", 0))
            if content_length > 1024 * 10:
                self.send_error(413, "Form too large")
                return
            post_data = self.rfile.read(content_length).decode("utf-8")
            form = urllib.parse.parse_qs(post_data, max_num_fields=5)
            username = form.get("username", [""])[0].strip()
            password = form.get("password", [""])[0]

            with users_lock:
                user = users.get(username)
            if not user:
                self.send_response(200)
                self.send_header("Content-Type", self._HTML_HEADER)
                self.end_headers()
                self.wfile.write(self._render_login_form("用户名或密码错误").encode("utf-8"))
                return

            salt = user["salt"]
            hashed = user["hash"]
            if not verify_password(password, salt, hashed):
                self.send_response(200)
                self.send_header("Content-Type", self._HTML_HEADER)
                self.end_headers()
                self.wfile.write(self._render_login_form("用户名或密码错误").encode("utf-8"))
                return

            token = create_session(username)
            self.send_response(302)
            self._set_session_cookie(token)
            self.send_header("Location", f"/user/{username}/")
            self.end_headers()
            return

        # ---------- 创建分享：/user/<用户名>/shares/ ----------
        shares_create_match = re.match(r'^/user/([^/]+)/shares/?$', path)
        if shares_create_match:
            username = shares_create_match.group(1)
            if not validate_username(username):
                self.send_error(400, "Invalid username")
                return
            if not self.is_authenticated(username):
                self.send_error(401, "Unauthorized")
                return
            content_length = int(self.headers.get("Content-Length", 0))
            if content_length > 1024 * 10:
                self.send_error(413, "Form too large")
                return
            post_data = self.rfile.read(content_length).decode("utf-8")
            form = urllib.parse.parse_qs(post_data, max_num_fields=5)
            note_id = form.get("note_id", [""])[0].strip()
            editable = form.get("editable", ["0"])[0] in ("1", "on", "true")

            if not validate_note_id(note_id):
                self.send_response(200)
                self.send_header("Content-Type", self._HTML_HEADER)
                self.end_headers()
                self.wfile.write(self._render_shares_page(username, "请选择有效的笔记").encode("utf-8"))
                return
            note_path = get_note_path(username, note_id)
            if note_path is None or not os.path.exists(note_path):
                self.send_response(200)
                self.send_header("Content-Type", self._HTML_HEADER)
                self.end_headers()
                self.wfile.write(self._render_shares_page(username, "笔记不存在，请选择已有的笔记").encode("utf-8"))
                return

            token = create_share(username, note_id, editable)
            self.send_response(302)
            self.send_header("Location", f"/user/{username}/shares/")
            self.end_headers()
            return

        # ---------- 删除分享：/user/<用户名>/shares/delete ----------
        shares_delete_match = re.match(r'^/user/([^/]+)/shares/delete$', path)
        if shares_delete_match:
            username = shares_delete_match.group(1)
            if not validate_username(username):
                self.send_error(400, "Invalid username")
                return
            if not self.is_authenticated(username):
                self.send_error(401, "Unauthorized")
                return
            content_length = int(self.headers.get("Content-Length", 0))
            if content_length > 1024 * 10:
                self.send_error(413, "Form too large")
                return
            post_data = self.rfile.read(content_length).decode("utf-8")
            form = urllib.parse.parse_qs(post_data, max_num_fields=5)
            token = form.get("token", [""])[0].strip()
            if not re.match(r'^[A-Za-z0-9]{64}$', token):
                self.send_error(400, "Invalid share token")
                return
            delete_share(username, token)
            self.send_response(302)
            self.send_header("Location", f"/user/{username}/shares/")
            self.end_headers()
            return

        # ---------- 保存可编辑分享：/share/<token>（写回分享者原笔记） ----------
        share_save_match = re.match(r'^/share/([A-Za-z0-9]{64})$', path)
        if share_save_match:
            token = share_save_match.group(1)
            share = get_share(token)
            if share is None:
                self.send_error(404, "Share not found")
                return
            if not share.get("editable"):
                self.send_error(403, "This share is read-only")
                return
            content_length = int(self.headers.get("Content-Length", 0))
            if content_length > MAX_CONTENT_BYTES:
                self.send_error(413, f"Content too large (max {MAX_CONTENT_BYTES//1024//1024}MB)")
                return
            post_data = self.rfile.read(content_length).decode("utf-8")
            form = urllib.parse.parse_qs(post_data, max_num_fields=10)
            content = form.get("content", [""])[0]
            # 写回分享者的原笔记
            if write_note(share["owner"], share["note_id"], content):
                self.send_response(302)
                self.send_header("Location", f"/share/{token}")
                self.end_headers()
            else:
                self.send_error(500, "Failed to save note")
            return

        # 处理公开笔记保存：/world/<note_id>
        world_match = re.match(r'^/world/([^/]+)$', path)
        if world_match:
            note_id = world_match.group(1)
            if not validate_note_id(note_id):
                self.send_error(400, "Invalid note ID")
                return

            content_length = int(self.headers.get("Content-Length", 0))
            if content_length > MAX_CONTENT_BYTES:
                self.send_error(413, f"Content too large (max {MAX_CONTENT_BYTES//1024//1024}MB)")
                return

            post_data = self.rfile.read(content_length).decode("utf-8")
            form = urllib.parse.parse_qs(post_data, max_num_fields=10)
            content = form.get("content", [""])[0]

            if write_note("public", note_id, content):
                self.send_response(302)
                self.send_header("Location", f"/world/{note_id}")
                self.end_headers()
            else:
                self.send_error(500, "Failed to save note")
            return

        # 处理私有笔记保存：/user/<username>/<note_id>
        user_match = re.match(r'^/user/([^/]+)/([^/]+)$', path)
        if user_match:
            username = user_match.group(1)
            note_id = user_match.group(2)

            if not validate_username(username) or not validate_note_id(note_id):
                self.send_error(400, "Invalid username or note ID")
                return

            if not self.is_authenticated(username):
                self.send_error(401, "Unauthorized")
                return

            content_length = int(self.headers.get("Content-Length", 0))
            if content_length > MAX_CONTENT_BYTES:
                self.send_error(413, f"Content too large (max {MAX_CONTENT_BYTES//1024//1024}MB)")
                return

            post_data = self.rfile.read(content_length).decode("utf-8")
            form = urllib.parse.parse_qs(post_data, max_num_fields=10)
            content = form.get("content", [""])[0]

            if write_note(username, note_id, content):
                self.send_response(302)
                self.send_header("Location", f"/user/{username}/{note_id}")
                self.end_headers()
            else:
                self.send_error(500, "Failed to save note")
            return

        self.send_error(404, "Not found")

    def send_error(self, code, message=None, explain=None):
        self.log_error(f"code {code}, message {message}")
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        if message:
            response = f"<html><head><title>Error {code}</title></head><body><h1>{code} {message}</h1></body></html>"
            self.wfile.write(response.encode("utf-8"))


# ---------- 启动服务器 ----------
class TimedThreadingHTTPServer(ThreadingHTTPServer):
    """带 socket 超时的 ThreadingHTTPServer，防止慢速连接挂起线程（BUG-008）"""

    def get_request(self):
        sock, addr = super().get_request()
        sock.settimeout(SOCKET_TIMEOUT)
        return sock, addr

def run_server(port=8080):
    server_address = ("", port)
    httpd = TimedThreadingHTTPServer(server_address, NoteHandler)
    if SESSION_TIMEOUT_ENABLED:
        purge_expired_sessions()  # 启动时清理一次过期会话
        Thread(target=session_cleanup_loop, daemon=True).start()
    print("[启动] rusin-note 服务已启动 (公开+私有笔记)")
    print(f"[地址] http://localhost:{port}")
    print(f"[目录] 笔记保存在 ./{NOTES_BASE}/ (public/ 为公开笔记)")
    print(f"[限制] 每个笔记最大 {MAX_CONTENT_BYTES//1024//1024}MB")
    print(f"[限流] POST: 每个IP {RATE_MAX} 次 / {RATE_WINDOW} 秒")
    print(f"[限流] GET:  每个IP {GET_RATE_MAX} 次 / {GET_RATE_WINDOW} 秒")
    print(f"[连接] socket 超时: {SOCKET_TIMEOUT} 秒 (防止慢速连接挂起线程)")
    print("[公开笔记] 访问 /world/<id> 即可匿名编辑")
    print("[私有笔记] 注册登录后访问 /user/<username>/<id>")
    print("[快捷] 访问 /数字 自动重定向到 /world/数字")
    print("[统计] 访问 /count 查看笔记统计")
    print("[免责] 访问 /disclaimer 查看免责声明 (支持Markdown)")
    print("[Markdown] 访问 /world/<id>/md 渲染公开笔记为只读 Markdown (已启用XSS防护)")
    print("[Markdown] 访问 /user/<用户名>/<笔记ID>/md 渲染私有笔记为只读 Markdown (需登录)")
    print("[分享] 访问 /user/<用户名>/shares/ 管理分享链接 (创建/删除/查看次数)")
    print("[分享] 分享链接: /share/<64位token> (只读或可编辑，保存将写回分享者原笔记)")
    if SESSION_TIMEOUT_ENABLED:
        print(f"[超时] 会话超时已启用，超时时间 {SESSION_TIMEOUT_MINUTES} 分钟")
    else:
        print("[超时] 会话超时未启用")

    # 检查依赖状态
    if not MARKDOWN_AVAILABLE:
        print("[警告] Markdown 库未安装，Markdown 渲染功能将降级为纯文本 (pip install markdown)")
    if not BLEACH_AVAILABLE:
        print("[警告] Bleach 库未安装，Markdown 渲染将不进行安全清洗，请尽快安装 (pip install bleach)")

    print("[提示] 按 Ctrl+C 停止服务")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[停止] 服务已停止")
        httpd.shutdown()


if __name__ == "__main__":
    run_server()