"""本轮 Bug 修复的回归测试（pytest + logging）。

覆盖：分享浏览量批量落盘不丢增量、删笔记级联失效分享与评论板、评论目标必须
真实存在、验证码登录同样受 TOTP 第二因素约束、/lang 不回跳站外、功能开关缺省
值回退到 DEFAULT_CONFIG、组织邀请码越权与删组织残留、Markdown 代码块二次转义
与表格对齐丢失。

运行：``pytest tests/test_regression_fixes.py``
"""
from __future__ import annotations

import logging

from support import csrf_from, create_note, expect, register

from app.core import notes, store
from app.core.feature_flags import _default_of
from app.core.utils import render_markdown_html

logger = logging.getLogger("rusin.tests.regression")

USER = "reg_user"
OTHER = "reg_other"


class TestShareCounters:
    """分享浏览量：批量写盘与多实例合并"""

    def test_pending_increments_survive_flush(self, ctx):
        logger.info("=== 浏览量批量落盘保留增量 ===")
        register(ctx.client, USER)
        note_id = create_note(ctx.client, USER, "浏览量笔记")
        token = store.create_share(USER, note_id, False)
        expect(bool(token), "分享创建成功")
        for _ in range(3):
            store.increment_share_views(token)
        store.flush_share_views()
        on_disk = store._read(store.K_SHARES) or {}
        expect(on_disk.get(token, {}).get("views") == 3,
               "写盘内容为累加后的浏览量")
        # 模拟其它实例的整表重载：累加值不能被存储锁内的重读冲掉
        store._read_merge(store.K_SHARES, store.shares)
        expect(store.get_share(token)["views"] == 3, "重载后浏览量仍为 3")

    def test_note_deletion_revokes_share(self, ctx):
        logger.info("=== 删笔记后分享立即失效 ===")
        owner = "reg_share_del"
        register(ctx.client, owner)
        note_id = create_note(ctx.client, owner, "可编辑分享")
        response = ctx.client.post(f"/user/{owner}/shares", data={
            "note_id": note_id, "editable": "1",
            "csrf_token": csrf_from(ctx.client, f"/user/{owner}/shares"),
        })
        expect(response.status_code == 302, "分享创建成功")
        token = next(tok for tok, s in store.list_user_shares(owner)
                     if s.get("note_id") == note_id)
        store.add_comment("note", f"{owner}/{note_id}", OTHER, "评论")
        expect(ctx.client.post(f"/user/{owner}/{note_id}/delete", data={
            "csrf_token": csrf_from(ctx.client, f"/user/{owner}/{note_id}"),
        }).status_code == 302, "笔记删除成功")
        expect(store.get_share(token) is None, "分享随笔记级联删除")
        expect(ctx.anon.post(f"/share/{token}", data={
            "content": "匿名复活",
            "csrf_token": csrf_from(ctx.anon, "/login"),
        }).status_code == 404, "已删笔记的分享不再接受匿名写入")
        expect(notes.note_exists(owner, note_id) is False, "笔记未被分享写回复活")
        expect(store.count_comments("note", f"{owner}/{note_id}") == 0,
               "评论板随笔记级联删除")


class TestCommentTargets:
    """评论目标存在性"""

    def test_missing_note_target_is_404(self, ctx):
        logger.info("=== 不存在的笔记无评论板 ===")
        owner = "reg_cmt_owner"
        expect(ctx.anon.get("/comments/note/nobody/nothing").status_code == 404,
               "不存在的笔记评论页 -> 404")
        register(ctx.client, owner)
        note_id = create_note(ctx.client, owner, "私有笔记")
        expect(ctx.anon.get(f"/comments/note/{owner}/{note_id}").status_code == 200,
               "已存在笔记的评论页仍可访问")
        expect(ctx.anon.get(f"/comments/note/{owner}/{note_id}x").status_code == 404,
               "同用户的不存在笔记不再开板")
        expect(ctx.anon.post(f"/comments/note/{owner}/{note_id}x", data={
            "content": "刷屏", "csrf_token": csrf_from(ctx.anon, "/login"),
        }).status_code == 404, "不存在的笔记无法被建评论板")


class TestOtpSecondFactor:
    """验证码登录必须与密码登录同样受 2FA 约束"""

    def _login_by_code(self, ctx, monkeypatch, required: bool, owner: str):
        from app.apps.email import service as email_service
        from app.apps.email import views as email_views
        from app.apps.twofa import service as twofa_service

        monkeypatch.setattr(email_views, "_any_login_enabled", lambda: True)
        monkeypatch.setattr(email_service, "request_login_code",
                            lambda kind, contact: (owner, ""))
        monkeypatch.setattr(email_service, "verify_login_code",
                            lambda username, kind, code: True)
        monkeypatch.setattr(twofa_service, "is_required", lambda username: required)
        # 用未登录的客户端：register 会自动登录，无法区分「验证码登录建立的会话」
        client = ctx.app.test_client()
        csrf = csrf_from(client, "/login")
        expect(client.post("/login/otp", data={
            "action": "request", "kind": "email", "contact": "a@b.c",
            "csrf_token": csrf,
        }).status_code == 200, "验证码请求步骤成功")
        return client, client.post("/login/otp", data={
            "action": "verify", "code": "123456",
            "csrf_token": csrf_from(client, "/login"),
        })

    def test_otp_login_defers_to_totp(self, ctx, monkeypatch):
        logger.info("=== 已开启 2FA 时验证码登录转第二因素 ===")
        owner = "reg_otp_2fa"
        register(ctx.client, owner)
        client, response = self._login_by_code(ctx, monkeypatch, True, owner)
        expect(response.status_code == 302 and "/login/2fa" in response.headers.get("Location", ""),
               "验证码校验后转 /login/2fa")
        expect(client.get(f"/user/{owner}/settings").status_code == 401,
               "尚未取得已认证会话")

    def test_otp_login_without_2fa(self, ctx, monkeypatch):
        logger.info("=== 未开启 2FA 时验证码登录直接建立会话 ===")
        owner = "reg_otp_plain"
        register(ctx.client, owner)
        client, response = self._login_by_code(ctx, monkeypatch, False, owner)
        expect(response.status_code == 302 and response.headers.get("Location") == "/",
               "验证码登录成功回首页")
        expect(client.get(f"/user/{owner}/settings").status_code == 200,
               "会话已建立")


class TestLangSwitchRedirect:
    """/lang 只能回跳站内路径"""

    def test_protocol_relative_referer_rejected(self, ctx):
        logger.info("=== Referer 构造的站外跳转被拒 ===")
        response = ctx.anon.get("/lang/en", headers={"Referer": "http://site.test//evil.com/x"})
        location = response.headers.get("Location", "")
        expect(not location.startswith("//"), "不把 //evil.com 当作站内路径")
        expect(location in ("/lang/en", "/"), f"回跳站内地址（实际：{location}）")

    def test_normal_referer_preserves_query(self, ctx):
        response = ctx.anon.get("/lang/en", headers={"Referer": "http://site.test/user/a?q=1"})
        expect(response.headers.get("Location") == "/user/a?q=1", "站内路径与查询串保留")


class TestFeatureFlagDefaults:
    """config.json 缺少键时回退到 DEFAULT_CONFIG 声明的默认值"""

    def test_missing_key_uses_declared_default(self, monkeypatch):
        logger.info("=== 功能开关缺省值 ===")
        from app.core import feature_flags
        monkeypatch.setattr(feature_flags, "_FEATURES_CFG", {})
        for key in ("oauth_github", "oauth_qq", "two_factor_auth",
                    "email_verify", "phone_verify"):
            expect(_default_of(key) is False, f"{key} 默认关闭")
        expect(_default_of("world_notes") is True, "已声明为 True 的功能默认开启")
        expect(_default_of("not_declared_anywhere") is True, "两处都未登记的新功能默认开启")

    def test_config_value_still_wins(self, monkeypatch):
        from app.core import feature_flags
        monkeypatch.setattr(feature_flags, "_FEATURES_CFG", {"two_factor_auth": True})
        expect(_default_of("two_factor_auth") is True, "config.json 显式值优先")


class TestOrgInviteIsolation:
    """邀请码是全局键，删除与删组织都必须限定归属"""

    def test_cross_org_invite_delete_denied(self, ctx):
        logger.info("=== 跨组织删除邀请码被拒 ===")
        register(ctx.client, USER)
        register(ctx.app.test_client(), OTHER)
        expect(store.create_org("orga", "组织 A", USER) is True, "组织 A 创建成功")
        expect(store.create_org("orgb", "组织 B", OTHER) is True, "组织 B 创建成功")
        code = store.create_org_invite("orgb", OTHER, "invite", 7)
        expect(bool(code), "组织 B 邀请码创建成功")
        expect(store.delete_org_invite(code, "orga") is False, "组织 A 无权删除 B 的邀请码")
        expect(bool(store.validate_org_invite(code)), "邀请码仍然存在")
        expect(store.delete_org_invite(code, "orgb") is True, "本组织可删除自己的邀请码")
        expect(store.validate_org_invite(code) is None, "删除后邀请码失效")

    def test_delete_org_cascades_namespace(self, ctx):
        logger.info("=== 删组织级联清理笔记/邀请/申请 ===")
        register(ctx.client, USER)
        store.create_org("orgc", "组织 C", USER)
        store.create_org_invite("orgc", USER, "invite", 7)
        store.create_join_request("orgc", OTHER, "想加入")
        expect(notes.write_note("_orgs/orgc", "note1", "组织笔记") is True, "组织笔记写入成功")
        expect(store.delete_org("orgc") is True, "组织删除成功")
        expect(notes.note_exists("_orgs/orgc", "note1") is False,
               "组织笔记随组织删除（同名重建不再继承）")
        expect(store.get_org_invites("orgc") == [], "邀请码随组织删除")
        expect(store.get_org_join_requests("orgc") == {}, "入群申请随组织删除")


class TestMarkdownRendering:
    """代码块转义与表格对齐"""

    def test_code_block_escaped_once(self):
        logger.info("=== Pygments 不再二次转义代码正文 ===")
        html = render_markdown_html('```python\nprint("<hi>")\n```\n')
        expect("&lt;hi&gt;" in html, "尖括号按一次转义输出")
        expect("&amp;lt;" not in html, "不出现二次转义的字面量")
        expect("pygments-highlighted" in html, "服务端已着色的代码块带标记类")

    def test_unrecognized_language_left_for_client(self):
        html = render_markdown_html('```notalanguage\n<b>x</b>\n```\n')
        expect("pygments-highlighted" not in html, "未识别语言交给客户端 highlight.js")
        expect("&lt;b&gt;" in html, "正文仍是单次转义")

    def test_table_alignment_kept(self):
        logger.info("=== 表格列对齐不被清洗掉 ===")
        html = render_markdown_html('| a | b |\n|:-:|:-|\n| 1 | 2 |\n')
        expect('align="center"' in html and 'align="left"' in html, "align 属性保留")
        expect("style=" not in html, "不通过放行 style 来实现对齐")

    def test_style_and_events_still_stripped(self):
        html = render_markdown_html('<img src=x onerror="alert(1)">\n\n[链接](javascript:alert(1))\n')
        expect("onerror" not in html, "事件属性被清洗")
        expect("javascript:" not in html, "危险协议被清洗")
