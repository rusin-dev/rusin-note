"""工作台待办（TODO LIST）存储：内存缓存 + 统一存储层（file / memory / upstash / postgres）

待办与用户账号绑定，存通用 KV 键 todos（file 后端即 todos.json）：
{username: [{"id": str, "text": str, "done": bool, "created_at": float}, ...]}
列表按加入顺序排列（新增追加到末尾）。

写路径约定与 store.py / tags.py / pins.py 一致：持 threading.Lock（进程内）
+ storage.lock（跨进程/跨实例）的块内重读合并内存缓存，持久化在锁外执行。
"""
import secrets
import threading
import time

from . import config
from .logger import create_logger
from .storage import StorageError, storage

logger = create_logger("todos")

# 键名（与存储后端的 KV 布局一一对应；file 后端映射 todos.json）
K_TODOS = "todos"

# ---------- 内存缓存 ----------
user_todos = {}  # 格式: {username: [todo, ...]}
todos_lock = threading.Lock()


def _persist(data: dict) -> bool:
    """将整个待办表写回存储后端（锁外调用）"""
    try:
        return storage.set(K_TODOS, data)
    except StorageError as e:
        logger.error(f"[错误] 存储写入 {K_TODOS} 失败: {e}")
        return False


def _read() -> dict | None:
    try:
        value = storage.get(K_TODOS)
    except StorageError as e:
        logger.error(f"[错误] 存储读取 {K_TODOS} 失败: {e}")
        return None
    return value if isinstance(value, dict) else None


def _read_merge_locked():
    """存储锁保护下重读最新数据并合并进内存缓存（多实例同步）。
    须已持有 todos_lock 与 storage.lock(K_TODOS)。"""
    data = _read()
    if isinstance(data, dict):
        user_todos.clear()
        user_todos.update(data)


def load_user_todos():
    with todos_lock:
        _read_merge_locked()


def _clean_list(items) -> list:
    """把存储里的任意值规整为合法的待办列表（丢弃脏数据）"""
    out = []
    if not isinstance(items, list):
        return out
    for it in items:
        if not isinstance(it, dict):
            continue
        text = it.get("text")
        todo_id = it.get("id")
        if not isinstance(text, str) or not isinstance(todo_id, str):
            continue
        try:
            created = float(it.get("created_at") or 0)
        except (TypeError, ValueError):
            created = 0.0
        out.append({"id": todo_id, "text": text, "done": bool(it.get("done")), "created_at": created})
    return out


# ---------- 读写接口 ----------
def get_user_todos(username: str) -> list:
    """返回该用户全部待办的拷贝（按加入顺序）"""
    with todos_lock:
        items = user_todos.get(username)
        return [dict(it) for it in items] if isinstance(items, list) else []


def count_user_todos(username: str) -> int:
    return len(get_user_todos(username))


def add_user_todo(username: str, text: str) -> tuple[bool, str]:
    """新增待办。返回 (是否成功, 失败原因 i18n 键后缀)。"""
    text = (text or "").strip()
    if not text:
        return False, "empty"
    if len(text) > config.TODO_MAX_LENGTH:
        return False, "too_long"
    try:
        with todos_lock:
            with storage.lock(K_TODOS):
                _read_merge_locked()
                items = _clean_list(user_todos.get(username))
                if len(items) >= config.TODO_MAX_ITEMS:
                    return False, "too_many"
                items.append({
                    "id": secrets.token_hex(6),
                    "text": text,
                    "done": False,
                    "created_at": time.time(),
                })
                user_todos[username] = items
                if not _persist(user_todos):
                    return False, "storage"
        return True, ""
    except StorageError as e:
        logger.error(f"[错误] 新增待办 {username} 失败: {e}")
        return False, "storage"


def set_user_todo_done(username: str, todo_id: str, done: bool) -> bool:
    """设置单条待办的完成状态，返回是否写入成功"""
    try:
        with todos_lock:
            with storage.lock(K_TODOS):
                _read_merge_locked()
                items = _clean_list(user_todos.get(username))
                found = False
                for it in items:
                    if it["id"] == todo_id:
                        it["done"] = bool(done)
                        found = True
                        break
                if not found:
                    return False
                user_todos[username] = items
                return _persist(user_todos)
    except StorageError as e:
        logger.error(f"[错误] 更新待办 {username}/{todo_id} 失败: {e}")
        return False


def toggle_user_todo(username: str, todo_id: str) -> bool:
    """切换完成状态。返回切换后的新状态（True = 已完成）；条目不存在或写入失败返回原状态。"""
    for it in get_user_todos(username):
        if it["id"] == todo_id:
            new_done = not it["done"]
            if not set_user_todo_done(username, todo_id, new_done):
                return it["done"]
            return new_done
    return False


def delete_user_todo(username: str, todo_id: str) -> bool:
    """删除单条待办（不存在也算成功）"""
    try:
        with todos_lock:
            with storage.lock(K_TODOS):
                _read_merge_locked()
                items = _clean_list(user_todos.get(username))
                new_items = [it for it in items if it["id"] != todo_id]
                if len(new_items) == len(items):
                    return True
                if new_items:
                    user_todos[username] = new_items
                else:
                    user_todos.pop(username, None)
                return _persist(user_todos)
    except StorageError as e:
        logger.error(f"[错误] 删除待办 {username}/{todo_id} 失败: {e}")
        return False


def clear_done_user_todos(username: str) -> bool:
    """清理该用户所有已完成待办"""
    try:
        with todos_lock:
            with storage.lock(K_TODOS):
                _read_merge_locked()
                items = _clean_list(user_todos.get(username))
                new_items = [it for it in items if not it["done"]]
                if len(new_items) == len(items):
                    return True
                if new_items:
                    user_todos[username] = new_items
                else:
                    user_todos.pop(username, None)
                return _persist(user_todos)
    except StorageError as e:
        logger.error(f"[错误] 清理已完成待办 {username} 失败: {e}")
        return False


def rename_user_todos(old: str, new: str) -> bool:
    """把 old 用户的全部待办迁移到 new（用户改名用）。无条目视为成功。"""
    try:
        with todos_lock:
            with storage.lock(K_TODOS):
                _read_merge_locked()
                if old not in user_todos:
                    return True
                moved = user_todos.pop(old)
                existing = user_todos.get(new)
                if isinstance(existing, list) and isinstance(moved, list):
                    existing.extend(moved)
                else:
                    user_todos[new] = moved
                return _persist(user_todos)
    except StorageError as e:
        logger.error(f"[错误] 迁移待办 {old} 失败: {e}")
        return False


load_user_todos()
