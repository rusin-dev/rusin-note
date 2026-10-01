"""注册、登录、登出、语言切换"""
import os
import urllib.parse
from flask import (
    Blueprint, abort, g, jsonify, make_response, redirect, render_template,
    request, session, url_for,
)

from app.core import config
from app.core.auth import (
    check_password_complexity,
    clear_session_cookie,
    create_session,
    delete_session,
    generate_salt,
    hash_password,
    set_session_cookie,
    verify_password,
)
from app.core.extensions import limiter
from app.core.feature_flags import feature_enabled, require_feature
from app.core.i18n import LANG_COOKIE, t
from app.core.notes import RESERVED_USERNAMES, validate_username
from app.core.store import get_user, register_user
from app.core.middleware import get_session_token


bp = Blueprint("auth", __name__)

# 2FA 待验证标记的会话键（与 app/apps/twofa/views.py 保持一致）
PENDING_2FA_KEY = "pending_2fa"


def _login_ctx(with_captcha: bool = False):
    """登录/注册页上下文：启用的第三方登录 Provider；with_captcha 为真且开关
    打开时生成一次性图形验证码（token + 内联 SVG）。"""
    from app.apps.oauth import service as oauth_service
    ctx = {
        "oauth_providers": oauth_service.available_providers(),
        "captcha_enabled": False, "captcha_token": "", "captcha_svg": "",
    }
    if with_captcha and feature_enabled("login_captcha"):
        from app.core import captcha
        token, code = captcha.generate()
        ctx.update({
            "captcha_enabled": True,
            "captcha_token": token,
            "captcha_svg": captcha.render_svg(code),
        })
    return ctx


# ---------- GET ----------

@bp.route("/register", methods=["GET"])
@require_feature("open_register")
@limiter.limit(lambda: f"{config.GET_RATE_MAX} per {config.GET_RATE_WINDOW} second")
def register_get():
    resp = make_response(render_template("auth/register.html", error="", **_login_ctx(with_captcha=True)))
    resp.headers["Cache-Control"] = "no-store"
    return resp


@bp.route("/login", methods=["GET"])
@limiter.limit(lambda: f"{config.GET_RATE_MAX} per {config.GET_RATE_WINDOW} second")
def login_get():
    lang = getattr(g, "lang", "zh")
    err_key = request.args.get("oauth_error", "")
    error = t(lang, err_key) if err_key else ""
    resp = make_response(render_template("auth/login.html", error=error, **_login_ctx(with_captcha=True)))
    # 防止浏览器缓存/BFCache 回退到旧版页面
    resp.headers["Cache-Control"] = "no-store"
    return resp


@bp.route("/login/captcha", methods=["GET"])
@limiter.limit(lambda: f"{config.GET_RATE_MAX} per {config.GET_RATE_WINDOW} second")
def login_captcha_refresh():
    """刷新图形验证码：返回新的一次性 token 与 SVG 标记（登录页 JS 调用）。"""
    from app.core import captcha
    if not feature_enabled("login_captcha"):
        abort(404)
    token, code = captcha.generate()
    return jsonify({"token": token, "svg": captcha.render_svg(code)})


@bp.route("/logout", methods=["POST"])
def logout():
    token = get_session_token()
    if token:
        delete_session(token)
    resp = make_response(redirect("/"))
    clear_session_cookie(resp)
    return resp


@bp.route("/lang/<lang>")
@limiter.limit(lambda: f"{config.GET_RATE_MAX} per {config.GET_RATE_WINDOW} second")
def lang_switch(lang):
    if lang not in ("zh", "en"):
        abort(400)
    location = "/"
    referer = request.headers.get("Referer", "")
    if referer:
        ref = urllib.parse.urlparse(referer)
        location = ref.path + (("?" + ref.query) if ref.query else "")
        # 仅接受站内绝对路径：//evil.com 与 /\evil.com 都会被浏览器解析为站外地址
        if not location.startswith("/") or location[1:2] in ("/", "\\"):
            location = "/"
    resp = make_response(redirect(location))
    resp.set_cookie(LANG_COOKIE, value=lang, max_age=31536000, samesite="Lax", path="/")
    return resp


# ---------- POST ----------

@bp.route("/register", methods=["POST"])
@require_feature("open_register")
@limiter.limit(lambda: f"{config.REGISTER_RATE_MAX} per {config.REGISTER_RATE_WINDOW} second")
def register_post():
    lang = getattr(g, "lang", "zh")

    def _fail(error: str):
        return render_template("auth/register.html", error=error,
                               **_login_ctx(with_captcha=True)), 400

    # 图形验证码先行校验（与登录一致）：一次性 token，成败即销毁，失败重新签发
    if feature_enabled("login_captcha"):
        from app.core import captcha
        if not captcha.verify(request.form.get("captcha_token", ""),
                              request.form.get("captcha", "")):
            return _fail(t(lang, "err_captcha"))

    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")
    confirm = request.form.get("confirm", "")

    if not validate_username(username):
        if username.lower() in RESERVED_USERNAMES:
            return _fail(t(lang, "err_username_reserved"))
        return _fail(t(lang, "err_username_invalid"))

    if password != confirm:
        return _fail(t(lang, "err_password_mismatch"))

    if not check_password_complexity(password):
        from app.core.config import get_password_requirements_description
        req_desc = get_password_requirements_description(lang)
        return _fail(t(lang, "err_password_weak", req=req_desc))

    salt = generate_salt()
    hashed = hash_password(password, salt)
    if not register_user(username, {"salt": salt, "hash": hashed}):
        return _fail(t(lang, "err_username_taken"))

    token = create_session(username)
    # 注册后直接进入工作台首页（而不是编辑器）
    resp = make_response(redirect("/"))
    set_session_cookie(resp, token)
    return resp


@bp.route("/login", methods=["POST"])
@limiter.limit(lambda: f"{config.RATE_MAX} per {config.RATE_WINDOW} second")
def login_post():
    lang = getattr(g, "lang", "zh")
    # 图形验证码先行校验：一次性 token，无论成败即销毁（防重放），失败重新签发
    if feature_enabled("login_captcha"):
        from app.core import captcha
        if not captcha.verify(request.form.get("captcha_token", ""),
                              request.form.get("captcha", "")):
            return render_template("auth/login.html", error=t(lang, "err_captcha"),
                                   **_login_ctx(with_captcha=True)), 400

    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")

    if len(password) > config.PW_MAX_LENGTH:
        return render_template("auth/login.html", error=t(lang, "err_login_failed"),
                               **_login_ctx(with_captcha=True)), 401

    user = get_user(username)

    salt = user.get("salt") if isinstance(user, dict) else None
    hashed = user.get("hash") if isinstance(user, dict) else None
    if not salt or not hashed or not isinstance(salt, str) or not isinstance(hashed, str):
        salt, hashed = None, None
    if salt is None or not verify_password(password, salt, hashed):
        return render_template("auth/login.html", error=t(lang, "err_login_failed"),
                               **_login_ctx(with_captcha=True)), 401

    # 已开启 TOTP 双因素认证：先写入待验证标记，转到第二因素校验页
    from app.apps.twofa import service as twofa_service
    if twofa_service.is_required(username):
        import time as _time
        session[PENDING_2FA_KEY] = {"u": username, "t": _time.time()}
        return redirect("/login/2fa")

    token = create_session(username)
    # 登录后跳转到工作台样式的首页
    resp = make_response(redirect("/"))
    set_session_cookie(resp, token)
    return resp