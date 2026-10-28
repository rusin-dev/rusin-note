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
CODE_LENGTH = 6
TTL_SECONDS = 600
_TOKEN_RE = re.compile(r"^[0-9a-f]{16,64}$")
# 去混淆字符集（排除 O/0、I/1/l 等易混字符）
_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
_COLORS = ("#0e8a6d", "#2fae8b", "#1a7f37", "#353740", "#546271")
_GLYPHS = {
    "A": (((0, 16), (5, 0), (10, 16)), ((2, 10), (8, 10))),
    "B": (((0, 0), (0, 16)), ((0, 0), (6, 0), (10, 4), (6, 8), (0, 8)),
          ((6, 8), (10, 12), (6, 16), (0, 16))),
    "C": (((10, 2), (7, 0), (3, 0), (0, 4), (0, 12), (3, 16), (7, 16), (10, 14)),),
    "D": (((0, 0), (0, 16)), ((0, 0), (5, 0), (10, 5), (10, 11), (5, 16), (0, 16))),
    "E": (((10, 0), (0, 0), (0, 16), (10, 16)), ((0, 8), (8, 8))),
    "F": (((0, 16), (0, 0), (10, 0)), ((0, 8), (8, 8))),
    "G": (((10, 2), (7, 0), (3, 0), (0, 4), (0, 12), (3, 16), (7, 16),
           (10, 12), (10, 9), (6, 9)),),
    "H": (((0, 0), (0, 16)), ((10, 0), (10, 16)), ((0, 8), (10, 8))),
    "J": (((10, 0), (10, 12), (7, 16), (3, 16), (0, 13)),),
    "K": (((0, 0), (0, 16)), ((10, 0), (0, 9), (10, 16))),
    "M": (((0, 16), (0, 0), (5, 8), (10, 0), (10, 16)),),
    "N": (((0, 16), (0, 0), (10, 16), (10, 0)),),
    "P": (((0, 16), (0, 0), (6, 0), (10, 4), (6, 8), (0, 8)),),
    "Q": (((5, 0), (1, 3), (0, 8), (1, 13), (5, 16), (9, 13), (10, 8), (9, 3), (5, 0)),
          ((6, 12), (11, 17))),
    "R": (((0, 16), (0, 0), (6, 0), (10, 4), (6, 8), (0, 8)), ((5, 8), (10, 16))),
    "S": (((10, 2), (7, 0), (3, 0), (0, 4), (1, 7), (8, 9), (10, 12),
           (7, 16), (3, 16), (0, 14)),),
    "T": (((0, 0), (10, 0)), ((5, 0), (5, 16))),
    "U": (((0, 0), (0, 12), (3, 16), (7, 16), (10, 12), (10, 0)),),
    "V": (((0, 0), (5, 16), (10, 0)),),
    "W": (((0, 0), (2, 16), (5, 9), (8, 16), (10, 0)),),
    "X": (((0, 0), (10, 16)), ((10, 0), (0, 16))),
    "Y": (((0, 0), (5, 8), (10, 0)), ((5, 8), (5, 16))),
    "Z": (((0, 0), (10, 0), (0, 16), (10, 16)),),
    "2": (((0, 4), (3, 0), (7, 0), (10, 4), (9, 8), (0, 16), (10, 16)),),
    "3": (((0, 2), (3, 0), (7, 0), (10, 4), (7, 8), (3, 8)),
          ((7, 8), (10, 12), (7, 16), (3, 16), (0, 14))),
    "4": (((8, 16), (8, 0), (0, 11), (10, 11)),),
    "5": (((10, 0), (1, 0), (0, 8), (6, 7), (10, 10), (8, 15), (3, 16), (0, 14)),),
    "6": (((9, 1), (5, 0), (1, 4), (0, 11), (3, 16), (7, 16),
           (10, 12), (8, 8), (3, 8), (0, 11)),),
    "7": (((0, 0), (10, 0), (3, 16)),),
    "8": (((5, 0), (1, 2), (1, 6), (5, 8), (9, 6), (9, 2), (5, 0)),
          ((5, 8), (0, 11), (1, 15), (5, 16), (9, 15), (10, 11), (5, 8))),
    "9": (((10, 8), (7, 8), (2, 7), (0, 4), (3, 0), (7, 0),
           (10, 4), (9, 12), (5, 16), (1, 15)),),
}

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


def _jitter(amount: float) -> float:
    return (secrets.randbelow(2001) - 1000) * amount / 1000


def _stroke_path(points) -> str:
    commands = [f"M{points[0][0]} {points[0][1]}"]
    for start, end in zip(points, points[1:]):
        cx = (start[0] + end[0]) / 2 + _jitter(1.2)
        cy = (start[1] + end[1]) / 2 + _jitter(1.2)
        commands.append(f"Q{cx:.2f} {cy:.2f} {end[0]} {end[1]}")
    return " ".join(commands)


def render_svg(code: str) -> str:
    """把验证码字符渲染为随机变形的矢量路径，避免 SVG 文本节点泄露答案。"""
    width, height = 168, 48
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-hidden="true">',
        f'<rect width="{width}" height="{height}" rx="8" fill="#eef2f0"/>',
    ]
    for _ in range(5):
        x1, y1 = secrets.randbelow(width), secrets.randbelow(height)
        x2, y2 = secrets.randbelow(width), secrets.randbelow(height)
        cx, cy = secrets.randbelow(width), secrets.randbelow(height)
        parts.append(
            f'<path d="M{x1} {y1} Q{cx} {cy} {x2} {y2}" fill="none" '
            f'stroke="{secrets.choice(_COLORS)}" stroke-opacity="0.28" stroke-width="1.2"/>')
    for _ in range(42):
        cx, cy = secrets.randbelow(width), secrets.randbelow(height)
        radius = 6 + secrets.randbelow(9)
        parts.append(
            f'<circle cx="{cx}" cy="{cy}" r="{radius / 10:.1f}" '
            f'fill="{secrets.choice(_COLORS)}" fill-opacity="0.28"/>')
    step = (width - 20) / max(len(code), 1)
    for i, ch in enumerate(code):
        x = 10 + (i + 0.5) * step + _jitter(1.5)
        y = height / 2 + _jitter(2.5)
        rotation = secrets.randbelow(45) - 22
        skew = secrets.randbelow(29) - 14
        scale_x = (95 + secrets.randbelow(31)) / 100
        scale_y = (115 + secrets.randbelow(26)) / 100
        stroke_width = (15 + secrets.randbelow(6)) / 10
        parts.append(
            f'<g transform="translate({x:.2f} {y:.2f}) rotate({rotation}) skewX({skew}) '
            f'scale({scale_x:.2f} {scale_y:.2f}) translate(-5 -8)" fill="none" '
            f'stroke="{secrets.choice(_COLORS)}" stroke-width="{stroke_width:.1f}" '
            'stroke-linecap="round" stroke-linejoin="round">')
        for stroke in _GLYPHS[ch]:
            parts.append(f'<path d="{_stroke_path(stroke)}"/>')
        parts.append("</g>")
    for _ in range(2):
        x1, y1 = secrets.randbelow(width), secrets.randbelow(height)
        x2, y2 = secrets.randbelow(width), secrets.randbelow(height)
        cx, cy = secrets.randbelow(width), secrets.randbelow(height)
        parts.append(
            f'<path d="M{x1} {y1} Q{cx} {cy} {x2} {y2}" fill="none" '
            f'stroke="{secrets.choice(_COLORS)}" stroke-opacity="0.2" stroke-width="1"/>')
    parts.append("</svg>")
    return "".join(parts)
