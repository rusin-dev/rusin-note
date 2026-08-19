"""Flask 扩展单例（CSRF / 限流）

单例放在独立模块以避免与 app factory 循环导入。

限流存储：默认 memory://（单实例可用）。设置 REDIS_URL（如
redis://default:pass@host:port）后使用 Redis 计数，多实例共享限流状态。
"""
import os

from flask_wtf.csrf import CSRFProtect
from flask_limiter import Limiter
from flask import g
from flask_limiter.util import get_remote_address

csrf = CSRFProtect()


def _client_ip_key() -> str:
    """优先用 g.client_ip（由 middleware 写入），fallback 到 remote_addr"""
    ip = getattr(g, "client_ip", None)
    if ip:
        return ip
    return get_remote_address()


limiter = Limiter(
    key_func=_client_ip_key,
    storage_uri=os.environ.get("REDIS_URL") or "memory://",
    headers_enabled=True,
)