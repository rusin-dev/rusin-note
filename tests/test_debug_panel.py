"""调试面板（--debug-panel / RUSIN_DEBUG_PANEL）端到端测试。

覆盖：默认关闭不渲染；回环开启后渲染并暴露图形码答案 / 滑动缺口与阻尼曲线；
远程客户端默认隐藏（RUSIN_DEBUG_PANEL_REMOTE 才放行）；POST 校验后面板显示
可疑度/置信度/原因与 IP 风控分；性能与环境字段就位。

运行：``pytest tests/test_debug_panel.py``
"""
from __future__ import annotations

import logging
import re

import pytest

from app.core import captcha
from app.core import config
from app.core import slide_captcha
from support import _solve_slide, csrf_of, expect

logger = logging.getLogger("rusin.tests.debug_panel")

_TOKEN_RE = re.compile(r'name="captcha_token"[^>]*value="([^"]+)"')


def _token_of(html: str) -> str:
    m = _TOKEN_RE.search(html)
    expect(bool(m), "页面含验证码 token")
    return m.group(1)


@pytest.fixture(autouse=True)
def _restore_debug_flags():
    old = (config.DEBUG_PANEL, config.DEBUG_PANEL_REMOTE, config.CAPTCHA_TYPE)
    config.DEBUG_PANEL = False
    config.DEBUG_PANEL_REMOTE = False
    yield
    config.DEBUG_PANEL, config.DEBUG_PANEL_REMOTE, config.CAPTCHA_TYPE = old


class TestDebugPanel:
    def test_default_off(self, ctx):
        logger.info("=== [A] 默认关闭不渲染面板 ===")
        config.DEBUG_PANEL = False
        html = ctx.client.get("/login").get_data(as_text=True)
        expect("dbg-panel" not in html, "关闭时无面板容器")
        expect("DEBUG PANEL" not in html, "关闭时无面板标题")

    def test_loopback_image_shows_answer(self, ctx):
        logger.info("=== [B] 回环 + 图形码：面板暴露实际验证码 ===")
        config.DEBUG_PANEL = True
        config.CAPTCHA_TYPE = "image"
        html = ctx.client.get("/login").get_data(as_text=True)
        expect("dbg-panel" in html and "DEBUG PANEL" in html, "回环开启渲染面板")
        code = captcha.peek(_token_of(html))
        expect(bool(code) and code.upper() in html, "面板含实际验证码答案")

    def test_loopback_slide_shows_target_and_curve(self, ctx):
        logger.info("=== [C] 回环 + 滑动：面板暴露缺口与阻尼曲线 ===")
        config.DEBUG_PANEL = True
        config.CAPTCHA_TYPE = "slide"
        html = ctx.client.get("/login").get_data(as_text=True)
        expect("dbg-panel" in html, "回环开启渲染面板")
        sec = slide_captcha.peek(_token_of(html))
        expect(str(sec["t"]) in html, "面板含缺口 target")
        expect("curve" in html and "ttfb_ms" in html, "面板含阻尼曲线与 TTFB 占位")

    def test_remote_hidden_unless_allowed(self, ctx):
        logger.info("=== [D] 远程默认隐藏，显式 remote 才放行 ===")
        config.DEBUG_PANEL = True
        ctx.client.environ_base["REMOTE_ADDR"] = "203.0.113.9"
        try:
            html = ctx.client.get("/login").get_data(as_text=True)
            expect("dbg-panel" not in html, "远程客户端默认不渲染面板")
            config.DEBUG_PANEL_REMOTE = True
            html = ctx.client.get("/login").get_data(as_text=True)
            expect("dbg-panel" in html, "显式 remote 后远程可见")
        finally:
            config.DEBUG_PANEL_REMOTE = False
            ctx.client.environ_base["REMOTE_ADDR"] = "127.0.0.1"

    def test_post_verify_shows_confidence_and_risk(self, ctx):
        logger.info("=== [E] 错位提交：面板显示可疑度/置信度/原因与风控分 ===")
        config.DEBUG_PANEL = True
        config.CAPTCHA_TYPE = "slide"
        html = ctx.client.get("/register").get_data(as_text=True)
        fields = _solve_slide(_token_of(html))
        fields["captcha_x"] = "3"  # 故意错位
        resp = ctx.client.post("/register", data={
            "username": "dbgpost", "password": "TestPass1!", "confirm": "TestPass1!",
            "csrf_token": csrf_of(html), "agree_terms": "1", **fields,
        })
        expect(resp.status_code == 400, "错位返回 400 并重渲染")
        body = resp.get_data(as_text=True)
        expect("dbg-panel" in body, "错误页仍渲染面板")
        expect("suspicion" in body and "confidence" in body, "面板含可疑度与置信度")
        expect("misaligned" in body, "面板含失败原因 misaligned")
        expect("score" in body, "面板含 IP 风控分")

    def test_perf_and_env_fields(self, ctx):
        logger.info("=== [F] 性能与环境字段就位 ===")
        config.DEBUG_PANEL = True
        html = ctx.client.get("/login").get_data(as_text=True)
        for key in ("server_ms", "ttfb_ms", "dns_ms", "load_ms",
                    "storage", "data_dir", "client_ip", "tier"):
            expect(key in html, f"面板含字段 {key}")