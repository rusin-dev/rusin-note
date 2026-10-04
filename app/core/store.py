"""用户/会话/分享/犇犇/评论/组织存储：内存缓存 + 统一存储层。

写路径锁序：threading.Lock（进程内）→ storage.lock（跨实例），
锁内重读合并后再写，持久化在锁外的 _persist 执行。
"""
import secrets
import threading
import time

from app.core import config
from app.core.config import (
    BENBEN_COOLDOWN_SECONDS,
    BENBEN_MAX_POSTS,
    SHARE_TOKEN_CHARSET,
    SHARE_TOKEN_LENGTH,
    SHARE_VIEWS_FLUSH_INTERVAL,
    SHARE_VIEWS_FLUSH_THRESHOLD,
)
from app.core.logger import create_logger
from app.core.storage import StorageError, storage

logger = create_logger("store")

# 键名（与存储后端的 KV 布局一一对应）
K_USERS = "users.json"
K_SESSIONS = "sessions.json"
K_SHARES = "shares.json"
K_BENBEN = "benben:posts"

# ---------- 内存缓存 ----------
users = {}
sessions = {}  # {sha256(token): {"username", "created_at"}}
shares = {}  # {token: {"owner", "note_id", "created_at", "editable", "views"}}
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
    """重新加载用户表（多实例同步注册）。原地更新以保持引用有效。"""
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
    """跨实例安全注册。False = 用户名已存在或写入失败。"""
    try:
        with users_lock:
            with storage.lock(K_USERS):
                _read_merge(K_USERS, users)
                if username in users:
                    return False
                users[username] = data
                if _persist(K_USERS, users):
                    return True
                # 写盘失败必须回滚内存，否则幻影记录固化后误报「用户名已存在」
                users.pop(username, None)
                return False
    except StorageError as e:
        logger.error(f"[错误] 注册用户失败: {e}")
        return False


def update_user(username: str, updates: dict) -> bool:
    """跨实例安全读改更新用户记录，未列出字段保留。"""
    try:
        with users_lock:
            with storage.lock(K_USERS):
                _read_merge(K_USERS, users)
                user = users.get(username)
                if not isinstance(user, dict):
                    return False
                user.update(updates)
                return _persist(K_USERS, users)
    except StorageError as e:
        logger.error(f"[错误] 更新用户 {username} 失败: {e}")
        return False


# 用户总数：周期重载同步多实例，避免每次 /count 都读存储
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
    """重新加载会话（多实例同步登录/登出）。原地更新以保持引用有效。"""
    with sessions_lock:
        _read_merge(K_SESSIONS, sessions)


def store_session(token_hash: str, data: dict) -> bool:
    """跨实例安全写入会话（锁内重读，防并发登录丢更新）"""
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
    """删除满足 pred(token_hash, session) 的会话并落盘；pred 需容忍脏数据。"""
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


# ---------- 分享存储 ----------
def load_shares():
    with shares_lock:
        data = _read(K_SHARES)
        if isinstance(data, dict):
            shares.clear()
            shares.update(data)


# 只读路径周期重载（多实例）；浏览量增量存 _views_deltas，重载不丢（见 flush_share_views）
_shares_last_resync = 0.0
_SHARES_RESYNC_INTERVAL = 5.0


def _resync_shares_locked():
    """周期重载分享表（多实例同步）。须已持有 shares_lock。"""
    global _shares_last_resync
    now = time.time()
    if now - _shares_last_resync < _SHARES_RESYNC_INTERVAL:
        return
    _shares_last_resync = now
    _read_merge(K_SHARES, shares)


def generate_share_token() -> str:
    return ''.join(secrets.choice(SHARE_TOKEN_CHARSET) for _ in range(SHARE_TOKEN_LENGTH))


def create_share(username: str, note_id: str, editable: bool) -> str:
    """创建分享并返回 token；写入失败返回空串。"""
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
                if _persist(K_SHARES, shares):
                    return token
                shares.pop(token, None)
    except StorageError as e:
        logger.error(f"[错误] 创建分享失败: {e}")
        with shares_lock:
            shares.pop(token, None)
    return ""


def get_share(token: str) -> dict | None:
    """返回分享条目；损坏/旧版数据（缺 owner/note_id）返回 None"""
    with shares_lock:
        _resync_shares_locked()
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


def delete_shares_for_note(username: str, note_id: str) -> list:
    """级联删除指向该笔记的全部分享，返回被删 token 列表。

    不级联的话，可编辑分享链接会把匿名访客的 POST 写回已删笔记的命名空间。
    """
    removed = []
    try:
        with shares_lock:
            with storage.lock(K_SHARES):
                _read_merge(K_SHARES, shares)
                for tok, share in list(shares.items()):
                    if (isinstance(share, dict) and share.get("owner") == username
                            and share.get("note_id") == note_id):
                        del shares[tok]
                        removed.append(tok)
                if not removed:
                    return []
                if not _persist(K_SHARES, shares):
                    return []
    except StorageError as e:
        logger.error(f"[错误] 级联删除分享失败: {e}")
        return []
    with shares_lock:
        for tok in removed:
            _views_deltas.pop(tok, None)
    return removed


# 分享浏览量延迟批量写盘：非关键数据，达阈值或超时才整表写一次
_VIEWS_DIRTY = False
_VIEWS_PENDING = 0
_last_views_flush = time.time()
# 每 token 的待写增量须独立保存：写盘前内存表会被存储最新数据替换（多实例合并），
# 否则增量在合并时被丢弃
_views_deltas = {}


def increment_share_views(token: str):
    """访问分享链接时计数（内存累加，延迟批量持久化）"""
    global _VIEWS_DIRTY, _VIEWS_PENDING, _last_views_flush
    with shares_lock:
        share = shares.get(token)
        if not isinstance(share, dict):
            return
        share["views"] = share.get("views", 0) + 1
        _views_deltas[token] = _views_deltas.get(token, 0) + 1
        _VIEWS_PENDING += 1
        _VIEWS_DIRTY = True
    if _VIEWS_PENDING >= SHARE_VIEWS_FLUSH_THRESHOLD or \
            (time.time() - _last_views_flush) >= SHARE_VIEWS_FLUSH_INTERVAL:
        flush_share_views()


def flush_share_views():
    """将浏览量计数持久化（阈值/超时触发，后台线程定期调用）"""
    global _VIEWS_DIRTY, _VIEWS_PENDING, _last_views_flush
    deltas = {}
    requeue = False
    # 锁序与其它写路径一致（线程锁 → 存储锁），存储锁内先重读合并再写
    try:
        with shares_lock:
            with storage.lock(K_SHARES):
                if not _VIEWS_DIRTY:
                    return
                deltas = dict(_views_deltas)
                _views_deltas.clear()
                _read_merge(K_SHARES, shares)
                for tok, delta in deltas.items():
                    share = shares.get(tok)
                    if isinstance(share, dict):
                        share["views"] = share.get("views", 0) + delta
                if _persist(K_SHARES, shares):
                    _VIEWS_PENDING = 0
                    _VIEWS_DIRTY = False
                else:
                    logger.error("[错误] 分享视图写盘失败，计数将延后重试")
                    requeue = True
                _last_views_flush = time.time()
    except StorageError as e:
        logger.error(f"[错误] 分享视图刷新失败: {e}")
        requeue = True
        _last_views_flush = time.time()
    if requeue:
        _requeue_views(deltas)


def _requeue_views(deltas: dict):
    """把未落盘的浏览增量并回待写集合，下次触发重试"""
    if not deltas:
        return
    with shares_lock:
        for tok, delta in deltas.items():
            _views_deltas[tok] = _views_deltas.get(tok, 0) + delta


def list_user_shares(username: str) -> list:
    """返回该用户创建的所有分享 [(token, share), ...]"""
    with shares_lock:
        _resync_shares_locked()
        return [(tok, dict(s)) for tok, s in shares.items()
                if isinstance(s, dict) and s.get("owner") == username]


# ---------- 犇犇（用户动态）存储 ----------
benben_posts = []  # [{"username", "content", "time", "ip"}]，旧→新
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


# ---------- 犇犇发布冷却（内存态，秒数见 config.BENBEN_COOLDOWN_SECONDS） ----------
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


# ---------- 评论存储 ----------
# 单键 comments:all：{target_key: [comment, ...]}，target_key 为 "share:<token>" 或 "note:<用户>/<笔记>"
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
                # 存储锁内必须无条件重读：TTL 节流重载会基于过期整表覆盖其它实例的评论
                _read_merge(K_COMMENTS, comments_data)
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


def delete_comments_for_note(username: str, note_id: str) -> bool:
    """删除挂在指定笔记上的评论板（笔记删除时级联调用）。"""
    target_key = _comments_target_key("note", f"{username}/{note_id}")
    try:
        with comments_lock:
            with storage.lock(K_COMMENTS):
                _read_merge(K_COMMENTS, comments_data)
                if target_key not in comments_data:
                    return True
                del comments_data[target_key]
                return _persist(K_COMMENTS, dict(comments_data))
    except StorageError as e:
        logger.error(f"[错误] 级联删除评论失败: {e}")
        return False


# ---------- 评论发布冷却（内存态，秒数见 config.COMMENTS_COOLDOWN_SECONDS） ----------
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


# ---------- 组织存储 ----------
orgs = {}  # {org_name: {"name", "description", "owner", "join_policy", "created_at"}}
org_members = {}  # {org_name: {username: {"role", "joined_at"}}}
org_invites = {}  # {invite_code: {"org_name", "created_by", "type", "created_at", "expires_at"}}
org_join_requests = {}  # {org_name: {username: {"message", "created_at", "status"}}}

orgs_lock = threading.Lock()
org_members_lock = threading.Lock()
org_invites_lock = threading.Lock()
org_join_requests_lock = threading.Lock()

K_ORGS = "orgs"
K_ORG_MEMBERS = "org_members"
K_ORG_INVITES = "org_invites"
K_ORG_JOIN_REQUESTS = "org_join_requests"

# 组织角色层级
ROLE_LEVELS = {"owner": 3, "admin": 2, "member": 1}


def load_orgs():
    with orgs_lock:
        data = _read(K_ORGS)
        if isinstance(data, dict):
            orgs.clear()
            orgs.update(data)


def load_org_members():
    with org_members_lock:
        data = _read(K_ORG_MEMBERS)
        if isinstance(data, dict):
            org_members.clear()
            org_members.update(data)


def load_org_invites():
    with org_invites_lock:
        data = _read(K_ORG_INVITES)
        if isinstance(data, dict):
            org_invites.clear()
            org_invites.update(data)


def load_org_join_requests():
    with org_join_requests_lock:
        data = _read(K_ORG_JOIN_REQUESTS)
        if isinstance(data, dict):
            org_join_requests.clear()
            org_join_requests.update(data)


def create_org(org_name: str, name: str, owner: str, description: str = "", join_policy: str = "invite") -> bool:
    """创建组织，创建者自动成为 owner"""
    try:
        with orgs_lock:
            with org_members_lock:
                with storage.lock(K_ORGS):
                    with storage.lock(K_ORG_MEMBERS):
                        _read_merge(K_ORGS, orgs)
                        if org_name in orgs:
                            return False
                        orgs[org_name] = {
                            "name": name,
                            "description": description,
                            "owner": owner,
                            "join_policy": join_policy,
                            "created_at": time.time(),
                        }
                        if not _persist(K_ORGS, orgs):
                            return False
                        _read_merge(K_ORG_MEMBERS, org_members)
                        if org_name not in org_members:
                            org_members[org_name] = {}
                        org_members[org_name][owner] = {
                            "role": "owner",
                            "joined_at": time.time(),
                        }
                        return _persist(K_ORG_MEMBERS, org_members)
    except StorageError as e:
        logger.error(f"[错误] 创建组织失败: {e}")
        return False


# 只读路径周期重载：只读实例否则永远看不到其它实例的成员/组织变更
_orgs_last_resync = 0.0
_org_members_last_resync = 0.0
_ORG_RESYNC_INTERVAL = 5.0


def _resync_orgs_locked():
    """周期重载组织表。须已持有 orgs_lock。"""
    global _orgs_last_resync
    now = time.time()
    if now - _orgs_last_resync < _ORG_RESYNC_INTERVAL:
        return
    _orgs_last_resync = now
    _read_merge(K_ORGS, orgs)


def _resync_org_members_locked():
    """周期重载组织成员表。须已持有 org_members_lock。"""
    global _org_members_last_resync
    now = time.time()
    if now - _org_members_last_resync < _ORG_RESYNC_INTERVAL:
        return
    _org_members_last_resync = now
    _read_merge(K_ORG_MEMBERS, org_members)


def get_org(org_name: str) -> dict | None:
    with orgs_lock:
        _resync_orgs_locked()
        return orgs.get(org_name)


_org_invites_last_resync = 0.0


def _resync_org_invites_locked():
    """周期重载邀请码表（否则已撤销/已用码在其它实例仍可用）。须已持锁。"""
    global _org_invites_last_resync
    now = time.time()
    if now - _org_invites_last_resync < _ORG_RESYNC_INTERVAL:
        return
    _org_invites_last_resync = now
    _read_merge(K_ORG_INVITES, org_invites)


def update_org(org_name: str, updates: dict) -> bool:
    """更新组织信息（仅 owner/admin 可调用）"""
    try:
        with orgs_lock:
            with storage.lock(K_ORGS):
                _read_merge(K_ORGS, orgs)
                if org_name not in orgs:
                    return False
                orgs[org_name].update(updates)
                return _persist(K_ORGS, orgs)
    except StorageError as e:
        logger.error(f"[错误] 更新组织失败: {e}")
        return False


def delete_org(org_name: str) -> bool:
    """删除组织（仅 owner），级联清理成员、邀请码、入群申请与组织笔记。"""
    try:
        with orgs_lock:
            with org_members_lock:
                with storage.lock(K_ORGS):
                    with storage.lock(K_ORG_MEMBERS):
                        _read_merge(K_ORGS, orgs)
                        if org_name not in orgs:
                            return False
                        del orgs[org_name]
                        if not _persist(K_ORGS, orgs):
                            return False
                        _read_merge(K_ORG_MEMBERS, org_members)
                        org_members.pop(org_name, None)
                        if not _persist(K_ORG_MEMBERS, org_members):
                            return False
    except StorageError as e:
        logger.error(f"[错误] 删除组织失败: {e}")
        return False

    # 级联清理须在 orgs/org_members 线程锁之外（笔记删除钩子会再取存储锁），
    # 否则同名重建的组织会继承旧笔记与邀请码
    from app.core.notes import write_note
    namespace = f"_orgs/{org_name}"
    try:
        for note_id in storage.list_notes(namespace):
            write_note(namespace, note_id, "")
    except StorageError as e:
        logger.error(f"[错误] 清理组织笔记失败: {e}")
    delete_org_invites_for(org_name)
    delete_org_join_requests_for(org_name)
    return True


def add_org_member(org_name: str, username: str, role: str = "member") -> bool:
    """添加组织成员"""
    try:
        with org_members_lock:
            with storage.lock(K_ORG_MEMBERS):
                _read_merge(K_ORG_MEMBERS, org_members)
                if org_name not in org_members:
                    org_members[org_name] = {}
                if username in org_members[org_name]:
                    return False  # 已是成员
                org_members[org_name][username] = {
                    "role": role,
                    "joined_at": time.time(),
                }
                return _persist(K_ORG_MEMBERS, org_members)
    except StorageError as e:
        logger.error(f"[错误] 添加组织成员失败: {e}")
        return False


def remove_org_member(org_name: str, username: str) -> bool:
    """移除组织成员（不能移除 owner）"""
    try:
        with orgs_lock:
            with org_members_lock:
                with storage.lock(K_ORGS):
                    with storage.lock(K_ORG_MEMBERS):
                        _read_merge(K_ORGS, orgs)
                        org = orgs.get(org_name)
                        if not org or org.get("owner") == username:
                            return False  # 不能移除 owner
                        _read_merge(K_ORG_MEMBERS, org_members)
                        if org_name not in org_members:
                            return False
                        if username not in org_members[org_name]:
                            return False
                        del org_members[org_name][username]
                        return _persist(K_ORG_MEMBERS, org_members)
    except StorageError as e:
        logger.error(f"[错误] 移除组织成员失败: {e}")
        return False


def update_org_member_role(org_name: str, username: str, new_role: str) -> bool:
    """更新成员角色（不能修改 owner 的角色）"""
    try:
        with orgs_lock:
            with org_members_lock:
                with storage.lock(K_ORGS):
                    with storage.lock(K_ORG_MEMBERS):
                        _read_merge(K_ORGS, orgs)
                        org = orgs.get(org_name)
                        if not org or org.get("owner") == username:
                            return False  # 不能修改 owner 角色
                        _read_merge(K_ORG_MEMBERS, org_members)
                        if org_name not in org_members or username not in org_members[org_name]:
                            return False
                        org_members[org_name][username]["role"] = new_role
                        return _persist(K_ORG_MEMBERS, org_members)
    except StorageError as e:
        logger.error(f"[错误] 更新成员角色失败: {e}")
        return False


def get_org_member_role(org_name: str, username: str) -> str | None:
    """获取成员角色，返回 None if not a member"""
    with org_members_lock:
        _resync_org_members_locked()
        return org_members.get(org_name, {}).get(username, {}).get("role")


def get_org_members(org_name: str) -> dict:
    """获取组织所有成员及角色"""
    with org_members_lock:
        _resync_org_members_locked()
        return dict(org_members.get(org_name, {}))


def get_user_orgs(username: str) -> list:
    """获取用户所在的所有组织"""
    result = []
    with org_members_lock:
        _resync_org_members_locked()
        for org_name, members in org_members.items():
            if username in members:
                result.append(org_name)
    return result


def get_user_role_level(username: str, org_name: str) -> int:
    """获取用户在组织中的角色等级（用于权限比较）"""
    role = get_org_member_role(org_name, username)
    return ROLE_LEVELS.get(role, 0)


def can_org_do(org_name: str, username: str, min_role: str) -> bool:
    """检查用户是否有足够的组织权限（min_role: member < admin < owner）"""
    return get_user_role_level(username, org_name) >= ROLE_LEVELS.get(min_role, 0)


def create_org_invite(org_name: str, created_by: str, invite_type: str = "invite",
                      expires_days: int = 7) -> str | None:
    """创建邀请码，返回邀请码字符串"""
    try:
        invite_code = secrets.token_hex(16)
        with org_invites_lock:
            with storage.lock(K_ORG_INVITES):
                _read_merge(K_ORG_INVITES, org_invites)
                org_invites[invite_code] = {
                    "org_name": org_name,
                    "created_by": created_by,
                    "type": invite_type,
                    "created_at": time.time(),
                    "expires_at": time.time() + expires_days * 86400,
                }
                if _persist(K_ORG_INVITES, org_invites):
                    return invite_code
                return None
    except StorageError as e:
        logger.error(f"[错误] 创建邀请码失败: {e}")
        return None


def validate_org_invite(invite_code: str) -> dict | None:
    """验证邀请码是否有效，返回邀请信息或 None"""
    with org_invites_lock:
        _resync_org_invites_locked()
        invite = org_invites.get(invite_code)
        if not invite:
            return None
        if time.time() > invite.get("expires_at", 0):
            return None
        return dict(invite)


def delete_org_invite(invite_code: str, org_name: str | None = None) -> bool:
    """删除邀请码。给出 org_name 时只删该组织自己的码，防跨组织销毁。"""
    try:
        with org_invites_lock:
            with storage.lock(K_ORG_INVITES):
                _read_merge(K_ORG_INVITES, org_invites)
                invite = org_invites.get(invite_code)
                if not isinstance(invite, dict):
                    return False
                if org_name is not None and invite.get("org_name") != org_name:
                    return False
                del org_invites[invite_code]
                return _persist(K_ORG_INVITES, org_invites)
    except StorageError as e:
        logger.error(f"[错误] 删除邀请码失败: {e}")
        return False


def delete_org_invites_for(org_name: str) -> bool:
    """删除该组织的全部邀请码（组织被删除时级联，避免同名重建后旧码仍可用）"""
    try:
        with org_invites_lock:
            with storage.lock(K_ORG_INVITES):
                _read_merge(K_ORG_INVITES, org_invites)
                doomed = [code for code, info in org_invites.items()
                          if isinstance(info, dict) and info.get("org_name") == org_name]
                if not doomed:
                    return True
                for code in doomed:
                    del org_invites[code]
                return _persist(K_ORG_INVITES, org_invites)
    except StorageError as e:
        logger.error(f"[错误] 清理组织邀请码失败: {e}")
        return False


def delete_org_join_requests_for(org_name: str) -> bool:
    """删除该组织的全部加入申请（组织被删除时级联）。申请按组织名分键存储。"""
    try:
        with org_join_requests_lock:
            with storage.lock(K_ORG_JOIN_REQUESTS):
                _read_merge(K_ORG_JOIN_REQUESTS, org_join_requests)
                if org_name not in org_join_requests:
                    return True
                del org_join_requests[org_name]
                return _persist(K_ORG_JOIN_REQUESTS, org_join_requests)
    except StorageError as e:
        logger.error(f"[错误] 清理组织加入申请失败: {e}")
        return False


def get_org_invites(org_name: str) -> list:
    """获取组织所有有效邀请码"""
    result = []
    with org_invites_lock:
        _resync_org_invites_locked()
        for code, info in org_invites.items():
            if info.get("org_name") == org_name and time.time() <= info.get("expires_at", 0):
                result.append({"code": code, **info})
    return result


def create_join_request(org_name: str, username: str, message: str = "") -> bool:
    """创建加入申请（申请审批制）"""
    try:
        with org_join_requests_lock:
            with storage.lock(K_ORG_JOIN_REQUESTS):
                _read_merge(K_ORG_JOIN_REQUESTS, org_join_requests)
                if org_name not in org_join_requests:
                    org_join_requests[org_name] = {}
                if username in org_join_requests[org_name]:
                    return False  # 已有申请
                org_join_requests[org_name][username] = {
                    "message": message,
                    "created_at": time.time(),
                    "status": "pending",
                }
                return _persist(K_ORG_JOIN_REQUESTS, org_join_requests)
    except StorageError as e:
        logger.error(f"[错误] 创建加入申请失败: {e}")
        return False


def approve_join_request(org_name: str, username: str) -> bool:
    """批准加入申请，同时自动添加为成员"""
    try:
        with org_join_requests_lock:
            with org_members_lock:
                with storage.lock(K_ORG_JOIN_REQUESTS):
                    with storage.lock(K_ORG_MEMBERS):
                        _read_merge(K_ORG_JOIN_REQUESTS, org_join_requests)
                        if org_name not in org_join_requests:
                            return False
                        req = org_join_requests[org_name].get(username)
                        if not req or req.get("status") != "pending":
                            return False
                        req["status"] = "approved"
                        if not _persist(K_ORG_JOIN_REQUESTS, org_join_requests):
                            return False
                        _read_merge(K_ORG_MEMBERS, org_members)
                        if org_name not in org_members:
                            org_members[org_name] = {}
                        org_members[org_name][username] = {
                            "role": "member",
                            "joined_at": time.time(),
                        }
                        return _persist(K_ORG_MEMBERS, org_members)
    except StorageError as e:
        logger.error(f"[错误] 批准加入申请失败: {e}")
        return False


def reject_join_request(org_name: str, username: str) -> bool:
    """拒绝加入申请"""
    try:
        with org_join_requests_lock:
            with storage.lock(K_ORG_JOIN_REQUESTS):
                _read_merge(K_ORG_JOIN_REQUESTS, org_join_requests)
                if org_name not in org_join_requests:
                    return False
                req = org_join_requests[org_name].get(username)
                if not req or req.get("status") != "pending":
                    return False
                req["status"] = "rejected"
                return _persist(K_ORG_JOIN_REQUESTS, org_join_requests)
    except StorageError as e:
        logger.error(f"[错误] 拒绝加入申请失败: {e}")
        return False


def get_org_join_requests(org_name: str, status: str = None) -> dict:
    """获取组织的加入申请，可按 status 过滤"""
    with org_join_requests_lock:
        requests = org_join_requests.get(org_name, {})
        if status:
            return {u: r for u, r in requests.items() if r.get("status") == status}
        return dict(requests)


def org_invite_join(invite_code: str, username: str) -> bool:
    """通过邀请码加入组织"""
    try:
        invite = validate_org_invite(invite_code)
        if not invite:
            return False
        org_name = invite.get("org_name")
        org = get_org(org_name)
        if not org:
            return False
        policy = org.get("join_policy")
        if policy == "invite" and invite.get("type") != "invite":
            return False
        with org_members_lock:
            if org_name in org_members and username in org_members[org_name]:
                return False  # 已是成员
        return add_org_member(org_name, username, "member")
    except StorageError as e:
        logger.error(f"[错误] 通过邀请码加入组织失败: {e}")
        return False


def org_public_join(org_name: str, username: str) -> bool:
    """公开加入组织"""
    org = get_org(org_name)
    if not org or org.get("join_policy") != "public":
        return False
    return add_org_member(org_name, username, "member")


# ---------- 用户改名：身份标识迁移 ----------
# 用户名同时是笔记/图床/附件的存储命名空间，改名需迁移下列各表中的用户标识。
# 各子系统独立加锁（threading.Lock → storage.lock），任一失败返回 False 供重试。
def rename_user_records(old: str, new: str) -> bool:
    """迁移 users / sessions / shares / benben / comments / orgs 中的用户标识。"""
    ok = True

    # users：移动整条记录
    try:
        with users_lock:
            with storage.lock(K_USERS):
                _read_merge(K_USERS, users)
                if old not in users or new in users:
                    return False
                users[new] = users.pop(old)
                ok = _persist(K_USERS, users) and ok
    except StorageError as e:
        logger.error(f"[错误] 迁移用户记录失败: {e}")
        return False

    # sessions.json：会话记录里的 username 字段
    try:
        with sessions_lock:
            with storage.lock(K_SESSIONS):
                _read_merge(K_SESSIONS, sessions)
                changed = False
                for sess in sessions.values():
                    if isinstance(sess, dict) and sess.get("username") == old:
                        sess["username"] = new
                        changed = True
                if changed:
                    ok = _persist(K_SESSIONS, sessions) and ok
    except StorageError as e:
        logger.error(f"[错误] 迁移会话失败: {e}")
        return False

    # shares.json：分享的 owner 字段
    try:
        with shares_lock:
            with storage.lock(K_SHARES):
                _read_merge(K_SHARES, shares)
                changed = False
                for share in shares.values():
                    if isinstance(share, dict) and share.get("owner") == old:
                        share["owner"] = new
                        changed = True
                if changed:
                    ok = _persist(K_SHARES, shares) and ok
    except StorageError as e:
        logger.error(f"[错误] 迁移分享失败: {e}")
        return False

    # 犇犇：帖子作者字段
    try:
        with benben_lock:
            with storage.lock(K_BENBEN):
                data = _read(K_BENBEN)
                posts = data if isinstance(data, list) else list(benben_posts)
                changed = False
                for post in posts:
                    if isinstance(post, dict) and post.get("username") == old:
                        post["username"] = new
                        changed = True
                if changed:
                    ok = _persist(K_BENBEN, posts) and ok
                benben_posts.clear()
                benben_posts.extend(posts)
    except StorageError as e:
        logger.error(f"[错误] 迁移犇犇失败: {e}")
        return False

    # comments:all：评论作者字段 + 目标键 note:<user>:<id>
    try:
        with comments_lock:
            with storage.lock(K_COMMENTS):
                data = _read(K_COMMENTS)
                table = data if isinstance(data, dict) else dict(comments_data)
                migrated = {}
                # 目标键有 note:<用户>/<笔记> 与 note:<用户>:<笔记> 两种历史写法，都要迁移
                for target_key, items in table.items():
                    new_key = target_key
                    if isinstance(target_key, str) and target_key.startswith("note:"):
                        body = target_key[len("note:"):]
                        if body.startswith(old) and len(body) > len(old) and body[len(old)] in "/:":
                            sep = body[len(old)]
                            new_key = f"note:{new}{sep}{body[len(old) + 1:]}"
                    if isinstance(items, list):
                        for comment in items:
                            if isinstance(comment, dict) and comment.get("username") == old:
                                comment["username"] = new
                    existing = migrated.get(new_key)
                    if existing is None:
                        migrated[new_key] = items
                    elif isinstance(existing, list) and isinstance(items, list):
                        # 键撞车时合并，整表赋值会丢掉一边
                        merged = existing + items
                        merged.sort(
                            key=lambda c: c.get("time", 0) if isinstance(c, dict) else 0)
                        migrated[new_key] = merged
                    else:
                        migrated[new_key] = items
                if migrated != table:
                    ok = _persist(K_COMMENTS, migrated) and ok
                comments_data.clear()
                comments_data.update(migrated)
    except StorageError as e:
        logger.error(f"[错误] 迁移评论失败: {e}")
        return False

    # 组织：owner 字段、成员键、邀请创建者、入群申请键
    try:
        with orgs_lock:
            with storage.lock(K_ORGS):
                _read_merge(K_ORGS, orgs)
                changed = False
                for org in orgs.values():
                    if isinstance(org, dict) and org.get("owner") == old:
                        org["owner"] = new
                        changed = True
                if changed:
                    ok = _persist(K_ORGS, orgs) and ok
    except StorageError as e:
        logger.error(f"[错误] 迁移组织失败: {e}")
        return False

    try:
        with org_members_lock:
            with storage.lock(K_ORG_MEMBERS):
                _read_merge(K_ORG_MEMBERS, org_members)
                changed = False
                for members in org_members.values():
                    if isinstance(members, dict) and old in members:
                        members[new] = members.pop(old)
                        changed = True
                if changed:
                    ok = _persist(K_ORG_MEMBERS, org_members) and ok
    except StorageError as e:
        logger.error(f"[错误] 迁移组织成员失败: {e}")
        return False

    try:
        with org_invites_lock:
            with storage.lock(K_ORG_INVITES):
                _read_merge(K_ORG_INVITES, org_invites)
                changed = False
                for invite in org_invites.values():
                    if isinstance(invite, dict) and invite.get("created_by") == old:
                        invite["created_by"] = new
                        changed = True
                if changed:
                    ok = _persist(K_ORG_INVITES, org_invites) and ok
    except StorageError as e:
        logger.error(f"[错误] 迁移组织邀请失败: {e}")
        return False

    try:
        with org_join_requests_lock:
            with storage.lock(K_ORG_JOIN_REQUESTS):
                _read_merge(K_ORG_JOIN_REQUESTS, org_join_requests)
                changed = False
                for requests in org_join_requests.values():
                    if isinstance(requests, dict) and old in requests:
                        requests[new] = requests.pop(old)
                        changed = True
                if changed:
                    ok = _persist(K_ORG_JOIN_REQUESTS, org_join_requests) and ok
    except StorageError as e:
        logger.error(f"[错误] 迁移组织申请失败: {e}")
        return False

    # 发布冷却表是内存态，尽力迁移（缺失不影响功能正确性）
    with benben_cooldown_lock:
        if old in benben_last_post:
            benben_last_post[new] = benben_last_post.pop(old)
    with comments_cooldown_lock:
        if old in comments_last_post:
            comments_last_post[new] = comments_last_post.pop(old)

    return ok


load_users()
load_sessions()
load_shares()
load_orgs()
load_org_members()
load_org_invites()
load_org_join_requests()