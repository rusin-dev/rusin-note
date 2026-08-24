"""用户/会话/分享/犇犇存储：内存缓存 + 统一存储层（file / memory / upstash）

存储后端由 app.storage 的 select_backend() 决定：
- file 后端：保持原有「进程内字典缓存 + JSON 文件原子落盘」行为（本地/VPS）；
- upstash 后端：跨实例共享同一份数据（无服务器部署），写操作通过
  storage.lock 做跨实例互斥（SET NX EX），避免多实例并发读改写丢更新；
- memory 后端：纯内存，重启清空。

写路径约定：持 threading.Lock（进程内）+ storage.lock（跨进程/跨实例）
的块内**只更新内存缓存**，持久化在锁外执行（避免与 reload 死锁）。
"""
import secrets
import threading
import time

from . import config
from .config import (
    BENBEN_COOLDOWN_SECONDS,
    BENBEN_MAX_POSTS,
    SHARE_TOKEN_CHARSET,
    SHARE_TOKEN_LENGTH,
    SHARE_VIEWS_FLUSH_INTERVAL,
    SHARE_VIEWS_FLUSH_THRESHOLD,
)
from .logger import create_logger
from .storage import StorageError, storage

logger = create_logger("store")

# 键名（与存储后端的 KV 布局一一对应）
K_USERS = "users.json"
K_SESSIONS = "sessions.json"
K_SHARES = "shares.json"
K_BENBEN = "benben:posts"

# ---------- 内存缓存 ----------
users = {}
sessions = {}  # 格式: {sha256(token): {"username": str, "created_at": float}}
shares = {}  # 格式: {token: {"owner": str, "note_id": str, "created_at": float, "editable": bool, "views": int}}
users_lock = threading.Lock()
sessions_lock = threading.Lock()
shares_lock = threading.Lock()


def _persist(key: str, data: dict | list) -> bool:
    """将整个数据写回存储后端（锁外调用）"""
    try:
        return storage.set(key, data)
    except StorageError as e:
        logger.error(f"[错误] 存储写入 {key} 失败: {e}")
        return False


def _read(key: str):
    """从存储后端读取整个数据；缺失返回空容器，失败返回 None"""
    try:
        value = storage.get(key)
        if value is None:
            return None
        if isinstance(value, (dict, list)):
            return value
        return None
    except StorageError as e:
        logger.error(f"[错误] 存储读取 {key} 失败: {e}")
        return None


def _read_merge(key: str, target: dict):
    """存储锁保护下重读并合并进内存缓存（多实例同步最新数据）"""
    data = _read(key)
    if isinstance(data, dict):
        target.clear()
        target.update(data)


# ---------- 用户存储 ----------
def load_users():
    with users_lock:
        data = _read(K_USERS)
        if isinstance(data, dict):
            users.clear()
            users.update(data)


def reload_users() -> None:
    """从存储后端重新加载用户表（多实例下同步其它实例的注册）。原地更新以保持引用有效。"""
    with users_lock:
        _read_merge(K_USERS, users)


def get_user(username: str) -> dict | None:
    """读取用户记录：内存未命中时先从存储重载再查"""
    with users_lock:
        user = users.get(username)
    if user is not None:
        return user
    reload_users()
    with users_lock:
        return users.get(username)


def register_user(username: str, data: dict) -> bool:
    """跨实例安全注册：存储锁下重读最新用户表后检查并写入。
    返回 True 表示注册成功，False 表示用户名已存在或写入失败。"""
    try:
        with users_lock:
            with storage.lock(K_USERS):
                _read_merge(K_USERS, users)
                if username in users:
                    return False
                users[username] = data
                return _persist(K_USERS, users)
    except StorageError as e:
        logger.error(f"[错误] 注册用户失败: {e}")
        return False


def save_users():
    with users_lock:
        _persist(K_USERS, users)


# 用户总数统计：周期重载以同步多实例注册（避免每次 /count 都触发存储读取）
_last_users_reload = 0.0
_USERS_RELOAD_INTERVAL = 5.0


def get_user_count() -> int:
    """返回当前用户总数（带周期重载的缓存值）"""
    global _last_users_reload
    now = time.time()
    if now - _last_users_reload >= _USERS_RELOAD_INTERVAL:
        _last_users_reload = now
        reload_users()
    with users_lock:
        return len(users)


# ---------- 会话存储 ----------
def load_sessions():
    with sessions_lock:
        data = _read(K_SESSIONS)
        if isinstance(data, dict):
            sessions.clear()
            sessions.update(data)


def reload_sessions() -> None:
    """从存储后端重新加载会话（多实例下同步登录/登出）。原地更新以保持引用有效。"""
    with sessions_lock:
        _read_merge(K_SESSIONS, sessions)


def store_session(token_hash: str, data: dict) -> bool:
    """跨实例安全写入会话：存储锁下重读最新数据，避免多实例并发登录丢失更新"""
    try:
        with sessions_lock:
            with storage.lock(K_SESSIONS):
                _read_merge(K_SESSIONS, sessions)
                sessions[token_hash] = data
                return _persist(K_SESSIONS, sessions)
    except StorageError as e:
        logger.error(f"[错误] 写入会话失败: {e}")
        return False


def remove_session(token_hash: str) -> bool:
    """跨实例安全删除会话，返回是否存在并删除成功"""
    try:
        with sessions_lock:
            with storage.lock(K_SESSIONS):
                _read_merge(K_SESSIONS, sessions)
                if token_hash not in sessions:
                    return False
                del sessions[token_hash]
                return _persist(K_SESSIONS, sessions)
    except StorageError as e:
        logger.error(f"[错误] 删除会话失败: {e}")
        return False


def delete_sessions_if(pred) -> int:
    """跨实例安全删除满足 pred(token_hash, session) 的会话并落盘，返回删除数量。
    pred 需容忍 session 非 dict 的脏数据。"""
    try:
        with sessions_lock:
            with storage.lock(K_SESSIONS):
                _read_merge(K_SESSIONS, sessions)
                doomed = [h for h, s in sessions.items() if pred(h, s)]
                for h in doomed:
                    del sessions[h]
                if doomed:
                    _persist(K_SESSIONS, sessions)
                return len(doomed)
    except StorageError as e:
        logger.error(f"[错误] 清理会话失败: {e}")
        return 0


def save_sessions():
    with sessions_lock:
        _persist(K_SESSIONS, sessions)


# ---------- 分享存储 ----------
def load_shares():
    with shares_lock:
        data = _read(K_SHARES)
        if isinstance(data, dict):
            shares.clear()
            shares.update(data)


def save_shares():
    with shares_lock:
        _persist(K_SHARES, shares)


def generate_share_token() -> str:
    return ''.join(secrets.choice(SHARE_TOKEN_CHARSET) for _ in range(SHARE_TOKEN_LENGTH))


def create_share(username: str, note_id: str, editable: bool) -> str:
    """创建分享，返回分享 token（长度与字符集由配置决定）"""
    token = generate_share_token()
    try:
        with shares_lock:
            with storage.lock(K_SHARES):
                _read_merge(K_SHARES, shares)
                shares[token] = {
                    "owner": username,
                    "note_id": note_id,
                    "created_at": time.time(),
                    "editable": bool(editable),
                    "views": 0,
                }
                _persist(K_SHARES, shares)
    except StorageError as e:
        logger.error(f"[错误] 创建分享失败: {e}")
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
    try:
        with shares_lock:
            with storage.lock(K_SHARES):
                _read_merge(K_SHARES, shares)
                share = shares.get(token)
                if share is None or share.get("owner") != username:
                    return False
                del shares[token]
                return _persist(K_SHARES, shares)
    except StorageError as e:
        logger.error(f"[错误] 删除分享失败: {e}")
        return False


# 分享视图计数延迟批量持久化（BUG-06）：视图数非关键数据，允许延迟写盘。
# 内存累计达到阈值或距上次写盘超时后，才全量写一次，避免高并发下每次都触发写盘。
_VIEWS_DIRTY = False
_VIEWS_PENDING = 0
_last_views_flush = time.time()


def increment_share_views(token: str):
    """每次访问分享链接时计数（内存累加，延迟批量持久化，BUG-06）"""
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
    """将内存中的分享视图计数持久化（阈值/超时触发，后台线程定期调用）"""
    global _VIEWS_DIRTY, _VIEWS_PENDING, _last_views_flush
    # 锁顺序与其它写路径一致（线程锁 → 存储锁），存储锁内重读最新数据
    # 再合并计数，避免覆盖其它实例的新增分享
    try:
        with shares_lock:
            with storage.lock(K_SHARES):
                if not _VIEWS_DIRTY:
                    return
                _read_merge(K_SHARES, shares)
                _persist(K_SHARES, shares)
                _VIEWS_PENDING = 0
                _VIEWS_DIRTY = False
                _last_views_flush = time.time()
    except StorageError as e:
        logger.error(f"[错误] 分享视图刷新失败: {e}")


def list_user_shares(username: str) -> list:
    """返回该用户创建的所有分享 [(token, share), ...]"""
    with shares_lock:
        return [(tok, dict(s)) for tok, s in shares.items()
                if isinstance(s, dict) and s.get("owner") == username]


# ---------- 犇犇（用户动态）存储 ----------
# 内存缓存 + 持久化到存储后端（外部存储可用时重启不丢，最多保留 BENBEN_MAX_POSTS 条）
benben_posts = []  # 格式: [{"username": str, "content": str, "time": float, "ip": str}]，旧→新
benben_lock = threading.Lock()
_benben_last_resync = 0.0
_BENBEN_RESYNC_INTERVAL = 2.0


def _resync_benben_locked():
    """周期重载犇犇（多实例同步）。须已持有 benben_lock。"""
    global _benben_last_resync
    now = time.time()
    if now - _benben_last_resync < _BENBEN_RESYNC_INTERVAL:
        return
    _benben_last_resync = now
    data = _read(K_BENBEN)
    if isinstance(data, list):
        benben_posts.clear()
        benben_posts.extend(data)


def add_benben_post(username: str, content: str, ip: str = "") -> bool:
    """新增一条犇犇并持久化（跨实例互斥，超出上限丢弃最旧）。ip 为发布者 IP。"""
    try:
        with benben_lock:
            with storage.lock(K_BENBEN):
                data = _read(K_BENBEN)
                if isinstance(data, list):
                    benben_posts.clear()
                    benben_posts.extend(data)
                benben_posts.append({
                    "username": username,
                    "content": content,
                    "time": time.time(),
                    "ip": ip,
                })
                trimmed = benben_posts[-BENBEN_MAX_POSTS:] if BENBEN_MAX_POSTS > 0 else benben_posts
                ok = _persist(K_BENBEN, trimmed)
                if ok and len(trimmed) != len(benben_posts):
                    benben_posts.clear()
                    benben_posts.extend(trimmed)
                return ok
    except StorageError as e:
        logger.error(f"[错误] 发布犇犇失败: {e}")
        return False


# ---------- 犇犇发布冷却（单用户限流，内存态） ----------
# 格式: {username: 上次发布时间戳}。冷却时间由 config.BENBEN_COOLDOWN_SECONDS 控制。
benben_last_post = {}
benben_cooldown_lock = threading.Lock()


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
        _resync_benben_locked()
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


# ---------- 评论系统存储 ----------
# 所有评论存储在单个 KV 键 comments:all，格式：{target_key: [comment, ...]}
# target_key 格式："share:<token>" 或 "note:<username>:<note_id>"
# 每条评论格式: {"username": str, "content": str, "time": float, "ip": str, "is_anonymous": bool}
K_COMMENTS = "comments:all"
comments_data = {}  # {target_key: [comment, ...]}
comments_lock = threading.Lock()
_comments_last_resync = 0.0
_COMMENTS_RESYNC_INTERVAL = 2.0


def _comments_target_key(target_type: str, target_id: str) -> str:
    """构造评论目标键（内存中的键，不含存储层前缀）"""
    return f"{target_type}:{target_id}"


def _resync_comments_locked():
    """周期重载所有评论（多实例同步）。须已持有 comments_lock。"""
    global _comments_last_resync
    now = time.time()
    if now - _comments_last_resync < _COMMENTS_RESYNC_INTERVAL:
        return
    _comments_last_resync = now
    data = _read(K_COMMENTS)
    if isinstance(data, dict):
        comments_data.clear()
        comments_data.update(data)


def add_comment(target_type: str, target_id: str, username: str, content: str,
                ip: str = "", is_anonymous: bool = False) -> bool:
    """新增一条评论并持久化（跨实例互斥，超出上限丢弃最旧）。"""
    target_key = _comments_target_key(target_type, target_id)
    try:
        with comments_lock:
            with storage.lock(K_COMMENTS):
                _resync_comments_locked()
                if target_key not in comments_data:
                    comments_data[target_key] = []
                comments_data[target_key].append({
                    "username": username,
                    "content": content,
                    "time": time.time(),
                    "ip": ip,
                    "is_anonymous": is_anonymous,
                })
                # 超出上限丢弃最旧
                max_comments = config.COMMENTS_MAX_POSTS
                if max_comments > 0 and len(comments_data[target_key]) > max_comments:
                    comments_data[target_key] = comments_data[target_key][-max_comments:]
                ok = _persist(K_COMMENTS, dict(comments_data))
                return ok
    except StorageError as e:
        logger.error(f"[错误] 发布评论失败: {e}")
        return False


def get_comments(target_type: str, target_id: str, page: int, page_size: int):
    """按页返回评论（新→旧），page 从 1 开始。返回 (comments, has_more)。"""
    target_key = _comments_target_key(target_type, target_id)
    with comments_lock:
        _resync_comments_locked()
        posts = comments_data.get(target_key, [])
        total = len(posts)
    start = total - page * page_size
    if start < 0:
        start = 0
    end = total - (page - 1) * page_size
    if end <= 0:
        return [], False
    with comments_lock:
        result = list(posts[start:end])  # 旧→新
    result.reverse()  # 新→旧
    has_more = total > page * page_size
    return result, has_more


def count_comments(target_type: str, target_id: str) -> int:
    """返回指定目标的评论总数"""
    target_key = _comments_target_key(target_type, target_id)
    with comments_lock:
        _resync_comments_locked()
        return len(comments_data.get(target_key, []))


# ---------- 评论发布冷却（单用户限流，内存态） ----------
# 格式: {username: 上次发布时间戳}。冷却时间由 config.COMMENTS_COOLDOWN_SECONDS 控制。
comments_last_post = {}
comments_cooldown_lock = threading.Lock()


def get_comment_cooldown(username: str) -> float:
    """返回该用户距下次可发布的剩余冷却秒数，0 表示可以发布"""
    with comments_cooldown_lock:
        last = comments_last_post.get(username, 0)
    remaining = config.COMMENTS_COOLDOWN_SECONDS - (time.time() - last)
    return remaining if remaining > 0 else 0.0


def mark_comment_post(username: str):
    """记录用户最近一次成功发布评论的时间（发布成功后调用）"""
    with comments_cooldown_lock:
        comments_last_post[username] = time.time()


load_users()
load_sessions()
load_shares()