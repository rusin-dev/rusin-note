"""双因素认证（TOTP）端到端测试（pytest + logging）。

覆盖：
- 服务层：绑定 / 确认 / 动态码与防重放 / 恢复码 / 停用 / 改名迁移；
- 路由层：开启后密码登录转第二因素页、动态码与恢复码校验、管理页操作；
- 功能开关关闭时路由 404。

运行：``pytest tests/test_twofa.py``
"""
from __future__ import annotations

import logging
import re
import time

from app.core import totp
from app.core.feature_flags import FEATURE_KEYS, set_flags
from app.apps.twofa import service
from support import expect, login, logout, register, register_and_login

logger = logging.getLogger("rusin.tests.twofa")

USER = "twofa_user"
PASSWORD = "TestPass1!"


def _enable():
    set_flags({key: True for key in FEATURE_KEYS})


def _csrf(html: str) -> str:
    m = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', html)
    assert m, "未找到 csrf_token"
    return m.group(1)


class TestTwoFA:
    """A-E：2FA 服务与登录流程。"""

    def test_service_lifecycle(self, ctx):
        logger.info("=== [A] 服务层：绑定 / 校验 / 恢复码 / 停用 ===")
        _enable()
        expect(service.is_enabled(USER) is False, "默认未开启")

        secret, uri = service.start_setup(USER)
        expect(bool(secret) and uri.startswith("otpauth://totp/"), "生成密钥与 otpauth 链接")
        expect(service.is_enabled(USER) is False, "确认前仍未启用")

        code = totp.generate_code(secret)
        plain = service.confirm_setup(USER, code)
        expect(isinstance(plain, list) and len(plain) == 8, "确认后返回 8 个恢复码")
        expect(service.is_enabled(USER) is True, "确认后启用")
        expect(service.count_recovery_codes(USER) == 8, "恢复码已入库（哈希）")

        # 当前时间步的动态码在确认时已被记录，重放应失败
        expect(service.verify(USER, code) is False, "同一时间步动态码重放被拒绝")
        next_code = totp.generate_code(secret, at=time.time() + 30)
        expect(service.verify(USER, next_code) is True, "下一时间步动态码通过")
        expect(service.verify(USER, next_code) is False, "再次重放被拒绝")

        expect(service.verify(USER, plain[0]) is True, "恢复码可用")
        expect(service.verify(USER, plain[0]) is False, "恢复码一次性")
        expect(service.count_recovery_codes(USER) == 7, "恢复码已消费")

        expect(service.rename_user_two_factor(USER, "twofa_renamed"), "改名迁移成功")
        expect(service.is_enabled("twofa_renamed") is True, "迁移后新用户已开启")
        expect(service.disable("twofa_renamed") is True, "停用成功")
        expect(service.is_enabled("twofa_renamed") is False, "停用后关闭")

    def test_http_flow(self, ctx):
        logger.info("=== [B] 路由层：登录第二因素 ===")
        _enable()
        register_and_login(ctx.client, "twofa_http")
        # 通过管理页开启
        page = ctx.client.get("/user/twofa_http/twofa").get_data(as_text=True)
        start = ctx.client.post("/user/twofa_http/twofa",
                                data={"action": "start", "csrf_token": _csrf(page)})
        secret = re.search(r'<div class="secret-box">([^<]+)</div>',
                           start.get_data(as_text=True)).group(1)
        confirm = ctx.client.post("/user/twofa_http/twofa",
                                  data={"action": "confirm", "code": totp.generate_code(secret),
                                        "csrf_token": _csrf(start.get_data(as_text=True))})
        expect(confirm.status_code == 200, "确认绑定返回管理页")
        expect(service.is_enabled("twofa_http") is True, "HTTP 流程已开启 2FA")
        ctx.secret = secret

        logout(ctx.client)
        resp = login(ctx.client, "twofa_http", PASSWORD)
        expect(resp.status_code == 302 and resp.headers["Location"] == "/login/2fa",
               "密码登录后转第二因素页")
        expect(ctx.client.get("/login/2fa").status_code == 200, "第二因素页可访问")

        wrong = ctx.client.post("/login/2fa", data={"code": "000000",
                                                    "csrf_token": _csrf(ctx.client.get("/login/2fa").get_data(as_text=True))})
        expect(wrong.status_code == 401, "错误动态码 -> 401")

        ok = ctx.client.post("/login/2fa", data={
            "code": totp.generate_code(ctx.secret, at=time.time() + 30),
            "csrf_token": _csrf(ctx.client.get("/login/2fa").get_data(as_text=True)),
        })
        expect(ok.status_code == 302 and ok.headers["Location"] == "/", "正确动态码登录成功")
        expect(ctx.client.get("/user/twofa_http/").status_code == 200, "会话已建立")

    def test_recovery_login(self, ctx):
        logger.info("=== [C] 恢复码登录 ===")
        _enable()
        register_and_login(ctx.client, "twofa_recovery")
        secret, _ = service.start_setup("twofa_recovery")
        codes = service.confirm_setup("twofa_recovery", totp.generate_code(secret))
        logout(ctx.client)

        login(ctx.client, "twofa_recovery", PASSWORD)
        page = ctx.client.get("/login/2fa").get_data(as_text=True)
        resp = ctx.client.post("/login/2fa", data={"code": codes[0], "csrf_token": _csrf(page)})
        expect(resp.status_code == 302 and resp.headers["Location"] == "/", "恢复码登录成功")


class TestTwoFADisabled:
    """功能开关关闭时（默认）路由 404。"""

    def test_disabled(self, ctx):
        logger.info("=== [D] 功能关闭 -> 404 ===")
        expect(ctx.anon.get("/login/2fa").status_code == 404, "第二因素页 404")
        register_and_login(ctx.client, "twofa_off")
        expect(ctx.client.get("/user/twofa_off/twofa").status_code == 404, "管理页 404")
