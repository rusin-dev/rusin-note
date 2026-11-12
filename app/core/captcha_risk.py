"""验证码 IP 风险分体系：静默放行 + 逐步升级 + 注册风控标记。

反高级 Agent 的"不打草惊蛇"策略
--------------------------------
行为轨迹像机器但拼图位置对齐时**仍然放行**（见 slide_captcha.verify），避免当场
拒绝让攻击者察觉防线；改为按 IP 累计风险分：

- 每次"像机器的放行"加 suspicious_points，每次位置失败加 fail_points；
- 风险分随时间按半衰期衰减（decay_hours），正常用户不会误伤累积；
- 分数达到 escalate_score → 验证收紧（容差减半 + 要求类人轨迹），更难通过；
- 达到 flag_score 或窗口内第二次注册且有可疑历史 → 标记该 IP，并把后续注册账号
  打上风控标（users.risk_flagged + KV captcha_risk_flags），供管理员处置。

状态存 KV ``captcha_ip_risk``（每 IP 一条），标记存 ``captcha_risk_flags``
（username → 详情）。无进程内缓存：每次重读 KV，多实例天然一致；写路径锁序
threading.Lock → storage.lock（与全站一致）。
"""
from __future__ import annotations

import threading
import time

from app.core import config
from app.core.logger import create_logger
from app.core.storage import StorageError, storage

logger = create_logger("captcha_risk")

K_RISK = "captcha_ip_risk"
K_FLAGS = "captcha_risk_flags"
_lock = threading.Lock()

# 轨迹可疑度达到该值视为"像机器"（与 slide_captcha 的 require_human 阈值一致）
ROBOTIC_THRESHOLD = 40.0


def _cfg(key: str, default):
    val = config.CAPTCHA_RISK.get(key, default)
    return val if val is not None else default


def _int(key: str, default: int, minimum: int = 0) -> int:
    try:
        return max(minimum, int(_cfg(key, default)))
    except (TypeError, ValueError):
        return default


def _float(key: str, default: float) -> float:
    try:
        return float(_cfg(key, default))
    except (TypeError, ValueError):
        return default


def enabled() -> bool:
    return bool(_cfg("enabled", True))


def _load(key: str) -> dict:
    try:
        data = storage.get(key)
    except StorageError:
        return {}
    return data if isinstance(data, dict) else {}


def _decay(entry: dict, now: float) -> dict:
    """按半衰期衰减风险分，并重置过期注册计数窗口（原地更新）。"""
    half = _float("decay_hours", 12)
    if half <= 0:
        half = 12
    updated = float(entry.get("updated", now) or now)
    elapsed_h = max(0.0, (now - updated) / 3600.0)
    score = float(entry.get("score", 0) or 0) * (0.5 ** (elapsed_h / half))
    entry["score"] = round(score, 3)
    entry["updated"] = now
    window = _int("reg_window_seconds", 3600, 60)
    if now - float(entry.get("reg_start", now) or now) > window:
        entry["regs"] = 0
        entry["reg_start"] = now
    return entry


def tier_of(score: float, flagged: bool) -> int:
    """0=正常（静默放行）；1=升级（收紧）；2=标记（最严 + 注册风控）。"""
    if flagged or score >= _float("flag_score", 60):
        return 2
    if score >= _float("escalate_score", 30):
        return 1
    return 0


def get_state(ip: str) -> dict:
    """读取并衰减后的 IP 风险状态（不写盘）。"""
    now = time.time()
    entry = _decay(dict(_load(K_RISK).get(ip, {}) or {}), now)
    score = float(entry.get("score", 0) or 0)
    flagged = bool(entry.get("flagged", False))
    return {
        "score": score,
        "tier": tier_of(score, flagged),
        "flagged": flagged,
        "suspicious": int(entry.get("suspicious", 0) or 0),
        "fails": int(entry.get("fails", 0) or 0),
        "regs": int(entry.get("regs", 0) or 0),
    }


def difficulty(ip: str) -> tuple[float, bool]:
    """据风险等级返回 (位置容差 px, 是否要求类人轨迹)。"""
    base = float(config.CAPTCHA_SLIDE.get("tolerance_px", 6) or 6)
    tier = get_state(ip)["tier"]
    if tier >= 2:
        return max(2.0, base * 0.34), True
    if tier == 1:
        return max(2.0, base * 0.5), True
    return base, False


def record(ip: str, ok: bool, suspicion: float, kind: str = "slide") -> dict:
    """记录一次验证结果，累计/衰减风险分并写盘，返回最新状态。

    ok=False（位置失败）加 fail_points；ok=True 但轨迹像机器加 suspicious_points
    （静默放行）；类人放行不加分。风险体系停用时仅返回正常态。
    """
    if not enabled() or not ip:
        return {"score": 0.0, "tier": 0, "flagged": False,
                "suspicious": 0, "fails": 0, "regs": 0}
    now = time.time()
    with _lock:
        try:
            with storage.lock(K_RISK):
                data = _load(K_RISK)
                entry = _decay(dict(data.get(ip, {}) or {}), now)
                entry.setdefault("reg_start", now)
                if not ok:
                    entry["score"] = round(float(entry.get("score", 0)) + _float("fail_points", 5), 3)
                    entry["fails"] = int(entry.get("fails", 0) or 0) + 1
                elif suspicion >= ROBOTIC_THRESHOLD:
                    entry["score"] = round(float(entry.get("score", 0)) + _float("suspicious_points", 14), 3)
                    entry["suspicious"] = int(entry.get("suspicious", 0) or 0) + 1
                entry["updated"] = now
                data[ip] = entry
                # 机会式清理：丢弃长期无活动且分数衰减到近零的条目，防 KV 膨胀
                if len(data) > 512:
                    data = {k: v for k, v in data.items()
                            if float(v.get("score", 0)) >= 0.5 or v.get("flagged")
                            or now - float(v.get("updated", now)) < 86400}
                storage.set(K_RISK, data)
        except StorageError:
            return get_state(ip)
    return get_state(ip)


def on_register(ip: str, username: str) -> bool:
    """注册成功后调用：窗口内计数，达阈值且有可疑历史则标记 IP 与账号风控。

    返回是否触发了风控标记。标记会写入 users.risk_flagged 与 KV captcha_risk_flags，
    并记 WARNING 日志（不回显给客户端，避免打草惊蛇）。
    """
    if not enabled() or not ip or not username:
        return False
    now = time.time()
    flagged = False
    with _lock:
        try:
            with storage.lock(K_RISK):
                data = _load(K_RISK)
                entry = _decay(dict(data.get(ip, {}) or {}), now)
                entry.setdefault("reg_start", now)
                entry["regs"] = int(entry.get("regs", 0) or 0) + 1
                score = float(entry.get("score", 0) or 0)
                suspicious = int(entry.get("suspicious", 0) or 0)
                already = bool(entry.get("flagged", False))
                max_regs = _int("max_registrations", 2, 1)
                trigger = (
                    already
                    or score >= _float("flag_score", 60)
                    or (entry["regs"] >= max_regs and (suspicious > 0 or score >= _float("escalate_score", 30)))
                )
                if trigger:
                    entry["flagged"] = True
                    entry["flagged_at"] = now
                    flagged = True
                entry["updated"] = now
                data[ip] = entry
                storage.set(K_RISK, data)
        except StorageError:
            return False
    if flagged:
        _mark_user(ip, username, score, now)
    return flagged


def _mark_user(ip: str, username: str, score: float, now: float) -> None:
    """把风控标记落到账号与 flags KV（失败只记日志，不影响注册流程）。"""
    reason = {"ip": ip, "score": round(score, 2), "at": now}
    try:
        with _lock:
            with storage.lock(K_FLAGS):
                flags = _load(K_FLAGS)
                flags[username] = reason
                storage.set(K_FLAGS, flags)
    except StorageError:
        logger.error("[错误] 写入风控标记失败：user=%s", username)
    try:
        from app.core import store
        store.update_user(username, {"risk_flagged": True, "risk_at": now})
    except Exception as e:  # 账号标记失败不阻断注册
        logger.error("[错误] 标记账号风控失败：user=%s err=%s", username, e)
    logger.warning("验证码风控标记：user=%s ip=%s score=%.1f（疑似自动化注册）",
                   username, ip, score)


def is_flagged(username: str) -> bool:
    return username in _load(K_FLAGS)


def get_flag(username: str) -> dict:
    entry = _load(K_FLAGS).get(username)
    return entry if isinstance(entry, dict) else {}