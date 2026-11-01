"""Gitee 云同步连接、仓库配置、手动同步与 Webhook。"""
from __future__ import annotations

import secrets
import time

from flask import (
    Blueprint, abort, g, jsonify, redirect, render_template, request, session,
    url_for,
)

from app.core import config
from app.core.extensions import csrf, limiter
from app.core.feature_flags import feature_enabled
from app.core.i18n import t
from app.core.notes import validate_username
from app.apps.common.helpers import require_auth
from app.apps.gitee_sync import api, service, store

bp = Blueprint("gitee_sync", __name__)

_OAUTH_KEY = "gitee_sync_oauth"


def _guard_user(username: str) -> None:
    if not validate_username(username):
        abort(400)
    require_auth(username)
    if not feature_enabled("gitee_sync"):
        abort(404)


def _guard_configured() -> None:
    if not service.is_configured():
        abort(404)


def _manage_redirect(username: str, **params):
    return redirect(url_for("gitee_sync.manage", username=username, **params))


@bp.route("/user/<username>/gitee", methods=["GET"])
@limiter.limit(lambda: f"{config.GET_RATE_MAX} per {config.GET_RATE_WINDOW} second")
def manage(username):
    _guard_user(username)
    connection = store.get_connection(username)
    state = store.get_sync_state(username)
    repos = []
    repo_error = ""
    if (connection and not (connection.get("repo") or {}).get("name")
            and request.args.get("repos") == "1"):
        try:
            repos = service.list_repositories(connection)
        except Exception as e:  # noqa: BLE001
            repo_error = str(e)[:300]
    return render_template(
        "gitee_sync/manage.html",
        username=username,
        configured=service.is_configured(),
        connection=service.public_connection(connection),
        repos=repos,
        repo_error=repo_error,
        conflicts=list((state.get("conflicts") or {}).values()),
        last_sync=state.get("last_sync") or 0,
        last_error=state.get("last_error") or "",
        saved=request.args.get("saved", ""),
        error=request.args.get("error", ""),
    )


@bp.route("/user/<username>/gitee/connect", methods=["GET"])
@limiter.limit(lambda: f"{config.GET_RATE_MAX} per {config.GET_RATE_WINDOW} second")
def connect(username):
    _guard_user(username)
    _guard_configured()
    state_value = secrets.token_urlsafe(24)
    session[_OAUTH_KEY] = {
        "state": state_value, "username": username, "t": time.time(),
    }
    return redirect(api.build_authorize_url(
        config.GITEE_SYNC_CLIENT_ID, service.callback_url(),
        state_value, service.oauth_scope()))


@bp.route("/gitee/callback", methods=["GET"])
@limiter.limit(lambda: f"{config.GET_RATE_MAX} per {config.GET_RATE_WINDOW} second")
def oauth_callback():
    if not feature_enabled("gitee_sync"):
        abort(404)
    _guard_configured()
    stored = session.pop(_OAUTH_KEY, None)
    state_value = request.args.get("state", "")
    username = (stored or {}).get("username") if isinstance(stored, dict) else None
    if (not username or not state_value
            or not secrets.compare_digest(str(stored.get("state") or ""), state_value)
            or time.time() - float(stored.get("t") or 0) > config.SECURITY_CHALLENGE_TTL):
        return redirect("/login")
    if getattr(g, "current_user", None) != username:
        return redirect("/login")
    if request.args.get("error") or not request.args.get("code"):
        return _manage_redirect(username, error="err_gitee_oauth_denied")
    try:
        tokens = api.exchange_code(
            config.GITEE_SYNC_CLIENT_ID, config.GITEE_SYNC_CLIENT_SECRET,
            request.args.get("code", ""), service.callback_url())
        profile = api.fetch_profile(tokens.get("access_token") or "")
    except Exception:  # noqa: BLE001
        return _manage_redirect(username, error="err_gitee_oauth_failed")
    service.create_connection(username, tokens, profile)
    return _manage_redirect(username, saved="connected")


@bp.route("/user/<username>/gitee/setup", methods=["POST"])
@limiter.limit(lambda: f"{config.RATE_MAX} per {config.RATE_WINDOW} second")
def setup(username):
    _guard_user(username)
    _guard_configured()
    connection = store.get_connection(username)
    if not connection:
        return _manage_redirect(username, error="err_gitee_not_connected")
    try:
        owner, repo, branch, directory = service.validate_repo_fields(
            request.form.get("owner", ""), request.form.get("repo", ""),
            request.form.get("branch", ""), request.form.get("directory", ""))
        webhook_url = url_for(
            "gitee_sync.webhook", token=connection.get("webhook_token") or "",
            _external=True)
        service.setup_repository(
            username, owner, repo, branch, directory, webhook_url)
    except ValueError as e:
        return _manage_redirect(username, error=str(e))
    except api.GiteeAPIError as e:
        return _manage_redirect(username, error=f"Gitee: {e}")
    return _manage_redirect(username, saved="repository")


@bp.route("/user/<username>/gitee/sync", methods=["POST"])
@limiter.limit(lambda: f"{config.RATE_MAX} per {config.RATE_WINDOW} second")
def sync_now(username):
    _guard_user(username)
    try:
        summary = service.sync_user(username)
    except Exception as e:  # noqa: BLE001
        return _manage_redirect(username, error=f"Gitee: {e}")
    params = {key: value for key, value in summary.items() if value}
    return _manage_redirect(username, saved="synced", **params)


@bp.route("/user/<username>/gitee/conflict/<note_id>/retry", methods=["POST"])
@limiter.limit(lambda: f"{config.RATE_MAX} per {config.RATE_WINDOW} second")
def retry_conflict(username, note_id):
    _guard_user(username)
    state = store.get_sync_state(username)
    if note_id in state.get("conflicts", {}):
        state["conflicts"].pop(note_id, None)
        store.save_sync_state(username, state)
    return _manage_redirect(username, saved="retry")


@bp.route("/user/<username>/gitee/disconnect", methods=["POST"])
@limiter.limit(lambda: f"{config.RATE_MAX} per {config.RATE_WINDOW} second")
def disconnect(username):
    _guard_user(username)
    store.delete_connection(username)
    store.delete_sync_state(username)
    queued = list(store.get_outbox(username))
    if queued:
        store.clear_outbox(username, queued)
    return _manage_redirect(username, saved="disconnected")


@bp.route("/gitee/webhook/<token>", methods=["POST"])
@csrf.exempt
@limiter.limit("120 per 60 second")
def webhook(token):
    if not feature_enabled("gitee_sync"):
        abort(404)
    if request.content_length and request.content_length > 1024 * 1024:
        abort(413)
    supplied = request.headers.get("X-Gitee-Token", "")
    username = service.accept_webhook(token, supplied)
    if not username:
        abort(403)
    return jsonify({"ok": True, "queued": True}), 202
