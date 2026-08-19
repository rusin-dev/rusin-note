"""请求钩子：客户端 IP、语言、主题、当前用户

将每次请求共用的字段写入 flask.g，供视图与限流 key_func 复用。
IP 提取保留 BUG-101 代理头优先级：CF-Connecting-IP > X-Real-IP > XFF 最右非空 > remote_addr。
"""
import time

from flask import Flask, g, request

from . import config
from .auth import get_session_user, purge_expired_sessions
from .i18n import detect_lang_from_request
from .notes import purge_expired_notes
from .store import flush_share_views


def get_client_ip() -> str:
    """BUG-101：代理头按可信度从高到低读取"""
    if config.TRUST_PROXY_HEADERS:
        cf_ip = request.headers.get("CF-Connecting-IP", "").strip()
        if cf_ip:
            return cf_ip
        real_ip = request.headers.get("X-Real-IP", "").strip()
        if real_ip:
            return real_ip
        xff = request.headers.get("X-Forwarded-For", "")
        if xff:
            for item in reversed(xff.split(",")):
                ip = item.strip()
                if ip:
                    return ip
    return request.remote_addr or "0.0.0.0"


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
        g.client_ip = get_client_ip()
        g.lang = detect_lang_from_request()
        g.theme = get_theme_from_cookie()
        g.current_user = get_current_user()
        if config.SERVERLESS:
            _opportunistic_cleanup()