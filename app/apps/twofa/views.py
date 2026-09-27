"""双因素认证（TOTP）路由

- ``/login/2fa``：密码校验通过后的第二因素校验（受 ``two_factor_auth`` 开关控制）；
- ``/user/<u>/twofa``：绑定 / 确认 / 停用 / 重生成恢复码的管理页。

业务逻辑见 ``service.py``；模板见 ``templates/twofa/``。
"""
import time

from flask import Blueprint, abort, g, redirect, render_template, request, session, url_for

from app.core import config
from app.core.auth import create_session, set_session_cookie
from app.core.extensions import limiter
from app.core.feature_flags import require_feature
from app.core.i18n import t
from app.core.notes import validate_username
from app.apps.common.helpers import require_auth
from app.apps.twofa import service

bp = Blueprint("twofa", __name__)

# 密码校验通过后写入 Flask 签名会话的待验证标记（{username, created_at}）
PENDING_2FA_KEY = "pending_2fa"


def _clear_pending() -> None:
    session.pop(PENDING_2FA_KEY, None)


def _pending_username():
    """读取待验证用户名；不存在或已过期返回 None。"""
    pending = session.get(PENDING_2FA_KEY)
    if not isinstance(pending, dict):
        return None
    username = pending.get("u")
    created = pending.get("t")
    if not username or not isinstance(created, (int, float)):
        return None
    if time.time() - created > config.SECURITY_CHALLENGE_TTL:
        return None
    return username


# ---------- 登录第二因素 ----------
@bp.route("/login/2fa", methods=["GET"])
@require_feature("two_factor_auth")
@limiter.limit(lambda: f"{config.GET_RATE_MAX} per {config.GET_RATE_WINDOW} second")
def challenge_get():
    if not _pending_username():
        _clear_pending()
        return redirect("/login")
    return render_template("twofa/challenge.html", error="")


@bp.route("/login/2fa", methods=["POST"])
@require_feature("two_factor_auth")
@limiter.limit(lambda: f"{config.RATE_MAX} per {config.RATE_WINDOW} second")
def challenge_post():
    username = _pending_username()
    if not username:
        _clear_pending()
        return redirect("/login")
    code = request.form.get("code", "")
    if not service.verify(username, code):
        lang = getattr(g, "lang", "zh")
        return render_template("twofa/challenge.html",
                               error=t(lang, "err_2fa_invalid")), 401
    _clear_pending()
    token = create_session(username)
    resp = redirect("/")
    set_session_cookie(resp, token)
    return resp


# ---------- 管理页 ----------
def _render(username, error="", setup=None, secret=None, uri=None,
            recovery=None, saved=""):
    return render_template(
        "twofa/manage.html",
        username=username,
        record=service.get_record(username),
        enabled=service.is_enabled(username),
        recovery_count=service.count_recovery_codes(username),
        error=error,
        setup=setup,
        secret=secret,
        uri=uri,
        recovery=recovery,
        saved=saved,
    )


@bp.route("/user/<username>/twofa", methods=["GET"])
@require_feature("two_factor_auth")
@limiter.limit(lambda: f"{config.GET_RATE_MAX} per {config.GET_RATE_WINDOW} second")
def manage_get(username):
    if not validate_username(username):
        abort(400)
    require_auth(username)
    return _render(username, saved=request.args.get("saved", ""))


@bp.route("/user/<username>/twofa", methods=["POST"])
@require_feature("two_factor_auth")
@limiter.limit(lambda: f"{config.RATE_MAX} per {config.RATE_WINDOW} second")
def manage_post(username):
    if not validate_username(username):
        abort(400)
    require_auth(username)
    lang = getattr(g, "lang", "zh")
    action = request.form.get("action", "")

    if action == "start":
        if service.is_enabled(username):
            return _render(username, error=t(lang, "err_2fa_already_enabled"))
        secret, uri = service.start_setup(username)
        if not secret:
            return _render(username, error=t(lang, "err_2fa_save_failed"))
        return _render(username, setup=True, secret=secret, uri=uri)

    if action == "confirm":
        codes = service.confirm_setup(username, request.form.get("code", ""))
        if codes is None:
            # 保留待确认的密钥，允许用户重新输入
            record = service.get_record(username) or {}
            return _render(username, error=t(lang, "err_2fa_invalid"),
                           setup=True, secret=record.get("secret", ""))
        return _render(username, recovery=codes, saved="enabled")

    if action == "disable":
        if not service.verify(username, request.form.get("code", "")):
            return _render(username, error=t(lang, "err_2fa_invalid"))
        service.disable(username)
        return redirect(url_for("twofa.manage_get", username=username, saved="disabled"))

    if action == "regenerate":
        codes = service.regenerate_recovery_codes(username, request.form.get("code", ""))
        if codes is None:
            return _render(username, error=t(lang, "err_2fa_invalid"))
        return _render(username, recovery=codes, saved="recovery")

    abort(400)
