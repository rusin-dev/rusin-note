"""Host 头污染防护：OAuth 回调与 OIDC issuer 只取配置的站点基址。"""
from __future__ import annotations

import logging
import urllib.parse

from app.core import config
from app.core.feature_flags import FEATURE_KEYS, set_flags
from support import expect

logger = logging.getLogger("rusin.tests.host_pinning")


def _configure_oauth(monkeypatch, provider="github"):
    monkeypatch.setattr(config, "OAUTH_ENABLED", True)
    monkeypatch.setattr(config, "OAUTH_CFG", {
        "providers": {provider: {"client_id": "cid", "client_secret": "secret"}},
    })


class TestHostPinning:
    def test_oidc_issuer_ignores_host_header(self, ctx, monkeypatch):
        logger.info("=== [A] OIDC issuer 不受 Host 头影响 ===")
        set_flags({**{k: True for k in FEATURE_KEYS}, "oauth_server": True})
        monkeypatch.setattr(config, "OAUTH_SERVER_ISSUER", "")
        monkeypatch.setattr(config, "SITE_BASE_URL", "https://notes.example")
        resp = ctx.client.get("/.well-known/openid-configuration",
                              headers={"Host": "evil.example"})
        expect(resp.status_code == 200, "discovery 可访问")
        data = resp.get_json()
        expect(data["issuer"] == "https://notes.example", "issuer 取自固定站点基址")
        expect("evil.example" not in data["issuer"], "issuer 不含攻击者 Host")
        expect(all("evil.example" not in data[k] for k in
                   ("jwks_uri", "token_endpoint", "userinfo_endpoint")),
               "端点地址不随 Host 漂移")

    def test_oidc_without_stable_issuer_refuses(self, ctx, monkeypatch):
        logger.info("=== [B] 未配置 issuer/base URL 时拒绝服务 ===")
        set_flags({**{k: True for k in FEATURE_KEYS}, "oauth_server": True})
        monkeypatch.setattr(config, "OAUTH_SERVER_ISSUER", "")
        monkeypatch.setattr(config, "SITE_BASE_URL", "")
        resp = ctx.client.get("/.well-known/openid-configuration",
                              headers={"Host": "evil.example"})
        expect(resp.status_code == 503, "无稳定 issuer 时 503，不输出 Host 推导值")

    def test_oauth_redirect_uri_uses_site_base(self, ctx, monkeypatch):
        logger.info("=== [C] OAuth 回调地址固定为站点基址 ===")
        set_flags({k: True for k in FEATURE_KEYS})
        _configure_oauth(monkeypatch)
        monkeypatch.setattr(config, "SITE_BASE_URL", "https://notes.example")
        resp = ctx.client.get("/oauth/github", headers={"Host": "evil.example"})
        expect(resp.status_code == 302, "授权跳转 302")
        query = urllib.parse.urlparse(resp.headers["Location"]).query
        redirect_uri = urllib.parse.parse_qs(query).get("redirect_uri", [""])[0]
        expect(redirect_uri == "https://notes.example/oauth/github/callback",
               "redirect_uri 不随 Host 变化")

    def test_oauth_unavailable_without_site_base(self, ctx, monkeypatch):
        logger.info("=== [D] 未配置站点基址时 OAuth 不可用 ===")
        set_flags({k: True for k in FEATURE_KEYS})
        _configure_oauth(monkeypatch)
        monkeypatch.setattr(config, "SITE_BASE_URL", "")
        expect(ctx.client.get("/oauth/github", headers={"Host": "evil.example"}).status_code == 404,
               "直接访问 Provider 入口 404")
