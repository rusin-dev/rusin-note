"""管理员用户名不可抢注/不可改名（pytest + logging）。

管理员身份绑定 config.json 的 admin_users / RUSIN_ADMIN；若允许公开注册
同名账号，任何人都能在管理员注册前抢占该名字并直接获得管理权限。
"""
from __future__ import annotations

import logging

from app.core import config
from app.core.notes import validate_username
from app.core.store import get_user
from support import (
    DEFAULT_PASSWORD, csrf_of, expect, register, register_and_login,
)

logger = logging.getLogger("rusin.tests.admin_identity")


def _rename(client, username: str, new_name: str):
    html = client.get(f"/user/{username}/settings").get_data(as_text=True)
    return client.post(f"/user/{username}/settings", data={
        "action": "username",
        "new_username": new_name,
        "password": DEFAULT_PASSWORD,
        "csrf_token": csrf_of(html),
    })


class TestAdminIdentity:
    def test_admin_name_cannot_register(self, ctx, monkeypatch):
        logger.info("=== [A] 管理员用户名禁止公开注册 ===")
        monkeypatch.setattr(config, "ADMIN_USERS", frozenset({"ops_admin"}))
        expect(not validate_username("ops_admin"), "validate_username 拒绝管理员名")
        expect(not validate_username("OPS_ADMIN"), "大小写变体同样拒绝")
        resp = register(ctx.client, "ops_admin")
        expect(resp.status_code == 400, "注册管理员名返回 400")
        expect(get_user("ops_admin") is None, "管理员账号未被创建")

    def test_rename_into_admin_name_rejected(self, ctx, monkeypatch):
        logger.info("=== [B] 改名不能占用管理员用户名 ===")
        register_and_login(ctx.client, "normaluser")
        monkeypatch.setattr(config, "ADMIN_USERS", frozenset({"locked_admin"}))
        resp = _rename(ctx.client, "normaluser", "locked_admin")
        expect(resp.status_code != 302, "改名被拒绝（未重定向）")
        expect(get_user("normaluser") is not None, "原账号仍存在")
        expect(get_user("locked_admin") is None, "管理员名未被占用")

    def test_admin_cannot_rename_away(self, ctx, monkeypatch):
        logger.info("=== [C] 管理员账号不可改名（避免权限丢失） ===")
        register_and_login(ctx.client, "admin_user")
        monkeypatch.setattr(config, "ADMIN_USERS", frozenset({"admin_user"}))
        resp = _rename(ctx.client, "admin_user", "admin_renamed")
        expect(resp.status_code != 302, "管理员改名被拒绝")
        expect(get_user("admin_user") is not None, "管理员原账号保留")
        expect(get_user("admin_renamed") is None, "新用户名未被创建")
