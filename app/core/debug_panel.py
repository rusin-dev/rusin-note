"""开发/排障诊断面板：仅在显式开启（--debug-panel / RUSIN_DEBUG_PANEL）时渲染。

把请求上下文、服务端耗时、验证码挑战与校验结果（答案/缺口/阻尼曲线/轨迹可疑度与
置信度）、IP 风控分、运行环境汇总为一个快照，供模板 partial 可视化。因暴露敏感
信息，默认仅回环客户端可见（RUSIN_DEBUG_PANEL_REMOTE=1 才放行远程）。
"""
from __future__ import annotations

import ipaddress
import time

from flask import g, has_request_context, request

from app.core import config
from app.core.storage import storage


def request_allowed() -> bool:
    """开关开启且客户端为回环（或显式允许远程）时才渲染面板。"""
    if not config.DEBUG_PANEL or not has_request_context():
        return False
    if config.DEBUG_PANEL_REMOTE:
        return True
    ip = getattr(g, "client_ip", "") or request.remote_addr or ""
    try:
        return ipaddress.ip_address(ip).is_loopback
    except ValueError:
        return False


def _request() -> dict:
    return {
        "method": request.method,
        "path": request.path,
        "client_ip": getattr(g, "client_ip", ""),
        "ip_source": getattr(g, "client_ip_source", ""),
        "remote_addr": request.remote_addr,
        "user": getattr(g, "current_user", None),
        "simple_mode": getattr(g, "simple_mode", False),
        "user_agent": (request.headers.get("User-Agent", "") or "")[:120],
    }


def _perf() -> dict:
    t0 = getattr(g, "debug_t0", None)
    server_ms = round((time.perf_counter() - t0) * 1000, 2) if t0 else None
    return {"server_ms": server_ms}


def _captcha() -> dict:
    from app.core import captcha
    out = {"type": captcha.current_type()}
    challenge = getattr(g, "debug_challenge", None)
    if challenge:
        out["challenge"] = challenge
    verify = getattr(g, "debug_verify", None)
    if verify:
        out["verify"] = verify
    return out


def _risk() -> dict:
    from app.core import captcha_risk
    ip = getattr(g, "client_ip", "") or ""
    state = captcha_risk.get_state(ip)
    tolerance, require_human = captcha_risk.difficulty(ip)
    return {"enabled": captcha_risk.enabled(), "ip": ip, **state,
            "tolerance_px": tolerance, "require_human": require_human}


def _env() -> dict:
    from app.core.feature_flags import feature_enabled
    return {
        "storage": getattr(storage, "kind", "?"),
        "data_dir": config.DATA_DIR,
        "serverless": config.SERVERLESS,
        "secure_cookies": config.SECURE_COOKIES,
        "trusted_proxies": config.TRUSTED_PROXIES,
        "login_captcha": feature_enabled("login_captcha"),
        "cache_backend": config.CACHE_BACKEND,
        "lang": getattr(g, "lang", ""),
    }


def snapshot() -> dict:
    """汇总当前请求的诊断快照（仅开关开启时由 context processor 调用）。"""
    return {"request": _request(), "perf": _perf(), "captcha": _captcha(),
            "risk": _risk(), "env": _env()}