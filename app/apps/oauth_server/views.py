"""受限 OIDC Provider 端点与管理员客户端管理。"""
from __future__ import annotations

import base64
import hmac
import secrets
import time
import urllib.parse

from flask import (
    Blueprint, Response, abort, g, jsonify, redirect, render_template, request,
    session, url_for,
)

from app.core import config
from app.core.extensions import csrf, limiter
from app.core.feature_flags import feature_enabled, is_admin
from app.core.i18n import t
from app.core.login_next import remember as remember_login_next
from app.core.middleware import get_current_user
from app.apps.oauth_server import oidc, service

bp = Blueprint("oauth_server", __name__)

_CONSENT_KEY = "oidc_authorize_request"
_SECRET_KEY = "oidc_client_secret_once"
_CONSENT_TTL = 600


def _guard() -> None:
    if not feature_enabled("oauth_server"):
        abort(404)


def _require_admin() -> str:
    _guard()
    username = get_current_user()
    if not username or not is_admin(username):
        abort(404)
    return username


def _issuer() -> str:
    return config.OAUTH_SERVER_ISSUER or request.url_root.rstrip("/")


def _json_error(error: str, description: str, status: int = 400):
    response = jsonify({"error": error, "error_description": description})
    response.status_code = status
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    return response


def _append_query(uri: str, **params) -> str:
    parts = urllib.parse.urlsplit(uri)
    query = urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
    query.extend((key, value) for key, value in params.items() if value is not None)
    return urllib.parse.urlunsplit((
        parts.scheme, parts.netloc, parts.path,
        urllib.parse.urlencode(query), parts.fragment))


def _validated_authorize():
    client_id = (request.args.get("client_id") or "").strip()
    redirect_uri = (request.args.get("redirect_uri") or "").strip()
    client = service.get_client(client_id)
    if not client or not client.get("enabled"):
        return None, redirect_uri, "invalid_client", "客户端不存在或已停用"
    if not oidc.valid_redirect_uri(client, redirect_uri):
        return None, redirect_uri, "invalid_request", "redirect_uri 未注册"
    if request.args.get("response_type") != "code":
        return None, redirect_uri, "unsupported_response_type", "仅支持 authorization code"
    scopes = oidc.normalize_scopes(
        request.args.get("scope", ""), client.get("allowed_scopes") or [])
    if scopes is None:
        return None, redirect_uri, "invalid_scope", "请求的 scope 不允许"
    challenge = (request.args.get("code_challenge") or "").strip()
    if not 43 <= len(challenge) <= 128:
        return None, redirect_uri, "invalid_request", "缺少有效 code_challenge"
    if request.args.get("code_challenge_method") != "S256":
        return None, redirect_uri, "invalid_request", "仅支持 S256 PKCE"
    state = (request.args.get("state") or "")[:500]
    nonce = (request.args.get("nonce") or "")[:255]
    return {
        "client": client, "client_id": client_id, "redirect_uri": redirect_uri,
        "scopes": scopes, "state": state, "nonce": nonce,
        "code_challenge": challenge,
    }, redirect_uri, "", ""


@bp.route("/.well-known/openid-configuration", methods=["GET"])
@limiter.limit(lambda: f"{config.GET_RATE_MAX} per {config.GET_RATE_WINDOW} second")
def discovery():
    _guard()
    issuer = _issuer()
    response = jsonify({
        "issuer": issuer,
        "authorization_endpoint": issuer + "/oauth/authorize",
        "token_endpoint": issuer + "/oauth/token",
        "userinfo_endpoint": issuer + "/oauth/userinfo",
        "revocation_endpoint": issuer + "/oauth/revoke",
        "jwks_uri": issuer + "/.well-known/jwks.json",
        "response_types_supported": ["code"],
        "response_modes_supported": ["query"],
        "grant_types_supported": ["authorization_code"],
        "subject_types_supported": ["public"],
        "id_token_signing_alg_values_supported": ["RS256"],
        "token_endpoint_auth_methods_supported": [
            "client_secret_basic", "client_secret_post", "none"],
        "scopes_supported": list(oidc.SUPPORTED_SCOPES),
        "claims_supported": [
            "sub", "iss", "aud", "exp", "iat", "auth_time", "nonce",
            "preferred_username", "name", "picture", "email", "email_verified"],
        "code_challenge_methods_supported": ["S256"],
    })
    response.headers["Cache-Control"] = "public, max-age=300"
    return response


@bp.route("/.well-known/jwks.json", methods=["GET"])
@limiter.limit(lambda: f"{config.GET_RATE_MAX} per {config.GET_RATE_WINDOW} second")
def jwks():
    _guard()
    response = jsonify({"keys": [service.signing_public_jwk()]})
    response.headers["Cache-Control"] = "public, max-age=300"
    return response


@bp.route("/oauth/authorize", methods=["GET"])
@limiter.limit(lambda: f"{config.GET_RATE_MAX} per {config.GET_RATE_WINDOW} second")
def authorize():
    _guard()
    data, redirect_uri, error, description = _validated_authorize()
    if error:
        client = service.get_client(request.args.get("client_id", ""))
        if client and oidc.valid_redirect_uri(client, redirect_uri):
            return redirect(_append_query(
                redirect_uri, error=error, error_description=description,
                state=request.args.get("state") or None))
        return render_template("oauth_server/error.html",
                               error=error, description=description), 400
    if not g.current_user:
        remember_login_next(request.full_path)
        return redirect("/login")
    request_id = secrets.token_urlsafe(24)
    session[_CONSENT_KEY] = {
        **data, "request_id": request_id, "username": g.current_user,
        "auth_time": time.time(), "created": time.time(),
    }
    return render_template(
        "oauth_server/consent.html",
        client=data["client"], scopes=data["scopes"],
        request_id=request_id, signed_in_as=g.current_user)


@bp.route("/oauth/authorize", methods=["POST"])
@limiter.limit(lambda: f"{config.RATE_MAX} per {config.RATE_WINDOW} second")
def authorize_decision():
    _guard()
    stored = session.pop(_CONSENT_KEY, None)
    request_id = request.form.get("request_id", "")
    if (not isinstance(stored, dict)
            or not hmac.compare_digest(str(stored.get("request_id") or ""), request_id)
            or time.time() - float(stored.get("created") or 0) > _CONSENT_TTL
            or getattr(g, "current_user", None) != stored.get("username")):
        return render_template(
            "oauth_server/error.html", error="invalid_request",
            description="授权请求已失效，请重新发起"), 400
    redirect_uri = stored["redirect_uri"]
    if request.form.get("decision") != "approve":
        return redirect(_append_query(
            redirect_uri, error="access_denied",
            error_description="用户拒绝了授权", state=stored.get("state") or None))
    code = service.issue_code(
        stored["username"], stored["client_id"], redirect_uri, stored["scopes"],
        stored["nonce"], stored["code_challenge"], stored["auth_time"])
    return redirect(_append_query(
        redirect_uri, code=code, state=stored.get("state") or None))


def _client_credentials():
    header = request.headers.get("Authorization", "")
    form_client_id = request.form.get("client_id", "")
    form_secret = request.form.get("client_secret", "")
    if header.lower().startswith("basic "):
        try:
            decoded = base64.b64decode(header[6:].strip()).decode("utf-8")
            basic_id, basic_secret = decoded.split(":", 1)
        except (ValueError, UnicodeDecodeError):
            return None
        client_id, secret = basic_id, basic_secret
    else:
        client_id, secret = form_client_id, form_secret
    client = service.get_client(client_id.strip())
    if not client or not client.get("enabled"):
        return None
    if client.get("client_type") == "confidential":
        if not service.verify_client_secret(client, secret):
            return None
    elif secret:
        return None
    return client


def _client_auth_error():
    response = _json_error("invalid_client", "客户端认证失败", 401)
    response.headers["WWW-Authenticate"] = 'Basic realm="oauth-token"'
    return response


@bp.route("/oauth/token", methods=["POST"])
@csrf.exempt
@limiter.limit(lambda: f"{config.RATE_MAX} per {config.RATE_WINDOW} second")
def token():
    _guard()
    client = _client_credentials()
    if not client:
        return _client_auth_error()
    if request.form.get("grant_type") != "authorization_code":
        return _json_error("unsupported_grant_type", "仅支持 authorization_code")
    code = request.form.get("code", "")
    redirect_uri = request.form.get("redirect_uri", "")
    verifier = request.form.get("code_verifier", "")
    record = service.take_code(code)
    valid = (
        isinstance(record, dict)
        and float(record.get("expires_at") or 0) > time.time()
        and record.get("client_id") == client["client_id"]
        and record.get("redirect_uri") == redirect_uri
        and oidc.verify_pkce(verifier, record.get("code_challenge") or "")
    )
    if not valid:
        return _json_error("invalid_grant", "授权码无效、已过期或 PKCE 校验失败")
    access_token, expires_in = service.issue_access_token(
        record["username"], client["client_id"], record["scope"],
        record.get("auth_time") or time.time())
    id_token = service.issue_id_token(
        record["username"], client["client_id"], record["scope"],
        record.get("nonce") or "", record.get("auth_time") or time.time(), _issuer())
    service.touch_client(client["client_id"])
    response = jsonify({
        "access_token": access_token, "token_type": "Bearer",
        "expires_in": expires_in, "id_token": id_token,
        "scope": " ".join(record["scope"]),
    })
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    return response


def _bearer_token() -> str:
    header = request.headers.get("Authorization", "")
    if not header.lower().startswith("bearer "):
        return ""
    return header[7:].strip()


@bp.route("/oauth/userinfo", methods=["GET", "POST"])
@csrf.exempt
@limiter.limit(lambda: f"{config.GET_RATE_MAX} per {config.GET_RATE_WINDOW} second")
def userinfo():
    _guard()
    token_value = _bearer_token()
    record = service.get_access_token(token_value)
    client = service.get_client((record or {}).get("client_id") or "")
    if not record or not client or not client.get("enabled"):
        response = _json_error("invalid_token", "access token 无效或已过期", 401)
        response.headers["WWW-Authenticate"] = 'Bearer error="invalid_token"'
        return response
    claims = service.user_claims(record["username"], record.get("scope") or [])
    response = jsonify(claims)
    response.headers["Cache-Control"] = "no-store"
    return response


@bp.route("/oauth/revoke", methods=["POST"])
@csrf.exempt
@limiter.limit(lambda: f"{config.RATE_MAX} per {config.RATE_WINDOW} second")
def revoke():
    _guard()
    client = _client_credentials()
    if not client:
        return _client_auth_error()
    token_value = request.form.get("token", "")
    if not token_value:
        return _json_error("invalid_request", "缺少 token")
    service.revoke_access_token(token_value, client["client_id"])
    return Response("", status=200, mimetype="text/plain")


# ---------- 管理员客户端管理 ----------
@bp.route("/admin/oauth-clients", methods=["GET"])
@limiter.limit(lambda: f"{config.GET_RATE_MAX} per {config.GET_RATE_WINDOW} second")
def admin_clients():
    _require_admin()
    secret_once = session.pop(_SECRET_KEY, None)
    return render_template(
        "oauth_server/admin_clients.html",
        clients=service.list_clients(),
        secret_once=secret_once,
        error=request.args.get("error", ""),
    )


@bp.route("/admin/oauth-clients", methods=["POST"])
@limiter.limit(lambda: f"{config.RATE_MAX} per {config.RATE_WINDOW} second")
def admin_clients_post():
    _require_admin()
    action = request.form.get("action", "")
    client_id = (request.form.get("client_id") or "").strip()
    try:
        if action == "create":
            scopes = ["openid"]
            if request.form.get("scope_profile") == "1":
                scopes.append("profile")
            if request.form.get("scope_email") == "1":
                scopes.append("email")
            record, secret = service.create_client(
                request.form.get("name", ""),
                [line.strip() for line in
                 (request.form.get("redirect_uris") or "").splitlines() if line.strip()],
                request.form.get("client_type", ""),
                scopes,
                get_current_user() or "",
            )
            if secret:
                session[_SECRET_KEY] = {
                    "client_id": record["client_id"], "secret": secret}
        elif action == "disable":
            service.set_client_enabled(client_id, False)
        elif action == "enable":
            service.set_client_enabled(client_id, True)
        elif action == "delete":
            service.delete_client(client_id)
        elif action == "rotate":
            secret = service.rotate_client_secret(client_id)
            if secret:
                session[_SECRET_KEY] = {"client_id": client_id, "secret": secret}
        else:
            abort(400)
    except ValueError as e:
        return redirect(url_for("oauth_server.admin_clients", error=str(e)))
    return redirect(url_for("oauth_server.admin_clients"))
