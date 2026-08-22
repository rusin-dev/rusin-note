"""笔记文件夹存储：内存缓存 + 统一存储层（file / memory / upstash / postgres）

文件夹归属与笔记本体分离，存通用 KV 键 note_folders（file 后端即
note_folders.json）：{username: {note_id: folder_name}}。每篇笔记至多归属
一个文件夹，空/缺省即未归类。文件夹是派生概念：只要还有笔记引用即存在，
把笔记全部移走后文件夹自然消失，无需单独的管理入口。

写路径约定与 store.py / tags.py 一致：持 threading.Lock（进程内）+
storage.lock（跨进程/跨实例）的块内重读合并内存缓存，持久化在锁外执行。
"""
import re
import threading

from .config import MAX_FOLDER_NAME_LENGTH
from .logger import create_logger
from .storage import StorageError, storage

logger = create_logger("folders")

# 键名（与存储后端的 KV 布局一一对应；file 后端映射 note_folders.json）
K_FOLDERS = "note_folders"

# 合法文件夹名字符：字母 / 数字 / 下划线 / 连字符 / 中日韩文字（\w 在
# Python3 的 str 模式下默认按 Unicode 匹配，已覆盖中日韩）
_FOLDER_RE = re.compile(r'^[\w\-]+$')

# ---------- 内存缓存 ----------
note_folders = {}  # 格式: {username: {note_id: folder_name}}
folders_lock = threading.Lock()


def _persist(data: dict) -> bool:
    """将整个归属表写回存储后端（锁外调用）"""
    try:
        return storage.set(K_FOLDERS, data)
    except StorageError as e:
        logger.error(f"[错误] 存储写入 {K_FOLDERS} 失败: {e}")
        return False


def _read() -> dict | None:
    try:
        value = storage.get(K_FOLDERS)
    except StorageError as e:
        logger.error(f"[错误] 存储读取 {K_FOLDERS} 失败: {e}")
        return None
    return value if isinstance(value, dict) else None


def _read_merge_locked():
    """存储锁保护下重读最新数据并合并进内存缓存（多实例同步）。
    须已持有 folders_lock 与 storage.lock(K_FOLDERS)。"""
    data = _read()
    if isinstance(data, dict):
        note_folders.clear()
        note_folders.update(data)


def load_note_folders():
    with folders_lock:
        data = _read()
        if isinstance(data, dict):
            note_folders.clear()
            note_folders.update(data)


# ---------- 解析与校验 ----------
def valid_folder(name: str) -> bool:
    """单个文件夹名是否合法（字符集 + 长度）"""
    return bool(name) and len(name) <= MAX_FOLDER_NAME_LENGTH and bool(_FOLDER_RE.match(name))


def parse_folder_input(raw: str) -> str:
    """规范化用户输入的文件夹名：去空白后校验字符集与长度，
    非法或超长返回空串（等价于未归类）。"""
    name = (raw or "").strip()
    return name if valid_folder(name) else ""


# ---------- 读写接口 ----------
def get_user_note_folders(username: str) -> dict:
    """返回该用户全部归属的拷贝 {note_id: folder_name}"""
    with folders_lock:
        user = note_folders.get(username)
        if not isinstance(user, dict):
            return {}
        return {nid: f for nid, f in user.items() if isinstance(f, str)}


def get_note_folder(username: str, note_id: str) -> str:
    """返回单篇笔记的文件夹名，未归类或读取失败返回空串"""
    with folders_lock:
        user = note_folders.get(username)
        if not isinstance(user, dict):
            return ""
        folder = user.get(note_id)
        return folder if isinstance(folder, str) else ""


def set_note_folder(username: str, note_id: str, folder: str) -> bool:
    """跨实例安全写入单篇笔记的文件夹归属；空串即取消归类。"""
    clean = parse_folder_input(folder)
    try:
        with folders_lock:
            with storage.lock(K_FOLDERS):
                _read_merge_locked()
                user = note_folders.get(username)
                if clean:
                    if not isinstance(user, dict):
                        user = {}
                        note_folders[username] = user
                    user[note_id] = clean
                elif isinstance(user, dict):
                    user.pop(note_id, None)
                    if not user:
                        note_folders.pop(username, None)
                return _persist(note_folders)
    except StorageError as e:
        logger.error(f"[错误] 写入笔记文件夹 {username}/{note_id} 失败: {e}")
        return False


def delete_note_folder(username: str, note_id: str) -> bool:
    """删除单篇笔记的归属条目（笔记删除时调用，条目不存在也算成功）"""
    return set_note_folder(username, note_id, "")


def list_user_folders(username: str, note_ids=None) -> list:
    """统计该用户的文件夹列表 [(folder, count), ...]，按 count 降序、名称升序。
    note_ids 给定时只统计仍存在的笔记（过滤已删除笔记的残留条目）。"""
    counts: dict[str, int] = {}
    for nid, folder in get_user_note_folders(username).items():
        if not folder:
            continue
        if note_ids is not None and nid not in note_ids:
            continue
        counts[folder] = counts.get(folder, 0) + 1
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))


load_note_folders()
