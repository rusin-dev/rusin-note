"""Gitee 同步连接、事件队列、Token 刷新与后台调度。"""
from __future__ import annotations

import re
import secrets
import threading
import time

from flask import current_app, has_app_context

from app.core import config
from app.core.cleanup import register_cleanup
from app.core.feature_flags import feature_enabled
from app.core.logger import create_logger
from app.core.sync_hooks import register as register_sync_hook
from app.apps.gitee_sync import api, store
from app.apps.gitee_sync.engine import sync_user as run_sync

logger = create_logger("gitee_sync")

_OWNER_RE = re.compile(r"^[A-Za-z0-9_.\-]{1,100}$")
_REPO_RE = re.compile(r"^[A-Za-z0-9_.\-]{1,100}$")
_BRANCH_RE = re.compile(r"^[A-Za-z0-9._/\-]{1,100}$")
_DIR_RE = re.compile(r"^[A-Za-z0-9_.\-]{1,64}$")

_schedule_guard = threading.Lock()
_scheduled = set()
_poll_guard = threading.Lock()
_poll_running = False


def is_configured() -> bool:
    return bool(config.GITEE_SYNC_CLIENT_ID and config.GITEE_SYNC_CLIENT_SECRET)


def oauth_scope() -> str:
    return config.GITEE_SYNC_SCOPE


def callback_url() -> str:
    from flask import url_for
    return url_for("gitee_sync.oauth_callback", _external=True)


def create_connection(username: str, token: dict, profile: dict) -> dict:
    expires_in = token.get("expires_in")
    try:
        expires_at = time.time() + int(expires_in) if expires_in else 0
    except (TypeError, ValueError):
        expires_at = 0
    connection = {
        "token": token.get("access_token") or "",
        "refresh_token": token.get("refresh_token") or "",
        "expires_at": expires_at,
        "scope": token.get("scope") or oauth_scope(),
        "profile": dict(profile or {}),
        "repo": {},
        "webhook_token": secrets.token_urlsafe(24),
        "webhook_secret": secrets.token_urlsafe(32),
        "webhook_state": "none",
        "connected_at": time.time(),
        "last_sync": 0,
        "last_error": "",
    }
    store.save_connection(username, connection)
    return connection


def get_connection(username: str) -> dict | None:
    return store.get_connection(username)


def public_connection(connection: dict | None) -> dict | None:
    if not connection:
        return None
    return {
        "profile": connection.get("profile") or {},
        "repo": connection.get("repo") or {},
        "webhook_state": connection.get("webhook_state") or "none",
        "connected_at": connection.get("connected_at") or 0,
        "last_sync": connection.get("last_sync") or 0,
        "last_error": connection.get("last_error") or "",
    }


def validate_repo_fields(owner: str, repo: str, branch: str,
                         directory: str) -> tuple[str, str, str, str]:
    owner = (owner or "").strip()
    repo = (repo or "").strip()
    branch = (branch or "master").strip()
    directory = (directory or "rusin-note").strip().strip("/")
    if not _OWNER_RE.match(owner) or not _REPO_RE.match(repo):
        raise ValueError("err_gitee_repo_invalid")
    if not _BRANCH_RE.match(branch):
        raise ValueError("err_gitee_branch_invalid")
    segments = directory.split("/") if directory else []
    if (not segments or len(segments) > 4
            or any(segment in (".", "..") or not _DIR_RE.match(segment)
                   for segment in segments)):
        raise ValueError("err_gitee_directory_invalid")
    return owner, repo, branch, directory


def list_repositories(connection: dict) -> list[dict]:
    token = _valid_token(connection, connection.get("username") or "")
    return api.list_repositories(token)


def _valid_token(connection: dict, username: str = "") -> str:
    token = connection.get("token") or ""
    expires_at = connection.get("expires_at") or 0
    refresh_token = connection.get("refresh_token") or ""
    if expires_at and expires_at <= time.time() + 120 and refresh_token:
        tokens = api.refresh_access_token(
            config.GITEE_SYNC_CLIENT_ID, config.GITEE_SYNC_CLIENT_SECRET,
            refresh_token)
        token = tokens.get("access_token") or token
        expires_in = tokens.get("expires_in")
        try:
            expires_at = time.time() + int(expires_in) if expires_in else 0
        except (TypeError, ValueError):
            expires_at = 0
        connection["token"] = token
        connection["refresh_token"] = tokens.get("refresh_token") or refresh_token
        connection["expires_at"] = expires_at
        if username:
            store.update_connection(
                username, lambda item: item.update({
                    "token": connection["token"],
                    "refresh_token": connection["refresh_token"],
                    "expires_at": connection["expires_at"],
                }))
    if not token:
        raise api.GiteeAPIError(401, "Gitee 授权已失效，请重新连接")
    return token


def setup_repository(username: str, owner: str, repo: str, branch: str,
                     directory: str, webhook_url: str) -> dict:
    owner, repo, branch, directory = validate_repo_fields(
        owner, repo, branch, directory)
    connection = store.get_connection(username)
    if not connection:
        raise ValueError("err_gitee_not_connected")
    token = _valid_token(connection, username)
    repo_info = api.get_repository(token, owner, repo)
    if not repo_info:
        raise api.GiteeAPIError(404, "仓库不存在或无权访问")
    connection["token"] = token
    connection["repo"] = {
        "owner": owner, "name": repo, "branch": branch,
        "directory": directory,
    }
    connection["webhook_token"] = connection.get("webhook_token") or secrets.token_urlsafe(24)
    connection["webhook_secret"] = connection.get("webhook_secret") or secrets.token_urlsafe(32)
    try:
        api.create_webhook(
            token, owner, repo, webhook_url, connection["webhook_secret"])
        connection["webhook_state"] = "active"
    except Exception as e:  # noqa: BLE001 - 创建失败时仍可轮询
        logger.warning(f"Gitee Webhook 创建失败，将依赖轮询: {e}")
        connection["webhook_state"] = "failed"
        connection["last_error"] = str(e)[:300]
    connection["last_sync"] = 0
    store.save_connection(username, connection)
    return connection


def on_note_change(username: str, note_id: str, deleted: bool,
                   origin: str = "user") -> None:
    if origin != "user":
        return
    connection = store.get_connection(username)
    if not connection or not (connection.get("repo") or {}).get("name"):
        return
    if not feature_enabled("gitee_sync"):
        return
    store.enqueue(username, note_id, deleted)
    schedule_user(username)


def schedule_user(username: str) -> None:
    if config.SERVERLESS:
        return
    if has_app_context() and current_app.config.get("TESTING"):
        return
    with _schedule_guard:
        if username in _scheduled:
            return
        _scheduled.add(username)

    def _run():
        try:
            sync_user(username)
        except Exception as e:  # noqa: BLE001
            logger.error(f"Gitee 后台同步失败 ({username}): {e}")
        finally:
            with _schedule_guard:
                _scheduled.discard(username)

    timer = threading.Timer(1.0, _run)
    timer.daemon = True
    timer.start()


def sync_user(username: str, connection: dict | None = None,
              *, notify: bool = True) -> dict:
    connection = connection or store.get_connection(username)
    if not connection:
        raise ValueError("err_gitee_not_connected")
    if not (connection.get("repo") or {}).get("name"):
        raise ValueError("err_gitee_repo_not_ready")
    token = _valid_token(connection, username)
    connection["token"] = token
    client = api.GiteeClient(connection)
    queued_before = list(store.get_outbox(username))
    try:
        summary = run_sync(username, client, connection, notify=notify)
    except Exception as e:
        store.update_connection(
            username, lambda item: item.update({
                "last_sync": time.time(), "last_error": str(e)[:500]}))
        raise
    if queued_before:
        store.clear_outbox(username, queued_before)
    store.update_connection(
        username, lambda item: item.update({
            "last_sync": time.time(), "last_error": ""}))
    return summary


def accept_webhook(token: str, supplied_secret: str) -> str | None:
    found = store.find_by_webhook_token(token)
    if not found:
        return None
    username, connection = found
    expected = connection.get("webhook_secret") or ""
    if not expected or not secrets.compare_digest(expected, supplied_secret or ""):
        return None
    if not (connection.get("repo") or {}).get("name"):
        return None
    store.mark_remote_dirty(username)
    schedule_user(username)
    return username


def _due_users() -> list[str]:
    now = time.time()
    users = list(store.users_with_pending())
    seen = set(users)
    for username, connection in store.all_connections().items():
        if not isinstance(connection, dict) or username in seen:
            continue
        repo = connection.get("repo") or {}
        if not repo.get("name"):
            continue
        last_sync = float(connection.get("last_sync") or 0)
        if now - last_sync >= config.GITEE_SYNC_POLL_SECONDS:
            users.append(username)
    return users


def process_pending() -> None:
    if not feature_enabled("gitee_sync"):
        return
    for username in _due_users():
        try:
            sync_user(username)
        except Exception as e:  # noqa: BLE001
            logger.error(f"Gitee 轮询同步失败 ({username}): {e}")


def _poll_tick() -> None:
    """清理线程入口：本地后台执行，无服务器环境每次请求只处理一个用户。"""
    global _poll_running
    if not feature_enabled("gitee_sync"):
        return
    if config.SERVERLESS:
        due = store.users_with_pending() or _due_users()
        if due:
            try:
                sync_user(due[0])
            except Exception as e:  # noqa: BLE001
                logger.error(f"Gitee 机会式同步失败 ({due[0]}): {e}")
        return
    with _poll_guard:
        if _poll_running:
            return
        _poll_running = True

    def _run():
        global _poll_running
        try:
            process_pending()
        finally:
            with _poll_guard:
                _poll_running = False

    threading.Thread(target=_run, daemon=True).start()


register_sync_hook(on_note_change)
register_cleanup(_poll_tick)
