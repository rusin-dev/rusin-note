"""Flask app factory：组装所有扩展、蓝图、请求钩子

用法：
    from app import create_app
    app = create_app()

无服务器部署（Vercel 等）入口：api/index.py（见 vercel.json）。
"""
import os
import secrets

from flask import Flask, render_template
from werkzeug.middleware.proxy_fix import ProxyFix

from . import config
from .background import start_background_threads
from .extensions import csrf, limiter
from .i18n import register_i18n
from .middleware import register_request_hooks
from .storage import StorageError, storage
from .views import register_blueprints


def _load_or_create_secret_key() -> str:
    """获取 SECRET_KEY：多实例/多次重启共用同一密钥（否则 CSRF 签名跨实例随机失效）。

    优先级：环境变量 RUSIN_SECRET_KEY > 存储后端 secret_key（file 后端即
    旧的 .secret_key 文件，upstash 后端存于外部 KV，多实例共享）> 随机兜底。
    """
    key = os.environ.get("RUSIN_SECRET_KEY", "").strip()
    if key:
        return key
    if storage.persistent:
        try:
            key = storage.get("secret_key")
            if isinstance(key, str) and key.strip():
                return key.strip()
            new_key = secrets.token_hex(32)
            if storage.set("secret_key", new_key):
                return new_key
        except StorageError:
            pass
    # 兜底：无法持久化时退回随机密钥（仅影响重启/多实例一致性）
    return secrets.token_hex(32)


def create_app() -> Flask:
    app = Flask(
        __name__,
        template_folder=os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates"),
        static_folder=None,
    )

    secret = os.environ.get("RUSIN_SECRET_KEY")
    if not secret:
        secret = _load_or_create_secret_key()

    app.config.update(
        SECRET_KEY=secret,
        MAX_CONTENT_LENGTH=config.MAX_CONTENT_BYTES,
        SESSION_COOKIE_SECURE=config.SECURE_COOKIES,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        WTF_CSRF_TIME_LIMIT=None,
        RATELIMIT_STORAGE_URI=os.environ.get("REDIS_URL") or "memory://",
        GLOBAL_CDN=config.GLOBAL_CDN,
    )

    if config.TRUST_PROXY_HEADERS:
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=0)

    csrf.init_app(app)
    limiter.init_app(app)
    register_request_hooks(app)
    register_i18n(app)
    register_blueprints(app)
    register_error_handlers(app)

    if not app.config.get("TESTING") and not config.SERVERLESS:
        start_background_threads()

    return app


def register_error_handlers(app: Flask) -> None:
    from flask import abort, g

    @app.errorhandler(400)
    def err_400(e):
        return render_template("errors/400.html",
                               message=str(getattr(e, "description", "Bad Request"))), 400

    @app.errorhandler(401)
    def err_401(e):
        shares = False
        from flask import request
        if request.path.startswith("/user/") and "/shares" in request.path:
            shares = True
        return render_template("errors/401.html", shares=shares), 401

    @app.errorhandler(403)
    def err_403(e):
        return render_template("errors/400.html",
                               message=str(getattr(e, "description", "Forbidden"))), 403

    @app.errorhandler(404)
    def err_404(e):
        return render_template("errors/404.html"), 404

    @app.errorhandler(413)
    def err_413(e):
        return render_template("errors/400.html", message="Request body too large"), 413

    @app.errorhandler(429)
    def err_429(e):
        return render_template("errors/429.html"), 429

    @app.errorhandler(500)
    def err_500(e):
        return render_template("errors/500.html"), 500