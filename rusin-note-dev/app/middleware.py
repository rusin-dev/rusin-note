"""请求钩子：客户端 IP、语言、主题、当前用户

将每次请求共用的字段写入 flask.g，供视图与限流 key_func 复用。
IP 提取保留 BUG-101 代理头优先级：CF-Connecting-IP > X-Real-IP > XFF 最右非空 > remote_addr。
"""
from flask import Flask, g, request

from . import config
from .auth import get_session_user
from .i18n import detect_lang_from_request


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
    for pair in cookie.split(";"):
        pair = pair.strip()
        if pair.startswith("session="):
            return pair[len("session="):]
    return None


def get_current_user() -> str | None:
    token = get_session_token()
    if not token:
        return None
    return get_session_user(token)


def register_request_hooks(app: Flask) -> None:
    @app.before_request
    def _attach_request_context():
        g.client_ip = get_client_ip()
        g.lang = detect_lang_from_request()
        g.theme = get_theme_from_cookie()
        g.current_user = get_current_user()