from logging import ERROR, INFO, Logger, StreamHandler
from logging.handlers import RotatingFileHandler
import os
import sys
import time

from .config import DEBUG, LOGGER_MAX_SIZE, LOGGER_PATH

def create_logger(name: str) -> Logger:
    """
    name: str -> 显示名称
    无服务器环境（只读文件系统）回退到 stderr，日志进入平台日志流。
    """
    logger = Logger(name, ERROR if DEBUG else INFO)
    timestamp = time.time()
    log_path = LOGGER_PATH.format(timestamp=timestamp)
    log_directory = os.path.dirname(log_path)
    if log_directory:
        try:
            os.makedirs(log_directory, exist_ok=True)
        except (OSError, IOError):
            pass
    try:
        handler = RotatingFileHandler(log_path, maxBytes=LOGGER_MAX_SIZE)
    except (OSError, IOError):
        handler = StreamHandler(sys.stderr)
    logger.addHandler(handler)
    return logger