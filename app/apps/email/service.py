"""邮箱 / 手机号验证：绑定验证（purpose=bind）与验证码免密登录（purpose=login）

数据存 KV 键 user_contacts（联系方式+verified）与 verification_codes（只存哈希）。
投递失败不落库；网络投递（SMTP / Webhook）在存储锁之外执行。
"""
import hashlib
import json
import re
import secrets
import smtplib
import threading
import time
import urllib.error
import urllib.request
from email.message import EmailMessage

from app.core import config
from app.core.feature_flags import feature_enabled
from app.core.logger import create_logger
from app.core.storage import StorageError, storage

logger = create_logger("email_verify")

K_CONTACTS = "user_contacts"
K_CODES = "verification_codes"

KINDS = ("email", "phone")
PURPOSES = ("bind", "login")

# 邮箱：宽松但明确的常见格式校验（最终归属由验证码证明）
_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")
# 手机号：可选国际区号 +，6-20 位数字
_PHONE_RE = re.compile(r"^\+?\d{6,20}$")

_lock = threading.Lock()


# ---------- 通用 KV 读写 ----------
def _read(key: str) -> dict:
    try:
        data = storage.get(key)
    except StorageError as e:
        logger.error(f"[错误] 读取 {key} 失败: {e}")
        return {}
    return data if isinstance(data, dict) else {}


def _update(key: str, mutate):
    """跨实例安全读改写（返回 mutate 的结果；存储失败返回 None）"""
    try:
        with _lock:
            with storage.lock(key):
                data = _read(key)
                result = mutate(data)
                if not storage.set(key, data):
                    logger.error(f"[错误] 写入 {key} 失败")
                    return None
                return result
    except StorageError as e:
        logger.error(f"[错误] 更新 {key} 失败: {e}")
        return None


# ---------- 联系方式规范化 / 校验 ----------
def feature_key(kind: str) -> str:
    return "email_verify" if kind == "email" else "phone_verify"


def is_kind_enabled(kind: str) -> bool:
    if kind not in KINDS:
        return False
    return feature_enabled(feature_key(kind))


def normalize(kind: str, value: str) -> str:
    value = (value or "").strip()
    if kind == "email":
        return value.lower()
    # 手机号去掉空格、连字符、括号，保留可选的前导 +
    return re.sub(r"[\s\-()]", "", value)


def is_valid(kind: str, value: str) -> bool:
    if kind == "email":
        return bool(_EMAIL_RE.match(value or ""))
    if kind == "phone":
        return bool(_PHONE_RE.match(value or ""))
    return False


# ---------- 投递（可在测试中替换） ----------
def deliver_email(to_addr: str, code: str) -> bool:
    """通过 SMTP 发送验证码；未配置 SMTP 时记录日志并返回 False。"""
    smtp = config.SMTP_CFG or {}
    host = (smtp.get("host") or "").strip()
    if not host:
        logger.warning("[邮件] 未配置 security.smtp.host，验证码未发送（to=%s）", to_addr)
        return False
    from_addr = (smtp.get("from_addr") or smtp.get("username") or "").strip()
    try:
        port = int(smtp.get("port", 587) or 587)
    except (TypeError, ValueError):
        port = 587
    message = EmailMessage()
    message["Subject"] = f"[{config.SITE_NAME}] 验证码 / Verification code"
    message["From"] = from_addr or "no-reply@localhost"
    message["To"] = to_addr
    message.set_content(
        f"您的验证码是 {code}，{config.SECURITY_CODE_TTL // 60} 分钟内有效。\n"
        f"Your verification code is {code}; it expires in "
        f"{config.SECURITY_CODE_TTL // 60} minutes."
    )
    try:
        if smtp.get("use_ssl"):
            server = smtplib.SMTP_SSL(host, port, timeout=config.SECURITY_TIMEOUT_SECONDS)
        else:
            server = smtplib.SMTP(host, port, timeout=config.SECURITY_TIMEOUT_SECONDS)
        with server:
            if smtp.get("use_tls") and not smtp.get("use_ssl"):
                server.starttls()
            username = (smtp.get("username") or "").strip()
            if username:
                server.login(username, smtp.get("password", ""))
            server.send_message(message)
        return True
    except Exception as e:  # noqa: BLE001 - 投递失败原因多样，统一降级
        logger.error(f"[邮件] 发送失败（to={to_addr}）: {e}")
        return False


def deliver_sms(phone: str, code: str) -> bool:
    """通过通用 HTTP Webhook（POST JSON）发送验证码；未配置时返回 False。

    请求体：``{"phone": "...", "code": "...", "site": "...", "ttl": <秒>}``；
    配置了 ``security.sms.token`` 时附加 ``Authorization: Bearer <token>``。
    """
    sms = config.SMS_CFG or {}
    url = (sms.get("webhook_url") or "").strip()
    if not url:
        logger.warning("[短信] 未配置 security.sms.webhook_url，验证码未发送（to=%s）", phone)
        return False
    payload = json.dumps({
        "phone": phone, "code": code, "site": config.SITE_NAME,
        "ttl": config.SECURITY_CODE_TTL,
    }).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    token = (sms.get("token") or "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, data=payload, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=config.SECURITY_TIMEOUT_SECONDS) as resp:
            return 200 <= resp.status < 300
    except (urllib.error.URLError, OSError, ValueError) as e:
        logger.error(f"[短信] 发送失败（to={phone}）: {e}")
        return False


def _deliver(kind: str, target: str, code: str) -> bool:
    return deliver_email(target, code) if kind == "email" else deliver_sms(target, code)


# ---------- 联系人查询 ----------
def get_contacts(username: str) -> dict:
    contacts = _read(K_CONTACTS).get(username)
    if not isinstance(contacts, dict):
        return {}
    return {k: dict(v) for k, v in contacts.items() if isinstance(v, dict)}


def get_contact(username: str, kind: str) -> dict | None:
    return get_contacts(username).get(kind)


def get_verified_contact(username: str, kind: str) -> str | None:
    entry = get_contact(username, kind)
    if isinstance(entry, dict) and entry.get("verified") and entry.get("value"):
        return entry["value"]
    return None


def remove_contact(username: str, kind: str) -> bool:
    def _mutate(data):
        contacts = data.get(username)
        if not isinstance(contacts, dict) or kind not in contacts:
            return True
        contacts.pop(kind, None)
        if not contacts:
            data.pop(username, None)
        return True

    return _update(K_CONTACTS, _mutate) is not None


def find_username(kind: str, value: str) -> str | None:
    """按已**验证**的联系方式查找用户（验证码登录用）"""
    normalized = normalize(kind, value)
    if not normalized:
        return None
    for username, contacts in _read(K_CONTACTS).items():
        entry = contacts.get(kind) if isinstance(contacts, dict) else None
        if (isinstance(entry, dict) and entry.get("verified")
                and entry.get("value") == normalized):
            return username
    return None


# ---------- 验证码 ----------
def _code_key(purpose: str, kind: str, username: str) -> str:
    return f"{purpose}:{kind}:{username}"


def _hash_code(username: str, kind: str, purpose: str, code: str) -> str:
    raw = f"{username}|{kind}|{purpose}|{code}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _generate_code() -> str:
    length = config.SECURITY_CODE_LENGTH
    start = 10 ** (length - 1)
    return str(secrets.randbelow(9 * start) + start)


def issue_code(username: str, kind: str, target: str, purpose: str = "bind"):
    """生成并投递验证码。

    返回 ``None`` 表示成功；否则返回 i18n 错误键。投递失败不写库，
    并受 ``security.code_resend_cooldown_seconds`` 冷却约束。
    """
    if purpose not in PURPOSES or kind not in KINDS:
        return "err_contact_invalid"
    if not is_kind_enabled(kind):
        return "err_feature_disabled"
    target = normalize(kind, target)
    if not is_valid(kind, target):
        return "err_contact_invalid"

    key = _code_key(purpose, kind, username)
    now = time.time()
    existing = _read(K_CODES).get(key)
    if isinstance(existing, dict):
        sent_at = existing.get("sent_at")
        if isinstance(sent_at, (int, float)) and \
                now - sent_at < config.SECURITY_CODE_RESEND_COOLDOWN:
            return "err_code_cooldown"

    code = _generate_code()
    # 网络投递在存储锁之外执行
    if not _deliver(kind, target, code):
        return "err_code_send_failed"

    def _mutate(data):
        data[key] = {
            "hash": _hash_code(username, kind, purpose, code),
            "target": target,
            "expires_at": now + config.SECURITY_CODE_TTL,
            "attempts": 0,
            "sent_at": now,
        }
        return True

    if _update(K_CODES, _mutate) is None:
        return "err_settings_save_failed"
    return None


def check_code(username: str, kind: str, purpose: str, code: str) -> bool:
    """校验验证码（不消费）；失败累计尝试次数，超限即作废。"""
    if purpose not in PURPOSES or kind not in KINDS:
        return False
    code = (code or "").strip()
    if not code.isdigit():
        return False
    key = _code_key(purpose, kind, username)
    now = time.time()
    data = _read(K_CODES)
    entry = data.get(key)
    if not isinstance(entry, dict):
        return False
    if not isinstance(entry.get("expires_at"), (int, float)) or entry["expires_at"] < now:
        _drop_code(key)
        return False
    if not isinstance(entry.get("attempts"), int):
        entry["attempts"] = 0
    if entry["attempts"] >= config.SECURITY_CODE_MAX_ATTEMPTS:
        _drop_code(key)
        return False

    expected = entry.get("hash")
    candidate = _hash_code(username, kind, purpose, code)
    if isinstance(expected, str) and secrets.compare_digest(expected, candidate):
        return True

    # 失败：累加尝试次数，超限作废
    def _mutate(table):
        record = table.get(key)
        if not isinstance(record, dict):
            return False
        record["attempts"] = int(record.get("attempts", 0)) + 1
        if record["attempts"] >= config.SECURITY_CODE_MAX_ATTEMPTS:
            table.pop(key, None)
        return False

    _update(K_CODES, _mutate)
    return False


def consume_code(username: str, kind: str, purpose: str) -> None:
    """消费验证码（成功后调用，防止重放）"""
    _drop_code(_code_key(purpose, kind, username))


def _drop_code(key: str) -> None:
    def _mutate(data):
        data.pop(key, None)
        return True

    _update(K_CODES, _mutate)


def purge_expired_codes() -> int:
    """清理已过期验证码，返回清理数量（供机会式清理调用）"""
    now = time.time()
    removed = {"n": 0}

    def _mutate(data):
        doomed = [k for k, v in data.items()
                  if not isinstance(v, dict)
                  or not isinstance(v.get("expires_at"), (int, float))
                  or v["expires_at"] < now]
        for key in doomed:
            data.pop(key, None)
        removed["n"] = len(doomed)
        return True

    _update(K_CODES, _mutate)
    return removed["n"]


# ---------- 绑定流程 ----------
def request_bind_code(username: str, kind: str, value: str):
    """请求绑定验证码；成功返回 None，失败返回 i18n 错误键。"""
    return issue_code(username, kind, value, purpose="bind")


def confirm_bind_code(username: str, kind: str, code: str) -> bool:
    """校验绑定验证码；成功后把联系方式标记为已验证。"""
    if not check_code(username, kind, "bind", code):
        return False
    data = _read(K_CODES)
    entry = data.get(_code_key("bind", kind, username))
    target = entry.get("target") if isinstance(entry, dict) else None
    if not target:
        return False
    consume_code(username, kind, "bind")

    def _mutate(contacts):
        user = contacts.get(username)
        if not isinstance(user, dict):
            user = {}
            contacts[username] = user
        user[kind] = {"value": target, "verified": True, "verified_at": time.time()}
        return True

    return _update(K_CONTACTS, _mutate) is not None


# ---------- 验证码登录 ----------
def request_login_code(kind: str, value: str):
    """请求登录验证码：返回 (username, None) 或 (None, i18n 错误键)。"""
    if not is_kind_enabled(kind):
        return None, "err_feature_disabled"
    if kind == "email" and not config.SECURITY_EMAIL_LOGIN:
        return None, "err_feature_disabled"
    if kind == "phone" and not config.SECURITY_PHONE_LOGIN:
        return None, "err_feature_disabled"
    normalized = normalize(kind, value)
    if not is_valid(kind, normalized):
        return None, "err_contact_invalid"
    username = find_username(kind, normalized)
    if not username:
        # 不区分「未绑定」与「未验证」，避免暴露账号是否存在
        return None, "err_login_failed"
    err = issue_code(username, kind, normalized, purpose="login")
    if err:
        return None, err
    return username, None


def verify_login_code(username: str, kind: str, code: str) -> bool:
    """校验登录验证码；成功后消费。"""
    if not check_code(username, kind, "login", code):
        return False
    consume_code(username, kind, "login")
    return True


# ---------- 用户改名迁移 ----------
def rename_user_contacts(old: str, new: str) -> bool:
    """迁移联系人记录与未消费验证码（用户改名用）。无记录视为成功。"""
    def _mutate_contacts(data):
        if old in data:
            data[new] = data.pop(old)
        return True

    if _update(K_CONTACTS, _mutate_contacts) is None:
        return False

    def _mutate_codes(data):
        moved = {}
        old_suffix = f":{old}"
        for key, value in list(data.items()):
            if key.endswith(old_suffix):
                moved[key[:-len(old_suffix)] + f":{new}"] = value
                data.pop(key, None)
        data.update(moved)
        return True

    return _update(K_CODES, _mutate_codes) is not None


# 过期验证码由内核的后台/机会式清理调度（core.cleanup 依赖倒置，避免 core→app）
from app.core.cleanup import register_cleanup  # noqa: E402

register_cleanup(purge_expired_codes)
