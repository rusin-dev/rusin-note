"""日志入口：桌面端日志落盘到数据目录，按大小轮转。"""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

_MAX_BYTES = 4 * 1024 * 1024
_BACKUP_COUNT = 2
_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"


def get_logger(name: str, filename: str) -> logging.Logger:
    """取得（或复用）写入 filename 的 logger，重复调用不会叠加 handler。"""
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    target = str(Path(filename).resolve())
    for handler in logger.handlers:
        if isinstance(handler, RotatingFileHandler) and handler.baseFilename == target:
            return logger
    Path(filename).parent.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        filename, maxBytes=_MAX_BYTES, backupCount=_BACKUP_COUNT, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter(_FORMAT))
    logger.addHandler(handler)
    return logger