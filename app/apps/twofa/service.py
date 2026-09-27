"""双因素认证（TOTP）业务逻辑

算法实现见共享内核 ``app/core/totp.py``（纯标准库 RFC 6238）；本模块负责
状态存储、启用/停用流程与登录二次校验。

数据存 KV 键 ``two_factor``（file 后端即 ``two_factor.json``）::

    {username: {
        "secret": <Base32>,
        "enabled": bool,
        "recovery": [<sha256(恢复码)>, ...],
        "created_at": ts,
        "confirmed_at": ts,
        "last_step": int,           # 防重放：最近一次成功校验的时间步
    }}

写路径遵循项目约定：``threading.Lock``（进程内）→ ``storage.lock``（跨实例），
锁内重读合并后整值写回，锁外不持久化（见 store.py / pins.py）。
"""
import threading
import time

from app.core import totp
from app.core.feature_flags import feature_enabled
from app.core.logger import create_logger
from app.core.storage import StorageError, storage

logger = create_logger("twofa")

# 键名（与存储后端 KV 布局对应；file 后端映射 two_factor.json）
K_TWO_FACTOR = "two_factor"

_lock = threading.Lock()


def _read() -> dict:
    try:
        data = storage.get(K_TWO_FACTOR)
    except StorageError as e:
        logger.error(f"[错误] 读取双因素认证数据失败: {e}")
        return {}
    return data if isinstance(data, dict) else {}


def _update(mutate):
    """跨实例安全的读改写：线程锁 → 存储锁 → 重读 → mutate → 落盘。"""
    try:
        with _lock:
            with storage.lock(K_TWO_FACTOR):
                data = _read()
                result = mutate(data)
                if not storage.set(K_TWO_FACTOR, data):
                    logger.error("[错误] 写入双因素认证数据失败")
                    return None
                return result
    except StorageError as e:
        logger.error(f"[错误] 更新双因素认证数据失败: {e}")
        return None


# ---------- 查询 ----------
def get_record(username: str) -> dict | None:
    """返回用户的双因素记录拷贝（无记录返回 None）"""
    if not username:
        return None
    record = _read().get(username)
    return dict(record) if isinstance(record, dict) else None


def is_enabled(username: str) -> bool:
    record = get_record(username)
    return bool(record and record.get("enabled"))


def is_required(username: str) -> bool:
    """登录时是否需要第二因素：功能开关启用且用户已开启 TOTP。"""
    return feature_enabled("two_factor_auth") and is_enabled(username)


def count_recovery_codes(username: str) -> int:
    record = get_record(username)
    if not isinstance(record, dict):
        return 0
    codes = record.get("recovery")
    return len(codes) if isinstance(codes, list) else 0


# ---------- 启用 / 停用 ----------
def start_setup(username: str):
    """开始绑定：生成待确认密钥并返回 (secret, otpauth 链接)。

    此时尚未启用（``enabled=False``），必须调用 :func:`confirm_setup` 用一次
    动态码确认，避免用户扫错/未保存密钥就被锁在账号外。
    """
    secret = totp.generate_secret()
    uri = totp.provisioning_uri(secret, username)

    def _mutate(data):
        record = data.get(username)
        base = {k: v for k, v in record.items() if k != "secret"} if isinstance(record, dict) else {}
        base.update({
            "secret": secret,
            "enabled": False,
            "recovery": base.get("recovery", []),
            "created_at": time.time(),
            "confirmed_at": None,
            "last_step": 0,
        })
        data[username] = base
        return True

    if not _update(_mutate):
        return None, None
    return secret, uri


def confirm_setup(username: str, code: str) -> list[str] | None:
    """确认绑定：校验动态码后启用并一次性返回恢复码明文。

    返回 None 表示失败（无待确认记录 / 动态码错误）；恢复码只在此返回明文，
    存储层只有哈希。
    """
    record = get_record(username)
    secret = record.get("secret") if isinstance(record, dict) else None
    if not secret or record.get("enabled"):
        return None
    step = totp.match_step(secret, code)
    if step is None:
        return None

    plain = totp.generate_recovery_codes()
    hashes = [totp.hash_recovery_code(c) for c in plain]

    def _mutate(data):
        record = data.get(username)
        if not isinstance(record, dict):
            return False
        record["enabled"] = True
        record["recovery"] = hashes
        record["confirmed_at"] = time.time()
        record["last_step"] = step
        return True

    if not _update(_mutate):
        return None
    return plain


def disable(username: str) -> bool:
    """停用并删除全部双因素数据（含恢复码）。"""
    def _mutate(data):
        return data.pop(username, None) is not None

    return bool(_update(_mutate))


def regenerate_recovery_codes(username: str, code: str) -> list[str] | None:
    """校验当前动态码后重新生成恢复码，返回新明文列表。"""
    record = get_record(username)
    secret = record.get("secret") if isinstance(record, dict) else None
    if not secret or not record.get("enabled"):
        return None
    if not _verify_totp(username, record, code):
        return None

    plain = totp.generate_recovery_codes()
    hashes = [totp.hash_recovery_code(c) for c in plain]

    def _mutate(data):
        rec = data.get(username)
        if not isinstance(rec, dict):
            return False
        rec["recovery"] = hashes
        return True

    if not _update(_mutate):
        return None
    return plain


# ---------- 校验 ----------
def _verify_totp(username: str, record: dict, code: str) -> bool:
    """TOTP 校验 + 防重放：成功且**命中的时间步**大于上次记录时更新 ``last_step``。

    注意使用实际命中的时间步而非当前时间步：否则在窗口内用「下一步」的码
    登录后，当前步的码仍可能被判定为旧步骤而误拒，或造成重放绕过的边界问题。
    """
    secret = record.get("secret")
    if not secret:
        return False
    step = totp.match_step(secret, code)
    if step is None:
        return False
    last = record.get("last_step") or 0
    if step <= last:
        return False

    def _mutate(data):
        rec = data.get(username)
        if not isinstance(rec, dict):
            return False
        rec["last_step"] = step
        return True

    _update(_mutate)
    return True


def _consume_recovery_code(username: str, code: str) -> bool:
    """一次性恢复码校验，命中后从存储中移除该哈希。"""
    digest = totp.hash_recovery_code(code)
    if not digest:
        return False
    matched = {"hit": False}

    def _mutate(data):
        rec = data.get(username)
        if not isinstance(rec, dict):
            return False
        codes = rec.get("recovery")
        if not isinstance(codes, list) or digest not in codes:
            return False
        codes.remove(digest)
        rec["recovery"] = codes
        matched["hit"] = True
        return True

    _update(_mutate)
    return matched["hit"]


def verify(username: str, code: str) -> bool:
    """登录二次校验：先按动态码，再按一次性恢复码。"""
    record = get_record(username)
    if not isinstance(record, dict) or not record.get("enabled"):
        return False
    if _verify_totp(username, record, code):
        return True
    return _consume_recovery_code(username, code)


# ---------- 用户改名迁移 ----------
def rename_user_two_factor(old: str, new: str) -> bool:
    """把 old 的双因素记录迁移到 new（用户改名用）。无记录视为成功。"""
    def _mutate(data):
        if old not in data:
            return True
        data[new] = data.pop(old)
        return True

    return _update(_mutate) is not None
