"""应用装配：数据目录 → 单实例锁 → 客户端配置 → WebView 原生壳。

桌面端不存笔记：笔记/附件/同步全部由 rusin-note 网页版负责，本地数据目录
只放客户端配置、日志与 WebView 会话数据（用于保持登录态）。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from src.core.data import DataService
from src.core.logger import get_logger
from src.core.window import run

APP_DIR_NAME = "rusin-note-desktop"
DATA_DIR_ENV = "RUSIN_DESKTOP_DATA_DIR"


def data_dir() -> Path:
    """客户端数据目录（可用 RUSIN_DESKTOP_DATA_DIR 覆盖，便于测试与便携运行）"""
    override = os.environ.get(DATA_DIR_ENV)
    if override:
        return Path(override).expanduser().resolve()
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    elif sys.platform == "darwin":
        base = str(Path.home() / "Library" / "Application Support")
    else:
        base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / APP_DIR_NAME


def acquire_instance_lock(directory: Path):
    """取得单实例锁，已被占用时返回 None。

    返回的文件句柄必须保持打开到进程结束——关闭即释放锁。重复启动时直接
    退出，避免两个实例并发写同一份配置。
    """
    directory.mkdir(parents=True, exist_ok=True)
    handle = open(directory / "instance.lock", "a+", encoding="utf-8")
    try:
        handle.seek(0)
        if sys.platform == "win32":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        return None
    return handle


def main() -> int:
    directory = data_dir()
    logger = get_logger("rusin.desktop", str(directory / "logs" / "desktop.log"))
    lock = acquire_instance_lock(directory)
    if lock is None:
        logger.info("已有实例在运行，本次启动退出")
        return 0
    try:
        service = DataService.local(directory)
        run(service, directory, logger)
    except Exception:
        logger.exception("桌面端异常退出")
        raise
    finally:
        lock.close()
    return 0