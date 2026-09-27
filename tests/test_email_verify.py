"""邮箱 / 手机号验证端到端测试（pytest + logging）。

覆盖：
- 联系方式绑定：发送 / 校验 / 重复发送冷却 / 非法值 / 解绑；
- 验证码登录：请求验证码 -> 校验 -> 建立会话；
- 功能开关关闭时路由 404。

投递通过 monkeypatch ``service.deliver_email`` / ``deliver_sms`` 捕获验证码，
不依赖真实 SMTP / 短信服务。

运行：``pytest tests/test_email_verify.py``
"""
from __future__ import annotations

import logging
import re

from app.core.feature_flags import FEATURE_KEYS, set_flags
from app.apps.email import service
from support import expect, logout, register_and_login

logger = logging.getLogger("rusin.tests.email_verify")

USER = "email_user"
EMAIL = "user@example.com"
PHONE = "+8613800138000"


def _enable():
    set_flags({key: True for key in FEATURE_KEYS})


def _csrf(html: str) -> str:
    m = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', html)
    assert m, "未找到 csrf_token"
    return m.group(1)


class TestEmailVerify:
    """A-D：绑定、验证码登录与管理。"""

    def test_bind_and_cooldown(self, ctx, monkeypatch):
        logger.info("=== [A] 绑定邮箱：验证码、冷却、非法值 ===")
        _enable()
        sent = {}

        def fake_email(to_addr, code):
            sent["email"] = (to_addr, code)
            return True

        def fake_sms(phone, code):
            sent["phone"] = (phone, code)
            return True

        monkeypatch.setattr(service, "deliver_email", fake_email)
        monkeypatch.setattr(service, "deliver_sms", fake_sms)
        register_and_login(ctx.client, USER)

        page = ctx.client.get(f"/user/{USER}/email").get_data(as_text=True)
        expect(page is not None, "管理页可访问")

        resp = ctx.client.post(f"/user/{USER}/email", data={
            "action": "bind_request", "kind": "email", "value": EMAIL,
            "csrf_token": _csrf(page)})
        expect(resp.status_code == 200 and "email" in sent, "发送邮箱验证码")
        code = sent["email"][1]

        # 冷却：立即重发被拒绝
        cool = ctx.client.post(f"/user/{USER}/email", data={
            "action": "bind_request", "kind": "email", "value": EMAIL,
            "csrf_token": _csrf(resp.get_data(as_text=True))})
        expect("验证码发送过于频繁" in cool.get_data(as_text=True), "重发冷却生效")

        # 非法值
        bad = ctx.client.post(f"/user/{USER}/email", data={
            "action": "bind_request", "kind": "email", "value": "not-an-email",
            "csrf_token": _csrf(cool.get_data(as_text=True))})
        expect("有效的邮箱地址" in bad.get_data(as_text=True), "非法邮箱被拒绝")

        # 错误验证码
        wrong = ctx.client.post(f"/user/{USER}/email", data={
            "action": "bind_confirm", "kind": "email", "code": "000000",
            "csrf_token": _csrf(bad.get_data(as_text=True))})
        expect("验证码无效" in wrong.get_data(as_text=True), "错误验证码被拒绝")

        # 正确验证码
        ok = ctx.client.post(f"/user/{USER}/email", data={
            "action": "bind_confirm", "kind": "email", "code": code,
            "csrf_token": _csrf(wrong.get_data(as_text=True))})
        expect(ok.status_code == 302, "正确验证码 -> 302")
        expect(service.get_verified_contact(USER, "email") == EMAIL, "邮箱已标记验证")

    def test_phone_bind(self, ctx, monkeypatch):
        logger.info("=== [B] 绑定手机号 ===")
        _enable()
        sent = {}
        monkeypatch.setattr(service, "deliver_sms",
                            lambda phone, code: sent.update(phone=(phone, code)) or True)
        page = ctx.client.get(f"/user/{USER}/email").get_data(as_text=True)
        resp = ctx.client.post(f"/user/{USER}/email", data={
            "action": "bind_request", "kind": "phone", "value": PHONE,
            "csrf_token": _csrf(page)})
        code = sent["phone"][1]
        ok = ctx.client.post(f"/user/{USER}/email", data={
            "action": "bind_confirm", "kind": "phone", "code": code,
            "csrf_token": _csrf(resp.get_data(as_text=True))})
        expect(ok.status_code == 302, "手机号验证 -> 302")
        expect(service.get_verified_contact(USER, "phone") == PHONE, "手机号已验证")

    def test_passwordless_login(self, ctx, monkeypatch):
        logger.info("=== [C] 邮箱验证码登录 ===")
        _enable()
        expect(service.get_verified_contact(USER, "email") == EMAIL, "前置邮箱已验证")
        sent = {}
        monkeypatch.setattr(service, "deliver_email",
                            lambda to_addr, code: sent.update(email=(to_addr, code)) or True)
        logout(ctx.client)

        page = ctx.client.get("/login/otp")
        expect(page.status_code == 200, "验证码登录页可访问")
        resp = ctx.client.post("/login/otp", data={
            "action": "request", "kind": "email", "contact": EMAIL,
            "csrf_token": _csrf(page.get_data(as_text=True))})
        expect("验证码已发送" in resp.get_data(as_text=True), "请求后进入验证步骤")
        code = sent["email"][1]

        login_resp = ctx.client.post("/login/otp", data={
            "action": "verify", "code": code,
            "csrf_token": _csrf(resp.get_data(as_text=True))})
        expect(login_resp.status_code == 302 and login_resp.headers["Location"] == "/",
               "验证码登录成功")
        expect(ctx.client.get(f"/user/{USER}/").status_code == 200, "会话已建立")

    def test_remove_contact(self, ctx):
        logger.info("=== [D] 解绑联系方式 ===")
        _enable()
        page = ctx.client.get(f"/user/{USER}/email").get_data(as_text=True)
        resp = ctx.client.post(f"/user/{USER}/email", data={
            "action": "remove", "kind": "phone", "csrf_token": _csrf(page)})
        expect(resp.status_code == 302, "解绑手机号 -> 302")
        expect(service.get_verified_contact(USER, "phone") is None, "手机号已解绑")


class TestEmailVerifyDisabled:
    """功能开关关闭时（默认）路由 404。"""

    def test_disabled(self, ctx):
        logger.info("=== [E] 功能关闭 -> 404 ===")
        resp = ctx.anon.get("/login/otp")
        expect(resp.status_code == 404, "验证码登录页 404")
        register_and_login(ctx.client, "email_off")
        expect(ctx.client.get("/user/email_off/email").status_code == 404, "管理页 404")
