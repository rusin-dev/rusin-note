"""邮箱 / 手机号验证路由

- ``/login/otp``：使用已验证的邮箱 / 手机号 + 验证码免密码登录（两步表单）；
- ``/user/<u>/email``：绑定 / 验证 / 解绑联系方式的管理页。

业务逻辑见 ``service.py``；模板见 ``templates/email/``。
"""
import time

from flask import Blueprint, abort, g, redirect, render_template, request, session, url_for

from app.core import config
from app.core.auth import create_session, set_session_cookie
from app.core.extensions import limiter
from app.core.i18n import t
from app.core.notes import validate_username
from app.apps.common.helpers import require_auth
from app.apps.email import service

bp = Blueprint("email", __name__)

PENDING_OTP_KEY = "pending_otp"


# ---------- 验证码登录 ----------
def _any_login_enabled() -> bool:
    return service.is_kind_enabled("email") or service.is_kind_enabled("phone")


def _pending():
    pending = session.get(PENDING_OTP_KEY)
    if not isinstance(pending, dict):
        return None
    if not pending.get("u") or not isinstance(pending.get("t"), (int, float)):
        return None
    if time.time() - pending["t"] > config.SECURITY_CHALLENGE_TTL:
        session.pop(PENDING_OTP_KEY, None)
        return None
    return pending


@bp.route("/login/otp", methods=["GET"])
@limiter.limit(lambda: f"{config.GET_RATE_MAX} per {config.GET_RATE_WINDOW} second")
def login_get():
    if not _any_login_enabled():
        abort(404)
    pending = _pending()
    return render_template(
        "email/login.html",
        step="verify" if pending else "request",
        kind=pending.get("kind") if pending else "email",
        error="",
    )


@bp.route("/login/otp", methods=["POST"])
@limiter.limit(lambda: f"{config.RATE_MAX} per {config.RATE_WINDOW} second")
def login_post():
    if not _any_login_enabled():
        abort(404)
    lang = getattr(g, "lang", "zh")
    action = request.form.get("action", "request")

    if action == "cancel":
        session.pop(PENDING_OTP_KEY, None)
        return redirect("/login")

    if action == "request":
        kind = request.form.get("kind", "email")
        contact = request.form.get("contact", "")
        username, err = service.request_login_code(kind, contact)
        if err:
            return render_template("email/login.html", step="request", kind=kind,
                                   error=t(lang, err)), 400
        session[PENDING_OTP_KEY] = {"u": username, "kind": kind, "t": time.time()}
        return render_template("email/login.html", step="verify", kind=kind,
                               error="", sent=True)

    if action == "verify":
        pending = _pending()
        if not pending:
            return render_template("email/login.html", step="request", kind="email",
                                   error=t(lang, "err_code_expired")), 400
        if not service.verify_login_code(pending["u"], pending["kind"],
                                         request.form.get("code", "")):
            return render_template("email/login.html", step="verify",
                                   kind=pending["kind"],
                                   error=t(lang, "err_code_invalid")), 401
        username = pending["u"]
        session.pop(PENDING_OTP_KEY, None)
        token = create_session(username)
        resp = redirect("/")
        set_session_cookie(resp, token)
        return resp

    abort(400)


# ---------- 管理页 ----------
def _render(username, error="", saved="", active_kind=None):
    return render_template(
        "email/manage.html",
        username=username,
        contacts=service.get_contacts(username),
        email_enabled=service.is_kind_enabled("email"),
        phone_enabled=service.is_kind_enabled("phone"),
        error=error,
        saved=saved,
        active_kind=active_kind,
    )


@bp.route("/user/<username>/email", methods=["GET"])
@limiter.limit(lambda: f"{config.GET_RATE_MAX} per {config.GET_RATE_WINDOW} second")
def manage_get(username):
    if not validate_username(username):
        abort(400)
    require_auth(username)
    if not (service.is_kind_enabled("email") or service.is_kind_enabled("phone")):
        abort(404)
    return _render(username, saved=request.args.get("saved", ""))


@bp.route("/user/<username>/email", methods=["POST"])
@limiter.limit(lambda: f"{config.RATE_MAX} per {config.RATE_WINDOW} second")
def manage_post(username):
    if not validate_username(username):
        abort(400)
    require_auth(username)
    lang = getattr(g, "lang", "zh")
    action = request.form.get("action", "")
    kind = request.form.get("kind", "email")
    if kind not in service.KINDS or not service.is_kind_enabled(kind):
        abort(404)

    if action == "bind_request":
        err = service.request_bind_code(username, kind, request.form.get("value", ""))
        if err:
            return _render(username, error=t(lang, err), active_kind=kind)
        return _render(username, saved="code_sent", active_kind=kind)

    if action == "bind_confirm":
        if not service.confirm_bind_code(username, kind, request.form.get("code", "")):
            return _render(username, error=t(lang, "err_code_invalid"), active_kind=kind)
        return redirect(url_for("email.manage_get", username=username, saved="bound"))

    if action == "remove":
        service.remove_contact(username, kind)
        return redirect(url_for("email.manage_get", username=username, saved="removed"))

    abort(400)
