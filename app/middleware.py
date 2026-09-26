"""请求钩子：客户端 IP、语言、主题、当前用户

将每次请求共用的字段写入 flask.g，供视图与限流 key_func 复用。

客户端 IP 由 ``ip_utils.analyze_client_ip`` 安全解析（防 XFF 伪造）：
仅当 TCP 直连对端属于可信代理网段（config 的 ``trusted_proxies``）时才采信
``X-Forwarded-For`` / ``X-Real-IP`` / ``CF-Connecting-IP``；XFF 从右往左解析，
非法值一律丢弃。命中 ``ip_blocklist`` 的请求直接 403，命中 ``ip_allowlist``
的请求标记为免限流（``g.rate_limit_exempt``）。
"""
import time

from flask import Flask, abort, g, request

from . import config
from .auth import get_session_user, purge_expired_sessions
from .i18n import detect_lang_from_request, t
from .ip_utils import analyze_client_ip, ip_in_any, note_ignored_proxy_headers
from .logger import create_logger
from .notes import purge_expired_notes
from .store import flush_share_views

logger = create_logger("middleware")


def get_client_ip() -> str:
    """安全解析真实客户端 IP（仅可信代理才采信代理头，防伪造 XFF）"""
    cached = getattr(g, "client_ip", None)
    if cached:
        return cached
    resolution = analyze_client_ip(request.remote_addr, request.headers)
    if resolution.headers_ignored:
        note_ignored_proxy_headers(resolution.ip, request.remote_addr)
    return resolution.ip


def get_theme_from_cookie() -> str | None:
    cookie = request.headers.get("Cookie", "")
    for pair in cookie.split(";"):
        pair = pair.strip()
        if pair.startswith("rusin-theme="):
            value = pair[len("rusin-theme="):]
            if value in ("dark", "light"):
                return value
    return None


def get_session_token() -> str | None:
    cookie = request.headers.get("Cookie", "")
    prefix = f"{config.SESSION_COOKIE}="
    for pair in cookie.split(";"):
        pair = pair.strip()
        if pair.startswith(prefix):
            return pair[len(prefix):]
    return None


def get_current_user() -> str | None:
    token = get_session_token()
    if not token:
        return None
    return get_session_user(token)


# 无服务器环境没有后台守护线程：清理任务改为「请求内机会式执行」，
# 以本实例为粒度节流（间隔与后台线程相同），保持过期清理/视图刷盘生效。
_last_opportunistic_cleanup = 0.0


def _opportunistic_cleanup() -> None:
    """冷启动无后台线程时，在请求中周期执行清理任务"""
    global _last_opportunistic_cleanup
    now = time.time()
    if now - _last_opportunistic_cleanup < config.SESSION_CLEANUP_INTERVAL:
        return
    _last_opportunistic_cleanup = now
    try:
        purge_expired_sessions()
        purge_expired_notes()
        flush_share_views()
    except Exception:
        pass


def register_request_hooks(app: Flask) -> None:
    @app.before_request
    def _attach_request_context():
        resolution = analyze_client_ip(request.remote_addr, request.headers)
        if resolution.headers_ignored:
            # 携带了代理头但直连对端不可信：疑似伪造，按直连 IP 处理并告警
            note_ignored_proxy_headers(resolution.ip, request.remote_addr)
        g.client_ip = resolution.ip
        g.client_ip_source = resolution.source
        g.lang = detect_lang_from_request()
        g.theme = get_theme_from_cookie()
        g.current_user = get_current_user()
        # IP 黑名单：直接拒绝（在读取会话之后，保证错误页能按语言渲染）
        if config.IP_BLOCKLIST and ip_in_any(g.client_ip, config.IP_BLOCKLIST):
            logger.warning("黑名单 IP 访问被拒绝：ip=%s path=%s", g.client_ip, request.path)
            abort(403, description=t(g.lang, "err_ip_blocked"))
        # IP 白名单：免限流（限流 key_func 依据该标志返回一次性键）
        g.rate_limit_exempt = bool(config.IP_ALLOWLIST) and ip_in_any(
            g.client_ip, config.IP_ALLOWLIST)
        # 简洁模式是账号级界面偏好（存 users.json），登录用户在服务端直接渲染
        # <html class="simple-mode">，避免客户端 cookie/localStorage 与多设备冲突
        from .user_settings import get_simple_mode
        g.simple_mode = get_simple_mode(g.current_user) if g.current_user else False
        if config.SERVERLESS:
            _opportunistic_cleanup()