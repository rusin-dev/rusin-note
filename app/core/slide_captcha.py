"""滑动拼图验证码：纯标准库栅格化 PNG（无图像库依赖），行为轨迹校验 + 随机阻尼。

设计要点
--------
- 服务端生成背景 PNG（含缺口）与拼图块 PNG（背景在缺口处的裁剪）。缺口横坐标
  ``target`` 与阻尼曲线随一次性 token 存 KV ``slide_captchas``（TTL 默认 5 分钟，
  与图形验证码同模式：写入时机会式清理过期项，verify 即销毁防重放）。
- **缺口不进入 DOM**：背景与拼图块都在服务端栅格化后以 data URI 下发，客户端
  拿不到 ``target`` 或可反解的精确画布坐标，只能靠像素匹配猜位置。
- **随机阻尼**：滑块位移 d → 拼图位移 piece_x 经一条随机单调曲线映射，局部斜率
  时大时小（"移动 10px 拼图走 20px"或"走 8px"的过滑/阻滞手感）。曲线终点归一到
  travel_max，故 curve(S)=travel_max ≥ target，保证滑块到底之前拼图必能送到缺口。
  服务端按曲线反算最终拼图位置再比对 target——naive bot 直接拖 d=target 会因
  curve(target)≠target 而落空。
- **行为轨迹**：客户端采集拖动采样 {x,y,t}，服务端分析时长/采样数/速度方差/是否
  瞬移等给出 suspicion 分（0..100，越高越像机器）。**位置对齐即通过**（即使轨迹
  像机器也静默放行，避免打草惊蛇），suspicion 交由 captcha_risk 累计 IP 风险分，
  风险越高验证越严（容差收紧 + 要求类人轨迹）。轨迹中的非有限数值（NaN/Inf）
  一律丢弃，避免评分被污染成 0。

所有随机性来自 secrets。
"""
from __future__ import annotations

import base64
import math
import re
import secrets
import struct
import threading
import time
import zlib

from app.core import config
from app.core.storage import StorageError, storage

K_SLIDE = "slide_captchas"
_TOKEN_RE = re.compile(r"^[0-9a-f]{16,64}$")
_lock = threading.Lock()


# ---------- 配置读取（带兜底，非法值回退默认） ----------

def _cfg(key: str, default):
    val = config.CAPTCHA_SLIDE.get(key, default)
    return val if val is not None else default


def _int_cfg(key: str, default: int, minimum: int = 1) -> int:
    try:
        return max(minimum, int(_cfg(key, default)))
    except (TypeError, ValueError):
        return default


def _float_cfg(key: str, default: float) -> float:
    try:
        return float(_cfg(key, default))
    except (TypeError, ValueError):
        return default


def _rand_float(low: float, high: float) -> float:
    if high <= low:
        return low
    return low + (high - low) * secrets.randbelow(10001) / 10000.0


def _valid_token(token: str) -> bool:
    return bool(_TOKEN_RE.match(token or ""))


def _load() -> dict:
    try:
        data = storage.get(K_SLIDE)
    except StorageError:
        return {}
    return data if isinstance(data, dict) else {}


# ---------- 几何与阻尼曲线 ----------

def make_curve(slider_width: float, travel_max: float,
               damping_min: float, damping_max: float) -> list:
    """生成随机单调阻尼曲线：控制点 [[d, piece_x], ...]，端点 (0,0)→(S,travel_max)。

    各段局部斜率在 [damping_min, damping_max] 随机，再整体归一使终点恰为
    travel_max——既保留"时而过滑时而阻滞"的手感，又保证滑块到底拼图必达最远端。
    """
    segs = 4 + secrets.randbelow(3)  # 4..6 段
    fracs = sorted(_rand_float(0.05, 0.95) for _ in range(segs - 1))
    ds = [0.0]
    for f in fracs:
        d = round(f * slider_width, 2)
        if d > ds[-1] + 1:
            ds.append(d)
    ds.append(float(slider_width))
    slopes = [_rand_float(damping_min, damping_max) for _ in range(len(ds) - 1)]
    raw = [slopes[i] * (ds[i + 1] - ds[i]) for i in range(len(ds) - 1)]
    total = sum(raw) or 1.0
    scale = travel_max / total
    points = [[0.0, 0.0]]
    acc = 0.0
    for i in range(len(ds) - 1):
        acc += raw[i] * scale
        points.append([ds[i + 1], round(acc, 3)])
    points[-1][1] = float(travel_max)
    return points


def curve_value(points: list, d: float) -> float:
    """按控制点线性插值：滑块位移 d → 拼图位移 piece_x（d 钳制到 [0, S]）。"""
    if not points:
        return 0.0
    if d <= points[0][0]:
        return float(points[0][1])
    if d >= points[-1][0]:
        return float(points[-1][1])
    for (d0, p0), (d1, p1) in zip(points, points[1:]):
        if d0 <= d <= d1:
            span = (d1 - d0) or 1.0
            return float(p0 + (p1 - p0) * (d - d0) / span)
    return float(points[-1][1])


# ---------- SVG 生成 ----------

_PALETTE = [
    ("#0e8a6d", "#2fae8b"), ("#1a7f37", "#57ab5a"), ("#2b6cb0", "#63b3ed"),
    ("#6b46c1", "#b794f4"), ("#b7791f", "#f6e05e"), ("#c05621", "#f6ad55"),
    ("#2c7a7b", "#81e6d9"), ("#97266d", "#fbb6ce"),
]


def _scene(width: int, height: int) -> tuple:
    """生成随机场景：返回 (色1, 色2, 渐变角度, 圆列表, 线列表)。

    背景与拼图块共用同一组场景数据，各自按区域栅格化；缺口坐标只落在像素中，
    客户端载荷不再包含可解析的画布坐标。
    """
    c1, c2 = secrets.choice(_PALETTE)
    angle = secrets.randbelow(360)
    circles = []
    for _ in range(7 + secrets.randbelow(5)):
        circles.append((
            secrets.randbelow(width), secrets.randbelow(height),
            8 + secrets.randbelow(34),
            "#ffffff" if secrets.randbelow(2) else "#000000",
            _rand_float(0.06, 0.22),
        ))
    lines = []
    for _ in range(3):
        lines.append((
            secrets.randbelow(width), secrets.randbelow(height),
            secrets.randbelow(width), secrets.randbelow(height),
            2 + secrets.randbelow(4),
        ))
    return c1, c2, angle, circles, lines


def _rgb(hex_color: str) -> tuple[int, int, int]:
    return (int(hex_color[1:3], 16), int(hex_color[3:5], 16),
            int(hex_color[5:7], 16))


def _blend(buf: bytearray, idx: int, r: int, g: int, b: int, alpha: float) -> None:
    inv = 1.0 - alpha
    buf[idx] = int(buf[idx] * inv + r * alpha)
    buf[idx + 1] = int(buf[idx + 1] * inv + g * alpha)
    buf[idx + 2] = int(buf[idx + 2] * inv + b * alpha)


def _scene_rgb(scene_w: int, scene_h: int, ox: float, oy: float,
               out_w: int, out_h: int, c1: str, c2: str, angle: int,
               circles: list, lines: list) -> bytearray:
    """把场景的 [ox, ox+out_w) × [oy, oy+out_h) 区域栅格化为 RGB 缓冲区。"""
    r1, g1, b1 = _rgb(c1)
    r2, g2, b2 = _rgb(c2)
    rad = math.radians(angle)
    dx, dy = math.cos(rad), math.sin(rad)
    buf = bytearray(out_w * out_h * 3)
    for y in range(out_h):
        gy = (oy + y + 0.5) / scene_h - 0.5
        row = y * out_w * 3
        for x in range(out_w):
            gx = (ox + x + 0.5) / scene_w - 0.5
            t = 0.5 + gx * dx + gy * dy
            t = 0.0 if t < 0 else (1.0 if t > 1 else t)
            i = row + x * 3
            buf[i] = int(r1 + (r2 - r1) * t)
            buf[i + 1] = int(g1 + (g2 - g1) * t)
            buf[i + 2] = int(b1 + (b2 - b1) * t)
    for cx, cy, radius, fill, opacity in circles:
        cr, cg, cb = (255, 255, 255) if fill == "#ffffff" else (0, 0, 0)
        x0 = max(0, int(cx - radius - ox) - 1)
        x1 = min(out_w, int(cx + radius - ox) + 2)
        y0 = max(0, int(cy - radius - oy) - 1)
        y1 = min(out_h, int(cy + radius - oy) + 2)
        r2sq = radius * radius
        for yy in range(y0, y1):
            py = oy + yy + 0.5
            dy2 = (py - cy) ** 2
            row = yy * out_w * 3
            for xx in range(x0, x1):
                px = ox + xx + 0.5
                if (px - cx) ** 2 + dy2 <= r2sq:
                    _blend(buf, row + xx * 3, cr, cg, cb, opacity)
    for x1, y1, x2, y2, width in lines:
        lx, ly = x2 - x1, y2 - y1
        seg_len2 = lx * lx + ly * ly
        half = width / 2.0
        bx0 = max(0, int(min(x1, x2) - ox - half) - 1)
        bx1 = min(out_w, int(max(x1, x2) - ox + half) + 2)
        by0 = max(0, int(min(y1, y2) - oy - half) - 1)
        by1 = min(out_h, int(max(y1, y2) - oy + half) + 2)
        for yy in range(by0, by1):
            py = oy + yy + 0.5
            row = yy * out_w * 3
            for xx in range(bx0, bx1):
                px = ox + xx + 0.5
                if seg_len2 <= 0:
                    dist2 = (px - x1) ** 2 + (py - y1) ** 2
                else:
                    t = ((px - x1) * lx + (py - y1) * ly) / seg_len2
                    t = 0.0 if t < 0 else (1.0 if t > 1 else t)
                    qx, qy = x1 + t * lx, y1 + t * ly
                    dist2 = (px - qx) ** 2 + (py - qy) ** 2
                if dist2 <= half * half:
                    _blend(buf, row + xx * 3, 255, 255, 255, 0.12)
    return buf


def _piece_inside(lx: float, ly: float, pw: float, ph: float, kr: float) -> bool:
    """拼图块本地坐标是否在形状内：方形主体 + 顶部半圆凸榫。"""
    if 0.0 <= lx <= pw and kr <= ly <= ph:
        return True
    if ly <= kr:
        cx = pw / 2.0
        return (lx - cx) ** 2 + (ly - kr) ** 2 <= kr * kr
    return False


def _piece_border(lx: float, ly: float, pw: float, ph: float, kr: float) -> bool:
    for dx, dy in ((-1.2, 0.0), (1.2, 0.0), (0.0, -1.2), (0.0, 1.2)):
        if not _piece_inside(lx + dx, ly + dy, pw, ph, kr):
            return True
    return False


def _png(width: int, height: int, data: bytearray, channels: int) -> bytes:
    """最小 PNG 编码（RGB / RGBA，8 位，无滤波）。"""
    stride = width * channels
    raw = bytearray()
    for y in range(height):
        raw.append(0)
        raw.extend(data[y * stride:(y + 1) * stride])

    def chunk(tag: bytes, payload: bytes) -> bytes:
        return (struct.pack(">I", len(payload)) + tag + payload +
                struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF))

    color_type = 6 if channels == 4 else 2
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, color_type, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(bytes(raw), 6))
        + chunk(b"IEND", b"")
    )


def _data_uri(png: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(png).decode("ascii")


def _render(target: float, body_top: float, geom: dict) -> dict:
    """栅格化背景/拼图块并返回客户端字段。

    背景与拼图块均为服务端渲染的 PNG，缺口坐标只存在于像素中，客户端
    载荷不再包含 ``target`` 或可反解的精确画布坐标。
    """
    W, H = geom["W"], geom["H"]
    pw, ph, kr = geom["pw"], geom["ph"], geom["kr"]
    c1, c2, angle, circles, lines = _scene(W, H)
    piece_top = body_top - kr

    bg = _scene_rgb(W, H, 0.0, 0.0, W, H, c1, c2, angle, circles, lines)
    hx0 = max(0, int(math.floor(target)) - 1)
    hx1 = min(W, int(math.ceil(target + pw)) + 1)
    hy0 = max(0, int(math.floor(piece_top)) - 1)
    hy1 = min(H, int(math.ceil(piece_top + ph)) + 1)
    for yy in range(hy0, hy1):
        ly = yy + 0.5 - piece_top
        row = yy * W * 3
        for xx in range(hx0, hx1):
            lx = xx + 0.5 - target
            if not _piece_inside(lx, ly, pw, ph, kr):
                continue
            i = row + xx * 3
            if _piece_border(lx, ly, pw, ph, kr):
                _blend(bg, i, 255, 255, 255, 0.45)
            else:
                _blend(bg, i, 11, 15, 14, 0.5)

    out_w = int(math.ceil(pw))
    out_h = int(math.ceil(ph))
    rgb = _scene_rgb(W, H, target, piece_top, out_w, out_h,
                     c1, c2, angle, circles, lines)
    piece = bytearray(out_w * out_h * 4)
    for yy in range(out_h):
        ly = yy + 0.5
        row = yy * out_w * 3
        prow = yy * out_w * 4
        for xx in range(out_w):
            lx = xx + 0.5
            if not _piece_inside(lx, ly, pw, ph, kr):
                continue
            j = prow + xx * 4
            if _piece_border(lx, ly, pw, ph, kr):
                piece[j], piece[j + 1], piece[j + 2] = 255, 255, 255
                piece[j + 3] = 191
            else:
                i = row + xx * 3
                piece[j], piece[j + 1], piece[j + 2] = rgb[i], rgb[i + 1], rgb[i + 2]
                piece[j + 3] = 255

    bg_img = (f'<img src="{_data_uri(_png(W, H, bg, 3))}" '
              f'width="{W}" height="{H}" alt="">')
    piece_img = (f'<img src="{_data_uri(_png(out_w, out_h, piece, 4))}" '
                 f'width="{out_w}" height="{out_h}" alt="">')
    return {"bg": bg_img, "piece": piece_img, "y_top": round(piece_top, 2),
            "pw": pw, "ph": ph}


# ---------- 签发 / 校验 ----------

def generate(ttl: float | None = None) -> tuple[str, dict]:
    """签发一次性滑动挑战，返回 (token, 客户端挑战字段)。

    客户端字段含 bg/piece（PNG data URI）/y_top/pw/ph/curve/S/tm；
    缺口 target 仅存服务端。ttl 传负数得到已过期条目（测试用）。
    """
    W = _int_cfg("width", 320, 120)
    H = _int_cfg("height", 160, 80)
    pw = _int_cfg("piece", 46, 24)
    if pw > W - 40:
        pw = max(24, W - 40)
    kr = round(pw * 0.22, 2)
    body_h = pw
    ph = round(body_h + kr, 2)
    travel_max = W - pw
    slider_width = travel_max
    if ttl is None:
        ttl = _int_cfg("ttl_seconds", 300, 30)
    dmin = _float_cfg("damping_min", 0.55)
    dmax = _float_cfg("damping_max", 2.2)
    if dmax <= dmin:
        dmin, dmax = 0.55, 2.2
    curve = make_curve(slider_width, travel_max, dmin, dmax)
    # 缺口横坐标：保证有意义拖动距离，且不超过最远可达（curve(S)=travel_max）
    lo = min(60.0, travel_max * 0.3)
    hi = travel_max - 12.0
    if hi <= lo:
        lo, hi = travel_max * 0.2, travel_max * 0.8
    target = round(_rand_float(lo, hi), 2)
    body_top = round(_rand_float(kr + 6, max(kr + 7, H - body_h - 6)), 2)
    geom = {"W": W, "H": H, "pw": pw, "ph": ph, "kr": kr}
    client = _render(target, body_top, geom)
    client.update({"curve": curve, "S": slider_width, "tm": travel_max,
                   "W": W, "H": H})
    token = secrets.token_hex(16)
    now = time.time()
    entry = {"t": target, "curve": curve, "S": slider_width, "tm": travel_max,
             "exp": now + ttl}
    with _lock:
        try:
            with storage.lock(K_SLIDE):
                data = {k: v for k, v in _load().items()
                        if isinstance(v, dict) and v.get("exp", 0) > now}
                data[token] = entry
                storage.set(K_SLIDE, data)
        except StorageError:
            pass
    return token, client


def _normalize_traj(traj) -> list:
    """把客户端轨迹规整为 [(x, y, t), ...]，丢弃非法采样。"""
    out = []
    if not isinstance(traj, (list, tuple)):
        return out
    for item in traj:
        try:
            if isinstance(item, dict):
                x, y, t = float(item["x"]), float(item.get("y", 0)), float(item["t"])
            elif isinstance(item, (list, tuple)) and len(item) >= 3:
                x, y, t = float(item[0]), float(item[1]), float(item[2])
            else:
                continue
        except (KeyError, TypeError, ValueError):
            continue
        if not all(math.isfinite(v) for v in (x, y, t)):
            continue
        out.append((x, y, t))
    return out


def behavior_suspicion(traj, min_samples: int | None = None,
                       min_drag_ms: float | None = None,
                       max_drag_ms: float | None = None) -> float:
    """行为轨迹可疑度评分（0..100，越高越像机器）。

    信号：采样过少 / 时长过短(瞬移)或过长 / 单步跨越过大( teleport ) /
    速度过于均匀 / 完全水平无抖动 / 末段不减速。各信号加权累加，封顶 100。
    """
    if min_samples is None:
        min_samples = _int_cfg("min_samples", 8, 3)
    if min_drag_ms is None:
        min_drag_ms = _float_cfg("min_drag_ms", 250)
    if max_drag_ms is None:
        max_drag_ms = _float_cfg("max_drag_ms", 20000)
    pts = _normalize_traj(traj)
    n = len(pts)
    score = 0.0
    if n < min_samples:
        score += 32
    if n < 2:
        return min(100.0, score + 40)
    pts.sort(key=lambda p: p[2])
    duration = pts[-1][2] - pts[0][2]
    if duration < min_drag_ms:
        score += 30
    elif duration > max_drag_ms:
        score += 14
    xs = [p[0] for p in pts]
    total_dx = xs[-1] - xs[0]
    steps = [xs[i + 1] - xs[i] for i in range(n - 1)]
    max_step = max(steps) if steps else 0.0
    if total_dx > 1 and max_step > 0.6 * total_dx:
        score += 30  # 瞬移：一步跨越大半距离
    speeds = []
    for i in range(n - 1):
        dt = pts[i + 1][2] - pts[i][2]
        if dt > 0:
            speeds.append(abs(steps[i]) / dt)
    if len(speeds) >= 3:
        mean = sum(speeds) / len(speeds)
        if mean > 0:
            var = sum((s - mean) ** 2 for s in speeds) / len(speeds)
            cv = (var ** 0.5) / mean
            if cv < 0.15:
                score += 20  # 速度过于均匀（匀速直线 = 机器）
            third = max(1, len(speeds) // 3)
            mid = sum(speeds[third:2 * third]) / third
            tail = sum(speeds[-third:]) / third
            if mid > 0 and tail > mid * 1.35:
                score += 8  # 末段未减速反而更快
    ys = [p[1] for p in pts]
    if max(ys) - min(ys) < 0.5:
        score += 8  # 完全水平，无手部抖动
    return min(100.0, score)


def verify(token: str, x, traj, tolerance: float | None = None,
           require_human: bool = False) -> tuple[bool, float, str]:
    """校验并销毁条目（无论成败防重放）。

    返回 (ok, suspicion, reason)。ok 仅取决于位置对齐（静默放行）；当
    require_human=True（风险升级）时 additionally 要求轨迹类人。suspicion 供
    上层累计 IP 风险分。x 为客户端最终**滑块**位移，服务端按曲线反算拼图位置。
    """
    if not _valid_token(token):
        return False, 100.0, "bad_token"
    with _lock:
        try:
            with storage.lock(K_SLIDE):
                data = _load()
                entry = data.pop(token, None)
                now = time.time()
                data = {k: v for k, v in data.items()
                        if isinstance(v, dict) and v.get("exp", 0) > now}
                storage.set(K_SLIDE, data)
        except StorageError:
            return False, 100.0, "storage"
    if not isinstance(entry, dict):
        return False, 100.0, "missing"
    if entry.get("exp", 0) < time.time():
        return False, 100.0, "expired"
    try:
        d = float(x)
    except (TypeError, ValueError):
        return False, 100.0, "bad_x"
    if not math.isfinite(d):
        return False, 100.0, "bad_x"
    if tolerance is None:
        tolerance = _float_cfg("tolerance_px", 6)
    piece_x = curve_value(entry.get("curve", []), d)
    target = float(entry.get("t", 0))
    suspicion = behavior_suspicion(traj)
    aligned = abs(piece_x - target) <= tolerance
    if not aligned:
        return False, suspicion, "misaligned"
    if require_human and suspicion >= 40:
        return False, suspicion, "robotic"
    return True, suspicion, "ok"


def peek(token: str) -> dict:
    """读取挑战服务端秘密（端到端测试辅助；条目短时效且一次性）。"""
    if not _valid_token(token):
        return {}
    entry = _load().get(token)
    if isinstance(entry, dict) and entry.get("exp", 0) > time.time():
        return entry
    return {}