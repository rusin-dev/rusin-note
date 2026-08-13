"""用户/会话/分享的字典存储与原子持久化，以及笔记文件路径与分享业务"""
import os
import json
import time
import secrets
from threading import Lock

from .config import (
    config,
    DEFAULT_CONFIG,
    SHARE_TOKEN_CHARSET,
    SHARE_TOKEN_LENGTH,
)

# ---------- 数据文件路径 ----------
USER_FILE = "users.json"
SESSION_FILE = "sessions.json"
SHARE_FILE = "shares.json"
NOTES_BASE = "notes"
os.makedirs(NOTES_BASE, exist_ok=True)

users = {}
sessions = {}  # 格式: {sha256(token): {"username": str, "created_at": float}}
shares = {}  # 格式: {token: {"owner": str, "note_id": str, "created_at": float, "editable": bool, "views": int}}
users_lock = Lock()
sessions_lock = Lock()
shares_lock = Lock()


def _atomic_json_dump(path: str, data: dict) -> bool:
    """原子写入 JSON 文件：临时文件 + flush + fsync + os.replace（BUG-6）
    防止写入中途崩溃/断电导致整个文件损坏、数据全部丢失"""
    try:
        temp_path = path + ".tmp"
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path, path)
        return True
    except Exception as e:
        print(f"[错误] 原子写入 {path} 失败: {e}")
        try:
            if os.path.exists(temp_path):
                os.remove(temp_path)
        except OSError:
            pass
        return False


# ---------- 用户存储 ----------
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
        _atomic_json_dump(USER_FILE, users)


# ---------- 会话存储 ----------
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
        _atomic_json_dump(SESSION_FILE, sessions)


# ---------- 分享存储 ----------
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
        _atomic_json_dump(SHARE_FILE, shares)


def generate_share_token() -> str:
    return ''.join(secrets.choice(SHARE_TOKEN_CHARSET) for _ in range(SHARE_TOKEN_LENGTH))


def create_share(username: str, note_id: str, editable: bool) -> str:
    """创建分享，返回分享 token（长度与字符集由配置决定）"""
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
    """返回分享条目；对损坏/旧版数据（缺 owner/note_id）返回 None，避免 KeyError（BUG-7）"""
    with shares_lock:
        share = shares.get(token)
        if not share or not isinstance(share, dict):
            return None
        if not share.get("owner") or not share.get("note_id"):
            return None
        return share


def delete_share(username: str, token: str) -> bool:
    """仅分享者本人可删除，返回是否删除成功"""
    with shares_lock:
        share = shares.get(token)
        if share is None or share.get("owner") != username:
            return False
        del shares[token]
    save_shares()
    return True


def increment_share_views(token: str):
    """每次访问分享链接时计数（持久化到 shares.json）"""
    with shares_lock:
        share = shares.get(token)
        if not isinstance(share, dict):
            return
        share["views"] = share.get("views", 0) + 1
    save_shares()


def list_user_shares(username: str) -> list:
    """返回该用户创建的所有分享 [(token, share), ...]"""
    with shares_lock:
        return [(tok, dict(s)) for tok, s in shares.items()
                if isinstance(s, dict) and s.get("owner") == username]


load_users()
load_sessions()
load_shares()
