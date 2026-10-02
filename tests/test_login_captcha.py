"""登录/注册图形验证码端到端测试（pytest + logging）。

覆盖：登录页分栏布局与验证码渲染、错误/缺失验证码拒绝、大小写不敏感、
一次性（重放失效）、过期失效、刷新端点、开关停用后免验证码登录，
以及注册页同样接入验证码（缺失拒绝、答对注册成功）。

运行：``pytest tests/test_login_captcha.py``
"""
from __future__ import annotations

import json
import logging
import re

from app.core import captcha as captcha_mod
from app.core.extensions import cache
from app.core.feature_flags import FEATURE_KEYS, set_flags
from app.core.store import get_user
from support import (
    DEFAULT_PASSWORD, csrf_of, expect, login, logout, register, register_and_login,
)

logger = logging.getLogger("rusin.tests.captcha")

_TOKEN_RE = re.compile(r'name="captcha_token"[^>]*value="([^"]+)"')
USER = "capuser"


def _login_with(client, username, password, code, token=None):
    html = client.get("/login").get_data(as_text=True)
    m = _TOKEN_RE.search(html)
    expect(bool(m), "登录页含验证码 token 字段")
    data = {
        "username": username,
        "password": password,
        "csrf_token": csrf_of(html),
        "captcha_token": token or m.group(1),
        "captcha": code,
    }
    return client.post("/login", data=data)


class TestLoginCaptcha:
    def test_page_layout(self, ctx):
        logger.info("=== [A] 登录页分栏与验证码渲染 ===")
        html = ctx.client.get("/login").get_data(as_text=True)
        expect("auth-split" in html and "/image/login-hero.webp" in html,
               "左图右表单分栏渲染")
        expect("captchaBox" in html and "<svg" in html, "验证码 SVG 内联渲染")
        expect("/login/captcha" in html, "刷新脚本就位")

    def test_wrong_captcha_rejected(self, ctx):
        logger.info("=== [B] 错误验证码拒绝 ===")
        register_and_login(ctx.client, USER)
        logout(ctx.client)
        resp = _login_with(ctx.client, USER, DEFAULT_PASSWORD, "0000")
        expect(resp.status_code == 400, "错误验证码返回 400")
        expect(ctx.client.get(f"/user/{USER}").status_code == 401, "未被登录")

    def test_case_insensitive_and_success(self, ctx):
        logger.info("=== [C] 大小写不敏感并登录成功 ===")
        html = ctx.client.get("/login").get_data(as_text=True)
        token = _TOKEN_RE.search(html).group(1)
        code = captcha_mod.peek(token).upper()
        expect(len(code) == 4, "peek 取到 4 位答案")
        resp = _login_with(ctx.client, USER, DEFAULT_PASSWORD, code, token=token)
        expect(resp.status_code in (200, 302), "大写提交登录成功")
        expect(ctx.client.get(f"/user/{USER}").status_code == 200, "会话已建立")

    def test_single_use_replay(self, ctx):
        logger.info("=== [D] 一次性：重放失效 ===")
        logout(ctx.client)
        html = ctx.client.get("/login").get_data(as_text=True)
        token = _TOKEN_RE.search(html).group(1)
        code = captcha_mod.peek(token)
        resp = _login_with(ctx.client, USER, DEFAULT_PASSWORD, code, token=token)
        expect(resp.status_code in (200, 302), "首次提交成功")
        logout(ctx.client)
        resp = _login_with(ctx.client, USER, DEFAULT_PASSWORD, code, token=token)
        expect(resp.status_code == 400, "同一 token 重放被拒")

    def test_expired_captcha(self, ctx):
        logger.info("=== [E] 过期验证码拒绝 ===")
        token, code = captcha_mod.generate(ttl=-1)
        resp = _login_with(ctx.client, USER, DEFAULT_PASSWORD, code, token=token)
        expect(resp.status_code == 400, "过期验证码返回 400")

    def test_refresh_endpoint(self, ctx):
        logger.info("=== [F] 刷新端点 ===")
        resp = ctx.client.get("/login/captcha")
        expect(resp.status_code == 200, "刷新端点 200")
        data = json.loads(resp.data)
        expect(data.get("token") and "<svg" in data.get("svg", ""), "返回新 token 与 SVG")
        expect(captcha_mod.peek(data["token"]), "新 token 可校验")

    def test_flag_off_skips_captcha(self, ctx):
        logger.info("=== [G] 开关停用后免验证码 ===")
        set_flags({k: (k != "login_captcha") for k in FEATURE_KEYS})
        cache.clear()
        html = ctx.client.get("/login").get_data(as_text=True)
        expect("captcha_token" not in html, "登录页不再渲染验证码")
        resp = login(ctx.client, USER, DEFAULT_PASSWORD)
        expect(resp.status_code in (200, 302), "免验证码登录成功")
        expect(ctx.client.get("/login/captcha").status_code == 404, "刷新端点随开关 404")
        set_flags({k: True for k in FEATURE_KEYS})
        cache.clear()


class TestRegisterCaptcha:
    NEW_USER = "regcap"

    def test_page_layout(self, ctx):
        logger.info("=== [H] 注册页分栏与验证码渲染 ===")
        html = ctx.client.get("/register").get_data(as_text=True)
        expect("auth-split" in html and "/image/login-hero.webp" in html,
               "注册页与登录页同构分栏渲染")
        expect("captchaBox" in html and "<svg" in html, "注册页验证码 SVG 内联渲染")
        expect("/login/captcha" in html, "注册页刷新脚本就位")
        expect('name="agree_terms"' in html and "/disclaimer" in html,
               "服务条款同意勾选框就位")
        expect('name="agree_terms"' not in ctx.client.get("/login").get_data(as_text=True),
               "登录页不出现条款勾选框")

    def test_missing_captcha_rejected(self, ctx):
        logger.info("=== [I] 缺失/错误验证码拒绝注册 ===")
        html = ctx.client.get("/register").get_data(as_text=True)
        token = _TOKEN_RE.search(html).group(1)
        resp = ctx.client.post("/register", data={
            "username": self.NEW_USER, "password": DEFAULT_PASSWORD,
            "confirm": DEFAULT_PASSWORD, "csrf_token": csrf_of(html),
            "agree_terms": "1",
        })
        expect(resp.status_code == 400, "缺失验证码返回 400")
        resp = ctx.client.post("/register", data={
            "username": self.NEW_USER, "password": DEFAULT_PASSWORD,
            "confirm": DEFAULT_PASSWORD, "csrf_token": csrf_of(html),
            "agree_terms": "1",
            "captcha_token": token, "captcha": "0000",
        })
        expect(resp.status_code == 400, "错误验证码返回 400")
        expect(not (get_user(self.NEW_USER) or {}).get("salt"), "用户未被创建")

    def test_terms_agreement_required(self, ctx):
        logger.info("=== [K] 未勾选服务条款拒绝注册 ===")
        resp = register(ctx.client, self.NEW_USER, agree=False)
        expect(resp.status_code == 400, "未勾选条款返回 400")
        expect("agree" in resp.get_data(as_text=True).lower(), "错误后仍回显条款勾选框")
        expect(not (get_user(self.NEW_USER) or {}).get("salt"), "用户未被创建")
        logger.info("勾选后注册成功由 [J] 覆盖")

    def test_correct_captcha_registers(self, ctx):
        logger.info("=== [J] 验证码答对注册成功 ===")
        resp = register(ctx.client, self.NEW_USER)
        expect(resp.status_code == 302, "带验证码注册成功 -> 302")
        expect(bool((get_user(self.NEW_USER) or {}).get("salt")), "用户已创建")
