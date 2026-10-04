"""第三方登录（OAuth 2.0）：GitHub / Google / Microsoft / 微信 / QQ

网络请求全部用标准库 urllib（最小依赖，不用 authlib/requests）。
可用性 = oauth.enabled ∧ 功能开关("oauth_<key>") ∧ 凭据已配置，三者缺一不展示。
账号绑定存 KV 键 oauth_accounts（provider:uid → username，一 uid 仅绑一人）；
自动注册生成带 Provider 前缀的随机用户名。
"""
import base64
import hashlib
import json
import re
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from app.core import config
from app.core.feature_flags import feature_enabled
from app.core.logger import create_logger
from app.core.notes import RESERVED_USERNAMES, validate_username
from app.core.storage import StorageError, storage
from app.core.store import get_user, register_user

logger = create_logger("oauth")

K_OAUTH = "oauth_accounts"

_lock = threading.Lock()

# ---------- Provider 注册表 ----------
# icon 为 FontAwesome 类名（可含 fa-brands 前缀，模板直接拼接）
PROVIDERS = {
    "github": {
        "label": "GitHub", "icon": "fa-brands fa-github", "prefix": "gh",
        "authorize_url": "https://github.com/login/oauth/authorize",
        "token_url": "https://github.com/login/oauth/access_token",
        "scope": "read:user user:email", "pkce": True, "creds": ("client_id", "client_secret"),
    },
    "google": {
        "label": "Google", "icon": "fa-brands fa-google", "prefix": "gg",
        "authorize_url": "https://accounts.google.com/o/oauth2/v2/auth",
        "token_url": "https://oauth2.googleapis.com/token",
        "scope": "openid email profile", "pkce": True, "creds": ("client_id", "client_secret"),
    },
    "microsoft": {
        "label": "Microsoft", "icon": "fa-brands fa-microsoft", "prefix": "ms",
        "authorize_url": "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize",
        "token_url": "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token",
        "scope": "openid profile email User.Read", "pkce": True,
        "creds": ("client_id", "client_secret"),
    },
    "wechat": {
        "label": "微信", "icon": "fa-brands fa-weixin", "prefix": "wx",
        "authorize_url": "https://open.weixin.qq.com/connect/qrconnect",
        "token_url": "https://api.weixin.qq.com/sns/oauth2/access_token",
        "scope": "snsapi_login", "pkce": False, "creds": ("app_id", "app_secret"),
    },
    "qq": {
        "label": "QQ", "icon": "fa-brands fa-qq", "prefix": "qq",
        "authorize_url": "https://graph.qq.com/oauth2.0/authorize",
        "token_url": "https://graph.qq.com/oauth2.0/token",
        "scope": "get_user_info", "pkce": False, "creds": ("app_id", "app_secret"),
    },
}
# 社交登录功能开关 key：oauth_<provider>
def feature_key(provider: str) -> str:
    return f"oauth_{provider}"


# ---------- 配置读取 ----------
def _provider_cfg(provider: str) -> dict:
    providers = config.OAUTH_CFG.get("providers", {}) or {}
    cfg = providers.get(provider, {})
    return cfg if isinstance(cfg, dict) else {}


def credentials(provider: str):
    spec = PROVIDERS.get(provider)
    if not spec:
        return "", ""
    cfg = _provider_cfg(provider)
    id_key, secret_key = spec["creds"]
    return (cfg.get(id_key, "") or "").strip(), (cfg.get(secret_key, "") or "").strip()


def is_configured(provider: str) -> bool:
    client_id, client_secret = credentials(provider)
    return bool(client_id and client_secret)


def is_globally_enabled() -> bool:
    """OAuth 总开关（config.json 的 ``oauth.enabled``，默认 false）"""
    return bool(config.OAUTH_ENABLED)


def is_available(provider: str) -> bool:
    """总开关 ∧ 功能开关 ∧ 凭据已配置（三者任一不满足即不可用）"""
    return (is_globally_enabled()
            and provider in PROVIDERS
            and feature_enabled(feature_key(provider))
            and is_configured(provider))


def available_providers() -> list:
    """登录页展示用的 Provider 列表（功能开启 + 凭据已配置）"""
    return [{"key": key, "label": spec["label"], "icon": spec["icon"]}
            for key, spec in PROVIDERS.items() if is_available(key)]


def _tenant(provider: str) -> str:
    value = (_provider_cfg(provider).get("tenant") or "common").strip()
    # 仅允许安全字符，避免 URL 注入
    return value if re.match(r"^[A-Za-z0-9._\-]+$", value) else "common"


# ---------- PKCE ----------
def make_pkce() -> tuple[str, str]:
    """生成 PKCE code_verifier / code_challenge（S256）"""
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


# ---------- HTTP 客户端（标准库） ----------
def _http(url: str, method: str = "GET", headers: dict | None = None,
          body: bytes | None = None, timeout: int | None = None):
    request = urllib.request.Request(url, data=body, headers=headers or {}, method=method)
    with urllib.request.urlopen(request, timeout=timeout or config.OAUTH_TIMEOUT_SECONDS) as resp:
        raw = resp.read(256 * 1024)
        return raw, resp.headers.get("Content-Type", "")


def _http_json(url: str, method: str = "GET", headers: dict | None = None,
               body: bytes | None = None) -> dict:
    raw, _ = _http(url, method=method, headers=headers, body=body)
    try:
        data = json.loads(raw.decode("utf-8", "replace"))
    except ValueError as e:
        raise OAuthError(f"响应不是合法 JSON: {e}") from e
    if not isinstance(data, dict):
        raise OAuthError("响应格式异常")
    return data


def _post_form(url: str, fields: dict, headers: dict | None = None) -> dict:
    body = urllib.parse.urlencode(fields).encode("ascii")
    hdrs = {"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"}
    if headers:
        hdrs.update(headers)
    return _http_json(url, method="POST", headers=hdrs, body=body)


class OAuthError(Exception):
    """OAuth 流程异常（网络错误、Provider 返回错误、响应异常）"""


# ---------- 授权 URL ----------
def build_authorize_url(provider: str, redirect_uri: str, state: str,
                        code_challenge: str | None = None) -> str:
    spec = PROVIDERS[provider]
    client_id, _ = credentials(provider)
    url = spec["authorize_url"]
    if "{tenant}" in url:
        url = url.format(tenant=_tenant(provider))

    if provider == "wechat":
        params = {"appid": client_id, "redirect_uri": redirect_uri,
                  "response_type": "code", "scope": spec["scope"], "state": state}
        url = f"{url}?{urllib.parse.urlencode(params)}#wechat_redirect"
        return url

    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": spec["scope"],
        "state": state,
    }
    if provider == "google":
        params["access_type"] = "online"
        params["prompt"] = "select_account"
    if provider == "microsoft":
        params["response_mode"] = "query"
    if spec.get("pkce") and code_challenge:
        params["code_challenge"] = code_challenge
        params["code_challenge_method"] = "S256"
    return f"{url}?{urllib.parse.urlencode(params)}"


# ---------- 令牌交换 ----------
def exchange_code(provider: str, code: str, redirect_uri: str,
                  code_verifier: str | None = None) -> dict:
    client_id, client_secret = credentials(provider)
    if not client_id or not client_secret:
        raise OAuthError("Provider 凭据未配置")

    if provider == "github":
        return _post_form(PROVIDERS[provider]["token_url"], {
            "client_id": client_id, "client_secret": client_secret,
            "code": code, "redirect_uri": redirect_uri,
        })

    if provider == "google":
        fields = {
            "code": code, "client_id": client_id, "client_secret": client_secret,
            "redirect_uri": redirect_uri, "grant_type": "authorization_code",
        }
        if code_verifier:
            fields["code_verifier"] = code_verifier
        return _post_form(PROVIDERS[provider]["token_url"], fields)

    if provider == "microsoft":
        fields = {
            "client_id": client_id, "client_secret": client_secret, "code": code,
            "redirect_uri": redirect_uri, "grant_type": "authorization_code",
            "scope": PROVIDERS[provider]["scope"],
        }
        if code_verifier:
            fields["code_verifier"] = code_verifier
        url = PROVIDERS[provider]["token_url"].format(tenant=_tenant(provider))
        return _post_form(url, fields)

    if provider == "wechat":
        query = urllib.parse.urlencode({
            "appid": client_id, "secret": client_secret, "code": code,
            "grant_type": "authorization_code",
        })
        return _http_json(f"{PROVIDERS[provider]['token_url']}?{query}")

    if provider == "qq":
        query = urllib.parse.urlencode({
            "grant_type": "authorization_code", "client_id": client_id,
            "client_secret": client_secret, "code": code,
            "redirect_uri": redirect_uri, "fmt": "json",
        })
        return _http_json(f"{PROVIDERS[provider]['token_url']}?{query}")

    raise OAuthError("未知 Provider")


# ---------- 用户信息 ----------
def fetch_profile(provider: str, token: dict) -> dict:
    """拉取并归一化第三方用户信息：{uid, display, email, avatar}"""
    if provider == "github":
        access = token.get("access_token")
        profile = _http_json("https://api.github.com/user", headers={
            "Authorization": f"Bearer {access}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "rusin-note",
        })
        email = profile.get("email")
        if not email:
            try:
                raw, _ = _http("https://api.github.com/user/emails", headers={
                    "Authorization": f"Bearer {access}",
                    "Accept": "application/vnd.github+json",
                    "User-Agent": "rusin-note",
                })
                listed = json.loads(raw.decode("utf-8", "replace"))
                if isinstance(listed, list):
                    primary = next(
                        (e for e in listed if isinstance(e, dict) and e.get("primary")),
                        None)
                    if primary is None:
                        primary = next(
                            (e for e in listed if isinstance(e, dict) and e.get("verified")),
                            None)
                    email = (primary or {}).get("email") if primary else None
            except (ValueError, OAuthError, urllib.error.URLError, OSError):
                email = None
        return {
            "uid": str(profile.get("id") or ""),
            "display": profile.get("login") or profile.get("name") or "",
            "email": email or "",
            "avatar": profile.get("avatar_url") or "",
        }

    if provider == "google":
        access = token.get("access_token")
        profile = _http_json("https://openidconnect.googleapis.com/v1/userinfo",
                             headers={"Authorization": f"Bearer {access}"})
        return {
            "uid": str(profile.get("sub") or ""),
            "display": profile.get("name") or profile.get("email") or "",
            "email": profile.get("email") or "",
            "avatar": profile.get("picture") or "",
        }

    if provider == "microsoft":
        access = token.get("access_token")
        profile = _http_json("https://graph.microsoft.com/v1.0/me",
                             headers={"Authorization": f"Bearer {access}"})
        return {
            "uid": str(profile.get("id") or ""),
            "display": profile.get("displayName") or "",
            "email": profile.get("mail") or profile.get("userPrincipalName") or "",
            "avatar": "",
        }

    if provider == "wechat":
        access = token.get("access_token")
        openid = token.get("openid")
        query = urllib.parse.urlencode({"access_token": access, "openid": openid})
        profile = _http_json(
            f"https://api.weixin.qq.com/sns/userinfo?{query}")
        return {
            "uid": str(profile.get("unionid") or openid or ""),
            "display": profile.get("nickname") or "",
            "email": "",
            "avatar": profile.get("headimgurl") or "",
        }

    if provider == "qq":
        access = token.get("access_token")
        openid = token.get("openid")
        if not openid:
            me = _http_json("https://graph.qq.com/oauth2.0/me?" + urllib.parse.urlencode(
                {"access_token": access, "fmt": "json"}))
            openid = me.get("openid")
        client_id, _ = credentials(provider)
        query = urllib.parse.urlencode({
            "access_token": access, "oauth_consumer_key": client_id,
            "openid": openid, "fmt": "json",
        })
        profile = _http_json(f"https://graph.qq.com/user/get_user_info?{query}")
        return {
            "uid": str(openid or ""),
            "display": profile.get("nickname") or "",
            "email": "",
            "avatar": profile.get("figureurl_qq_2") or profile.get("figureurl_qq_1") or "",
        }

    raise OAuthError("未知 Provider")


# ---------- 用户名生成 ----------
def generate_username(provider: str, profile: dict) -> str:
    """为自动注册生成候选用户名（带 Provider 前缀，避免冒用既有用户名）"""
    spec = PROVIDERS[provider]
    base = re.sub(r"[^A-Za-z0-9_\-]", "", profile.get("display") or "")[:16]
    if base:
        candidate = f"{spec['prefix']}_{base}"
    else:
        candidate = f"{spec['prefix']}_{secrets.token_hex(4)}"
    candidate = candidate[:32]
    if not validate_username(candidate) or candidate.lower() in RESERVED_USERNAMES:
        candidate = f"{spec['prefix']}_{secrets.token_hex(4)}"
    return candidate


def register_oauth_user(provider: str, profile: dict) -> str | None:
    """为第三方账号自动创建站内用户，返回新用户名；失败返回 None。

    用户名冲突时追加随机后缀重试；用户记录标记 ``oauth_only``，表示该账号
    没有密码（不可用密码登录，需先设置密码）。
    """
    candidate = generate_username(provider, profile)
    for attempt in range(6):
        username = candidate if attempt == 0 else f"{candidate[:24]}_{secrets.token_hex(3)}"
        record = {
            "salt": "", "hash": "",
            "oauth_only": True,
            "created_at": time.time(),
            "display_name": profile.get("display") or "",
        }
        if register_user(username, record):
            return username
    logger.error(f"[错误] 第三方自动注册失败（provider={provider}）")
    return None


# ---------- 账号绑定存储 ----------
def _read_accounts() -> dict:
    try:
        data = storage.get(K_OAUTH)
    except StorageError as e:
        logger.error(f"[错误] 读取第三方账号失败: {e}")
        return {}
    return data if isinstance(data, dict) else {}


def _update_accounts(mutate):
    try:
        with _lock:
            with storage.lock(K_OAUTH):
                data = _read_accounts()
                result = mutate(data)
                if not storage.set(K_OAUTH, data):
                    logger.error("[错误] 写入第三方账号失败")
                    return None
                return result
    except StorageError as e:
        logger.error(f"[错误] 更新第三方账号失败: {e}")
        return None


def get_account(provider: str, uid: str) -> dict | None:
    entry = _read_accounts().get(f"{provider}:{uid}")
    return dict(entry) if isinstance(entry, dict) else None


def get_user_accounts(username: str) -> list:
    """返回某用户已绑定的第三方账号列表（用于设置页展示）"""
    result = []
    for key, entry in _read_accounts().items():
        if isinstance(entry, dict) and entry.get("username") == username:
            spec = PROVIDERS.get(entry.get("provider"), {})
            result.append({
                "provider": entry.get("provider"),
                "label": spec.get("label", entry.get("provider")),
                "icon": spec.get("icon", "fa-solid fa-link"),
                "display": entry.get("display") or "",
                "linked_at": entry.get("linked_at"),
            })
    return result


def link_account(provider: str, uid: str, username: str, display: str = "") -> bool:
    """把第三方账号绑定到站内用户。已被他人绑定则返回 False。"""
    if not provider or not uid or not username:
        return False
    key = f"{provider}:{uid}"

    def _mutate(data):
        existing = data.get(key)
        if isinstance(existing, dict) and existing.get("username") != username:
            return False
        data[key] = {
            "provider": provider, "uid": uid, "username": username,
            "display": display or "", "linked_at": time.time(),
        }
        return True

    return _update_accounts(_mutate) is True


def unlink_account(provider: str, username: str) -> bool:
    """解绑某用户指定 Provider 的第三方账号"""
    removed = {"ok": False}

    def _mutate(data):
        for key, entry in list(data.items()):
            if (isinstance(entry, dict) and entry.get("provider") == provider
                    and entry.get("username") == username):
                data.pop(key, None)
                removed["ok"] = True
        return True

    return _update_accounts(_mutate) is not None and removed["ok"]


def rename_user_oauth(old: str, new: str) -> bool:
    """迁移第三方账号绑定关系（用户改名用）"""
    def _mutate(data):
        for entry in data.values():
            if isinstance(entry, dict) and entry.get("username") == old:
                entry["username"] = new
        return True

    return _update_accounts(_mutate) is not None
