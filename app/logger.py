from logging import Logger
from logging.handlers import RotatingFileHandler
import time

from .config import LOGGER_MAX_SIZE, LOGGER_PATH

def create_logger(name: str) -> Logger:
    """
    name: str -> 显示名称
    """
    logger = Logger(name)
    timestamp = time.time()
    handler = RotatingFileHandler(LOGGER_PATH.format(timestamp=timestamp), maxBytes=LOGGER_MAX_SIZE)
    logger.addHandler(handler)
    return logger