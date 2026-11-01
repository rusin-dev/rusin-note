"""Gitee OAuth 与仓库 Contents/Pull Request API 客户端（仅标准库）。"""
from __future__ import annotations

import base64
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from app.core import config
from app.core.logger import create_logger

logger = create_logger("gitee_sync")

API_BASE = "https://gitee.com/api/v5"
AUTHORIZE_URL = "https://gitee.com/oauth/authorize"
TOKEN_URL = "https://gitee.com/oauth/token"
MAX_RESPONSE_BYTES = 2 * 1024 * 1024


class GiteeAPIError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def _timeout() -> int:
    try:
        return max(3, int(getattr(config, "GITEE_SYNC_TIMEOUT_SECONDS", 10)))
    except (TypeError, ValueError):
        return 10


def _read_response(response, limit: int = MAX_RESPONSE_BYTES) -> bytes:
    raw = response.read(limit + 1)
    if len(raw) > limit:
        raise GiteeAPIError(413, "Gitee 响应超过大小限制")
    return raw


def _decode_json(raw: bytes):
    try:
        return json.loads(raw.decode("utf-8", "replace"))
    except ValueError as e:
        raise GiteeAPIError(502, f"Gitee 响应不是合法 JSON: {e}") from e


def _post_form(url: str, fields: dict) -> dict:
    body = urllib.parse.urlencode(fields).encode("ascii")
    request = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded",
                 "Accept": "application/json", "User-Agent": "rusin-note"})
    try:
        with urllib.request.urlopen(request, timeout=_timeout()) as response:
            data = _decode_json(_read_response(response))
    except urllib.error.HTTPError as e:
        raise GiteeAPIError(e.code, f"Gitee OAuth 请求失败 ({e.code})") from e
    except (urllib.error.URLError, OSError) as e:
        raise GiteeAPIError(503, f"无法连接 Gitee: {e}") from e
    if not isinstance(data, dict):
        raise GiteeAPIError(502, "Gitee OAuth 响应格式异常")
    if data.get("error"):
        raise GiteeAPIError(400, str(data.get("error_description") or data["error"]))
    return data


def _request_json(method: str, path: str, access_token: str = "",
                  payload: dict | None = None, params: dict | None = None):
    query = dict(params or {})
    if access_token:
        query["access_token"] = access_token
    url = path if path.startswith("http") else API_BASE + path
    if query:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(query)
    data = None
    headers = {"Accept": "application/json", "User-Agent": "rusin-note"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=_timeout()) as response:
            raw = _read_response(response)
    except urllib.error.HTTPError as e:
        message = f"Gitee API 请求失败 ({e.code})"
        try:
            detail = _decode_json(e.read(32 * 1024))
            if isinstance(detail, dict):
                message = str(detail.get("message") or detail.get("error") or message)
        except Exception:
            pass
        raise GiteeAPIError(e.code, message[:300]) from e
    except (urllib.error.URLError, OSError) as e:
        raise GiteeAPIError(503, f"无法连接 Gitee: {e}") from e
    if not raw.strip():
        return {}
    return _decode_json(raw)


def _encoded_path(path: str) -> str:
    return "/".join(urllib.parse.quote(part, safe="") for part in path.split("/") if part)


def build_authorize_url(client_id: str, redirect_uri: str, state: str,
                        scope: str) -> str:
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "state": state,
        "scope": scope,
    }
    return f"{AUTHORIZE_URL}?{urllib.parse.urlencode(params)}"


def exchange_code(client_id: str, client_secret: str, code: str,
                  redirect_uri: str) -> dict:
    return _post_form(TOKEN_URL, {
        "grant_type": "authorization_code",
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "redirect_uri": redirect_uri,
    })


def refresh_access_token(client_id: str, client_secret: str,
                         refresh_token: str) -> dict:
    return _post_form(TOKEN_URL, {
        "grant_type": "refresh_token",
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
    })


def fetch_profile(access_token: str) -> dict:
    data = _request_json("GET", "/user", access_token=access_token)
    return {
        "uid": str(data.get("id") or ""),
        "login": data.get("login") or "",
        "display": data.get("name") or data.get("login") or "",
        "email": data.get("email") or "",
        "avatar": data.get("avatar_url") or "",
    }


def list_repositories(access_token: str) -> list[dict]:
    data = _request_json(
        "GET", "/user/repos", access_token=access_token,
        params={"sort": "updated", "per_page": 100, "page": 1})
    if not isinstance(data, list):
        return []
    repos = []
    for item in data:
        if not isinstance(item, dict):
            continue
        full_name = item.get("full_name") or item.get("path") or ""
        namespace = item.get("namespace")
        owner_info = item.get("owner")
        owner = (namespace.get("path") if isinstance(namespace, dict) else "") or (
            owner_info.get("login") if isinstance(owner_info, dict) else "")
        name = item.get("path") or (full_name.split("/")[-1] if "/" in full_name else "")
        permission = item.get("permission")
        can_pull = (permission.get("pull", True)
                    if isinstance(permission, dict) else True)
        if owner and name and can_pull:
            repos.append({
                "owner": str(owner), "name": str(name),
                "full_name": f"{owner}/{name}",
                "private": bool(item.get("private")),
                "default_branch": item.get("default_branch") or "master",
            })
    return repos


def get_repository(access_token: str, owner: str, repo: str) -> dict:
    data = _request_json("GET", f"/repos/{owner}/{repo}", access_token=access_token)
    return data if isinstance(data, dict) else {}


def _contents_path(owner: str, repo: str, path: str = "") -> str:
    suffix = "/" + _encoded_path(path) if path else ""
    return f"/repos/{owner}/{repo}/contents{suffix}"


def create_webhook(access_token: str, owner: str, repo: str, url: str,
                   password: str) -> dict:
    return _request_json(
        "POST", f"/repos/{owner}/{repo}/hooks", access_token=access_token,
        payload={"url": url, "password": password, "push_events": True,
                 "merge_requests_events": True})


def create_pull_request(access_token: str, owner: str, repo: str, head: str,
                        base: str, title: str, body: str) -> dict:
    return _request_json(
        "POST", f"/repos/{owner}/{repo}/pulls", access_token=access_token,
        payload={"head": head, "base": base, "title": title, "body": body})


def create_branch(access_token: str, owner: str, repo: str, branch: str,
                  base_branch: str) -> dict:
    """从 base_branch 的 commit 创建分支（Gitee 使用 git/refs）。"""
    branch_info = _request_json(
        "GET", f"/repos/{owner}/{repo}/branches/{urllib.parse.quote(base_branch, safe='')}",
        access_token=access_token)
    commit = branch_info.get("commit") if isinstance(branch_info, dict) else None
    sha = (commit or {}).get("sha") if isinstance(commit, dict) else None
    if not sha:
        commit_info = _request_json(
            "GET", f"/repos/{owner}/{repo}/commits/{urllib.parse.quote(base_branch, safe='')}",
            access_token=access_token)
        sha = commit_info.get("sha") if isinstance(commit_info, dict) else None
    if not sha:
        raise GiteeAPIError(502, "无法获取基础分支的最新提交")
    return _request_json(
        "POST", f"/repos/{owner}/{repo}/git/refs", access_token=access_token,
        payload={"ref": f"refs/heads/{branch}", "sha": sha})


class GiteeClient:
    """已认证、绑定到单个仓库/分支的同步客户端。"""

    def __init__(self, connection: dict):
        repo = connection.get("repo") or {}
        self.token = connection.get("token") or ""
        self.owner = repo.get("owner") or ""
        self.repo = repo.get("name") or ""
        self.branch = repo.get("branch") or "master"
        self.directory = (repo.get("directory") or "rusin-note").strip("/")

    def _path(self, relative: str) -> str:
        return f"{self.directory}/{relative}".strip("/")

    def _list_directory(self, relative: str) -> list[dict]:
        path = self._path(relative)
        try:
            data = _request_json(
                "GET", _contents_path(self.owner, self.repo, path), self.token,
                params={"ref": self.branch})
        except GiteeAPIError as e:
            if e.status == 404:
                return []
            raise
        return data if isinstance(data, list) else [data]

    def _read_text(self, path: str) -> tuple[str, str] | None:
        try:
            data = _request_json(
                "GET", _contents_path(self.owner, self.repo, path), self.token,
                params={"ref": self.branch})
        except GiteeAPIError as e:
            if e.status == 404:
                return None
            raise
        if not isinstance(data, dict) or data.get("type") == "dir":
            return None
        try:
            raw = base64.b64decode((data.get("content") or "").replace("\n", ""))
            content = raw.decode("utf-8")
        except (ValueError, UnicodeDecodeError) as e:
            raise GiteeAPIError(502, f"仓库文件解码失败: {path}") from e
        return content, str(data.get("sha") or "")

    def list_notes(self, directory: str, branch: str,
                   known_shas: dict | None = None) -> dict:
        notes = {}
        known_shas = known_shas or {}
        for item in self._list_directory("notes"):
            if not isinstance(item, dict) or item.get("type") != "file":
                continue
            name = str(item.get("name") or "")
            if not name.endswith(".md"):
                continue
            note_id = name[:-3]
            if not re.match(r"^[A-Za-z0-9_\-]+$", note_id):
                continue
            path = item.get("path") or self._path("notes/" + name)
            item_sha = str(item.get("sha") or "")
            if item_sha and known_shas.get(note_id) == item_sha:
                notes[note_id] = {
                    "content": None, "sha": item_sha, "path": path,
                    "unchanged": True,
                }
                continue
            loaded = self._read_text(path)
            if loaded is None:
                continue
            content, sha = loaded
            max_kb = max(1, int(getattr(config, "GITEE_SYNC_MAX_FILE_KB", 2048)))
            if len(content.encode("utf-8")) > max_kb * 1024:
                continue
            notes[note_id] = {
                "content": content,
                "sha": sha or item_sha,
                "path": path,
            }
        return notes

    def read_manifest(self, directory: str, branch: str):
        loaded = self._read_text(self._path("rusin-note.json"))
        if loaded is None:
            return None, ""
        content, sha = loaded
        try:
            data = json.loads(content)
        except ValueError:
            return None, sha
        return (data if isinstance(data, dict) else None), sha

    def _put_file(self, path: str, content: str, sha: str | None, branch: str,
                  message: str) -> str:
        payload = {
            "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
            "message": message,
            "branch": branch,
        }
        if sha:
            payload["sha"] = sha
        data = _request_json(
            "POST", _contents_path(self.owner, self.repo, path), self.token,
            payload=payload)
        content_info = data.get("content") if isinstance(data, dict) else None
        return str((content_info or {}).get("sha") or "")

    def put_note(self, path: str, content: str, sha, branch: str) -> str:
        return self._put_file(path, content, sha, branch, "Update note from Rusin-Note")

    def put_manifest(self, directory: str, content: dict, sha, branch: str) -> str:
        return self._put_file(
            self._path("rusin-note.json"),
            json.dumps(content, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            sha, branch, "Update Rusin-Note sync manifest")

    def delete_note(self, path: str, sha, branch: str) -> bool:
        params = {"ref": branch}
        if sha:
            params["sha"] = sha
        _request_json(
            "DELETE", _contents_path(self.owner, self.repo, path), self.token,
            payload={"message": "Delete note from Rusin-Note", "sha": sha or "",
                     "branch": branch})
        return True

    def create_conflict_pr(self, note_id: str, conflict_text: str,
                           local_content, base_branch: str) -> dict:
        stamp = time.strftime("%Y%m%d%H%M%S", time.gmtime())
        safe_id = re.sub(r"[^A-Za-z0-9_\-]", "-", note_id)[:48]
        branch = f"rusin-sync/conflict/{safe_id}-{stamp}"
        create_branch(
            self.token, self.owner, self.repo, branch, base_branch)
        self._put_file(
            self._path(f"conflicts/{safe_id}-{stamp}.md"), conflict_text,
            None, branch, "Preserve Gitee sync conflict")
        if local_content is not None:
            self._put_file(
                self._path(f"notes/{note_id}.md"), local_content,
                None, branch, "Preserve local note version")
        pull = create_pull_request(
            self.token, self.owner, self.repo, branch, base_branch,
            f"Rusin-Note 同步冲突：{note_id}",
            "站内与 Gitee 同时修改了该笔记。请手动合并，并在 Rusin-Note 中重试同步。")
        return {"branch": branch,
                "pr_url": (pull or {}).get("html_url") or "",
                "pr_number": (pull or {}).get("number")}
