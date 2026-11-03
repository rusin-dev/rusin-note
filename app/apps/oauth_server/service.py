"""OIDC Provider 的客户端、授权码、令牌、subject 与签名密钥存储。"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
import time

from app.core import config
from app.core.cleanup import register_cleanup
from app.core.logger import create_logger
from app.core.storage import StorageError, storage
from app.apps.oauth_server import oidc

logger = create_logger("oauth_server")

K_CLIENTS = "oauth_oidc_clients"
K_CODES = "oauth_oidc_codes"
K_TOKENS = "oauth_oidc_tokens"
K_SUBJECTS = "oauth_oidc_subjects"
K_SIGNING_KEY = "oauth_oidc_signing_key"

MAX_REDIRECT_URIS = 5
_MAX_RECORDS = 5000

_locks_guard = threading.Lock()
_key_locks = {}


def _lock_for(key: str) -> threading.Lock:
    with _locks_guard:
        lock = _key_locks.get(key)
        if lock is None:
            lock = threading.Lock()
            _key_locks[key] = lock
        return lock


def _read(key: str) -> dict:
    try:
        data = storage.get(key)
    except StorageError as e:
        logger.error(f"[错误] 读取 OIDC 数据失败 ({key}): {e}")
        return {}
    return data if isinstance(data, dict) else {}


def _update(key: str, mutate):
    try:
        with _lock_for(key):
            with storage.lock(key):
                data = _read(key)
                result = mutate(data)
                if not storage.set(key, data):
                    return None
                return result
    except StorageError as e:
        logger.error(f"[错误] 更新 OIDC 数据失败 ({key}): {e}")
        return None


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _secret_hash(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def public_client(client: dict | None) -> dict | None:
    if not client:
        return None
    return {key: value for key, value in client.items() if key != "secret_hash"}


def create_client(name: str, redirect_uris, client_type: str,
                  scopes, created_by: str) -> tuple[dict, str | None]:
    name = (name or "").strip()[:100]
    if not name:
        raise ValueError("err_oidc_client_name")
    if client_type not in ("public", "confidential"):
        raise ValueError("err_oidc_client_type")
    redirects = []
    for uri in redirect_uris or []:
        uri = (uri or "").strip()
        if not oidc.validate_registered_redirect(uri):
            raise ValueError("err_oidc_redirect_uri")
        if uri not in redirects:
            redirects.append(uri)
    if not redirects or len(redirects) > MAX_REDIRECT_URIS:
        raise ValueError("err_oidc_redirect_uri")
    allowed = oidc.normalize_scopes(" ".join(scopes or ()), oidc.SUPPORTED_SCOPES)
    if allowed is None:
        raise ValueError("err_oidc_scope")

    client_id = "rn_" + secrets.token_hex(10)
    secret = "ocs_" + secrets.token_urlsafe(32) if client_type == "confidential" else None
    record = {
        "client_id": client_id,
        "name": name,
        "redirect_uris": redirects,
        "client_type": client_type,
        "allowed_scopes": allowed,
        "secret_hash": _secret_hash(secret) if secret else "",
        "created_by": created_by or "",
        "created_at": time.time(),
        "enabled": True,
        "last_used_at": 0,
    }

    def _mutate(data):
        data[client_id] = record
        return True

    if _update(K_CLIENTS, _mutate) is None:
        raise RuntimeError("无法保存 OAuth 客户端")
    return dict(record), secret


def get_client(client_id: str) -> dict | None:
    item = _read(K_CLIENTS).get(client_id or "")
    return dict(item) if isinstance(item, dict) else None


def list_clients() -> list[dict]:
    items = [public_client(item) for item in _read(K_CLIENTS).values()
             if isinstance(item, dict)]
    return sorted(items, key=lambda item: item.get("created_at") or 0, reverse=True)


def verify_client_secret(client: dict, supplied: str) -> bool:
    expected = (client or {}).get("secret_hash") or ""
    if not expected:
        return False
    return hmac.compare_digest(expected, _secret_hash(supplied or ""))


def touch_client(client_id: str) -> None:
    def _mutate(data):
        item = data.get(client_id)
        if isinstance(item, dict):
            item["last_used_at"] = time.time()
        return True

    _update(K_CLIENTS, _mutate)


def set_client_enabled(client_id: str, enabled: bool) -> bool:
    def _mutate(data):
        item = data.get(client_id)
        if not isinstance(item, dict):
            return False
        item["enabled"] = bool(enabled)
        return True

    result = _update(K_CLIENTS, _mutate) is True
    if result and not enabled:
        revoke_client_tokens(client_id)
    return result


def delete_client(client_id: str) -> bool:
    def _mutate(data):
        return data.pop(client_id, None) is not None

    result = _update(K_CLIENTS, _mutate) is True
    if result:
        revoke_client_tokens(client_id)
    return result


def rotate_client_secret(client_id: str) -> str | None:
    secret = "ocs_" + secrets.token_urlsafe(32)
    updated = {"ok": False}

    def _mutate(data):
        item = data.get(client_id)
        if not isinstance(item, dict) or item.get("client_type") != "confidential":
            return False
        item["secret_hash"] = _secret_hash(secret)
        updated["ok"] = True
        return True

    if _update(K_CLIENTS, _mutate) is True and updated["ok"]:
        revoke_client_tokens(client_id)
        return secret
    return None


# ---------- 稳定 subject ----------
def subject_for(username: str) -> str:
    result = {"sub": ""}

    def _mutate(data):
        subject = data.get(username)
        if not isinstance(subject, str) or not subject:
            subject = "sub_" + secrets.token_hex(16)
            data[username] = subject
        result["sub"] = subject
        return True

    _update(K_SUBJECTS, _mutate)
    return result["sub"] or "sub_" + hashlib.sha256(username.encode()).hexdigest()[:32]


# ---------- 签名密钥 ----------
def signing_key_record() -> dict:
    result = {"record": None}

    def _mutate(data):
        record = data.get("active")
        if not isinstance(record, dict) or not record.get("pem"):
            record = oidc.generate_signing_key()
            record["created_at"] = time.time()
            data["active"] = record
        result["record"] = record
        return True

    _update(K_SIGNING_KEY, _mutate)
    return result["record"] or oidc.generate_signing_key()


def signing_public_jwk() -> dict:
    return dict(signing_key_record()["jwk"])


# ---------- 授权码 ----------
def issue_code(username: str, client_id: str, redirect_uri: str, scope: list[str],
               nonce: str, code_challenge: str, auth_time: float) -> str:
    code = secrets.token_urlsafe(40)
    now = time.time()
    record = {
        "username": username, "client_id": client_id,
        "redirect_uri": redirect_uri, "scope": list(scope),
        "nonce": nonce or "", "code_challenge": code_challenge,
        "auth_time": auth_time, "created_at": now,
        "expires_at": now + config.OAUTH_SERVER_CODE_TTL,
    }

    def _mutate(data):
        data[_token_hash(code)] = record
        _trim(data)
        return True

    if _update(K_CODES, _mutate) is None:
        raise RuntimeError("无法保存授权码")
    return code


def take_code(code: str) -> dict | None:
    result = {"record": None}

    def _mutate(data):
        result["record"] = data.pop(_token_hash(code or ""), None)
        return True

    _update(K_CODES, _mutate)
    record = result["record"]
    return dict(record) if isinstance(record, dict) else None


# ---------- Access Token ----------
def issue_access_token(username: str, client_id: str, scope: list[str],
                       auth_time: float) -> tuple[str, int]:
    token = "rno_" + secrets.token_urlsafe(40)
    now = time.time()
    ttl = config.OAUTH_SERVER_ACCESS_TOKEN_TTL
    record = {
        "username": username, "client_id": client_id, "scope": list(scope),
        "auth_time": auth_time, "created_at": now, "expires_at": now + ttl,
    }

    def _mutate(data):
        data[_token_hash(token)] = record
        _trim(data)
        return True

    if _update(K_TOKENS, _mutate) is None:
        raise RuntimeError("无法保存访问令牌")
    return token, ttl


def get_access_token(token: str) -> dict | None:
    key = _token_hash(token or "")
    record = _read(K_TOKENS).get(key)
    if not isinstance(record, dict):
        return None
    if float(record.get("expires_at") or 0) <= time.time():
        _update(K_TOKENS, lambda data: data.pop(key, None) is not None)
        return None
    return dict(record)


def revoke_access_token(token: str, client_id: str) -> bool:
    key = _token_hash(token or "")

    def _mutate(data):
        record = data.get(key)
        if isinstance(record, dict) and record.get("client_id") == client_id:
            data.pop(key, None)
        return True

    return _update(K_TOKENS, _mutate) is not None


def revoke_client_tokens(client_id: str) -> None:
    def _mutate(data):
        for key, record in list(data.items()):
            if isinstance(record, dict) and record.get("client_id") == client_id:
                data.pop(key, None)
        return True

    _update(K_TOKENS, _mutate)


def _trim(data: dict) -> None:
    if len(data) <= _MAX_RECORDS:
        return
    ordered = sorted(data.items(), key=lambda item: item[1].get("created_at", 0)
                     if isinstance(item[1], dict) else 0, reverse=True)
    keep = dict(ordered[:_MAX_RECORDS])
    data.clear()
    data.update(keep)


# ---------- 声明 ----------
def user_claims(username: str, scopes) -> dict:
    from app.core.store import get_user
    from app.core.utils import get_avatar_url

    scope_set = set(scopes or ())
    claims = {"sub": subject_for(username)}
    if "profile" in scope_set:
        user = get_user(username) or {}
        claims.update({
            "preferred_username": username,
            "name": user.get("display_name") or username,
            "picture": get_avatar_url(username) or "",
        })
    if "email" in scope_set:
        from app.apps.email.service import get_verified_contact
        email = get_verified_contact(username, "email")
        if email:
            claims["email"] = email
            claims["email_verified"] = True
    return claims


def id_token_claims(username: str, client_id: str, scopes, nonce: str,
                    auth_time: float, issuer: str) -> dict:
    now = int(time.time())
    claims = {
        "iss": issuer,
        "aud": client_id,
        "iat": now,
        "exp": now + config.OAUTH_SERVER_ID_TOKEN_TTL,
        "auth_time": int(auth_time or now),
    }
    if nonce:
        claims["nonce"] = nonce
    claims.update(user_claims(username, scopes))
    return claims


def issue_id_token(username: str, client_id: str, scopes, nonce: str,
                   auth_time: float, issuer: str) -> str:
    key = signing_key_record()
    return oidc.jwt_encode(
        key["pem"], key["kid"],
        id_token_claims(username, client_id, scopes, nonce, auth_time, issuer))


def rename_user_oauth_server(old: str, new: str) -> bool:
    def _rename_subjects(data):
        if old in data:
            data[new] = data.pop(old)
        return True

    if _update(K_SUBJECTS, _rename_subjects) is None:
        return False

    def _rename_tokens(data):
        for record in data.values():
            if isinstance(record, dict) and record.get("username") == old:
                record["username"] = new
        return True

    if _update(K_TOKENS, _rename_tokens) is None:
        return False

    def _rename_codes(data):
        for record in data.values():
            if isinstance(record, dict) and record.get("username") == old:
                record["username"] = new
        return True

    return _update(K_CODES, _rename_codes) is not None


def cleanup_expired() -> None:
    now = time.time()

    def _clean(data):
        for key, record in list(data.items()):
            if isinstance(record, dict) and float(record.get("expires_at") or 0) <= now:
                data.pop(key, None)
        return True

    _update(K_CODES, _clean)
    _update(K_TOKENS, _clean)


register_cleanup(cleanup_expired)
