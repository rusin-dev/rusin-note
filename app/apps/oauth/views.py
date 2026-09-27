"""第三方登录（OAuth 2.0）路由

- ``GET /oauth/<provider>``：发起授权（登录；``?link=1`` 且已登录时为绑定）；
- ``GET /oauth/<provider>/callback``：授权回调，创建/绑定账号并建立会话；
- ``GET/POST /user/<u>/oauth``：第三方账号绑定管理。

业务逻辑见 ``service.py``；模板见 ``templates/oauth/``。
"""
import secrets
import time

from flask import (Blueprint, abort, g, redirect, render_template, request,
                   session, url_for)

from app.core import config
from app.core.auth import create_session, set_session_cookie
from app.core.extensions import limiter
from app.core.feature_flags import feature_enabled
from app.core.i18n import t
from app.core.logger import create_logger
from app.core.middleware import get_current_user
from app.core.notes import validate_username
from app.apps.common.helpers import require_auth
from app.apps.oauth import service

bp = Blueprint("oauth", __name__)

logger = create_logger("oauth")

# Flask 签名会话中的 OAuth state 存储键
_STATE_KEY = "oauth_state"


def _guard_provider(provider: str) -> None:
    """Provider 合法性 + 总开关 + 功能开关 + 凭据配置校验，任一不满足即 404。"""
    if not service.is_globally_enabled():
        abort(404)
    if provider not in service.PROVIDERS:
        abort(404)
    if not feature_enabled(service.feature_key(provider)):
        abort(404)
    if not service.is_configured(provider):
        abort(404)


def _redirect_uri(provider: str) -> str:
    return url_for("oauth.callback", provider=provider, _external=True)


def _login_error(key: str):
    """回调失败时回到登录页并携带错误文案 key。"""
    return redirect(url_for("auth.login_get", oauth_error=key))


# ---------- 发起授权 ----------
@bp.route("/oauth/<provider>")
@limiter.limit(lambda: f"{config.GET_RATE_MAX} per {config.GET_RATE_WINDOW} second")
def start(provider):
    _guard_provider(provider)
    link_mode = request.args.get("link") == "1" and bool(get_current_user())
    if request.args.get("link") == "1" and not get_current_user():
        return redirect("/login")

    state = secrets.token_urlsafe(24)
    verifier = challenge = None
    if service.PROVIDERS[provider].get("pkce"):
        verifier, challenge = service.make_pkce()
    session[_STATE_KEY] = {
        "state": state,
        "provider": provider,
        "link": link_mode,
        "verifier": verifier,
        "t": time.time(),
    }
    return redirect(service.build_authorize_url(
        provider, _redirect_uri(provider), state, challenge))


# ---------- 回调 ----------
@bp.route("/oauth/<provider>/callback")
@limiter.limit(lambda: f"{config.GET_RATE_MAX} per {config.GET_RATE_WINDOW} second")
def callback(provider):
    _guard_provider(provider)

    if request.args.get("error"):
        session.pop(_STATE_KEY, None)
        return _login_error("err_oauth_denied")

    stored = session.pop(_STATE_KEY, None)
    state = request.args.get("state", "")
    if (not isinstance(stored, dict) or stored.get("provider") != provider
            or not state or stored.get("state") != state):
        return _login_error("err_oauth_state")
    if not isinstance(stored.get("t"), (int, float)) or \
            time.time() - stored["t"] > config.SECURITY_CHALLENGE_TTL:
        return _login_error("err_oauth_state")

    code = request.args.get("code", "")
    if not code:
        return _login_error("err_oauth_failed")

    try:
        token = service.exchange_code(provider, code, _redirect_uri(provider),
                                      stored.get("verifier"))
        profile = service.fetch_profile(provider, token)
    except Exception as e:  # noqa: BLE001 - 统一降级为用户可见错误
        logger.error(f"[错误] OAuth 流程失败（provider={provider}）: {e}")
        return _login_error("err_oauth_failed")

    uid = profile.get("uid")
    if not uid:
        return _login_error("err_oauth_failed")

    if stored.get("link"):
        username = get_current_user()
        if not username:
            return redirect("/login")
        if not service.link_account(provider, uid, username, profile.get("display", "")):
            return redirect(url_for("oauth.manage_get", username=username,
                                    error="err_oauth_taken"))
        return redirect(url_for("oauth.manage_get", username=username, saved="linked"))

    # 登录 / 自动注册
    account = service.get_account(provider, uid)
    if account and account.get("username"):
        from app.core.store import get_user
        username = account["username"]
        if get_user(username) is None:
            username = None
    else:
        username = None

    if not username:
        if not (config.OAUTH_AUTO_REGISTER and feature_enabled("open_register")):
            return _login_error("err_oauth_no_account")
        username = service.register_oauth_user(provider, profile)
        if not username:
            return _login_error("err_oauth_failed")
        if not service.link_account(provider, uid, username, profile.get("display", "")):
            return _login_error("err_oauth_failed")

    # 与密码登录一致：已开启 TOTP 时转第二因素校验
    from app.apps.twofa import service as twofa_service
    if twofa_service.is_required(username):
        session["pending_2fa"] = {"u": username, "t": time.time()}
        return redirect("/login/2fa")

    token_value = create_session(username)
    resp = redirect("/")
    set_session_cookie(resp, token_value)
    return resp


# ---------- 绑定管理 ----------
def _render(username, error="", saved=""):
    return render_template(
        "oauth/manage.html",
        username=username,
        accounts=service.get_user_accounts(username),
        providers=service.available_providers(),
        error=error,
        saved=saved,
    )


@bp.route("/user/<username>/oauth", methods=["GET"])
@limiter.limit(lambda: f"{config.GET_RATE_MAX} per {config.GET_RATE_WINDOW} second")
def manage_get(username):
    if not validate_username(username):
        abort(400)
    require_auth(username)
    # 即使所有 Provider 都被停用/未配置，只要存在历史绑定也应能进入解绑
    if not service.available_providers() and not service.get_user_accounts(username):
        abort(404)
    lang = getattr(g, "lang", "zh")
    error = t(lang, request.args["error"]) if request.args.get("error") else ""
    return _render(username, error=error, saved=request.args.get("saved", ""))


@bp.route("/user/<username>/oauth/<provider>/unlink", methods=["POST"])
@limiter.limit(lambda: f"{config.RATE_MAX} per {config.RATE_WINDOW} second")
def unlink(username, provider):
    if not validate_username(username):
        abort(400)
    require_auth(username)
    if provider not in service.PROVIDERS:
        abort(404)
    service.unlink_account(provider, username)
    return redirect(url_for("oauth.manage_get", username=username, saved="unlinked"))
