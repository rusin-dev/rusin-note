"""Gitee 双向同步执行器：三方比较、冲突分支/PR 与安全删除。"""
from __future__ import annotations

import secrets
import threading
import time

from app.core import config
from app.core.folders import get_note_folder, set_note_folder
from app.core.logger import create_logger
from app.core.notes import (
    get_note_mtime, list_user_notes, note_title, read_note, validate_note_id,
    write_note,
)
from app.core.tags import get_note_tags, set_note_tags
from app.apps.gitee_sync import store
from app.apps.gitee_sync.merge import decide
from app.apps.notifications import service as notifications

logger = create_logger("gitee_sync")

_locks_guard = threading.Lock()
_user_locks = {}


def _user_lock(username: str) -> threading.Lock:
    with _locks_guard:
        lock = _user_locks.get(username)
        if lock is None:
            lock = threading.Lock()
            _user_locks[username] = lock
        return lock


def _note_path(directory: str, note_id: str) -> str:
    return f"{directory.strip('/')}/notes/{note_id}.md"


def _build_manifest(username: str, note_ids: list[str]) -> dict:
    notes = {}
    for note_id in note_ids:
        content = read_note(username, note_id)
        if not content:
            continue
        notes[note_id] = {
            "title": note_title(username, note_id),
            "tags": get_note_tags(username, note_id),
            "folder": get_note_folder(username, note_id),
            "updated_at": get_note_mtime(username, note_id) or 0,
        }
    return {"version": 1, "notes": notes}


def _apply_remote_manifest(username: str, manifest: dict | None,
                           remote_ids: set[str]) -> None:
    if not isinstance(manifest, dict):
        return
    notes = manifest.get("notes")
    if not isinstance(notes, dict):
        return
    for note_id in remote_ids:
        meta = notes.get(note_id)
        if not isinstance(meta, dict):
            continue
        tags = meta.get("tags")
        if isinstance(tags, list):
            clean = [str(tag)[:config.MAX_TAG_LENGTH] for tag in tags
                     if isinstance(tag, str) and tag.strip()]
            set_note_tags(username, note_id, clean[:config.MAX_NOTE_TAGS])
        folder = meta.get("folder")
        if isinstance(folder, str) and folder.strip():
            set_note_folder(username, note_id, folder[:config.MAX_FOLDER_NAME_LENGTH])


def _conflict_document(note_id: str, base: str | None, local: str | None,
                       remote: str | None, pr_url: str) -> str:
    local_text = local if local is not None else "(deleted locally)"
    remote_text = remote if remote is not None else "(deleted in Gitee)"
    return (
        f"<!-- gitee-sync-conflict note={note_id} -->\n"
        f"# Gitee sync conflict: {note_id}\n\n"
        f"Pull request: {pr_url or '(not created)'}\n\n"
        "<<<<<<< Local\n"
        f"{local_text}\n"
        "=======\n"
        f"{remote_text}\n"
        ">>>>>>> Gitee\n"
    )


def _conflict_note_id(username: str, source_id: str) -> str:
    for _ in range(8):
        candidate = f"{source_id[:180]}-conflict-{secrets.token_hex(2)}"
        if validate_note_id(candidate) and not read_note(username, candidate):
            return candidate
    return f"conflict-{secrets.token_hex(6)}"


def _notify_conflict(username: str, note_id: str, copy_id: str,
                     pr_url: str, error: str = "") -> None:
    details = [f"笔记 {note_id} 的站内与 Gitee 版本无法自动合并。"]
    if copy_id:
        details.append(f"冲突副本：{copy_id}")
    if pr_url:
        details.append(f"PR：{pr_url}")
    if error:
        details.append(f"创建 PR 时出错：{error}")
    notifications.add(
        username, "gitee_sync", "Gitee 同步失败", " ".join(details),
        url=f"/user/{username}/gitee",
        dedupe=f"gitee-conflict:{note_id}")


def _notify_sync_error(username: str, note_id: str, error: str) -> None:
    notifications.add(
        username, "gitee_sync", "Gitee 同步失败",
        f"笔记 {note_id} 同步失败：{error}"[:1000],
        url=f"/user/{username}/gitee",
        dedupe=f"gitee-error:{note_id}")


def sync_user(username: str, client, connection: dict, *, notify: bool = True) -> dict:
    """执行一次完整同步；client 需实现 api.GiteeClient 的同步方法。"""
    summary = {
        "pushed": 0, "pulled": 0, "merged": 0,
        "deleted_local": 0, "deleted_remote": 0,
        "conflicts": 0, "errors": 0,
    }
    repo = connection.get("repo") or {}
    directory = (repo.get("directory") or "rusin-note").strip("/")
    branch = repo.get("branch") or "master"
    with _user_lock(username):
        state = store.get_sync_state(username)
        known_shas = {
            note_id: entry.get("remote_sha")
            for note_id, entry in state["notes"].items()
            if isinstance(entry, dict) and entry.get("remote_sha")
        }
        try:
            remote_notes = client.list_notes(directory, branch, known_shas)
            remote_manifest, remote_manifest_sha = client.read_manifest(directory, branch)
        except Exception as e:  # noqa: BLE001 - 网络错误由调用方显示
            state["last_error"] = str(e)[:500]
            state["last_sync"] = time.time()
            store.save_sync_state(username, state)
            raise

        local_ids = set(list_user_notes(username))
        remote_ids = set(remote_notes)
        all_ids = local_ids | remote_ids | set(state["notes"])
        max_notes = max(1, int(getattr(config, "GITEE_SYNC_MAX_NOTES", 1000)))
        conflict_ids = set(state["conflicts"])

        for note_id in sorted(all_ids)[:max_notes]:
            if note_id in conflict_ids:
                continue
            entry = state["notes"].get(note_id, {})
            base = entry.get("base_content")
            local = read_note(username, note_id) if note_id in local_ids else None
            remote_item = remote_notes.get(note_id)
            remote = remote_item.get("content") if remote_item else None
            if remote_item and remote_item.get("unchanged"):
                remote = base
            remote_sha = (remote_item or {}).get("sha") or entry.get("remote_sha")
            path = _note_path(directory, note_id)
            action, merged = decide(base, local, remote)
            try:
                if action == "noop":
                    if remote_item or local is not None:
                        state["notes"][note_id] = {
                            "base_content": local,
                            "remote_sha": remote_sha or "",
                            "path": path,
                            "synced_at": time.time(),
                        }
                elif action == "push":
                    new_sha = client.put_note(path, local or "", remote_sha, branch)
                    state["notes"][note_id] = {
                        "base_content": local,
                        "remote_sha": new_sha or remote_sha or "",
                        "path": path,
                        "synced_at": time.time(),
                    }
                    summary["pushed"] += 1
                elif action == "pull":
                    write_note(username, note_id, remote or "", origin="gitee")
                    state["notes"][note_id] = {
                        "base_content": remote,
                        "remote_sha": remote_sha or "",
                        "path": path,
                        "synced_at": time.time(),
                    }
                    summary["pulled"] += 1
                elif action == "merge":
                    write_note(username, note_id, merged or "", origin="gitee")
                    new_sha = client.put_note(path, merged or "", remote_sha, branch)
                    state["notes"][note_id] = {
                        "base_content": merged,
                        "remote_sha": new_sha or remote_sha or "",
                        "path": path,
                        "synced_at": time.time(),
                    }
                    summary["merged"] += 1
                elif action == "delete_local":
                    write_note(username, note_id, "", origin="gitee")
                    state["notes"][note_id] = {
                        "base_content": None, "remote_sha": "",
                        "path": path, "deleted": True, "synced_at": time.time(),
                    }
                    summary["deleted_local"] += 1
                elif action == "delete_remote":
                    client.delete_note(path, remote_sha, branch)
                    state["notes"][note_id] = {
                        "base_content": None, "remote_sha": "",
                        "path": path, "deleted": True, "synced_at": time.time(),
                    }
                    summary["deleted_remote"] += 1
                else:
                    pr = {}
                    pr_error = ""
                    try:
                        pr = client.create_conflict_pr(
                            note_id,
                            _conflict_document(note_id, base, local, remote, ""),
                            local, branch)
                    except Exception as e:  # noqa: BLE001 - 保留冲突状态优先
                        pr_error = str(e)[:300]
                    pr_url = pr.get("pr_url") or ""
                    conflict_text = _conflict_document(
                        note_id, base, local, remote, pr_url)
                    copy_id = _conflict_note_id(username, note_id)
                    write_note(username, copy_id, conflict_text, origin="gitee")
                    state["conflicts"][note_id] = {
                        "note_id": note_id,
                        "copy_id": copy_id,
                        "branch": pr.get("branch") or "",
                        "pr_url": pr_url,
                        "error": pr_error,
                        "created_at": time.time(),
                    }
                    summary["conflicts"] += 1
                    if notify:
                        _notify_conflict(username, note_id, copy_id, pr_url, pr_error)
            except Exception as e:  # noqa: BLE001 - 单篇失败不影响其它笔记
                summary["errors"] += 1
                state["notes"][note_id] = {
                    "base_content": entry.get("base_content"),
                    "remote_sha": entry.get("remote_sha") or "",
                    "path": path,
                    "last_error": str(e)[:300],
                }
                if notify:
                    _notify_sync_error(username, note_id, str(e))

        # manifest：首轮以仓库元数据为准，之后站内变化优先；两侧同改时站内覆盖。
        local_ids = set(list_user_notes(username))
        local_manifest = _build_manifest(username, sorted(local_ids))
        base_manifest = state.get("manifest") or {}
        remote_changed = (remote_manifest or {}) != base_manifest
        local_changed = local_manifest != base_manifest
        if remote_changed and (not base_manifest or not local_changed):
            _apply_remote_manifest(username, remote_manifest, remote_ids & local_ids)
            local_manifest = _build_manifest(username, sorted(local_ids))
        if (local_manifest != base_manifest
                or (remote_manifest is None and local_manifest.get("notes"))):
            try:
                new_manifest_sha = client.put_manifest(
                    directory, local_manifest, remote_manifest_sha, branch)
                state["manifest_sha"] = new_manifest_sha or remote_manifest_sha or ""
            except Exception as e:  # noqa: BLE001
                summary["errors"] += 1
                state["last_error"] = str(e)[:500]
        else:
            state["manifest_sha"] = remote_manifest_sha or state.get("manifest_sha", "")
        state["manifest"] = local_manifest
        state["last_sync"] = time.time()
        state["last_error"] = ""
        store.save_sync_state(username, state)
    return summary
