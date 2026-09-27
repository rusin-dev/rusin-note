"""后台清理任务注册表（依赖倒置）

共享内核（``background`` / ``middleware``）需要周期性清理「过期数据」，
但具体数据属于各功能 App（如验证码在 email App）。为避免 core → app 的
反向依赖，各 App 在导入时通过 :func:`register_cleanup` 注册清理函数，
内核只负责调度 :func:`run_cleanups`。
"""
import threading

from app.core.logger import create_logger

logger = create_logger("cleanup")

_tasks = []
_lock = threading.Lock()


def register_cleanup(fn) -> None:
    """注册一个无参清理函数（重复注册自动忽略）"""
    if not callable(fn):
        return
    with _lock:
        if fn not in _tasks:
            _tasks.append(fn)


def run_cleanups() -> None:
    """依次执行全部已注册清理函数；单个失败不影响其它任务"""
    with _lock:
        tasks = list(_tasks)
    for fn in tasks:
        try:
            fn()
        except Exception as e:  # noqa: BLE001 - 清理任务失败不应影响主流程
            logger.error(f"[错误] 清理任务 {getattr(fn, '__name__', fn)} 失败: {e}")
