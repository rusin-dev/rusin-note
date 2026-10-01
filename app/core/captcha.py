"""图形验证码：纯标准库生成 SVG（无图像库依赖），答案存 storage KV。

流程：视图调用 ``generate()`` 得到 (token, code)，用 ``render_svg(code)`` 内联渲染
到登录页；表单提交携带 ``captcha_token`` + ``captcha``，``verify()`` 大小写不敏感
比对并删除该条目（一次性，防重放）。全部待验证条目存单一集合键
``login_captchas``（与 verification_codes 同模式），每次写入时机会式清理过期项，
TTL 默认 10 分钟；token 来自用户表单，读取前强制十六进制格式校验。
"""
import re
import secrets
import threading
import time

from app.core.storage import StorageError, storage

K_CAPTCHAS = "login_captchas"
CODE_LENGTH = 4
TTL_SECONDS = 600
_TOKEN_RE = re.compile(r"^[0-9a-f]{16,64}$")
# 去混淆字符集（排除 O/0、I/1/l 等易混字符）
_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
_COLORS = ("#0e8a6d", "#2fae8b", "#1a7f37", "#353740", "#546271")

_lock = threading.Lock()


def _valid_token(token: str) -> bool:
    return bool(_TOKEN_RE.match(token or ""))


def _load() -> dict:
    try:
        data = storage.get(K_CAPTCHAS)
    except StorageError:
        return {}
    return data if isinstance(data, dict) else {}


def generate(ttl: float = TTL_SECONDS) -> tuple[str, str]:
    """签发一次性验证码；ttl 传负数得到已过期条目（测试用）。"""
    token = secrets.token_hex(16)
    code = "".join(secrets.choice(_ALPHABET) for _ in range(CODE_LENGTH))
    now = time.time()
    with _lock:
        try:
            with storage.lock(K_CAPTCHAS):
                data = {k: v for k, v in _load().items()
                        if isinstance(v, dict) and v.get("exp", 0) > now}
                data[token] = {"c": code.lower(), "exp": now + ttl}
                storage.set(K_CAPTCHAS, data)
        except StorageError:
            pass
    return token, code


def verify(token: str, code: str) -> bool:
    """校验并销毁条目（无论成败，防重放）；大小写不敏感。"""
    if not _valid_token(token):
        return False
    with _lock:
        try:
            with storage.lock(K_CAPTCHAS):
                data = _load()
                entry = data.pop(token, None)
                now = time.time()
                data = {k: v for k, v in data.items()
                        if isinstance(v, dict) and v.get("exp", 0) > now}
                storage.set(K_CAPTCHAS, data)
        except StorageError:
            return False
    if not isinstance(entry, dict) or not (code or "").strip():
        return False
    if entry.get("exp", 0) < time.time():
        return False
    return str(entry.get("c", "")) == code.strip().lower()


def peek(token: str) -> str:
    """读取验证码答案（端到端测试辅助；条目本身短时效且一次性）。"""
    if not _valid_token(token):
        return ""
    entry = _load().get(token)
    if isinstance(entry, dict) and entry.get("exp", 0) > time.time():
        return str(entry.get("c", ""))
    return ""


def render_svg(code: str) -> str:
    """把验证码字符渲染为带旋转/噪点/干扰线的 SVG 标记（可直接内联到页面）。"""
    width, height = 132, 44
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-hidden="true">',
        f'<rect width="{width}" height="{height}" rx="8" fill="#eef2f0"/>',
    ]
    for _ in range(3):
        x1, y1 = secrets.randbelow(width), secrets.randbelow(height)
        x2, y2 = secrets.randbelow(width), secrets.randbelow(height)
        cx, cy = secrets.randbelow(width), secrets.randbelow(height)
        stroke = secrets.choice(_COLORS)
        parts.append(
            f'<path d="M{x1} {y1} Q{cx} {cy} {x2} {y2}" fill="none" '
            f'stroke="{stroke}" stroke-opacity="0.35" stroke-width="1.4"/>')
    for _ in range(24):
        cx, cy = secrets.randbelow(width), secrets.randbelow(height)
        fill = secrets.choice(_COLORS)
        parts.append(f'<circle cx="{cx}" cy="{cy}" r="1" fill="{fill}" fill-opacity="0.3"/>')
    step = (width - 26) / max(len(code), 1)
    for i, ch in enumerate(code):
        x = 15 + i * step + secrets.randbelow(7) - 3
        y = 29 + secrets.randbelow(9) - 4
        rot = secrets.randbelow(50) - 25
        size = 21 + secrets.randbelow(5)
        fill = secrets.choice(_COLORS)
        parts.append(
            f'<text x="{x:.1f}" y="{y:.1f}" font-family="Verdana,Arial,sans-serif" '
            f'font-size="{size}" font-weight="bold" fill="{fill}" '
            f'transform="rotate({rot} {x:.1f} {y:.1f})">{ch}</text>')
    parts.append("</svg>")
    return "".join(parts)
