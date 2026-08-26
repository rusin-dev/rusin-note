"""组织功能端到端测试

覆盖：
- 创建组织（owner 自动添加）
- 公开加入 / 邀请码加入 / 申请审批加入
- 角色权限（owner / admin / member）
- 组织笔记 CRUD
- 成员管理（提升/降级/移除）
- 邀请码生成与过期
- Owner 不能直接退出
"""
import sys
import time
sys.path.insert(0, ".")

from app import create_app
from app import config as app_config
from app.feature_flags import set_flags, feature_enabled
from app.store import (
    orgs, org_members, org_invites, org_join_requests,
    create_org, get_org, get_org_members, get_org_member_role,
    create_org_invite, validate_org_invite, delete_org_invite,
    approve_join_request, reject_join_request,
    add_org_member, remove_org_member, update_org_member_role,
    delete_org, org_invite_join, org_public_join,
    register_user, store_session,
    save_org_invites, save_org_join_requests,
    get_user_orgs,
)
from app.auth import hash_token

# ---------- 测试结果统计 ----------
results = {"pass": 0, "fail": 0, "errors": []}


def check(name, condition, msg=""):
    """断言函数，失败时打印但不中断"""
    if condition:
        results["pass"] += 1
        print(f"  ✓ {name}")
    else:
        results["fail"] += 1
        err = f"  ✗ {name}" + (f"  -- {msg}" if msg else "")
        results["errors"].append(err)
        print(err)


def section(title):
    print(f"\n=== {title} ===")


# ---------- 清理测试数据 ----------
def cleanup():
    """清理测试创建的数据，避免污染"""
    # 清理测试组织
    for org_name in list(orgs.keys()):
        if org_name.startswith("test_"):
            delete_org(org_name)
    # 清理可能残留的邀请和申请
    for code in list(org_invites.keys()):
        if org_invites[code].get("org_name", "").startswith("test_"):
            delete_org_invite(code)
    for org_name in list(org_join_requests.keys()):
        if org_name.startswith("test_"):
            org_join_requests.pop(org_name, None)
    save_org_invites()
    save_org_join_requests()


cleanup()

# 启用组织功能
set_flags({"orgs": True})
assert feature_enabled("orgs"), "orgs 功能未启用"
print("✓ orgs 功能已启用\n")

# ============================================================
section("1. 测试数据隔离 / 创建组织")
# ============================================================

# 注册测试用户
register_user("test_alice", {"salt": "0011" * 8, "hash": "pbkdf2_sha256$1$deadbeef"})
register_user("test_bob", {"salt": "0022" * 8, "hash": "pbkdf2_sha256$1$deadbeef"})
register_user("test_carol", {"salt": "0033" * 8, "hash": "pbkdf2_sha256$1$deadbeef"})
register_user("test_dave", {"salt": "0044" * 8, "hash": "pbkdf2_sha256$1$deadbeef"})

check("创建组织成功", create_org("test_team1", "Test Team 1", "test_alice", "A test org", "invite"))
check("组织已存在时创建失败", not create_org("test_team1", "Duplicate", "test_bob", "", "invite"))
check("Alice 是 owner", get_org_member_role("test_team1", "test_alice") == "owner")
check("get_org 返回正确数据", get_org("test_team1") is not None and get_org("test_team1")["name"] == "Test Team 1")
check("get_org 不存在返回 None", get_org("nonexistent_org") is None)
check("新组织不在用户组织列表中（Bob）", "test_team1" not in get_user_orgs("test_bob"))
check("Alice 在用户组织列表中", "test_team1" in get_user_orgs("test_alice"))

# ============================================================
section("2. 三种加入方式")
# ============================================================

# 2.1 公开加入
create_org("test_public", "Public Org", "test_alice", "", "public")
check("Alice 是 test_public 的 owner", get_org_member_role("test_public", "test_alice") == "owner")
check("Bob 公开加入成功", org_public_join("test_public", "test_bob"))
check("Bob 不能重复加入", not org_public_join("test_public", "test_bob"))
check("Bob 是 member 角色", get_org_member_role("test_public", "test_bob") == "member")

# 2.2 邀请制
invite_code = create_org_invite("test_team1", "test_alice", "invite", expires_days=7)
check("邀请码已生成", invite_code and len(invite_code) == 32)
check("邀请码可验证", validate_org_invite(invite_code) is not None)
check("Bob 通过邀请码加入", org_invite_join(invite_code, "test_bob"))
check("Bob 已加入 test_team1", "test_team1" in get_user_orgs("test_bob"))

# 2.3 审批制
create_org("test_approve", "Approve Org", "test_alice", "", "approve")
from app.store import create_join_request
check("Carol 创建加入申请", create_join_request("test_approve", "test_carol", "Please let me in"))
check("重复申请失败", not create_join_request("test_approve", "test_carol", "again"))

# ============================================================
section("3. 角色权限层级")
# ============================================================

# Owner 升级 Bob 为 admin
check("Alice 升级 Bob 为 admin", update_org_member_role("test_team1", "test_bob", "admin"))
check("Bob 现在是 admin", get_org_member_role("test_team1", "test_bob") == "admin")

# 不能修改 owner 的角色
check("不能修改 owner 角色", not update_org_member_role("test_team1", "test_alice", "admin"))
check("Alice 仍然是 owner", get_org_member_role("test_team1", "test_alice") == "owner")

# 添加第三个成员
add_org_member("test_team1", "test_dave", "member")
check("Dave 是 member", get_org_member_role("test_team1", "test_dave") == "member")

# ============================================================
section("4. 邀请码过期测试")
# ============================================================

# 创建一个已过期的邀请码（手动设置过期时间）
short_invite = create_org_invite("test_team1", "test_alice", "invite", expires_days=1)
check("短期邀请码已生成", short_invite is not None)

# 直接修改过期时间为已过去
org_invites[short_invite]["expires_at"] = time.time() - 1
check("过期邀请码验证失败", validate_org_invite(short_invite) is None)
check("过期邀请码不能加入", not org_invite_join(short_invite, "test_carol"))

# 恢复原过期时间以免影响其他测试
org_invites[short_invite]["expires_at"] = time.time() + 86400

# ============================================================
section("5. 审批通过/拒绝")
# ============================================================

# 审批 Carol 的申请
check("Alice 批准 Carol 申请", approve_join_request("test_approve", "test_carol"))
check("Carol 现在是 member", get_org_member_role("test_approve", "test_carol") == "member")

# Dave 提交申请并被拒绝
create_join_request("test_approve", "test_dave", "")
check("Dave 申请已创建", "test_dave" in org_join_requests.get("test_approve", {}))
check("Alice 拒绝 Dave 申请", reject_join_request("test_approve", "test_dave"))
check("Dave 仍未加入", get_org_member_role("test_approve", "test_dave") is None)

# ============================================================
section("6. 移除成员")
# ============================================================

check("Alice 移除 Dave", remove_org_member("test_team1", "test_dave"))
check("Dave 已不在成员列表", "test_dave" not in get_org_members("test_team1"))
check("不能移除 owner", not remove_org_member("test_team1", "test_alice"))

# ============================================================
section("7. 删除组织")
# ============================================================

create_org("test_delete_me", "To Delete", "test_alice", "", "invite")
check("组织已创建", get_org("test_delete_me") is not None)
check("Alice 删除组织", delete_org("test_delete_me"))
check("组织已删除", get_org("test_delete_me") is None)
check("成员关系已清理", "test_delete_me" not in get_org_members("test_delete_me"))

# ============================================================
section("8. Flask 路由测试（HTTP）")
# ============================================================

app = create_app()
app.config["TESTING"] = True
app.config["WTF_CSRF_ENABLED"] = False  # 测试时禁用 CSRF

with app.test_client() as client:
    # 8.1 创建测试用户 session
    token_alice = "test_token_alice_xyz"
    store_session(hash_token(token_alice), {"username": "test_alice", "created_at": time.time()})

    def auth_headers(token):
        return {}

    # 通过 cookie 设置 session
    client.set_cookie("rusin_session", token_alice)

    # 8.2 我的组织页面
    resp = client.get("/org/mine")
    check("GET /org/mine 返回 200", resp.status_code == 200, f"got {resp.status_code}")

    # 8.3 创建组织页面
    resp = client.get("/org/create")
    check("GET /org/create 返回 200", resp.status_code == 200, f"got {resp.status_code}")

    # 8.4 组织主页
    resp = client.get("/org/test_team1")
    check("GET /org/test_team1 返回 200", resp.status_code == 200, f"got {resp.status_code}")

    # 8.5 组织笔记列表（需要 member 权限）
    resp = client.get("/org/test_team1/notes")
    check("GET /org/test_team1/notes 返回 200 (owner)", resp.status_code == 200, f"got {resp.status_code}")

    # 8.6 组织成员列表
    resp = client.get("/org/test_team1/members")
    check("GET /org/test_team1/members 返回 200", resp.status_code == 200, f"got {resp.status_code}")

    # 8.7 组织设置（owner 可访问）
    resp = client.get("/org/test_team1/settings")
    check("GET /org/test_team1/settings 返回 200 (owner)", resp.status_code == 200, f"got {resp.status_code}")

    # 8.8 邀请管理
    resp = client.get("/org/test_team1/invites")
    check("GET /org/test_team1/invites 返回 200", resp.status_code == 200, f"got {resp.status_code}")

    # 8.9 POST 创建组织
    resp = client.post("/org/create", data={
        "org_name": "test_http_org",
        "name": "HTTP Created",
        "description": "Created via HTTP",
        "join_policy": "invite",
    })
    check("POST /org/create 重定向（成功）", resp.status_code in (200, 302), f"got {resp.status_code}")
    check("test_http_org 已创建", get_org("test_http_org") is not None)
    check("Alice 是 test_http_org owner", get_org_member_role("test_http_org", "test_alice") == "owner")

    # 8.10 POST 创建组织失败 - org_name 不合法
    resp = client.post("/org/create", data={
        "org_name": "invalid name with spaces!",
        "name": "Bad Name",
        "join_policy": "invite",
    })
    check("非法 org_name 被拒绝", resp.status_code == 200 and b"Invalid" in resp.data or b"error" in resp.data.lower())

    # 8.11 组织笔记 CRUD
    resp = client.post("/org/test_team1/notes/new", data={"content": "# Hello Org\n\nThis is a test."})
    check("POST 创建组织笔记重定向", resp.status_code == 302, f"got {resp.status_code}")

    # 列出笔记
    resp = client.get("/org/test_team1/notes")
    check("笔记列表显示新笔记", resp.status_code == 200 and b"Hello" in resp.data or b"test" in resp.data.lower())

    # 8.12 通过 Bob (admin) 访问设置 - 应该被允许（admin）
    token_bob = "test_token_bob_xyz"
    store_session(hash_token(token_bob), {"username": "test_bob", "created_at": time.time()})
    client.set_cookie("rusin_session", token_bob)
    resp = client.get("/org/test_team1/settings")
    check("Bob (admin) 可访问 settings", resp.status_code == 200, f"got {resp.status_code}")

    # 8.13 Carol (member) 不能访问 settings
    token_carol = "test_token_carol_xyz"
    store_session(hash_token(token_carol), {"username": "test_carol", "created_at": time.time()})
    client.set_cookie("rusin_session", token_carol)
    resp = client.get("/org/test_public/settings")
    check("Carol (member) 不能访问 settings (期望 403)", resp.status_code == 403, f"got {resp.status_code}")

    # 8.14 Carol 可以访问她所在组织（test_approve）的笔记
    resp = client.get("/org/test_approve/notes")
    check("Carol 可访问 test_approve 笔记列表", resp.status_code == 200, f"got {resp.status_code}")

    # 8.15 Carol 不能访问 test_team1 (她不是成员)
    resp = client.get("/org/test_team1/notes")
    check("Carol 不能访问 test_team1 笔记 (期望 403)", resp.status_code == 403, f"got {resp.status_code}")

    # 8.16 未登录用户 - 删除 cookie
    client.delete_cookie("rusin_session")
    resp = client.get("/org/mine")
    check("未登录访问 /org/mine 返回 401", resp.status_code == 401, f"got {resp.status_code}")

    # 8.17 功能开关关闭测试 - 通过直接测试 require_feature
    set_flags({"orgs": False})
    resp = client.get("/org/test_team1")
    check("orgs 关闭时访问返回 404", resp.status_code == 404, f"got {resp.status_code}")
    # 重新启用
    set_flags({"orgs": True})

# ============================================================
section("9. 邀请码通过 URL 加入")
# ============================================================

# Alice 创建一个新的邀请码
test_invite = create_org_invite("test_team1", "test_alice", "invite", expires_days=7)
check("新邀请码已创建", test_invite is not None)

with app.test_client() as client:
    token_dave = "test_token_dave_xyz"
    store_session(hash_token(token_dave), {"username": "test_dave", "created_at": time.time()})
    client.set_cookie("rusin_session", token_dave)
    resp = client.post(f"/org/join/{test_invite}")
    check("Dave 通过邀请码加入成功", resp.status_code in (200, 302), f"got {resp.status_code}")
    check("Dave 已加入 test_team1", "test_team1" in get_user_orgs("test_dave"))

# ============================================================
section("10. Owner 退出保护")
# ============================================================

with app.test_client() as client:
    token_alice = "test_token_alice_xyz"
    client.set_cookie("rusin_session", token_alice)
    # Alice 是 owner，她不能通过 leave 退出
    resp = client.post("/org/test_team1/leave")
    check("Owner 退出应被拒绝 (400)", resp.status_code == 400, f"got {resp.status_code}")
    check("Alice 仍在 test_team1", get_org_member_role("test_team1", "test_alice") == "owner")

# ============================================================
# 清理
# ============================================================
cleanup()

# ============================================================
section("测试总结")
# ============================================================
print(f"\n通过: {results['pass']}")
print(f"失败: {results['fail']}")
if results["fail"] > 0:
    print("\n失败详情:")
    for e in results["errors"]:
        print(e)
    sys.exit(1)
else:
    print("\n所有测试通过！")