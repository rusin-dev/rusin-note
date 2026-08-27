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


# ---------- 组织存储 ----------
# orgs: {org_name: {"name": str, "description": str, "owner": str, "join_policy": str, "created_at": float}}
orgs = {}
# org_members: {org_name: {username: {"role": str, "joined_at": float}}}
org_members = {}
# org_invites: {invite_code: {"org_name": str, "created_by": str, "type": str, "created_at": float, "expires_at": float}}
org_invites = {}
# org_join_requests: {org_name: {username: {"message": str, "created_at": float, "status": str}}}
org_join_requests = {}

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


def save_orgs():
    with orgs_lock:
        _persist(K_ORGS, orgs)


def save_org_members():
    with org_members_lock:
        _persist(K_ORG_MEMBERS, org_members)


def save_org_invites():
    with org_invites_lock:
        _persist(K_ORG_INVITES, org_invites)


def save_org_join_requests():
    with org_join_requests_lock:
        _persist(K_ORG_JOIN_REQUESTS, org_join_requests)


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
                        # 创建者自动成为 owner
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


def get_org(org_name: str) -> dict | None:
    with orgs_lock:
        return orgs.get(org_name)


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
    """删除组织（仅 owner 可调用）"""
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
                        # 删除成员关系
                        _read_merge(K_ORG_MEMBERS, org_members)
                        org_members.pop(org_name, None)
                        _persist(K_ORG_MEMBERS, org_members)
                        return True
    except StorageError as e:
        logger.error(f"[错误] 删除组织失败: {e}")
        return False


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
        return org_members.get(org_name, {}).get(username, {}).get("role")


def get_org_members(org_name: str) -> dict:
    """获取组织所有成员及角色"""
    with org_members_lock:
        return dict(org_members.get(org_name, {}))


def get_user_orgs(username: str) -> list:
    """获取用户所在的所有组织"""
    result = []
    with org_members_lock:
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
        invite = org_invites.get(invite_code)
        if not invite:
            return None
        if time.time() > invite.get("expires_at", 0):
            return None
        return dict(invite)


def delete_org_invite(invite_code: str) -> bool:
    """删除邀请码"""
    try:
        with org_invites_lock:
            with storage.lock(K_ORG_INVITES):
                _read_merge(K_ORG_INVITES, org_invites)
                if invite_code in org_invites:
                    del org_invites[invite_code]
                    return _persist(K_ORG_INVITES, org_invites)
                return False
    except StorageError as e:
        logger.error(f"[错误] 删除邀请码失败: {e}")
        return False


def get_org_invites(org_name: str) -> list:
    """获取组织所有有效邀请码"""
    result = []
    with org_invites_lock:
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
                        # 自动添加为成员
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
        # 公开加入或邀请加入
        org = get_org(org_name)
        if not org:
            return False
        policy = org.get("join_policy")
        if policy == "invite" and invite.get("type") != "invite":
            return False
        # 检查是否已有成员资格
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


load_users()
load_sessions()
load_shares()
load_orgs()
load_org_members()
load_org_invites()
load_org_join_requests()