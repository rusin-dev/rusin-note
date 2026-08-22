"""笔记置顶存储：内存缓存 + 统一存储层（file / memory / upstash / postgres）

置顶状态与笔记本体分离，存通用 KV 键 note_pins（file 后端即
note_pins.json）：{username: {note_id: pinned_at}}，值为置顶时间戳
（epoch 秒），用于置顶组内按置顶时间倒序排列。列表页提供图钉开关
（POST 切换），置顶笔记浮到列表最前。

写路径约定与 store.py / tags.py / folders.py 一致：持 threading.Lock
（进程内）+ storage.lock（跨进程/跨实例）的块内重读合并内存缓存，
持久化在锁外执行。
"""
import threading
import time

from .logger import create_logger
from .storage import StorageError, storage

logger = create_logger("pins")

# 键名（与存储后端的 KV 布局一一对应；file 后端映射 note_pins.json）
K_PINS = "note_pins"

# ---------- 内存缓存 ----------
note_pins = {}  # 格式: {username: {note_id: pinned_at}}
pins_lock = threading.Lock()


def _persist(data: dict) -> bool:
    """将整个置顶表写回存储后端（锁外调用）"""
    try:
        return storage.set(K_PINS, data)
    except StorageError as e:
        logger.error(f"[错误] 存储写入 {K_PINS} 失败: {e}")
        return False


def _read() -> dict | None:
    try:
        value = storage.get(K_PINS)
    except StorageError as e:
        logger.error(f"[错误] 存储读取 {K_PINS} 失败: {e}")
        return None
    return value if isinstance(value, dict) else None


def _read_merge_locked():
    """存储锁保护下重读最新数据并合并进内存缓存（多实例同步）。
    须已持有 pins_lock 与 storage.lock(K_PINS)。"""
    data = _read()
    if isinstance(data, dict):
        note_pins.clear()
        note_pins.update(data)


def load_note_pins():
    with pins_lock:
        data = _read()
        if isinstance(data, dict):
            note_pins.clear()
            note_pins.update(data)


# ---------- 读写接口 ----------
def get_user_pins(username: str) -> dict:
    """返回该用户全部置顶的拷贝 {note_id: pinned_at}"""
    with pins_lock:
        user = note_pins.get(username)
        if not isinstance(user, dict):
            return {}
        return {nid: at for nid, at in user.items() if isinstance(at, (int, float))}


def is_pinned(username: str, note_id: str) -> bool:
    """单篇笔记是否置顶"""
    return note_id in get_user_pins(username)


def set_note_pinned(username: str, note_id: str, pinned: bool) -> bool:
    """跨实例安全设置单篇笔记的置顶状态，返回是否写入成功。"""
    try:
        with pins_lock:
            with storage.lock(K_PINS):
                _read_merge_locked()
                user = note_pins.get(username)
                if pinned:
                    if not isinstance(user, dict):
                        user = {}
                        note_pins[username] = user
                    user[note_id] = time.time()
                elif isinstance(user, dict):
                    user.pop(note_id, None)
                    if not user:
                        note_pins.pop(username, None)
                return _persist(note_pins)
    except StorageError as e:
        logger.error(f"[错误] 写入笔记置顶 {username}/{note_id} 失败: {e}")
        return False


def toggle_note_pin(username: str, note_id: str) -> bool:
    """切换置顶状态，返回切换后的新状态（True = 已置顶）；写入失败时返回原状态"""
    now_pinned = not is_pinned(username, note_id)
    if not set_note_pinned(username, note_id, now_pinned):
        return not now_pinned
    return now_pinned


def delete_note_pins(username: str, note_id: str) -> bool:
    """删除单篇笔记的置顶条目（笔记删除时调用，条目不存在也算成功）"""
    return set_note_pinned(username, note_id, False)


load_note_pins()
