"""用户/会话/分享的字典存储与原子持久化，以及笔记文件路径与分享业务

多进程部署（gunicorn 多 worker）说明：
- 各进程内的字典（users/sessions）只是磁盘 JSON 的缓存副本。
- 写入走「进程内 Lock + 跨进程文件锁 + 原子写」保证不丢更新；
  读取在未命中/周期性从磁盘重载，保证其它 worker 的变更可见。
"""
import os
import json
import time
import secrets
from threading import Lock
from .logger import create_logger

try:
    import fcntl  # POSIX 跨进程文件锁
    _HAS_FCNTL = True
except ImportError:
    _HAS_FCNTL = False
    try:
        import msvcrt  # Windows 跨进程文件锁
    except ImportError:
        msvcrt = None


class _ProcessFileLock:
    """跨进程文件锁（POSIX fcntl.flock / Windows msvcrt.locking）。

    同一进程内的并发由各 store 的 threading.Lock 串行化，因此这里只会被
    单个线程持有，锁只用于仲裁不同 worker 进程之间的读改写。
    """

    def __init__(self, path: str):
        self._lock_path = path + ".lock"
        self._fh = None

    def acquire(self):
        fh = open(self._lock_path, "a+b")
        try:
            if _HAS_FCNTL:
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            elif msvcrt is not None:
                fh.seek(0)
                if fh.read(1) == b"":
                    fh.write(b"\0")
                    fh.flush()
                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_LOCK, 1)
        except Exception:
            fh.close()
            raise
        self._fh = fh
        return self

    def release(self):
        fh = self._fh
        if fh is None:
            return
        try:
            if _HAS_FCNTL:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
            elif msvcrt is not None:
                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
        finally:
            fh.close()
            self._fh = None

    def __enter__(self):
        return self.acquire()

    def __exit__(self, *exc):
        self.release()

from .config import (
    BENBEN_COOLDOWN_SECONDS,
    config,
    data_path,
    DEFAULT_CONFIG,
    SHARE_TOKEN_CHARSET,
    SHARE_TOKEN_LENGTH,
    SHARE_VIEWS_FLUSH_INTERVAL,
    SHARE_VIEWS_FLUSH_THRESHOLD,
)

logger = create_logger("store")

# ---------- 数据文件路径 ----------
USER_FILE = data_path("users.json")
SESSION_FILE = data_path("sessions.json")
SHARE_FILE = data_path("shares.json")
BENBEN_FILE = data_path("benben.json")
NOTES_BASE = data_path("notes")
os.makedirs(NOTES_BASE, exist_ok=True)

users = {}
sessions = {}  # 格式: {sha256(token): {"username": str, "created_at": float}}
shares = {}  # 格式: {token: {"owner": str, "note_id": str, "created_at": float, "editable": bool, "views": int}}
benben_posts = []  # 格式: [{"username": str, "content": str, "time": float}]，旧→新
users_lock = Lock()
sessions_lock = Lock()
shares_lock = Lock()
benben_lock = Lock()


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
        logger.error(f"[错误] 原子写入 {path} 失败: {e}")
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


def _read_json_safely(path: str):
    """读取 JSON 文件内容；文件缺失返回 {}，文件损坏返回 None（由调用方决定是否回退）"""
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def reload_users() -> None:
    """从磁盘重新加载用户表（多进程下同步其它 worker 的注册）。原地更新以保持引用有效。"""
    with users_lock:
        data = _read_json_safely(USER_FILE)
        if isinstance(data, dict):
            users.clear()
            users.update(data)


def get_user(username: str) -> dict | None:
    """跨进程读取用户记录：内存未命中时先从磁盘重载再查"""
    with users_lock:
        user = users.get(username)
    if user is not None:
        return user
    reload_users()
    with users_lock:
        return users.get(username)


def register_user(username: str, data: dict) -> bool:
    """跨进程安全注册：文件锁下重读最新用户表后检查并写入。
    返回 True 表示注册成功，False 表示用户名已存在或写入失败。"""
    with users_lock:
        with _ProcessFileLock(USER_FILE):
            disk = _read_json_safely(USER_FILE)
            if isinstance(disk, dict):
                users.clear()
                users.update(disk)
            if username in users:
                return False
            users[username] = data
            return _atomic_json_dump(USER_FILE, users)


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


def reload_sessions() -> None:
    """从磁盘重新加载会话（多进程下同步其它 worker 的登录/登出）。原地更新以保持引用有效。"""
    with sessions_lock:
        data = _read_json_safely(SESSION_FILE)
        if isinstance(data, dict):
            sessions.clear()
            sessions.update(data)


def store_session(token_hash: str, data: dict) -> bool:
    """跨进程安全写入会话：文件锁下重读最新数据，避免多 worker 并发登录丢失更新"""
    with sessions_lock:
        with _ProcessFileLock(SESSION_FILE):
            disk = _read_json_safely(SESSION_FILE)
            if isinstance(disk, dict):
                sessions.clear()
                sessions.update(disk)
            sessions[token_hash] = data
            return _atomic_json_dump(SESSION_FILE, sessions)


def remove_session(token_hash: str) -> bool:
    """跨进程安全删除会话，返回是否存在并删除成功"""
    with sessions_lock:
        with _ProcessFileLock(SESSION_FILE):
            disk = _read_json_safely(SESSION_FILE)
            if isinstance(disk, dict):
                sessions.clear()
                sessions.update(disk)
            if token_hash not in sessions:
                return False
            del sessions[token_hash]
            return _atomic_json_dump(SESSION_FILE, sessions)


def delete_sessions_if(pred) -> int:
    """跨进程安全删除满足 pred(token_hash, session) 的会话并落盘，返回删除数量。
    pred 需容忍 session 非 dict 的脏数据。"""
    with sessions_lock:
        with _ProcessFileLock(SESSION_FILE):
            disk = _read_json_safely(SESSION_FILE)
            if isinstance(disk, dict):
                sessions.clear()
                sessions.update(disk)
            doomed = [h for h, s in sessions.items() if pred(h, s)]
            for h in doomed:
                del sessions[h]
            if doomed:
                _atomic_json_dump(SESSION_FILE, sessions)
            return len(doomed)


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


# 分享视图计数延迟批量持久化（BUG-06）：视图数非关键数据，允许延迟写盘。
# 内存累计达到阈值或距上次写盘超时后，才全量写一次 shares.json，
# 避免高并发下每次访问分享链接都触发原子写盘（全量 JSON + fsync）。
_VIEWS_DIRTY = False
_VIEWS_PENDING = 0
_last_views_flush = time.time()


def increment_share_views(token: str):
    """每次访问分享链接时计数（内存累加，延迟批量写盘，BUG-06）"""
    global _VIEWS_DIRTY, _VIEWS_PENDING, _last_views_flush
    with shares_lock:
        share = shares.get(token)
        if not isinstance(share, dict):
            return
        share["views"] = share.get("views", 0) + 1
        _VIEWS_PENDING += 1
        _VIEWS_DIRTY = True
    if _VIEWS_PENDING >= SHARE_VIEWS_FLUSH_THRESHOLD or \
            (time.time() - _last_views_flush) >= SHARE_VIEWS_FLUSH_INTERVAL:
        flush_share_views()


def flush_share_views():
    """将内存中的分享视图计数写盘（阈值/超时触发，后台线程定期调用）"""
    global _VIEWS_DIRTY, _VIEWS_PENDING, _last_views_flush
    with shares_lock:
        if not _VIEWS_DIRTY:
            return
    save_shares()  # save_shares 会自行获取 shares_lock，须在持锁块外调用
    with shares_lock:
        _VIEWS_PENDING = 0
        _VIEWS_DIRTY = False
        _last_views_flush = time.time()


def list_user_shares(username: str) -> list:
    """返回该用户创建的所有分享 [(token, share), ...]"""
    with shares_lock:
        return [(tok, dict(s)) for tok, s in shares.items()
                if isinstance(s, dict) and s.get("owner") == username]


# ---------- 犇犇（用户动态）存储 ----------
def load_benben():
    global benben_posts
    if os.path.exists(BENBEN_FILE):
        try:
            with open(BENBEN_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                benben_posts = data
            else:
                benben_posts = []
        except Exception:
            benben_posts = []
    else:
        benben_posts = []


def save_benben():
    with benben_lock:
        _atomic_json_dump(BENBEN_FILE, benben_posts)


def add_benben_post(username: str, content: str, ip: str = "") -> bool:
    """新增一条犇犇（追加存储，不提供删除/清除）。ip 为发布者 IP（get_client_ip() 结果）。"""
    with benben_lock:
        benben_posts.append({
            "username": username,
            "content": content,
            "time": time.time(),
            "ip": ip,
        })
    save_benben()
    return True


# ---------- 犇犇发布冷却（单用户限流，内存态，重启清空） ----------
# 格式: {username: 上次发布时间戳}。冷却时间由 config.BENBEN_COOLDOWN_SECONDS 控制。
benben_last_post = {}
benben_cooldown_lock = Lock()


def get_benben_cooldown(username: str) -> float:
    """返回该用户距下次可发布的剩余冷却秒数，0 表示可以发布"""
    with benben_cooldown_lock:
        last = benben_last_post.get(username, 0)
    remaining = BENBEN_COOLDOWN_SECONDS - (time.time() - last)
    return remaining if remaining > 0 else 0.0


def mark_benben_post(username: str):
    """记录用户最近一次成功发布犇犇的时间（发布成功后调用）"""
    with benben_cooldown_lock:
        benben_last_post[username] = time.time()


def count_benben_posts() -> int:
    """返回犇犇总数"""
    with benben_lock:
        return len(benben_posts)


def get_benben_posts(page: int, page_size: int):
    """按页返回犇犇（新→旧），page 从 1 开始。返回 (posts, has_more)。"""
    with benben_lock:
        total = len(benben_posts)
    start = total - page * page_size
    if start < 0:
        start = 0
    end = total - (page - 1) * page_size
    if end <= 0:
        return [], False
    with benben_lock:
        posts = list(benben_posts[start:end])  # 旧→新
    posts.reverse()  # 新→旧
    has_more = total > page * page_size
    return posts, has_more


load_users()
load_sessions()
load_shares()
load_benben()
