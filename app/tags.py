"""笔记标签存储：内存缓存 + 统一存储层（file / memory / upstash / postgres）

标签与笔记本体分离，存通用 KV 键 note_tags（file 后端即 note_tags.json）：
{username: {note_id: [tag, ...]}}。笔记本体是纯文本无元数据，删除笔记时由
notes.write_note 钩子同步清理标签条目。

写路径约定与 store.py 一致：持 threading.Lock（进程内）+ storage.lock
（跨进程/跨实例）的块内重读合并内存缓存，持久化在锁外执行。
"""
import re
import threading

from .config import MAX_NOTE_TAGS, MAX_TAG_LENGTH
from .logger import create_logger
from .storage import StorageError, storage

logger = create_logger("tags")

# 键名（与存储后端的 KV 布局一一对应；file 后端映射 note_tags.json）
K_TAGS = "note_tags"

# 合法标签字符：字母 / 数字 / 下划线 / 连字符 / 中日韩文字（\w 在 Python3
# 的 str 模式下默认按 Unicode 匹配，已覆盖中日韩）
_TAG_RE = re.compile(r'^[\w\-]+$')

# ---------- 内存缓存 ----------
note_tags = {}  # 格式: {username: {note_id: [tag, ...]}}
tags_lock = threading.Lock()


def _persist(data: dict) -> bool:
    """将整个标签表写回存储后端（锁外调用）"""
    try:
        return storage.set(K_TAGS, data)
    except StorageError as e:
        logger.error(f"[错误] 存储写入 {K_TAGS} 失败: {e}")
        return False


def _read() -> dict | None:
    try:
        value = storage.get(K_TAGS)
    except StorageError as e:
        logger.error(f"[错误] 存储读取 {K_TAGS} 失败: {e}")
        return None
    return value if isinstance(value, dict) else None


def _read_merge_locked():
    """存储锁保护下重读最新数据并合并进内存缓存（多实例同步）。
    须已持有 tags_lock 与 storage.lock(K_TAGS)。"""
    data = _read()
    if isinstance(data, dict):
        note_tags.clear()
        note_tags.update(data)


def load_note_tags():
    with tags_lock:
        data = _read()
        if isinstance(data, dict):
            note_tags.clear()
            note_tags.update(data)


# ---------- 解析与校验 ----------
def valid_tag(tag: str) -> bool:
    """单个标签是否合法（字符集 + 长度）"""
    return bool(tag) and len(tag) <= MAX_TAG_LENGTH and bool(_TAG_RE.match(tag))


def parse_tag_input(raw: str) -> list[str]:
    """解析用户输入的标签串：按英文/中文逗号拆分、去空白、去重（保持顺序）、
    丢弃非法项，最多保留 MAX_NOTE_TAGS 个。"""
    tags: list[str] = []
    for part in re.split(r'[,，]', raw or ""):
        tag = part.strip()
        if not valid_tag(tag) or tag in tags:
            continue
        tags.append(tag)
        if len(tags) >= MAX_NOTE_TAGS:
            break
    return tags


# ---------- 读写接口 ----------
def get_user_note_tags(username: str) -> dict:
    """返回该用户全部笔记标签的拷贝 {note_id: [tag, ...]}"""
    with tags_lock:
        user = note_tags.get(username)
        return {nid: list(tags) for nid, tags in user.items()} if isinstance(user, dict) else {}


def get_note_tags(username: str, note_id: str) -> list[str]:
    """返回单篇笔记的标签列表（拷贝）"""
    with tags_lock:
        user = note_tags.get(username)
        if not isinstance(user, dict):
            return []
        tags = user.get(note_id)
        return list(tags) if isinstance(tags, list) else []


def set_note_tags(username: str, note_id: str, tags: list[str]) -> bool:
    """跨实例安全写入单篇笔记的标签；空列表即删除该笔记的标签条目。"""
    clean = parse_tag_input(",".join(tags)) if tags else []
    try:
        with tags_lock:
            with storage.lock(K_TAGS):
                _read_merge_locked()
                user = note_tags.get(username)
                if clean:
                    if not isinstance(user, dict):
                        user = {}
                        note_tags[username] = user
                    user[note_id] = clean
                elif isinstance(user, dict):
                    user.pop(note_id, None)
                    if not user:
                        note_tags.pop(username, None)
                return _persist(note_tags)
    except StorageError as e:
        logger.error(f"[错误] 写入笔记标签 {username}/{note_id} 失败: {e}")
        return False


def delete_note_tags(username: str, note_id: str) -> bool:
    """删除单篇笔记的标签条目（笔记删除时调用，条目不存在也算成功）"""
    return set_note_tags(username, note_id, [])


def count_user_tags(username: str, note_ids=None) -> list:
    """统计该用户的标签云 [(tag, count), ...]，按 count 降序、名称升序。
    note_ids 给定时只统计仍存在的笔记（过滤已删除笔记的残留条目）。"""
    counts: dict[str, int] = {}
    for nid, tags in get_user_note_tags(username).items():
        if note_ids is not None and nid not in note_ids:
            continue
        for tag in tags:
            counts[tag] = counts.get(tag, 0) + 1
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))


load_note_tags()
