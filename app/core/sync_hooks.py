"""笔记变更监听（依赖倒置）：功能 App 注册，核心笔记层只负责广播。"""
import threading

from app.core.logger import create_logger

logger = create_logger("sync_hooks")

_listeners = []
_lock = threading.Lock()


def register(listener) -> None:
    if not callable(listener):
        return
    with _lock:
        if listener not in _listeners:
            _listeners.append(listener)


def emit(username: str, note_id: str, deleted: bool, origin: str = "user") -> None:
    with _lock:
        listeners = list(_listeners)
    for listener in listeners:
        try:
            listener(username, note_id, deleted, origin)
        except Exception as e:  # noqa: BLE001 - 同步排队失败不能影响保存
            logger.error(f"[错误] 笔记变更监听失败: {e}")
