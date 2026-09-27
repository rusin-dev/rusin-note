"""用户设置 App：/user/<u>/settings（简洁模式 / 修改密码 / 修改用户名）。

业务逻辑（密码策略、改名数据迁移）见 app.apps.user.service。
"""
from flask import Blueprint, abort, g, redirect, render_template, request, url_for

from app.core import config
from app.core.extensions import limiter
from app.core.i18n import t
from app.core.auth import hash_token
from app.core.middleware import get_session_token
from app.core.notes import validate_username
from app.apps.user.service import (
    change_password,
    get_simple_mode,
    rename_user,
    set_simple_mode,
)
from app.apps.common.helpers import purge_page_cache, require_auth

bp = Blueprint("user", __name__)


# ---------- 用户设置：/user/<u>/settings（界面偏好 / 密码 / 用户名） ----------
# 必须注册在 /user/<username>/<note_id> 之前，否则 settings 会被当作笔记 ID。
@bp.route("/user/<username>/settings", methods=["GET"])
@limiter.limit(lambda: f"{config.GET_RATE_MAX} per {config.GET_RATE_WINDOW} second")
def user_settings_get(username):
    if not validate_username(username):
        abort(400)
    require_auth(username)
    return _render_settings(username, error="", saved=request.args.get("saved", ""))


@bp.route("/user/<username>/settings", methods=["POST"])
@limiter.limit(lambda: f"{config.RATE_MAX} per {config.RATE_WINDOW} second")
def user_settings_post(username):
    if not validate_username(username):
        abort(400)
    require_auth(username)
    lang = getattr(g, "lang", "zh")
    action = request.form.get("action", "")

    if action == "simple_mode":
        enabled = request.form.get("simple_mode") in ("1", "on", "true")
        if not set_simple_mode(username, enabled):
            return _render_settings(username, error=t(lang, "err_settings_save_failed"), saved="")
        return redirect(url_for("user.user_settings_get", username=username, saved="simple"))

    if action == "password":
        token = get_session_token()
        err = change_password(
            username,
            request.form.get("current_password", ""),
            request.form.get("new_password", ""),
            request.form.get("confirm_password", ""),
            keep_token_hash=hash_token(token) if token else None,
            lang=lang,
        )
        if err:
            return _render_settings(username, error=t(lang, err[0], **err[1]), saved="")
        return redirect(url_for("user.user_settings_get", username=username, saved="password"))

    if action == "username":
        new_username = request.form.get("new_username", "").strip()
        err = rename_user(username, new_username, request.form.get("password", ""))
        if err:
            return _render_settings(username, error=t(lang, err[0], **err[1]), saved="")
        # 改名前后的私有页面缓存都清理（旧键会随 TTL 过期，这里主动刷新新键）
        purge_page_cache([f"/user/{username}", f"/user/{username}/",
                          f"/user/{new_username}", f"/user/{new_username}/"],
                         viewers=(username, new_username))
        return redirect(url_for("user.user_settings_get", username=new_username, saved="username"))

    abort(400)


def _render_settings(username, error, saved=""):
    lang = getattr(g, "lang", "zh")
    # 账号安全总览：模板据此决定展示哪些区块（功能开关 + 当前状态）
    from app.core.feature_flags import feature_enabled
    from app.core.store import get_user
    from app.apps.twofa import service as twofa_service
    from app.apps.email import service as email_service
    from app.apps.oauth import service as oauth_service

    user = get_user(username) or {}
    contacts = email_service.get_contacts(username)
    return render_template(
        "notes/user_settings.html",
        username=username,
        simple_mode=get_simple_mode(username),
        error=error,
        saved=saved,
        req_desc=config.get_password_requirements_description(lang),
        has_password=bool(user.get("salt") and user.get("hash")),
        two_factor_feature=feature_enabled("two_factor_auth"),
        two_factor_on=twofa_service.is_enabled(username),
        two_factor_recovery=twofa_service.count_recovery_codes(username),
        email_feature=email_service.is_kind_enabled("email"),
        phone_feature=email_service.is_kind_enabled("phone"),
        email_contact=contacts.get("email"),
        phone_contact=contacts.get("phone"),
        oauth_providers=oauth_service.available_providers(),
        oauth_accounts=oauth_service.get_user_accounts(username),
    )
