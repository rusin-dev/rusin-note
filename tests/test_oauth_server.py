"""受限 OIDC Provider 的端到端与协议测试。"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import re
import urllib.parse

from app.core import config
from app.core.feature_flags import FEATURE_KEYS, set_flags
from support import csrf_of, expect, login, logout, register_and_login

logger = logging.getLogger("rusin.tests.oauth_server")

REDIRECT_URI = "https://client.example/callback"


def _enable_oidc(monkeypatch):
    set_flags({**{key: True for key in FEATURE_KEYS}, "oauth_server": True})
    monkeypatch.setattr(config, "OAUTH_SERVER_ISSUER", "")


def _client(monkeypatch, public=False):
    from app.apps.oauth_server import service
    return service.create_client(
        name="Example App",
        redirect_uris=[REDIRECT_URI],
        client_type="public" if public else "confidential",
        scopes=["openid", "profile", "email"],
        created_by="admin",
    )


def _authorize_params(client_id, verifier, state="state-1", scope="openid profile email"):
    from app.apps.oauth_server import oidc
    return {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "scope": scope,
        "state": state,
        "nonce": "nonce-1",
        "code_challenge": oidc.pkce_challenge(verifier),
        "code_challenge_method": "S256",
    }


def _b64decode(value):
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _verify_rs256(jwt_value, jwk):
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding, rsa
    header, payload, signature = jwt_value.split(".")
    key = rsa.RSAPublicNumbers(
        int.from_bytes(_b64decode(jwk["e"]), "big"),
        int.from_bytes(_b64decode(jwk["n"]), "big"),
    ).public_key()
    key.verify(_b64decode(signature), f"{header}.{payload}".encode("ascii"),
               padding.PKCS1v15(), hashes.SHA256())
    return json.loads(_b64decode(payload))


class TestOidcService:
    def test_client_secret_is_hashed_and_redirect_exact(self, data_dir):
        from app.apps.oauth_server import oidc, service
        client, secret = service.create_client(
            "Demo", [REDIRECT_URI], "confidential",
            ["openid", "profile"], "admin")
        stored = service.get_client(client["client_id"])
        expect(secret and secret not in json.dumps(stored), "Client Secret 不明文存储")
        expect(service.verify_client_secret(stored, secret), "Client Secret 可校验")
        expect(not service.verify_client_secret(stored, secret + "x"), "错误 Secret 被拒绝")
        expect(oidc.valid_redirect_uri(stored, REDIRECT_URI), "回调地址精确匹配")
        expect(not oidc.valid_redirect_uri(stored, REDIRECT_URI + "/evil"), "禁止回调地址前缀匹配")

    def test_pkce_s256(self):
        from app.apps.oauth_server import oidc
        verifier, challenge = oidc.make_pkce()
        expect(oidc.verify_pkce(verifier, challenge), "正确 PKCE verifier 通过")
        expect(not oidc.verify_pkce(verifier + "x", challenge), "错误 PKCE verifier 被拒绝")


class TestOidcFlow:
    def test_authorization_code_id_token_userinfo_and_revoke(self, ctx, monkeypatch):
        from app.apps.oauth_server import oidc, service
        logger.info("=== OIDC Authorization Code + PKCE 全流程 ===")
        _enable_oidc(monkeypatch)
        client, secret = _client(monkeypatch)
        verifier, _ = oidc.make_pkce()
        register_and_login(ctx.client, "oidc_user")

        consent = ctx.client.get("/oauth/authorize",
                                 query_string=_authorize_params(client["client_id"], verifier))
        html = consent.get_data(as_text=True)
        expect(consent.status_code == 200 and "Example App" in html, "展示应用授权同意页")
        request_match = re.search(r'name="request_id"[^>]*value="([^"]+)"', html)
        expect(bool(request_match), "同意页包含一次性 request_id")
        approved = ctx.client.post("/oauth/authorize", data={
            "csrf_token": csrf_of(html),
            "request_id": request_match.group(1),
            "decision": "approve",
        })
        expect(approved.status_code == 302, "同意后重定向回调地址")
        parsed = urllib.parse.urlparse(approved.headers["Location"])
        query = urllib.parse.parse_qs(parsed.query)
        expect(parsed.scheme == "https" and parsed.netloc == "client.example",
               "只重定向到已注册回调")
        expect(query.get("state") == ["state-1"] and query.get("code"), "回调携带 state 与 code")
        code = query["code"][0]

        basic = base64.b64encode(f"{client['client_id']}:{secret}".encode()).decode()
        token_resp = ctx.client.post(
            "/oauth/token",
            data={
                "grant_type": "authorization_code", "code": code,
                "redirect_uri": REDIRECT_URI, "code_verifier": verifier,
            },
            headers={"Authorization": f"Basic {basic}"})
        tokens = token_resp.get_json()
        expect(token_resp.status_code == 200 and tokens.get("access_token"),
               "授权码换取 access token")
        expect(tokens.get("token_type") == "Bearer" and tokens.get("id_token"),
               "返回 Bearer 与 ID Token")
        expect(not tokens.get("refresh_token"), "首期不签发 refresh token")

        jwk = service.signing_public_jwk()
        claims = _verify_rs256(tokens["id_token"], jwk)
        expect(claims["aud"] == client["client_id"] and claims["nonce"] == "nonce-1",
               "ID Token 包含 aud 与 nonce")
        expect(claims["iss"].startswith("http://localhost"), "ID Token issuer")
        expect(jwk["kty"] == "RSA" and jwk["alg"] == "RS256" and jwk["kid"],
               "JWKS 公钥可验证 RS256 ID Token")

        userinfo = ctx.client.get(
            "/oauth/userinfo",
            headers={"Authorization": "Bearer " + tokens["access_token"]})
        profile = userinfo.get_json()
        expect(userinfo.status_code == 200 and profile["preferred_username"] == "oidc_user",
               "userinfo 返回 profile scope 身份")
        expect("password" not in json.dumps(profile), "userinfo 不泄露敏感字段")

        reuse = ctx.client.post("/oauth/token", data={
            "grant_type": "authorization_code", "code": code,
            "redirect_uri": REDIRECT_URI, "code_verifier": verifier,
        }, headers={"Authorization": f"Basic {basic}"})
        expect(reuse.status_code == 400 and reuse.get_json()["error"] == "invalid_grant",
               "授权码只能使用一次")

        revoked = ctx.client.post("/oauth/revoke", data={
            "token": tokens["access_token"], "client_id": client["client_id"]},
            headers={"Authorization": f"Basic {basic}"})
        expect(revoked.status_code == 200, "revoke 成功")
        after = ctx.client.get(
            "/oauth/userinfo",
            headers={"Authorization": "Bearer " + tokens["access_token"]})
        expect(after.status_code == 401, "撤销后 access token 失效")

    def test_deny_returns_access_denied_without_code(self, ctx, monkeypatch):
        from app.apps.oauth_server import oidc
        logger.info("=== 拒绝授权 ===")
        _enable_oidc(monkeypatch)
        client, _ = _client(monkeypatch)
        verifier, _ = oidc.make_pkce()
        register_and_login(ctx.client, "oidc_deny")
        html = ctx.client.get(
            "/oauth/authorize",
            query_string=_authorize_params(client["client_id"], verifier)).get_data(as_text=True)
        request_id = re.search(r'name="request_id"[^>]*value="([^"]+)"', html).group(1)
        denied = ctx.client.post("/oauth/authorize", data={
            "csrf_token": csrf_of(html), "request_id": request_id,
            "decision": "deny"})
        query = urllib.parse.parse_qs(
            urllib.parse.urlparse(denied.headers["Location"]).query)
        expect(denied.status_code == 302 and query.get("error") == ["access_denied"],
               "拒绝授权返回 access_denied")
        expect("code" not in query and query.get("state") == ["state-1"],
               "拒绝时返回 state 且不签发 code")

    def test_wrong_pkce_is_rejected(self, ctx, monkeypatch):
        from app.apps.oauth_server import oidc, service
        logger.info("=== PKCE 校验失败 ===")
        _enable_oidc(monkeypatch)
        client, secret = _client(monkeypatch)
        verifier, _ = oidc.make_pkce()
        register_and_login(ctx.client, "oidc_pkce")
        html = ctx.client.get(
            "/oauth/authorize",
            query_string=_authorize_params(client["client_id"], verifier)).get_data(as_text=True)
        request_id = re.search(r'name="request_id"[^>]*value="([^"]+)"', html).group(1)
        approved = ctx.client.post("/oauth/authorize", data={
            "csrf_token": csrf_of(html), "request_id": request_id,
            "decision": "approve"})
        code = urllib.parse.parse_qs(
            urllib.parse.urlparse(approved.headers["Location"]).query)["code"][0]
        basic = base64.b64encode(f"{client['client_id']}:{secret}".encode()).decode()
        response = ctx.client.post("/oauth/token", data={
            "grant_type": "authorization_code", "code": code,
            "redirect_uri": REDIRECT_URI, "code_verifier": verifier + "wrong",
        }, headers={"Authorization": f"Basic {basic}"})
        expect(response.status_code == 400
               and response.get_json()["error"] == "invalid_grant",
               "错误 code_verifier 无法换取 Token")

    def test_authorize_requires_login_and_returns(self, ctx, monkeypatch):
        from app.apps.oauth_server import oidc
        logger.info("=== authorize 登录回跳 ===")
        _enable_oidc(monkeypatch)
        client, _ = _client(monkeypatch)
        verifier, _ = oidc.make_pkce()
        register_and_login(ctx.anon, "oidc_return")
        logout(ctx.anon)
        params = _authorize_params(client["client_id"], verifier)
        start = ctx.anon.get("/oauth/authorize", query_string=params)
        expect(start.status_code == 302 and "/login" in start.headers["Location"],
               "未登录先跳登录页")
        login(ctx.anon, "oidc_return")
        resumed = ctx.anon.get("/oauth/authorize", query_string=params)
        expect(resumed.status_code == 200 and "Example App" in resumed.get_data(as_text=True),
               "登录后回到授权同意页")

    def test_discovery_jwks_and_route_priority(self, ctx, monkeypatch):
        _enable_oidc(monkeypatch)
        discovery = ctx.anon.get("/.well-known/openid-configuration")
        data = discovery.get_json()
        expect(discovery.status_code == 200 and data["authorization_endpoint"].endswith("/oauth/authorize"),
               "暴露 OIDC discovery")
        expect("/oauth/token" in data["token_endpoint"], "discovery 包含 token 端点")
        expect(data["code_challenge_methods_supported"] == ["S256"], "仅支持 S256 PKCE")
        jwks = ctx.anon.get("/.well-known/jwks.json").get_json()
        expect(jwks["keys"] and jwks["keys"][0]["kty"] == "RSA", "JWKS 暴露 RSA 公钥")
        route = ctx.anon.get("/oauth/authorize")
        expect(route.status_code != 404, "/oauth/authorize 不被快捷登录动态路由吞掉")


class TestOidcIdentity:
    def test_subject_survives_username_rename(self, data_dir):
        from app.apps.oauth_server import service
        original = service.subject_for("old_oidc_subject")
        expect(service.rename_user_oauth_server("old_oidc_subject", "new_oidc_subject"),
               "改名迁移 OIDC 数据")
        expect(service.subject_for("new_oidc_subject") == original,
               "第三方应用看到的 sub 保持稳定")

    def test_login_next_rejects_external_redirect(self):
        from app.core.login_next import safe_path
        expect(safe_path("/oauth/authorize?x=1") == "/oauth/authorize?x=1",
               "允许站内回跳")
        expect(safe_path("https://evil.example/") == "/", "拒绝绝对外站地址")
        expect(safe_path("//evil.example/") == "/", "拒绝协议相对地址")
        expect(safe_path("/\\evil.example/") == "/", "拒绝反斜杠绕过")


class TestOidcAdmin:
    def test_admin_client_registration(self, ctx, monkeypatch):
        logger.info("=== 管理员注册 OAuth 客户端 ===")
        _enable_oidc(monkeypatch)
        monkeypatch.setattr(config, "ADMIN_USERS", ["oidc_admin"])
        register_and_login(ctx.client, "oidc_admin")
        page = ctx.client.get("/admin/oauth-clients")
        html = page.get_data(as_text=True)
        expect(page.status_code == 200 and "OAuth" in html, "管理员可访问客户端管理页")
        created = ctx.client.post("/admin/oauth-clients", data={
            "csrf_token": csrf_of(html),
            "action": "create",
            "name": "Admin Created",
            "redirect_uris": REDIRECT_URI,
            "client_type": "confidential",
            "scope_profile": "1",
            "scope_email": "1",
        })
        expect(created.status_code == 302, "创建客户端成功")
        listing = ctx.client.get(created.headers["Location"]).get_data(as_text=True)
        expect("Admin Created" in listing, "客户端出现在管理列表")

    def test_non_admin_gets_404(self, ctx, monkeypatch):
        _enable_oidc(monkeypatch)
        monkeypatch.setattr(config, "ADMIN_USERS", [])
        register_and_login(ctx.client, "oidc_plain")
        expect(ctx.client.get("/admin/oauth-clients").status_code == 404,
               "非管理员看不到客户端管理页")
