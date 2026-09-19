"""用户设置功能端到端测试（pytest + logging）。

覆盖：
- 设置页鉴权（未登录 401、非本人 401）
- 简洁模式的账号级持久化与页面渲染（<html class="simple-mode">、导航栏设置入口）
- 密码修改（原密码校验、确认一致、复杂度、注销其它会话而保留当前会话）
- 用户名变更（校验失败路径 + 笔记/标签/文件夹/置顶/分享/犇犇/评论/组织/会话整体迁移）
- 笔记 ID "settings" 与设置路由冲突保护
- file 后端落盘持久化

运行：``pytest tests/test_user_settings.py``
"""
from __future__ import annotations

import json
import logging
import os

from app.feature_flags import FEATURE_KEYS, set_flags
from app.folders import get_note_folder, set_note_folder
from app.notes import validate_note_id
from app.pins import is_pinned, set_note_pinned
from app.store import (
    add_benben_post,
    add_comment,
    create_org,
    create_share,
    get_benben_posts,
    get_org,
    get_org_member_role,
    get_share,
    get_user,
)
from app.tags import get_note_tags, set_note_tags
from app.user_settings import get_simple_mode, set_simple_mode
from support import (
    create_note,
    csrf_from,
    expect,
    login,
    register,
)

logger = logging.getLogger("rusin.tests.user_settings")

USER = "settings_user"
OTHER = "settings_other"
PASSWORD = "TestPass1!"
NEW_PASSWORD = "NewPass2@"
NEW_NAME = "renamed_user"


def settings_csrf(client, username: str) -> str:
    return csrf_from(client, f"/user/{username}/settings")


def _comment_migrated(new_name: str) -> bool:
    """评论存储在单个 KV 键；读取存储后端确认作者与目标键均已迁移。"""
    from app.storage import storage

    table = storage.get("comments:all")
    if not isinstance(table, dict):
        return False
    for target_key, items in table.items():
        if not target_key.startswith(f"note:{new_name}:"):
            continue
        for comment in items or []:
            if isinstance(comment, dict) and comment.get("username") == new_name:
                return True
    return False


class TestUserSettings:
    """A-G：用户设置模块行为、页面渲染、改密、改名与持久化。"""

    def test_module_level(self, ctx):
        logger.info("=== [A] user_settings 模块 ===")
        set_flags({key: True for key in FEATURE_KEYS})
        register(ctx.client, USER)
        expect(get_simple_mode(USER) is False, "默认未启用简洁模式")
        expect(set_simple_mode(USER, True) is True, "写入简洁模式成功")
        expect(get_simple_mode(USER) is True, "读回简洁模式为真")
        set_simple_mode(USER, False)
        expect(get_simple_mode(USER) is False, "关闭后读回为假")
        expect(get_simple_mode("") is False, "未登录用户读出假值")

    def test_settings_auth(self, ctx):
        logger.info("=== [B] 设置页鉴权 ===")
        expect(ctx.anon.get(f"/user/{USER}/settings").status_code == 401, "未登录访问设置页 -> 401")
        expect(ctx.client.get(f"/user/{OTHER}/settings").status_code == 401, "非本人访问设置页 -> 401")

    def test_simple_mode_rendering(self, ctx):
        logger.info("=== [C] 简洁模式开关与页面渲染 ===")
        html = ctx.client.get(f"/user/{USER}/").get_data(as_text=True)
        expect(f"/user/{USER}/settings" in html, "导航栏含设置入口")
        expect('class="simple-mode"' not in html, "默认不含 simple-mode 类")

        response = ctx.client.post(f"/user/{USER}/settings", data={
            "action": "simple_mode", "simple_mode": "1",
            "csrf_token": settings_csrf(ctx.client, USER),
        })
        expect(response.status_code == 302, "切换简洁模式 -> 302")
        html = ctx.client.get(f"/user/{USER}/").get_data(as_text=True)
        expect('class="simple-mode"' in html, "列表页渲染 simple-mode 类")
        expect(f"/user/{USER}/settings" in html, "列表页仍保留设置入口")

        ctx.note_id = create_note(ctx.client, USER, "简洁模式笔记")
        edit_html = ctx.client.get(f"/user/{USER}/{ctx.note_id}").get_data(as_text=True)
        expect('class="simple-mode"' in edit_html, "编辑页渲染 simple-mode 类")
        expect(ctx.client.get("/").status_code == 302, "简洁模式下首页 302 跳转")

        response = ctx.client.post(f"/user/{USER}/settings", data={
            "action": "simple_mode",
            "csrf_token": settings_csrf(ctx.client, USER),
        })
        expect(response.status_code == 302 and get_simple_mode(USER) is False,
               "取消勾选即关闭简洁模式")
        expect(ctx.client.get("/").status_code == 200, "关闭后首页恢复 200")

    def test_password_change(self, ctx):
        logger.info("=== [D] 密码修改 ===")
        other_client = ctx.app.test_client()
        login(other_client, USER)
        expect(other_client.get(f"/user/{USER}/").status_code == 200, "第二设备登录成功")

        response = ctx.client.post(f"/user/{USER}/settings", data={
            "action": "password", "current_password": "WrongOld1!",
            "new_password": NEW_PASSWORD, "confirm_password": NEW_PASSWORD,
            "csrf_token": settings_csrf(ctx.client, USER),
        })
        expect(response.status_code == 200 and "当前密码错误" in response.get_data(as_text=True),
               "原密码错误 -> 200 且报错")

        response = ctx.client.post(f"/user/{USER}/settings", data={
            "action": "password", "current_password": PASSWORD,
            "new_password": NEW_PASSWORD, "confirm_password": "Mismatch9!",
            "csrf_token": settings_csrf(ctx.client, USER),
        })
        expect(response.status_code == 200 and "两次密码不一致" in response.get_data(as_text=True),
               "两次新密码不一致 -> 报错")

        response = ctx.client.post(f"/user/{USER}/settings", data={
            "action": "password", "current_password": PASSWORD,
            "new_password": "weak", "confirm_password": "weak",
            "csrf_token": settings_csrf(ctx.client, USER),
        })
        expect(response.status_code == 200 and "密码不符合要求" in response.get_data(as_text=True),
               "弱密码被拒绝")

        response = ctx.client.post(f"/user/{USER}/settings", data={
            "action": "password", "current_password": PASSWORD,
            "new_password": NEW_PASSWORD, "confirm_password": NEW_PASSWORD,
            "csrf_token": settings_csrf(ctx.client, USER),
        })
        expect(response.status_code == 302, "修改密码成功 -> 302")
        expect(ctx.client.get(f"/user/{USER}/").status_code == 200, "当前设备保持登录")
        expect(other_client.get(f"/user/{USER}/").status_code == 401, "其它设备会话已注销")

        fresh = ctx.app.test_client()
        login(fresh, USER, NEW_PASSWORD)
        expect(fresh.get(f"/user/{USER}/").status_code == 200, "新密码可登录")

        stale = ctx.app.test_client()
        response = stale.post("/login", data={
            "username": USER, "password": PASSWORD,
            "csrf_token": csrf_from(stale, "/login"),
        })
        expect(response.status_code == 401, "旧密码无法登录")

    def test_username_change(self, ctx):
        logger.info("=== [E] 用户名变更 ===")
        register(ctx.app.test_client(), OTHER)  # 占用用户名用于冲突校验

        ctx.tag_note = create_note(ctx.client, USER, "带标签与文件夹的笔记")
        set_note_tags(USER, ctx.tag_note, ["alpha"])
        set_note_folder(USER, ctx.tag_note, "inbox")
        set_note_pinned(USER, ctx.tag_note, True)
        ctx.share_token = create_share(USER, ctx.tag_note, True)
        add_benben_post(USER, "改名前的犇犇")
        add_comment("note", f"{USER}:{ctx.tag_note}", USER, "改名前的评论")
        create_org("migration_org", "迁移组织", USER)

        response = ctx.client.post(f"/user/{USER}/settings", data={
            "action": "username", "new_username": USER, "password": NEW_PASSWORD,
            "csrf_token": settings_csrf(ctx.client, USER),
        })
        expect(response.status_code == 200 and "新用户名与当前用户名相同" in response.get_data(as_text=True),
               "新旧用户名相同被拒绝")

        response = ctx.client.post(f"/user/{USER}/settings", data={
            "action": "username", "new_username": "bad name!", "password": NEW_PASSWORD,
            "csrf_token": settings_csrf(ctx.client, USER),
        })
        expect(response.status_code == 200 and "用户名只能包含" in response.get_data(as_text=True),
               "非法用户名被拒绝")

        response = ctx.client.post(f"/user/{USER}/settings", data={
            "action": "username", "new_username": OTHER, "password": NEW_PASSWORD,
            "csrf_token": settings_csrf(ctx.client, USER),
        })
        expect(response.status_code == 200 and "用户名不可用" in response.get_data(as_text=True),
               "已占用用户名被拒绝")

        response = ctx.client.post(f"/user/{USER}/settings", data={
            "action": "username", "new_username": NEW_NAME, "password": "WrongPw1!",
            "csrf_token": settings_csrf(ctx.client, USER),
        })
        expect(response.status_code == 200 and "当前密码错误" in response.get_data(as_text=True),
               "改名密码错误被拒绝")

        response = ctx.client.post(f"/user/{USER}/settings", data={
            "action": "username", "new_username": NEW_NAME, "password": NEW_PASSWORD,
            "csrf_token": settings_csrf(ctx.client, USER),
        })
        expect(response.status_code == 302
               and f"/user/{NEW_NAME}/settings" in response.headers.get("Location", ""),
               "改名成功 -> 302 到新设置页")

        expect(get_user(USER) is None and isinstance(get_user(NEW_NAME), dict), "用户记录已迁移")
        expect(ctx.client.get(f"/user/{NEW_NAME}/").status_code == 200,
               "会话随改名迁移（当前设备仍登录）")
        expect(ctx.client.get(f"/user/{USER}/").status_code == 401, "旧用户名入口失效")

        expect(ctx.client.get(f"/user/{NEW_NAME}/{ctx.tag_note}").status_code == 200,
               "笔记已迁到新命名空间")
        expect("带标签与文件夹的笔记" in ctx.client.get(f"/user/{NEW_NAME}/{ctx.tag_note}").get_data(as_text=True),
               "笔记内容可读")
        expect(get_note_tags(NEW_NAME, ctx.tag_note) == ["alpha"], "标签已迁移")
        expect(get_note_folder(NEW_NAME, ctx.tag_note) == "inbox", "文件夹已迁移")
        expect(is_pinned(NEW_NAME, ctx.tag_note) is True, "置顶已迁移")
        expect(get_note_tags(USER, ctx.tag_note) == [], "旧标签清空")
        expect(is_pinned(USER, ctx.tag_note) is False, "旧置顶清空")

        share = get_share(ctx.share_token)
        expect(isinstance(share, dict) and share.get("owner") == NEW_NAME, "分享 owner 已迁移")
        posts, _ = get_benben_posts(1, 50)
        expect(any(p.get("username") == NEW_NAME for p in posts), "犇犇作者已迁移")
        expect(_comment_migrated(NEW_NAME), "评论作者与目标键已迁移")
        expect((get_org("migration_org") or {}).get("owner") == NEW_NAME, "组织 owner 已迁移")
        expect(get_org_member_role("migration_org", NEW_NAME) == "owner", "组织成员键已迁移")

    def test_route_conflict(self, ctx):
        logger.info("=== [F] 路由冲突保护与边界 ===")
        expect(validate_note_id("settings") is False, "settings 不能作为笔记 ID")
        response = ctx.client.post(f"/user/{NEW_NAME}/settings", data={
            "action": "unknown", "csrf_token": settings_csrf(ctx.client, NEW_NAME),
        })
        expect(response.status_code == 400, "未知 action -> 400")

    def test_persistence(self, ctx):
        logger.info("=== [G] 持久化 ===")
        users_path = os.path.join(ctx.data_dir, "users.json")
        with open(users_path, encoding="utf-8") as handle:
            stored = json.load(handle)
        expect(NEW_NAME in stored and USER not in stored, "users.json 含新用户名且无旧用户名")
        expect("simple_mode" in stored.get(NEW_NAME, {}), "简洁模式偏好已落盘")

        notes_dir = os.path.join(ctx.data_dir, "notes")
        expect(not os.path.isdir(os.path.join(notes_dir, USER))
               or not os.listdir(os.path.join(notes_dir, USER)), "旧命名空间目录已清空")
        expect(os.path.isdir(os.path.join(notes_dir, NEW_NAME))
               and bool(os.listdir(os.path.join(notes_dir, NEW_NAME))),
               "新命名空间目录存在笔记")
