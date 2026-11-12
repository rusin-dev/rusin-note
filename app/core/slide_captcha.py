"""滑动拼图验证码：纯标准库生成 SVG 拼图（无图像库依赖），行为轨迹校验 + 随机阻尼。

设计要点
--------
- 服务端生成背景 SVG（含缺口）与拼图块 SVG（背景在缺口处的裁剪）。缺口横坐标
  ``target`` 与阻尼曲线随一次性 token 存 KV ``slide_captchas``（TTL 默认 5 分钟，
  与图形验证码同模式：写入时机会式清理过期项，verify 即销毁防重放）。
- **随机阻尼**：滑块位移 d → 拼图位移 piece_x 经一条随机单调曲线映射，局部斜率
  时大时小（"移动 10px 拼图走 20px"或"走 8px"的过滑/阻滞手感）。曲线终点归一到
  travel_max，故 curve(S)=travel_max ≥ target，保证滑块到底之前拼图必能送到缺口。
  服务端按曲线反算最终拼图位置再比对 target——naive bot 直接拖 d=target 会因
  curve(target)≠target 而落空。
- **行为轨迹**：客户端采集拖动采样 {x,y,t}，服务端分析时长/采样数/速度方差/是否
  瞬移等给出 suspicion 分（0..100，越高越像机器）。**位置对齐即通过**（即使轨迹
  像机器也静默放行，避免打草惊蛇），suspicion 交由 captcha_risk 累计 IP 风险分，
  风险越高验证越严（容差收紧 + 要求类人轨迹）。

所有随机性来自 secrets；SVG 不含可读文本节点，缺口位置以矢量裁剪呈现。
"""
from __future__ import annotations

import re
import secrets
import threading
import time

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

def _piece_path(pw: float, ph: float, kr: float) -> str:
    """拼图块本地路径：方形主体 + 顶部圆形凸榫，整体落在 [0,pw]×[0,ph] 内。"""
    cx = pw / 2.0
    top = kr
    return (
        f"M0 {top:.2f} L{cx - kr:.2f} {top:.2f} "
        f"C{cx - kr:.2f} 0 {cx + kr:.2f} 0 {cx + kr:.2f} {top:.2f} "
        f"L{pw:.2f} {top:.2f} L{pw:.2f} {ph:.2f} L0 {ph:.2f} Z"
    )


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
    """生成随机场景：返回 (色1, 色2, 渐变角度, 图形 markup)。

    图形不含渐变引用（底色 rect 在 _render 中按各自渐变 id 单独拼），以便 bg 与
    piece 复用同一组随机图形、却各自携带独立渐变 def（SVG 自包含，不依赖跨元素 id）。
    """
    c1, c2 = secrets.choice(_PALETTE)
    angle = secrets.randbelow(360)
    shapes = []
    for _ in range(7 + secrets.randbelow(5)):
        cx, cy = secrets.randbelow(width), secrets.randbelow(height)
        r = 8 + secrets.randbelow(34)
        op = _rand_float(0.06, 0.22)
        fill = "#ffffff" if secrets.randbelow(2) else "#000000"
        shapes.append(f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{fill}" fill-opacity="{op:.2f}"/>')
    for _ in range(3):
        x1, y1 = secrets.randbelow(width), secrets.randbelow(height)
        x2, y2 = secrets.randbelow(width), secrets.randbelow(height)
        shapes.append(
            f'<path d="M{x1} {y1} L{x2} {y2}" stroke="#ffffff" '
            f'stroke-opacity="0.12" stroke-width="{2 + secrets.randbelow(4)}"/>')
    return c1, c2, angle, "".join(shapes)


def _grad(grad_id: str, c1: str, c2: str, angle: int) -> str:
    return (
        f'<linearGradient id="{grad_id}" gradientTransform="rotate({angle} 0.5 0.5)">'
        f'<stop offset="0" stop-color="{c1}"/><stop offset="1" stop-color="{c2}"/>'
        f'</linearGradient>'
    )


def _render(target: float, body_top: float, geom: dict) -> dict:
    """据缺口位置与几何参数渲染背景/拼图 SVG，返回客户端挑战字段。"""
    W, H = geom["W"], geom["H"]
    pw, ph, kr = geom["pw"], geom["ph"], geom["kr"]
    uid = secrets.token_hex(4)
    c1, c2, angle, shapes = _scene(W, H)
    gb, gp = f"gb{uid}", f"gp{uid}"
    rect = f'<rect width="{W}" height="{H}" fill="url(#{gb})"/>'
    rect_p = f'<rect width="{W}" height="{H}" fill="url(#{gp})"/>'
    local = _piece_path(pw, ph, kr)
    piece_top = body_top - kr
    bg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
        f'viewBox="0 0 {W} {H}" role="img" aria-label="puzzle">'
        f'<defs>{_grad(gb, c1, c2, angle)}</defs>{rect}{shapes}'
        f'<g transform="translate({target:.2f} {piece_top:.2f})">'
        f'<path d="{local}" fill="#0b0f0e" fill-opacity="0.5" '
        f'stroke="#ffffff" stroke-opacity="0.45" stroke-width="1.5"/></g>'
        f'</svg>'
    )
    piece = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{pw}" height="{ph}" '
        f'viewBox="0 0 {pw} {ph}" role="img" aria-label="piece">'
        f'<defs>{_grad(gp, c1, c2, angle)}<clipPath id="cp{uid}"><path d="{local}"/></clipPath></defs>'
        f'<g clip-path="url(#cp{uid})">'
        f'<g transform="translate({-target:.2f} {-piece_top:.2f})">{rect_p}{shapes}</g></g>'
        f'<path d="{local}" fill="none" stroke="#ffffff" stroke-opacity="0.75" stroke-width="1.5"/>'
        f'</svg>'
    )
    return {"bg": bg, "piece": piece, "y_top": round(piece_top, 2),
            "pw": pw, "ph": ph}


# ---------- 签发 / 校验 ----------

def generate(ttl: float | None = None) -> tuple[str, dict]:
    """签发一次性滑动挑战，返回 (token, 客户端挑战字段)。

    客户端字段含 bg/piece/y_top/pw/ph/curve/S/tm；缺口 target 仅存服务端。
    ttl 传负数得到已过期条目（测试用）。
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