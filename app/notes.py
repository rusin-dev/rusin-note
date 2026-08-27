"""笔记操作、校验、统计、随机 ID 与过期笔记清理（存储后端无关）"""
import re
import time
import random
from threading import Lock

from . import config
from .folders import delete_note_folder
from .logger import create_logger
from .pins import delete_note_pins
from .storage import StorageError, storage
from .store import count_benben_posts, get_user_count
from .tags import delete_note_tags

logger = create_logger("notes")

# 禁止的笔记ID（与路由冲突）
FORBIDDEN_NOTE_IDS = {"user", "world", "shares", "login", "register",
                      "refs",  # refs：与 /user/<u>/refs 引用搜索路由冲突
                      "images",  # images：与 /user/<u>/images 图床上传/管理路由冲突
                      "attachments",  # attachments：与 /user/<u>/attachments 附件上传/管理路由冲突
                      "admin"}  # admin：与 /admin/features 功能开关管理路由（#90）冲突

# 保留用户名（与固定路由或 notes/ 目录冲突，禁止注册）
# 注意：public 与公开笔记存储命名空间冲突，必须保留
RESERVED_USERNAMES = {"register", "login", "logout", "count", "disclaimer",
                      "favicon", "share", "shares", "world", "user", "new", "md",
                      "public", "benben", "admin"}


# ---------- 校验 ----------
def validate_username(username: str) -> bool:
    if username.lower() in RESERVED_USERNAMES:
        return False
    return bool(re.match(r'^[a-zA-Z0-9_\-]+$', username))


def validate_note_id(note_id: str) -> bool:
    if note_id in FORBIDDEN_NOTE_IDS:
        return False
    if not isinstance(note_id, str) or len(note_id) > config.MAX_NOTE_ID_LENGTH:
        return False
    return bool(re.match(r'^[a-zA-Z0-9_\-]+$', note_id))


# ---------- 笔记读写 ----------
# "public" 是内部公开笔记存储命名空间，不是用户账号，需放行（validate_username 会拒绝它）
# "_orgs/<org_name>" 是组织笔记命名空间，也需放行
def _namespace_ok(username: str) -> bool:
    if username == "public":
        return True
    if username.startswith("_orgs/"):
        org_name = username[len("_orgs/"):]
        return bool(re.match(r'^[a-zA-Z0-9_\-]+$', org_name))
    return validate_username(username)


def read_note(username: str, note_id: str) -> str:
    if not _namespace_ok(username) or not validate_note_id(note_id):
        return ""
    try:
        content = storage.read_note(username, note_id)
    except StorageError:
        return ""
    return content or ""


def note_exists(username: str, note_id: str) -> bool:
    """笔记是否存在（空内容等价于不存在：写入空串即删除）"""
    if not _namespace_ok(username) or not validate_note_id(note_id):
        return False
    try:
        return storage.read_note(username, note_id) is not None
    except StorageError:
        return False


# 按笔记隔离的写入锁（进程内互斥，保证同一笔记的保存顺序，避免慢写入覆盖新写入）
_note_locks_guard = Lock()
_note_locks: dict[str, Lock] = {}


def _get_note_lock(username: str, note_id: str) -> Lock:
    key = f"{username}:{note_id}"
    with _note_locks_guard:
        lock = _note_locks.get(key)
        if lock is None:
            lock = Lock()
            _note_locks[key] = lock
        return lock


def write_note(username: str, note_id: str, content: str) -> bool:
    if not _namespace_ok(username) or not validate_note_id(note_id):
        return False
    with _get_note_lock(username, note_id):
        try:
            ok = storage.write_note(username, note_id, content)
        except StorageError as e:
            logger.error(f"[错误] 保存笔记 {username}/{note_id} 失败: {e}")
            return False
    # 空内容即删除（视图与过期清理都走这里），同步清掉标签、文件夹归属与置顶
    if ok and not content:
        delete_note_tags(username, note_id)
        delete_note_folder(username, note_id)
        delete_note_pins(username, note_id)
    return ok


def get_note_mtime(username: str, note_id: str):
    """返回笔记最后修改时间（epoch 秒），笔记不存在或读取失败时返回 None"""
    if not _namespace_ok(username) or not validate_note_id(note_id):
        return None
    try:
        return storage.note_mtime(username, note_id)
    except StorageError:
        return None


def get_note_size(username: str, note_id: str) -> int | None:
    """返回笔记大小（字节），笔记不存在或读取失败时返回 None"""
    if not _namespace_ok(username) or not validate_note_id(note_id):
        return None
    try:
        return storage.note_size(username, note_id)
    except StorageError:
        return None


def list_user_notes(username: str) -> list[str]:
    if not _namespace_ok(username):
        return []
    try:
        return [nid for nid in storage.list_notes(username) if validate_note_id(nid)]
    except StorageError:
        return []


# ---------- 快捷引用（#87：GitHub Issues 风格的 # 引用） ----------
def title_from_content(content: str) -> str:
    """笔记首行去掉常见 Markdown 标记后作为标题预览（最长 80 字符）"""
    if not content:
        return ""
    first = content.split("\n", 1)[0].strip()
    first = re.sub(r'^(?:#{1,6}\s*|>\s*|[-*+]\s+|\d+[.)]\s+)', '', first)
    return first[:80]


def note_title(username: str, note_id: str) -> str:
    """返回笔记首行标题预览，读取失败或笔记不存在返回空串"""
    return title_from_content(read_note(username, note_id))


def search_user_notes(username: str, query: str) -> list[dict]:
    """快捷引用搜索：按修改时间倒序扫描用户笔记，ID 或首行标题包含 query
    （大小写不敏感）即命中，返回 [{"id", "title", "mtime"}]，最多
    config.NOTE_REF_SEARCH_LIMIT 条、扫描 config.NOTE_REF_SCAN_LIMIT 篇。

    query 为空时返回最近编辑的笔记（对应只输入 # 还没打字的情况）。
    """
    from . import config
    note_ids = list_user_notes(username)
    scored = []
    for nid in note_ids:
        mtime = get_note_mtime(username, nid) or 0
        scored.append((mtime, nid))
    scored.sort(reverse=True)  # 最近编辑优先

    query = (query or "").strip().lower()
    results: list[dict] = []
    for mtime, nid in scored[:config.NOTE_REF_SCAN_LIMIT]:
        title = note_title(username, nid)
        if query and query not in nid.lower() and query not in title.lower():
            continue
        results.append({"id": nid, "title": title, "mtime": mtime})
        if len(results) >= config.NOTE_REF_SEARCH_LIMIT:
            break
    return results


# ---------- 统计函数 ----------
# BUG-16: 统计结果缓存（TTL 30 秒），避免每次 /count 请求全量遍历
STATS_CACHE_TTL = 30
_stats_cache = None
_stats_cache_time = 0.0


def get_stats():
    """返回 (public_count, public_size, private_count, private_size, user_count, benben_count)"""
    global _stats_cache, _stats_cache_time
    now = time.time()
    if _stats_cache is not None and now - _stats_cache_time < STATS_CACHE_TTL:
        return _stats_cache

    public_count = 0
    public_size = 0
    private_count = 0
    private_size = 0

    try:
        for username, note_id in storage.iter_all_notes():
            size = get_note_size(username, note_id) or 0
            if username == "public":
                public_count += 1
                public_size += size
            else:
                private_count += 1
                private_size += size
    except StorageError:
        pass

    result = (public_count, public_size, private_count, private_size,
              get_user_count(), count_benben_posts())
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
    """删除最后修改时间超过 NOTE_EXPIRATION_SECONDS 的笔记，返回删除数量（仅在启用时生效）"""
    if not config.NOTE_EXPIRATION_ENABLED:
        return 0
    cutoff = time.time() - config.NOTE_EXPIRATION_SECONDS
    removed = 0
    try:
        for username, note_id in storage.iter_all_notes():
            mtime = get_note_mtime(username, note_id)
            if mtime is not None and mtime < cutoff:
                if write_note(username, note_id, ""):
                    removed += 1
    except StorageError:
        pass
    if removed:
        logger.info(f"[清理] 已清除 {removed} 个过期笔记（保存超过 {config.NOTE_EXPIRATION_HOURS} 小时）")
    return removed


def note_cleanup_loop():
    """后台线程：定时清除过期笔记"""
    while True:
        time.sleep(config.NOTE_CLEANUP_INTERVAL)
        try:
            purge_expired_notes()
        except Exception as e:
            logger.error(f"[错误] 过期笔记清理失败: {e}")