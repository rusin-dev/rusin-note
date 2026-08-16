"""注册、登录、登出、语言切换"""
import os
import urllib.parse
from flask import Blueprint, abort, g, make_response, redirect, render_template, request, url_for

from .. import config
from ..auth import (
    check_password_complexity,
    create_session,
    delete_session,
    generate_salt,
    hash_password,
    verify_password,
)
from ..extensions import limiter
from ..i18n import LANG_COOKIE
from ..notes import RESERVED_USERNAMES, validate_username
from ..store import save_users, users, users_lock
from ..middleware import get_session_token


bp = Blueprint("auth", __name__)


def _set_session_cookie(resp, token: str):
    if config.SESSION_TIMEOUT_ENABLED:
        max_age = int(config.SESSION_TIMEOUT_SECONDS)
    else:
        max_age = config.COOKIE_MAX_AGE_DEFAULT
    cookie = f"session={token}; Path=/; Max-Age={max_age}; HttpOnly; SameSite=Lax"
    if config.SECURE_COOKIES:
        cookie += "; Secure"
    resp.set_cookie("session", value=token, max_age=max_age, httponly=True, samesite="Lax",
                    secure=config.SECURE_COOKIES, path="/")


def _clear_session_cookie(resp):
    resp.delete_cookie("session", path="/")


# ---------- GET ----------

@bp.route("/register", methods=["GET"])
@limiter.limit(lambda: f"{config.GET_RATE_MAX} per {config.GET_RATE_WINDOW} second")
def register_get():
    return render_template("auth/register.html", error="")


@bp.route("/login", methods=["GET"])
@limiter.limit(lambda: f"{config.GET_RATE_MAX} per {config.GET_RATE_WINDOW} second")
def login_get():
    return render_template("auth/login.html", error="")


@bp.route("/logout", methods=["GET"])
def logout():
    token = get_session_token()
    if token:
        delete_session(token)
    resp = make_response(redirect("/"))
    _clear_session_cookie(resp)
    return resp


@bp.route("/lang/<lang>")
def lang_switch(lang):
    if lang not in ("zh", "en"):
        abort(400)
    location = "/"
    referer = request.headers.get("Referer", "")
    if referer:
        ref = urllib.parse.urlparse(referer)
        location = ref.path + (("?" + ref.query) if ref.query else "")
        if not location:
            location = "/"
    resp = make_response(redirect(location))
    resp.set_cookie(LANG_COOKIE, value=lang, max_age=31536000, samesite="Lax", path="/")
    return resp


# ---------- POST ----------

@bp.route("/register", methods=["POST"])
@limiter.limit(lambda: f"{config.REGISTER_RATE_MAX} per {config.REGISTER_RATE_WINDOW} second")
def register_post():
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")
    confirm = request.form.get("confirm", "")

    if not validate_username(username):
        if username.lower() in RESERVED_USERNAMES:
            error = "err_username_reserved"
        else:
            error = "err_username_invalid"
        return render_template("auth/register.html", error=error), 400

    if password != confirm:
        return render_template("auth/register.html", error="err_password_mismatch"), 400

    if not check_password_complexity(password):
        from ..config import get_password_requirements_description
        lang = getattr(g, "lang", "zh")
        req_desc = get_password_requirements_description(lang)
        from ..i18n import t
        msg = t(lang, "err_password_weak", req=req_desc)
        return render_template("auth/register.html", error=msg), 400

    with users_lock:
        if username in users:
            return render_template("auth/register.html", error="err_username_taken"), 400
        salt = generate_salt()
        hashed = hash_password(password, salt)
        users[username] = {"salt": salt, "hash": hashed}
    save_users()

    token = create_session(username)
    resp = make_response(redirect(f"/user/{username}/new"))
    _set_session_cookie(resp, token)
    return resp


@bp.route("/login", methods=["POST"])
@limiter.limit(lambda: f"{config.RATE_MAX} per {config.RATE_WINDOW} second")
def login_post():
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")

    if len(password) > config.PW_MAX_LENGTH:
        return render_template("auth/login.html", error="err_login_failed"), 401

    with users_lock:
        user = users.get(username)

    salt = user.get("salt") if isinstance(user, dict) else None
    hashed = user.get("hash") if isinstance(user, dict) else None
    if not salt or not hashed or not isinstance(salt, str) or not isinstance(hashed, str):
        salt, hashed = None, None
    if salt is None or not verify_password(password, salt, hashed):
        return render_template("auth/login.html", error="err_login_failed"), 401

    token = create_session(username)
    resp = make_response(redirect(f"/user/{username}/"))
    _set_session_cookie(resp, token)
    return resp