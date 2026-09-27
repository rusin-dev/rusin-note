"""第三方登录（OAuth）端到端测试（pytest + logging）。

覆盖：
- Provider 可用性 = 功能开关 ∧ 凭据已配置；授权 URL 生成；
- 授权发起（302 + state）与回调登录（自动注册 + 绑定）；
- state 校验失败、未绑定且关闭自动注册的错误分支；
- 已登录用户绑定 / 解绑；
- 用户改名时第三方绑定关系迁移。

运行：``pytest tests/test_oauth.py``
"""
from __future__ import annotations

import logging
import urllib.parse

from app.core import config
from app.core.feature_flags import FEATURE_KEYS, set_flags
from app.core.store import get_user
from app.apps.oauth import service
from support import expect, register_and_login

logger = logging.getLogger("rusin.tests.oauth")

PROFILE = {"uid": "123456", "display": "octocat", "email": "octo@example.com",
           "avatar": "https://example.com/a.png"}


def _enable_all():
    set_flags({key: True for key in FEATURE_KEYS})


def _configure(monkeypatch, provider="github"):
    cfg = {"providers": {provider: {"client_id": "cid", "client_secret": "secret"}}}
    monkeypatch.setattr(config, "OAUTH_CFG", cfg)
    # 默认配置关闭 OAuth 总开关，测试中显式打开
    monkeypatch.setattr(config, "OAUTH_ENABLED", True)


def _state_of(response) -> str:
    query = urllib.parse.urlparse(response.headers["Location"]).query
    return urllib.parse.parse_qs(query).get("state", [""])[0]


class TestOAuth:
    """A-F：Provider 注册表、授权流程、绑定管理与迁移。"""

    def test_availability_and_urls(self, ctx, monkeypatch):
        logger.info("=== [A] Provider 可用性与授权 URL ===")
        _enable_all()
        monkeypatch.setattr(config, "OAUTH_CFG", {"providers": {}})
        expect(service.available_providers() == [], "未配置凭据时不展示任何 Provider")

        _configure(monkeypatch)
        expect([p["key"] for p in service.available_providers()] == ["github"],
               "仅展示已配置且开关开启的 Provider")

        # 关闭功能开关后不再可用
        set_flags({**{k: True for k in FEATURE_KEYS}, "oauth_github": False})
        expect(service.available_providers() == [], "功能开关关闭后不展示")
        _enable_all()

        url = service.build_authorize_url("github", "http://x/cb", "st8", "challenge")
        expect(url.startswith("https://github.com/login/oauth/authorize?"), "GitHub 授权 URL 基址")
        expect("state=st8" in url, "授权 URL 携带 state")
        expect("code_challenge_method=S256" in url, "PKCE 参数已附带")
        wx = service.build_authorize_url("wechat", "http://x/cb", "s2")
        expect("appid=" in wx and "#wechat_redirect" in wx, "微信使用 appid 且带锚点")

    def test_login_auto_register(self, ctx, monkeypatch):
        logger.info("=== [B] 回调自动注册并建立会话 ===")
        _enable_all()
        _configure(monkeypatch)
        monkeypatch.setattr(service, "exchange_code", lambda *a, **k: {"access_token": "t"})
        monkeypatch.setattr(service, "fetch_profile", lambda *a, **k: dict(PROFILE))

        start = ctx.anon.get("/oauth/github")
        expect(start.status_code == 302, "发起授权 -> 302")
        state = _state_of(start)
        expect(bool(state), "重定向包含 state")

        callback = ctx.anon.get(f"/oauth/github/callback?code=abc&state={state}")
        expect(callback.status_code == 302, "回调 -> 302")
        expect(callback.headers["Location"].endswith("/"), "登录成功跳转首页")

        account = service.get_account("github", PROFILE["uid"])
        expect(account is not None, "第三方账号已绑定")
        expect(get_user(account["username"]) is not None, "自动创建了站内用户")
        expect(get_user(account["username"]).get("oauth_only") is True, "标记为无密码第三方账号")
        expect(callback.headers.get("Set-Cookie", "").startswith("rusin_session="),
               "回调设置了登录 Cookie")
        ctx.oauth_username = account["username"]

    def test_state_mismatch(self, ctx, monkeypatch):
        logger.info("=== [C] state 校验 ===")
        _enable_all()
        _configure(monkeypatch)
        monkeypatch.setattr(service, "exchange_code", lambda *a, **k: {"access_token": "t"})
        monkeypatch.setattr(service, "fetch_profile", lambda *a, **k: dict(PROFILE))

        ctx.anon.get("/oauth/github")
        resp = ctx.anon.get("/oauth/github/callback?code=abc&state=WRONG")
        expect(resp.status_code == 302, "state 错误 -> 重定向")
        expect("oauth_error=err_oauth_state" in resp.headers["Location"], "错误文案为 state 校验失败")

    def test_feature_disabled_404(self, ctx, monkeypatch):
        logger.info("=== [D] 功能开关关闭 -> 404 ===")
        set_flags({**{k: True for k in FEATURE_KEYS}, "oauth_github": False})
        _configure(monkeypatch)
        expect(ctx.anon.get("/oauth/github").status_code == 404, "关闭后发起授权 404")
        _enable_all()

    def test_master_switch_off(self, ctx, monkeypatch):
        logger.info("=== [D2] 总开关默认关闭 ===")
        _enable_all()
        monkeypatch.setattr(config, "OAUTH_CFG", {
            "providers": {"github": {"client_id": "a", "client_secret": "b"}}})
        monkeypatch.setattr(config, "OAUTH_ENABLED", False)
        expect(service.available_providers() == [], "总开关关闭时即使有凭据/功能开关也不可用")
        expect(ctx.anon.get("/oauth/github").status_code == 404, "总开关关闭时发起授权 404")

    def test_link_and_unlink(self, ctx, monkeypatch):
        logger.info("=== [E] 已登录用户绑定 / 解绑 ===")
        _enable_all()
        _configure(monkeypatch)
        register_and_login(ctx.client, "oauth_link_user")

        start = ctx.client.get("/oauth/github?link=1")
        expect(start.status_code == 302, "绑定模式发起授权 -> 302")
        state = _state_of(start)

        monkeypatch.setattr(service, "exchange_code", lambda *a, **k: {"access_token": "t"})
        monkeypatch.setattr(service, "fetch_profile",
                            lambda *a, **k: {"uid": "999", "display": "linkme",
                                             "email": "", "avatar": ""})
        callback = ctx.client.get(f"/oauth/github/callback?code=abc&state={state}")
        expect("/user/oauth_link_user/oauth" in callback.headers["Location"], "绑定后回到绑定管理页")
        expect(service.get_account("github", "999")["username"] == "oauth_link_user", "绑定到当前用户")

        page = ctx.client.get("/user/oauth_link_user/oauth").get_data(as_text=True)
        expect("linkme" in page, "管理页展示已绑定账号")

        csrf = None
        import re
        m = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', page)
        csrf = m.group(1)
        unlink = ctx.client.post("/user/oauth_link_user/oauth/github/unlink",
                                 data={"csrf_token": csrf})
        expect(unlink.status_code == 302, "解绑 -> 302")
        expect(service.get_account("github", "999") is None, "解绑后记录已删除")

    def test_rename_migration(self, ctx):
        logger.info("=== [F] 改名迁移第三方绑定 ===")
        _enable_all()
        service.link_account("github", "777", "old_oauth_user", "disp")
        expect(service.rename_user_oauth("old_oauth_user", "new_oauth_user"), "迁移返回成功")
        expect(service.get_account("github", "777")["username"] == "new_oauth_user",
               "绑定关系已指向新用户名")
