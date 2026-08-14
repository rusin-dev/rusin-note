"""笔记文件操作、校验、统计、随机 ID 与过期笔记清理"""
import os
import re
import time
import random

from . import config
from .store import NOTES_BASE, users

# 禁止的笔记ID（与路由冲突）
FORBIDDEN_NOTE_IDS = {"user", "world", "shares"}

# 保留用户名（与固定路由或 notes/ 目录冲突，禁止注册）
# 注意：public 与公开笔记存储目录 notes/public/ 冲突，必须保留
RESERVED_USERNAMES = {"register", "login", "logout", "count", "disclaimer",
                      "favicon", "share", "shares", "world", "user", "new", "md",
                      "public", "benben"}


# ---------- 校验 ----------
def validate_username(username: str) -> bool:
    if username.lower() in RESERVED_USERNAMES:
        return False
    return bool(re.match(r'^[a-zA-Z0-9_\-]+$', username))


def validate_note_id(note_id: str) -> bool:
    if note_id in FORBIDDEN_NOTE_IDS:
        return False
    return bool(re.match(r'^[a-zA-Z0-9_\-]+$', note_id))


# ---------- 笔记文件操作 ----------
def get_user_note_dir(username: str) -> str:
    path = os.path.join(NOTES_BASE, username)
    os.makedirs(path, exist_ok=True)
    return path


def get_note_path(username: str, note_id: str) -> str | None:
    # "public" 是内部公开笔记存储命名空间，不是用户账号，需放行（validate_username 会拒绝它）
    if username != "public" and not validate_username(username):
        return None
    if not validate_note_id(note_id):
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
# BUG-16: 统计结果缓存（TTL 30 秒），避免每次 /count 请求全目录遍历
STATS_CACHE_TTL = 30
_stats_cache = None
_stats_cache_time = 0.0


def get_stats():
    """返回 (public_count, public_size, private_count, private_size, user_count)"""
    global _stats_cache, _stats_cache_time
    now = time.time()
    if _stats_cache is not None and now - _stats_cache_time < STATS_CACHE_TTL:
        return _stats_cache

    public_count = 0
    public_size = 0
    private_count = 0
    private_size = 0
    user_count = len(users)

    if os.path.exists(NOTES_BASE):
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

    result = (public_count, public_size, private_count, private_size, user_count)
    _stats_cache = result
    _stats_cache_time = now
    return result


# ---------- 随机ID生成 ----------
def generate_random_id() -> str:
    while True:
        rid = ''.join(random.choices(config.ID_CHARSET, k=config.ID_LENGTH))
        if rid not in FORBIDDEN_NOTE_IDS:
            return rid


# ---------- 过期笔记清除（超出保存时间的剪贴板自动删除） ----------
def purge_expired_notes() -> int:
    """删除最后修改时间超过 NOTE_EXPIRATION_SECONDS 的笔记文件，返回删除数量（仅在启用时生效）"""
    if not config.NOTE_EXPIRATION_ENABLED:
        return 0
    cutoff = time.time() - config.NOTE_EXPIRATION_SECONDS
    removed = 0
    for dirpath, _dirs, filenames in os.walk(NOTES_BASE):
        for fname in filenames:
            if not fname.endswith(".txt"):
                continue
            fpath = os.path.join(dirpath, fname)
            try:
                if os.path.getmtime(fpath) < cutoff:
                    os.remove(fpath)
                    removed += 1
            except (IOError, OSError):
                pass
    if removed:
        print(f"[清理] 已清除 {removed} 个过期笔记（保存超过 {config.NOTE_EXPIRATION_HOURS} 小时）")
    return removed


def note_cleanup_loop():
    """后台线程：定时清除过期笔记"""
    while True:
        time.sleep(config.NOTE_CLEANUP_INTERVAL)
        try:
            purge_expired_notes()
        except Exception as e:
            print(f"[错误] 过期笔记清理失败: {e}")
