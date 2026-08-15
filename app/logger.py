from logging import Logger
from logging.handlers import RotatingFileHandler
import os
import time

from .config import LOGGER_MAX_SIZE, LOGGER_PATH, DEBUG

def create_logger(name: str) -> Logger:
    """
    name: str -> 显示名称
    """
    logger = Logger(name, "ERROR" if DEBUG else "INFO")
    timestamp = time.time()
    log_path = LOGGER_PATH.format(timestamp=timestamp)
    log_dir = os.path.dirname(log_path)
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)
    handler = RotatingFileHandler(log_path, maxBytes=LOGGER_MAX_SIZE)
    logger.addHandler(handler)
    return logger