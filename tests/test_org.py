"""组织功能端到端测试（pytest + logging）。

覆盖：
- 创建组织（owner 自动添加）
- 公开加入 / 邀请码加入 / 申请审批加入
- 角色权限（owner / admin / member）
- 组织笔记 CRUD
- 成员管理（提升/降级/移除）
- 邀请码生成与过期
- Owner 不能直接退出

运行：``pytest tests/test_org.py``
"""
from __future__ import annotations

import logging
import time

import pytest

from app.auth import hash_token
from app.feature_flags import feature_enabled, set_flags
from app.store import (
    add_org_member,
    approve_join_request,
    create_join_request,
    create_org,
    create_org_invite,
    delete_org,
    get_org,
    get_org_member_role,
    get_org_members,
    get_user_orgs,
    org_invite_join,
    org_invites,
    org_join_requests,
    org_public_join,
    register_user,
    reject_join_request,
    remove_org_member,
    store_session,
    update_org_member_role,
    validate_org_invite,
)
from support import expect

logger = logging.getLogger("rusin.tests.org")


def _login_as(app, username: str, token: str):
    """创建带会话 Cookie 的测试客户端。"""
    store_session(hash_token(token), {"username": username, "created_at": time.time()})
    client = app.test_client()
    client.set_cookie("rusin_session", token)
    return client


@pytest.fixture(autouse=True, scope="class")
def csrf_disabled(ctx):
    """组织测试直接使用 store 层构造会话，HTTP POST 无需 CSRF token。"""
    ctx.app.config["WTF_CSRF_ENABLED"] = False


class TestOrg:
    """组织 API 与 HTTP 路由（同一测试类内共享组织数据）。"""

    def test_create_org(self, ctx):
        logger.info("=== 1. 测试数据隔离 / 创建组织 ===")
        set_flags({"orgs": True})
        assert feature_enabled("orgs"), "orgs 功能未启用"
        logger.info("orgs 功能已启用")

        register_user("test_alice", {"salt": "0011" * 8, "hash": "pbkdf2_sha256$1$deadbeef"})
        register_user("test_bob", {"salt": "0022" * 8, "hash": "pbkdf2_sha256$1$deadbeef"})
        register_user("test_carol", {"salt": "0033" * 8, "hash": "pbkdf2_sha256$1$deadbeef"})
        register_user("test_dave", {"salt": "0044" * 8, "hash": "pbkdf2_sha256$1$deadbeef"})

        expect(create_org("test_team1", "Test Team 1", "test_alice", "A test org", "invite"),
               "创建组织成功")
        expect(not create_org("test_team1", "Duplicate", "test_bob", "", "invite"),
               "组织已存在时创建失败")
        expect(get_org_member_role("test_team1", "test_alice") == "owner", "Alice 是 owner")
        expect(get_org("test_team1") is not None and get_org("test_team1")["name"] == "Test Team 1",
               "get_org 返回正确数据")
        expect(get_org("nonexistent_org") is None, "get_org 不存在返回 None")
        expect("test_team1" not in get_user_orgs("test_bob"), "新组织不在用户组织列表中（Bob）")
        expect("test_team1" in get_user_orgs("test_alice"), "Alice 在用户组织列表中")

    def test_join_modes(self, ctx):
        logger.info("=== 2. 三种加入方式 ===")
        create_org("test_public", "Public Org", "test_alice", "", "public")
        expect(get_org_member_role("test_public", "test_alice") == "owner",
               "Alice 是 test_public 的 owner")
        expect(org_public_join("test_public", "test_bob"), "Bob 公开加入成功")
        expect(not org_public_join("test_public", "test_bob"), "Bob 不能重复加入")
        expect(get_org_member_role("test_public", "test_bob") == "member", "Bob 是 member 角色")

        ctx.invite_code = create_org_invite("test_team1", "test_alice", "invite", expires_days=7)
        expect(ctx.invite_code and len(ctx.invite_code) == 32, "邀请码已生成")
        expect(validate_org_invite(ctx.invite_code) is not None, "邀请码可验证")
        expect(org_invite_join(ctx.invite_code, "test_bob"), "Bob 通过邀请码加入")
        expect("test_team1" in get_user_orgs("test_bob"), "Bob 已加入 test_team1")

        create_org("test_approve", "Approve Org", "test_alice", "", "approve")
        expect(create_join_request("test_approve", "test_carol", "Please let me in"),
               "Carol 创建加入申请")
        expect(not create_join_request("test_approve", "test_carol", "again"), "重复申请失败")

    def test_role_hierarchy(self, ctx):
        logger.info("=== 3. 角色权限层级 ===")
        expect(update_org_member_role("test_team1", "test_bob", "admin"), "Alice 升级 Bob 为 admin")
        expect(get_org_member_role("test_team1", "test_bob") == "admin", "Bob 现在是 admin")
        expect(not update_org_member_role("test_team1", "test_alice", "admin"),
               "不能修改 owner 角色")
        expect(get_org_member_role("test_team1", "test_alice") == "owner", "Alice 仍然是 owner")
        add_org_member("test_team1", "test_dave", "member")
        expect(get_org_member_role("test_team1", "test_dave") == "member", "Dave 是 member")

    def test_invite_expiry(self, ctx):
        logger.info("=== 4. 邀请码过期测试 ===")
        short_invite = create_org_invite("test_team1", "test_alice", "invite", expires_days=1)
        expect(short_invite is not None, "短期邀请码已生成")
        org_invites[short_invite]["expires_at"] = time.time() - 1
        expect(validate_org_invite(short_invite) is None, "过期邀请码验证失败")
        expect(not org_invite_join(short_invite, "test_carol"), "过期邀请码不能加入")
        org_invites[short_invite]["expires_at"] = time.time() + 86400

    def test_approval(self, ctx):
        logger.info("=== 5. 审批通过/拒绝 ===")
        expect(approve_join_request("test_approve", "test_carol"), "Alice 批准 Carol 申请")
        expect(get_org_member_role("test_approve", "test_carol") == "member", "Carol 现在是 member")

        create_join_request("test_approve", "test_dave", "")
        expect("test_dave" in org_join_requests.get("test_approve", {}), "Dave 申请已创建")
        expect(reject_join_request("test_approve", "test_dave"), "Alice 拒绝 Dave 申请")
        expect(get_org_member_role("test_approve", "test_dave") is None, "Dave 仍未加入")

    def test_remove_member(self, ctx):
        logger.info("=== 6. 移除成员 ===")
        expect(remove_org_member("test_team1", "test_dave"), "Alice 移除 Dave")
        expect("test_dave" not in get_org_members("test_team1"), "Dave 已不在成员列表")
        expect(not remove_org_member("test_team1", "test_alice"), "不能移除 owner")

    def test_delete_org(self, ctx):
        logger.info("=== 7. 删除组织 ===")
        create_org("test_delete_me", "To Delete", "test_alice", "", "invite")
        expect(get_org("test_delete_me") is not None, "组织已创建")
        expect(delete_org("test_delete_me"), "Alice 删除组织")
        expect(get_org("test_delete_me") is None, "组织已删除")
        expect("test_delete_me" not in get_org_members("test_delete_me"), "成员关系已清理")

    def test_http_routes(self, ctx):
        logger.info("=== 8. Flask 路由测试（HTTP） ===")
        client = _login_as(ctx.app, "test_alice", "test_token_alice_xyz")

        expect(client.get("/org/mine").status_code == 200, "GET /org/mine 返回 200")
        expect(client.get("/org/create").status_code == 200, "GET /org/create 返回 200")
        expect(client.get("/org/test_team1").status_code == 200, "GET /org/test_team1 返回 200")
        expect(client.get("/org/test_team1/notes").status_code == 200,
               "GET /org/test_team1/notes 返回 200 (owner)")
        expect(client.get("/org/test_team1/members").status_code == 200,
               "GET /org/test_team1/members 返回 200")
        expect(client.get("/org/test_team1/settings").status_code == 200,
               "GET /org/test_team1/settings 返回 200 (owner)")
        expect(client.get("/org/test_team1/invites").status_code == 200,
               "GET /org/test_team1/invites 返回 200")

        response = client.post("/org/create", data={
            "org_name": "test_http_org",
            "name": "HTTP Created",
            "description": "Created via HTTP",
            "join_policy": "invite",
        })
        expect(response.status_code in (200, 302), "POST /org/create 重定向（成功）")
        expect(get_org("test_http_org") is not None, "test_http_org 已创建")
        expect(get_org_member_role("test_http_org", "test_alice") == "owner",
               "Alice 是 test_http_org owner")

        response = client.post("/org/create", data={
            "org_name": "invalid name with spaces!",
            "name": "Bad Name",
            "join_policy": "invite",
        })
        expect(response.status_code == 200 and (
            b"Invalid" in response.data or b"error" in response.data.lower()),
            "非法 org_name 被拒绝")

        response = client.post("/org/test_team1/notes/new",
                               data={"content": "# Hello Org\n\nThis is a test."})
        expect(response.status_code == 302, "POST 创建组织笔记重定向")
        response = client.get("/org/test_team1/notes")
        expect(response.status_code == 200 and (
            b"Hello" in response.data or b"test" in response.data.lower()),
            "笔记列表显示新笔记")

        bob = _login_as(ctx.app, "test_bob", "test_token_bob_xyz")
        expect(bob.get("/org/test_team1/settings").status_code == 200,
               "Bob (admin) 可访问 settings")

        carol = _login_as(ctx.app, "test_carol", "test_token_carol_xyz")
        expect(carol.get("/org/test_public/settings").status_code == 403,
               "Carol (member) 不能访问 settings (期望 403)")
        expect(carol.get("/org/test_approve/notes").status_code == 200,
               "Carol 可访问 test_approve 笔记列表")
        expect(carol.get("/org/test_team1/notes").status_code == 403,
               "Carol 不能访问 test_team1 笔记 (期望 403)")

        anon = ctx.app.test_client()
        expect(anon.get("/org/mine").status_code == 401, "未登录访问 /org/mine 返回 401")

        set_flags({"orgs": False})
        expect(client.get("/org/test_team1").status_code == 404, "orgs 关闭时访问返回 404")
        set_flags({"orgs": True})

    def test_invite_url_join(self, ctx):
        logger.info("=== 9. 邀请码通过 URL 加入 ===")
        ctx.test_invite = create_org_invite("test_team1", "test_alice", "invite", expires_days=7)
        expect(ctx.test_invite is not None, "新邀请码已创建")
        dave = _login_as(ctx.app, "test_dave", "test_token_dave_xyz")
        response = dave.post(f"/org/join/{ctx.test_invite}")
        expect(response.status_code in (200, 302), "Dave 通过邀请码加入成功")
        expect("test_team1" in get_user_orgs("test_dave"), "Dave 已加入 test_team1")

    def test_owner_leave_protection(self, ctx):
        logger.info("=== 10. Owner 退出保护 ===")
        alice = _login_as(ctx.app, "test_alice", "test_token_alice_xyz")
        response = alice.post("/org/test_team1/leave")
        expect(response.status_code == 400, "Owner 退出应被拒绝 (400)")
        expect(get_org_member_role("test_team1", "test_alice") == "owner",
               "Alice 仍在 test_team1")
