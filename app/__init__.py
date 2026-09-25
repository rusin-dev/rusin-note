"""Flask app factory：组装所有扩展、蓝图、请求钩子

用法：
    from app import create_app
    app = create_app()

无服务器部署（Vercel 等）入口：api/index.py（见 vercel.json）。
"""
import logging
import os
import secrets

from flask import Flask, render_template

from . import config
from .background import start_background_threads
from .extensions import csrf, limiter, cache
from .i18n import register_i18n
from .ip_utils import log_ip_policy
from .middleware import register_request_hooks
from .storage import StorageError, storage
from .views import register_blueprints

logger = logging.getLogger("rusin-note")


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


def _redis_available(url: str) -> bool:
    """探测 Redis 是否可连通。

    Flask-Caching 的 RedisCache.init_app 不会真正建连，连接失败要等到首个
    请求才暴露（导致请求内反复刷错误日志）。这里主动 ping 一次，不可达时
    让缓存降级到 SimpleCache。
    """
    try:
        import redis
        client = redis.from_url(
            url, socket_connect_timeout=2, socket_timeout=2, retry_on_timeout=False)
        try:
            return bool(client.ping())
        finally:
            try:
                client.close()
            except Exception:
                pass
    except Exception:
        return False


def _init_cache_backend(app: Flask) -> None:
    """根据 config.json 的 cache.backend 配置初始化缓存后端，自动降级到 SimpleCache"""
    if not config.CACHE_ENABLED:
        cache.init_app(app, config={"CACHE_TYPE": "null"})
        return
    backend = config.CACHE_BACKEND
    if backend == "redis":
        if _redis_available(config.CACHE_REDIS_URL):
            cache.init_app(app, config={
                "CACHE_TYPE": "RedisCache",
                "CACHE_DEFAULT_TIMEOUT": config.CACHE_DEFAULT_TIMEOUT,
                "CACHE_REDIS_URL": config.CACHE_REDIS_URL,
            })
            return
        logger.warning(
            "Redis 缓存不可达（%s），已降级到 SimpleCache", config.CACHE_REDIS_URL)
    cache.init_app(app, config={
        "CACHE_TYPE": "SimpleCache",
        "CACHE_DEFAULT_TIMEOUT": config.CACHE_DEFAULT_TIMEOUT,
    })


def create_app() -> Flask:
    app = Flask(
        __name__,
        template_folder=os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates"),
        static_folder=None,
    )

    # 注册 Jinja filter：format_note_time（将 Unix 时间戳格式化为可读时间）
    from .utils import format_note_time
    app.jinja_env.filters["format_note_time"] = format_note_time

    secret = os.environ.get("RUSIN_SECRET_KEY")
    if not secret:
        secret = _load_or_create_secret_key()

    app.config.update(
        SECRET_KEY=secret,
        # 全局请求体上限：笔记保存、图片上传与附件上传共用，取三者较大值
        MAX_CONTENT_LENGTH=max(config.MAX_CONTENT_BYTES, config.MAX_IMAGE_SIZE_BYTES, config.MAX_ATTACHMENT_SIZE_BYTES),
        SESSION_COOKIE_SECURE=config.SECURE_COOKIES,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        WTF_CSRF_TIME_LIMIT=None,
        RATELIMIT_STORAGE_URI=os.environ.get("REDIS_URL") or "memory://",
        GLOBAL_CDN=config.GLOBAL_CDN,
    )

    log_ip_policy()

    # 说明：这里不使用 werkzeug 的 ProxyFix——它会用客户端可伪造的
    # X-Forwarded-For 直接改写 request.remote_addr，使「可信代理」校验失去意义。
    # 真实客户端 IP 统一由 middleware + ip_utils.analyze_client_ip 在可信代理
    # 白名单（config.trusted_proxies）内安全解析，伪造头一律忽略。
    csrf.init_app(app)
    # 请求钩子必须先于 limiter 注册：Flask-Limiter 的应用级限流（全站 IP 上限）
    # 在 before_request 阶段执行，依赖 g.client_ip / g.rate_limit_exempt。
    register_request_hooks(app)
    limiter.init_app(app)
    _init_cache_backend(app)
    register_i18n(app)
    register_blueprints(app)
    register_error_handlers(app)

    if not app.config.get("TESTING") and not config.SERVERLESS:
        start_background_threads()
        # 插件 Phase 2：定期检查上游更新（Phase 1 安装在 register_blueprints 内完成）
        from . import plugins
        plugins.start_update_thread(app)

    return app


def register_error_handlers(app: Flask) -> None:
    from flask import abort, g, jsonify, make_response, request

    from flask_wtf.csrf import CSRFError
    from .i18n import t

    @app.errorhandler(CSRFError)
    def err_csrf(e):
        if request.path.startswith("/user/") and request.method == "POST":
            lang = getattr(g, "lang", "zh")
            return jsonify({"error": t(lang, "err_csrf")}), 400
        return render_template("errors/400.html",
                               message=str(getattr(e, "description", "Bad Request"))), 400

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
        # 附件下载等场景会带 description 说明具体原因（默认页面文案不带）
        return render_template("errors/401.html", shares=shares,
                               message=str(getattr(e, "description", "") or "")), 401

    @app.errorhandler(403)
    def err_403(e):
        return render_template("errors/400.html",
                               message=str(getattr(e, "description", "Forbidden"))), 403

    @app.errorhandler(404)
    def err_404(e):
        return render_template("errors/404.html"), 404

    @app.errorhandler(413)
    def err_413(e):
        if request.path.startswith("/user/") and request.method == "POST":
            lang = getattr(g, "lang", "zh")
            from . import config as app_config
            return jsonify({"error": t(lang, "err_file_too_large", max=app_config.MAX_ATTACHMENT_SIZE_KB)}), 413
        return render_template("errors/400.html", message="Request body too large"), 413

    @app.errorhandler(429)
    def err_429(e):
        """429 响应：附件上传接口返回 JSON（编辑器 fetch 需要），其余返回错误页。

        ``Retry-After`` 提示客户端稍后重试；错误页文案取自
        ``abort(429, description=...)``（如「单用户同时下载过多」，限流触发时可能为空）。
        """
        lang = getattr(g, "lang", "zh")
        if (request.method == "POST" and request.path.startswith("/user/")
                and request.path.endswith("/attachments")):
            # 编辑器/管理页用 fetch 上传，限流触发时也必须是 JSON 才能展示原因
            resp = jsonify({"error": t(lang, "err_too_many_requests")})
            resp.headers["Retry-After"] = "1"
            return resp, 429
        message = str(getattr(e, "description", "") or "")
        resp = make_response(render_template("errors/429.html", message=message), 429)
        resp.headers["Retry-After"] = "1"
        return resp

    @app.errorhandler(500)
    def err_500(e):
        return render_template("errors/500.html"), 500