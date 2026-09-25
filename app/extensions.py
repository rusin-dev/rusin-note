"""Flask 扩展单例（CSRF / 限流 / 缓存）

单例放在独立模块以避免与 app factory 循环导入。

限流存储：默认 memory://（单实例可用）。设置 REDIS_URL（如
redis://default:pass@host:port）后使用 Redis 计数，多实例共享限流状态。

限流键（key_func）：统一使用 ``g.client_ip``（由 middleware 经
``ip_utils.analyze_client_ip`` 安全解析，防伪造 X-Forwarded-For）。
另叠加一层「全站每 IP 总请求上限」（config 的 ``ip_rate_limit``，
应用级作用域，对所有路由生效）；白名单 IP（``ip_allowlist``）完全豁免限流。

缓存后端：Redis（REDIS_URL）或 SimpleCache（内存），可通过 config.json 的
cache.backend 切换，无服务器环境自动降级到 SimpleCache。
"""
import os
import secrets

from flask_wtf.csrf import CSRFProtect
from flask_limiter import Limiter
from flask import g, request

from . import config
from .ip_utils import resolve_client_ip
from .logger import create_logger

csrf = CSRFProtect()

logger = create_logger("ratelimit")


def _client_ip_key() -> str:
    """限流键：规范化后的客户端 IP。

    ``g.client_ip`` 由 before_request 钩子写入；若钩子尚未执行（如被其他
    扩展提前触发），则现场安全解析一次，绝不退回不可信的原始头部值。

    白名单 IP 返回一次性随机键，等价于「豁免任何限流」；该键随限流窗口到期
    被存储后端回收，不会无限增长。
    """
    ip = getattr(g, "client_ip", None)
    if not ip:
        ip = resolve_client_ip(request.remote_addr, request.headers)
    if getattr(g, "rate_limit_exempt", False):
        return f"exempt:{ip}:{secrets.token_hex(8)}"
    return ip


def _on_breach(request_limit):
    """限流触发回调：记录审计日志（不改变默认 429 响应）。"""
    ip = getattr(g, "client_ip", None) or request.remote_addr or "?"
    logger.warning("限流触发 ip=%s path=%s limit=%s",
                   ip, request.path, request_limit.limit)
    return None


def _application_limits():
    """全站每 IP 总请求上限（config 的 ``ip_rate_limit``，max_requests=0 时关闭）

    使用 ``application_limits``（应用级作用域）而非 ``default_limits``
    （按 endpoint 分别计数），这样即使用户在多个路由间轮询，也会受到同一个
    每 IP 总量约束——这才是「IP 限速」的真正兜底。
    """
    if not config.IP_RATE_ENABLED:
        return None
    return [f"{config.IP_RATE_MAX} per {config.IP_RATE_WINDOW} second"]


limiter = Limiter(
    key_func=_client_ip_key,
    storage_uri=os.environ.get("REDIS_URL") or "memory://",
    headers_enabled=True,
    application_limits=_application_limits(),
    on_breach=_on_breach,
)

# ---------- 缓存 ----------
from flask_caching import Cache

cache = Cache()