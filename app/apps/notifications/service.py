"""站内系统通知：持久化、未读数、去重与已读。"""
from __future__ import annotations

import secrets
import threading
import time

from app.core.logger import create_logger
from app.core.storage import StorageError, storage

logger = create_logger("notifications")

K_NOTIFICATIONS = "notifications"
MAX_NOTIFICATIONS = 100
_lock = threading.Lock()


def _read_all() -> dict:
    try:
        data = storage.get(K_NOTIFICATIONS)
    except StorageError as e:
        logger.error(f"[错误] 读取站内通知失败: {e}")
        return {}
    return data if isinstance(data, dict) else {}


def _update(mutate):
    try:
        with _lock:
            with storage.lock(K_NOTIFICATIONS):
                data = _read_all()
                result = mutate(data)
                if not storage.set(K_NOTIFICATIONS, data):
                    return None
                return result
    except StorageError as e:
        logger.error(f"[错误] 更新站内通知失败: {e}")
        return None


def add(username: str, kind: str, title: str, body: str = "", url: str = "",
        dedupe: str = "") -> dict | None:
    """新增通知；相同 dedupe 的未读通知只保留一条。"""
    if not username:
        return None
    safe_url = (url or "")[:500]
    if safe_url and (not safe_url.startswith("/") or safe_url.startswith("//")):
        safe_url = ""
    item = {
        "id": secrets.token_hex(8),
        "kind": (kind or "system")[:32],
        "title": (title or "")[:200],
        "body": (body or "")[:1000],
        "url": safe_url,
        "dedupe": (dedupe or "")[:200],
        "read": False,
        "created_at": time.time(),
    }

    def _mutate(data):
        items = data.get(username)
        if not isinstance(items, list):
            items = []
        if item["dedupe"]:
            for existing in items:
                if (isinstance(existing, dict) and not existing.get("read")
                        and existing.get("dedupe") == item["dedupe"]):
                    return dict(existing)
        items.insert(0, item)
        data[username] = items[:MAX_NOTIFICATIONS]
        return dict(item)

    result = _update(_mutate)
    return result


def list_for_user(username: str) -> list[dict]:
    items = _read_all().get(username, [])
    return [dict(item) for item in items if isinstance(item, dict)]


def unread_count(username: str) -> int:
    return sum(1 for item in list_for_user(username) if not item.get("read"))


def mark_read(username: str, notification_id: str) -> bool:
    found = {"ok": False}

    def _mutate(data):
        for item in data.get(username, []):
            if isinstance(item, dict) and item.get("id") == notification_id:
                item["read"] = True
                found["ok"] = True
                break
        return True

    return _update(_mutate) is not None and found["ok"]


def mark_all_read(username: str) -> bool:
    def _mutate(data):
        for item in data.get(username, []):
            if isinstance(item, dict):
                item["read"] = True
        return True

    return _update(_mutate) is not None


def rename_user_notifications(old: str, new: str) -> bool:
    def _mutate(data):
        if old in data:
            existing = data.pop(old)
            if new in data:
                data[new] = list(existing) + list(data[new])
            else:
                data[new] = existing
        return True

    return _update(_mutate) is not None
