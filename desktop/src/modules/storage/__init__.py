"""客户端配置存储。

桌面端不再保存笔记：笔记数据全部存放在 rusin-note 网页版，本地只落盘
客户端自身的配置（站点地址、窗口几何、更新渠道等）。
"""
from .config import (
    ConfigError,
    ConfigKeyNotFoundError,
    InvalidConfigKeyError,
    JsonConfigStore,
)

__all__ = [
    "JsonConfigStore",
    "ConfigError",
    "InvalidConfigKeyError",
    "ConfigKeyNotFoundError",
]