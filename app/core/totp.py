"""TOTP 双因素认证（RFC 6238）与恢复码：纯标准库实现

不引入 pyotp / qrcode 等第三方依赖，仅用 ``base64``/``hashlib``/``hmac``/
``struct``/``secrets``/``urllib`` 实现，保持与项目「最小依赖」约定一致
（图床魔数嗅探、Upstash 纯 urllib 都是同一思路）。

- :func:`generate_secret` 生成 Base32 密钥（默认 20 字节 = 160 bit，SHA-1 推荐长度）；
- :func:`generate_code` / :func:`verify_code` 按时间步派生 6 位动态码，
  校验时允许前后各 ``DEFAULT_WINDOW`` 个时间步以容忍时钟漂移，并使用常量
  时间比较；
- :func:`provisioning_uri` 生成 otpauth:// 链接，前端用 QR 服务渲染即可
  （不强制依赖本地二维码库）；
- :func:`generate_recovery_codes` / :func:`hash_recovery_code` 负责一次性
  恢复码的生成与哈希（存储层只保存哈希，明文仅展示一次）。
"""
import base64
import hashlib
import hmac
import secrets
import struct
import time
import urllib.parse

# RFC 6238 默认参数：SHA-1、6 位数字、30 秒时间步
DEFAULT_DIGITS = 6
DEFAULT_INTERVAL = 30
# 校验时允许前后各 1 个时间步（共 3 个窗口），容忍客户端时钟漂移
DEFAULT_WINDOW = 1
# 恢复码数量与长度
RECOVERY_CODE_COUNT = 8
_SECRET_BYTES = 20


def generate_secret(length: int = _SECRET_BYTES) -> str:
    """生成 Base32 编码的随机密钥（去掉 ``=`` 填充，便于用户手动录入）"""
    return base64.b32encode(secrets.token_bytes(length)).decode("ascii").rstrip("=")


def _normalize_secret(secret: str) -> bytes:
    """把用户/存储中的 Base32 密钥还原为字节；非法密钥抛 ValueError"""
    if not isinstance(secret, str) or not secret.strip():
        raise ValueError("empty secret")
    raw = secret.strip().replace(" ", "").upper()
    pad = "=" * ((8 - len(raw) % 8) % 8)
    return base64.b32decode(raw + pad, casefold=True)


def _hotp(key: bytes, counter: int, digits: int) -> str:
    """RFC 4226 HOTP：HMAC-SHA1 后动态截断为 digits 位十进制码"""
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    truncated = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(truncated % (10 ** digits)).zfill(digits)


def generate_code(secret: str, at: float | None = None,
                  digits: int = DEFAULT_DIGITS,
                  interval: int = DEFAULT_INTERVAL) -> str:
    """派生当前时间步的 TOTP 动态码（主要用于测试与调试）"""
    counter = int((time.time() if at is None else at) // interval)
    return _hotp(_normalize_secret(secret), counter, digits)


def match_step(secret: str, code: str, at: float | None = None,
               window: int = DEFAULT_WINDOW,
               digits: int = DEFAULT_DIGITS,
               interval: int = DEFAULT_INTERVAL) -> int | None:
    """校验 TOTP 动态码，返回命中的时间步编号；未命中返回 None。

    非法密钥、非数字码、长度不符一律返回 None；使用 ``hmac.compare_digest``
    做常量时间比较，避免时序侧信道。返回的步骤可用于「防重放」记录（比
    :func:`verify_code` 只返回布尔值更精确）。
    """
    if not secret or code is None:
        return None
    candidate = str(code).strip()
    if not candidate.isdigit() or len(candidate) != digits:
        return None
    try:
        key = _normalize_secret(secret)
    except (ValueError, TypeError):
        return None
    now = time.time() if at is None else at
    current = int(now // interval)
    for offset in range(-window, window + 1):
        step = current + offset
        if hmac.compare_digest(_hotp(key, step, digits), candidate):
            return step
    return None


def verify_code(secret: str, code: str, at: float | None = None,
                window: int = DEFAULT_WINDOW,
                digits: int = DEFAULT_DIGITS,
                interval: int = DEFAULT_INTERVAL) -> bool:
    """校验 TOTP 动态码（命中任一容忍窗口即通过）"""
    return match_step(secret, code, at=at, window=window,
                      digits=digits, interval=interval) is not None


def provisioning_uri(secret: str, username: str,
                     issuer: str = "Rusin-Note",
                     digits: int = DEFAULT_DIGITS,
                     interval: int = DEFAULT_INTERVAL) -> str:
    """生成 otpauth:// 链接，供认证器 App 扫码或手动录入。"""
    label = urllib.parse.quote(f"{issuer}:{username}", safe="")
    params = urllib.parse.urlencode({
        "secret": secret,
        "issuer": issuer,
        "algorithm": "SHA1",
        "digits": digits,
        "period": interval,
    })
    return f"otpauth://totp/{label}?{params}"


def generate_recovery_codes(count: int = RECOVERY_CODE_COUNT) -> list[str]:
    """生成一次性恢复码明文列表（形如 ``A1B2C3D4E5``，大写十六进制）"""
    return [secrets.token_hex(5).upper() for _ in range(count)]


def normalize_recovery_code(code: str) -> str:
    """规范化用户输入的恢复码（去空格/连字符、转大写）"""
    return str(code or "").strip().replace(" ", "").replace("-", "").upper()


def hash_recovery_code(code: str) -> str:
    """恢复码哈希（存储层只保存哈希，明文仅在生成时展示一次）"""
    return hashlib.sha256(normalize_recovery_code(code).encode("utf-8")).hexdigest()
