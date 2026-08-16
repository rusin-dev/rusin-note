"""后台守护线程：会话清理、分享视图刷盘、过期笔记清理

启动入口：start_background_threads() 在 create_app() 末尾调用。
"""
import time
from threading import Thread

from . import config
from .auth import purge_expired_sessions, session_cleanup_loop
from .logger import create_logger
from .notes import note_cleanup_loop, purge_expired_notes
from .store import flush_share_views


logger = create_logger("background")


def share_views_flush_loop() -> None:
    """后台线程：定期将内存中的分享视图计数写盘（BUG-06）"""
    while True:
        time.sleep(config.SHARE_VIEWS_FLUSH_INTERVAL)
        try:
            flush_share_views()
        except Exception as e:
            logger.error(f"[错误] 分享视图刷新失败: {e}")


def start_background_threads() -> None:
    """启动所有后台守护线程（一次性，不可重复调用）"""
    purge_expired_sessions()
    Thread(target=session_cleanup_loop, daemon=True).start()
    Thread(target=share_views_flush_loop, daemon=True).start()
    if config.NOTE_EXPIRATION_ENABLED:
        purge_expired_notes()
        Thread(target=note_cleanup_loop, daemon=True).start()