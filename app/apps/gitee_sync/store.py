"""Gitee 同步连接、同步基线与出站队列的持久化。"""
from __future__ import annotations

import copy
import threading
import time

from app.core.logger import create_logger
from app.core.storage import StorageError, storage

logger = create_logger("gitee_sync")

K_CONNECTIONS = "gitee_sync_connections"
K_STATE = "gitee_sync_state"
K_OUTBOX = "gitee_sync_outbox"

_connections_lock = threading.Lock()
_state_lock = threading.Lock()
_outbox_lock = threading.Lock()


def _read(key: str) -> dict:
    try:
        data = storage.get(key)
    except StorageError as e:
        logger.error(f"[错误] 读取 Gitee 同步数据失败: {e}")
        return {}
    return data if isinstance(data, dict) else {}


def _update(key: str, lock, mutate):
    try:
        with lock:
            with storage.lock(key):
                data = _read(key)
                result = mutate(data)
                if not storage.set(key, data):
                    return None
                return result
    except StorageError as e:
        logger.error(f"[错误] 更新 Gitee 同步数据失败: {e}")
        return None


def get_connection(username: str) -> dict | None:
    item = _read(K_CONNECTIONS).get(username)
    return copy.deepcopy(item) if isinstance(item, dict) else None


def save_connection(username: str, connection: dict) -> bool:
    value = copy.deepcopy(connection)
    value["username"] = username

    def _mutate(data):
        data[username] = value
        return True

    return _update(K_CONNECTIONS, _connections_lock, _mutate) is True


def delete_connection(username: str) -> bool:
    def _mutate(data):
        data.pop(username, None)
        return True

    return _update(K_CONNECTIONS, _connections_lock, _mutate) is not None


def all_connections() -> dict:
    return copy.deepcopy(_read(K_CONNECTIONS))


def find_by_webhook_token(token: str) -> tuple[str, dict] | None:
    if not token:
        return None
    for username, connection in _read(K_CONNECTIONS).items():
        if isinstance(connection, dict) and connection.get("webhook_token") == token:
            return username, copy.deepcopy(connection)
    return None


def update_connection(username: str, mutate) -> dict | None:
    result = {"value": None}

    def _mutate(data):
        item = data.get(username)
        if not isinstance(item, dict):
            return None
        mutate(item)
        result["value"] = copy.deepcopy(item)
        return True

    return result["value"] if _update(
        K_CONNECTIONS, _connections_lock, _mutate) is not None else None


def get_sync_state(username: str) -> dict:
    item = _read(K_STATE).get(username)
    if not isinstance(item, dict):
        return {"notes": {}, "conflicts": {}, "manifest": {}, "manifest_sha": ""}
    value = copy.deepcopy(item)
    value.setdefault("notes", {})
    value.setdefault("conflicts", {})
    value.setdefault("manifest", {})
    value.setdefault("manifest_sha", "")
    return value


def save_sync_state(username: str, state: dict) -> bool:
    value = copy.deepcopy(state)

    def _mutate(data):
        data[username] = value
        return True

    return _update(K_STATE, _state_lock, _mutate) is True


def delete_sync_state(username: str) -> bool:
    def _mutate(data):
        data.pop(username, None)
        return True

    return _update(K_STATE, _state_lock, _mutate) is not None


def enqueue(username: str, note_id: str, deleted: bool = False) -> bool:
    def _mutate(data):
        queue = data.get(username)
        if not isinstance(queue, dict):
            queue = {}
        queue[note_id] = {"deleted": bool(deleted), "at": time.time()}
        data[username] = queue
        return True

    return _update(K_OUTBOX, _outbox_lock, _mutate) is True


def mark_remote_dirty(username: str) -> bool:
    def _mutate(data):
        queue = data.get(username)
        if not isinstance(queue, dict):
            queue = {}
        queue["__remote__"] = {"remote": True, "at": time.time()}
        data[username] = queue
        return True

    return _update(K_OUTBOX, _outbox_lock, _mutate) is True


def get_outbox(username: str) -> dict:
    queue = _read(K_OUTBOX).get(username)
    return copy.deepcopy(queue) if isinstance(queue, dict) else {}


def clear_outbox(username: str, keys) -> bool:
    def _mutate(data):
        queue = data.get(username)
        if not isinstance(queue, dict):
            return True
        for key in keys:
            queue.pop(key, None)
        if queue:
            data[username] = queue
        else:
            data.pop(username, None)
        return True

    return _update(K_OUTBOX, _outbox_lock, _mutate) is not None


def users_with_pending() -> list[str]:
    return sorted(username for username, queue in _read(K_OUTBOX).items()
                  if isinstance(queue, dict) and queue)


def rename_user_gitee(old: str, new: str) -> bool:
    keys = (
        (K_CONNECTIONS, _connections_lock),
        (K_STATE, _state_lock),
        (K_OUTBOX, _outbox_lock),
    )
    for key, lock in keys:
        def _mutate(data, old=old, new=new):
            if old in data:
                data[new] = data.pop(old)
                if isinstance(data[new], dict):
                    data[new]["username"] = new
            return True

        if _update(key, lock, _mutate) is None:
            return False
    return True
