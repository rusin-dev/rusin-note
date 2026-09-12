"""用户设置功能端到端测试

覆盖：
- 设置页鉴权（未登录 401、非本人 401）
- 简洁模式的账号级持久化与页面渲染（<html class="simple-mode">、导航栏设置入口）
- 密码修改（原密码校验、确认一致、复杂度、注销其它会话而保留当前会话）
- 用户名变更（校验失败路径 + 笔记/标签/文件夹/置顶/分享/犇犇/评论/组织/会话整体迁移）
- 笔记 ID "settings" 与设置路由冲突保护
- file 后端落盘持久化

运行：python user_settings_test.py
自动使用临时 RUSIN_DATA_DIR，不影响现有数据目录。
"""
import json
import os
import re
import sys
import tempfile

# 隔离数据目录（必须在导入 app 之前设置）
DATA_DIR = tempfile.mkdtemp(prefix="rusin-user-settings-test-")
os.environ["RUSIN_DATA_DIR"] = DATA_DIR
os.environ["RUSIN_STORAGE"] = "file"

from app import create_app                                  # noqa: E402
from app.extensions import limiter                          # noqa: E402
from app.feature_flags import FEATURE_KEYS, set_flags       # noqa: E402
from app.notes import validate_note_id                      # noqa: E402
from app.store import (                                     # noqa: E402
    add_benben_post,
    add_comment,
    create_org,
    create_share,
    get_org,
    get_org_member_role,
    get_share,
    get_user,
    get_benben_posts,
)
from app.tags import get_note_tags, set_note_tags           # noqa: E402
from app.folders import get_note_folder, set_note_folder    # noqa: E402
from app.pins import is_pinned, set_note_pinned             # noqa: E402
from app.user_settings import get_simple_mode, set_simple_mode  # noqa: E402

USER = "settings_user"
OTHER = "settings_other"
PASSWORD = "TestPass1!"
NEW_PASSWORD = "NewPass2@"


def csrf_of(html: str) -> str:
    m = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', html)
    assert m, "页面中未找到 csrf_token"
    return m.group(1)


def register(client, username):
    r = client.get("/register")
    r = client.post("/register", data={
        "username": username, "password": PASSWORD, "confirm": PASSWORD,
        "csrf_token": csrf_of(r.get_data(as_text=True))})
    assert r.status_code in (200, 302), f"注册 {username} 失败: {r.status_code}"


def login(client, username, password=PASSWORD):
    r = client.get("/login")
    r = client.post("/login", data={
        "username": username, "password": password,
        "csrf_token": csrf_of(r.get_data(as_text=True))})
    assert r.status_code in (200, 302), f"登录 {username} 失败: {r.status_code}"
    return r


def settings_csrf(client, username):
    return csrf_of(client.get(f"/user/{username}/settings").get_data(as_text=True))


def create_note(client, username, content):
    r = client.get(f"/user/{username}/new")
    loc = r.headers["Location"]
    note_id = loc.rstrip("/").rsplit("/", 1)[-1]
    r = client.post(loc, data={
        "content": content,
        "csrf_token": csrf_of(client.get(loc).get_data(as_text=True))})
    assert r.status_code == 302, "保存笔记失败"
    return note_id


def main():
    passed = []

    def check(label, cond):
        assert cond, f"FAIL: {label}"
        passed.append(label)
        print(f"  [ok] {label}")

    app = create_app()
    app.config["TESTING"] = True
    limiter.enabled = False  # 测试内多次注册/登录，关闭限流计数
    # 全部功能开启，便于验证标签/置顶等迁移
    set_flags({key: True for key in FEATURE_KEYS})

    client = app.test_client()

    # ===== A. 模块级行为 =====
    print("[A] user_settings 模块")
    register(client, USER)
    check("默认未启用简洁模式", get_simple_mode(USER) is False)
    check("写入简洁模式成功", set_simple_mode(USER, True) is True)
    check("读回简洁模式为真", get_simple_mode(USER) is True)
    set_simple_mode(USER, False)
    check("关闭后读回为假", get_simple_mode(USER) is False)
    check("未登录用户读出假值", get_simple_mode("") is False)

    # ===== B. 设置页鉴权 =====
    print("[B] 设置页鉴权")
    anon = app.test_client()
    check("未登录访问设置页 -> 401", anon.get(f"/user/{USER}/settings").status_code == 401)
    check("非本人访问设置页 -> 401", client.get(f"/user/{OTHER}/settings").status_code == 401)

    # ===== C. 简洁模式开关与渲染 =====
    print("[C] 简洁模式开关与页面渲染")
    html = client.get(f"/user/{USER}/").get_data(as_text=True)
    check("导航栏含设置入口", f'/user/{USER}/settings' in html)
    check("默认不含 simple-mode 类", 'class="simple-mode"' not in html)
    r = client.post(f"/user/{USER}/settings", data={
        "action": "simple_mode", "simple_mode": "1",
        "csrf_token": settings_csrf(client, USER)})
    check("切换简洁模式 -> 302", r.status_code == 302)
    html = client.get(f"/user/{USER}/").get_data(as_text=True)
    check("列表页渲染 simple-mode 类", 'class="simple-mode"' in html)
    check("列表页仍保留设置入口", f'/user/{USER}/settings' in html)
    nid = create_note(client, USER, "简洁模式笔记")
    edit_html = client.get(f"/user/{USER}/{nid}").get_data(as_text=True)
    check("编辑页渲染 simple-mode 类", 'class="simple-mode"' in edit_html)
    r = client.get("/")
    check("简洁模式下首页 302 跳转", r.status_code == 302)
    r = client.post(f"/user/{USER}/settings", data={
        "action": "simple_mode",
        "csrf_token": settings_csrf(client, USER)})
    check("取消勾选即关闭简洁模式", r.status_code == 302 and get_simple_mode(USER) is False)
    check("关闭后首页恢复 200", client.get("/").status_code == 200)

    # ===== D. 密码修改 =====
    print("[D] 密码修改")
    other_client = app.test_client()
    login(other_client, USER)  # 第二台设备的会话
    check("第二设备登录成功", other_client.get(f"/user/{USER}/").status_code == 200)

    r = client.post(f"/user/{USER}/settings", data={
        "action": "password", "current_password": "WrongOld1!",
        "new_password": NEW_PASSWORD, "confirm_password": NEW_PASSWORD,
        "csrf_token": settings_csrf(client, USER)})
    check("原密码错误 -> 200 且报错", r.status_code == 200
          and "当前密码错误" in r.get_data(as_text=True))

    r = client.post(f"/user/{USER}/settings", data={
        "action": "password", "current_password": PASSWORD,
        "new_password": NEW_PASSWORD, "confirm_password": "Mismatch9!",
        "csrf_token": settings_csrf(client, USER)})
    check("两次新密码不一致 -> 报错", r.status_code == 200
          and "两次密码不一致" in r.get_data(as_text=True))

    r = client.post(f"/user/{USER}/settings", data={
        "action": "password", "current_password": PASSWORD,
        "new_password": "weak", "confirm_password": "weak",
        "csrf_token": settings_csrf(client, USER)})
    check("弱密码被拒绝", r.status_code == 200
          and "密码不符合要求" in r.get_data(as_text=True))

    r = client.post(f"/user/{USER}/settings", data={
        "action": "password", "current_password": PASSWORD,
        "new_password": NEW_PASSWORD, "confirm_password": NEW_PASSWORD,
        "csrf_token": settings_csrf(client, USER)})
    check("修改密码成功 -> 302", r.status_code == 302)
    check("当前设备保持登录", client.get(f"/user/{USER}/").status_code == 200)
    check("其它设备会话已注销", other_client.get(f"/user/{USER}/").status_code == 401)

    fresh = app.test_client()
    login(fresh, USER, NEW_PASSWORD)
    check("新密码可登录", fresh.get(f"/user/{USER}/").status_code == 200)
    stale = app.test_client()
    r = stale.get("/login")
    r = stale.post("/login", data={
        "username": USER, "password": PASSWORD, "csrf_token": csrf_of(r.get_data(as_text=True))})
    check("旧密码无法登录", r.status_code == 401)

    # ===== E. 用户名变更 =====
    print("[E] 用户名变更")
    # 注册一个已占用的用户名用于冲突校验（独立客户端，不影响主会话）
    register(app.test_client(), OTHER)
    # 准备跨子系统数据
    tag_note = create_note(client, USER, "带标签与文件夹的笔记")
    set_note_tags(USER, tag_note, ["alpha"])
    set_note_folder(USER, tag_note, "inbox")
    set_note_pinned(USER, tag_note, True)
    share_token = create_share(USER, tag_note, True)
    add_benben_post(USER, "改名前的犇犇")
    add_comment("note", f"{USER}:{tag_note}", USER, "改名前的评论")
    create_org("migration_org", "迁移组织", USER)

    # 校验失败路径
    r = client.post(f"/user/{USER}/settings", data={
        "action": "username", "new_username": USER, "password": NEW_PASSWORD,
        "csrf_token": settings_csrf(client, USER)})
    check("新旧用户名相同被拒绝", r.status_code == 200
          and "新用户名与当前用户名相同" in r.get_data(as_text=True))
    r = client.post(f"/user/{USER}/settings", data={
        "action": "username", "new_username": "bad name!", "password": NEW_PASSWORD,
        "csrf_token": settings_csrf(client, USER)})
    check("非法用户名被拒绝", r.status_code == 200 and "用户名只能包含" in r.get_data(as_text=True))
    r = client.post(f"/user/{USER}/settings", data={
        "action": "username", "new_username": OTHER, "password": NEW_PASSWORD,
        "csrf_token": settings_csrf(client, USER)})
    check("已占用用户名被拒绝", r.status_code == 200 and "用户名不可用" in r.get_data(as_text=True))
    r = client.post(f"/user/{USER}/settings", data={
        "action": "username", "new_username": "renamed_user", "password": "WrongPw1!",
        "csrf_token": settings_csrf(client, USER)})
    check("改名密码错误被拒绝", r.status_code == 200 and "当前密码错误" in r.get_data(as_text=True))

    NEW_NAME = "renamed_user"
    r = client.post(f"/user/{USER}/settings", data={
        "action": "username", "new_username": NEW_NAME, "password": NEW_PASSWORD,
        "csrf_token": settings_csrf(client, USER)})
    check("改名成功 -> 302 到新设置页", r.status_code == 302
          and f"/user/{NEW_NAME}/settings" in r.headers.get("Location", ""))

    check("用户记录已迁移", get_user(USER) is None and isinstance(get_user(NEW_NAME), dict))
    check("会话随改名迁移（当前设备仍登录）", client.get(f"/user/{NEW_NAME}/").status_code == 200)
    check("旧用户名入口失效", client.get(f"/user/{USER}/").status_code == 401)

    # 笔记与元数据迁移
    check("笔记已迁到新命名空间", client.get(f"/user/{NEW_NAME}/{tag_note}").status_code == 200)
    check("笔记内容可读", "带标签与文件夹的笔记" in client.get(f"/user/{NEW_NAME}/{tag_note}").get_data(as_text=True))
    check("标签已迁移", get_note_tags(NEW_NAME, tag_note) == ["alpha"])
    check("文件夹已迁移", get_note_folder(NEW_NAME, tag_note) == "inbox")
    check("置顶已迁移", is_pinned(NEW_NAME, tag_note) is True)
    check("旧标签清空", get_note_tags(USER, tag_note) == [])
    check("旧置顶清空", is_pinned(USER, tag_note) is False)

    # 分享 / 犇犇 / 评论 / 组织迁移
    share = get_share(share_token)
    check("分享 owner 已迁移", isinstance(share, dict) and share.get("owner") == NEW_NAME)
    posts, _ = get_benben_posts(1, 50)
    check("犇犇作者已迁移", any(p.get("username") == NEW_NAME for p in posts))
    check("评论作者与目标键已迁移",
          _comment_migrated(NEW_NAME))
    check("组织 owner 已迁移", (get_org("migration_org") or {}).get("owner") == NEW_NAME)
    check("组织成员键已迁移", get_org_member_role("migration_org", NEW_NAME) == "owner")

    # ===== F. 路由冲突保护与边界 =====
    print("[F] 路由冲突保护与边界")
    check("settings 不能作为笔记 ID", validate_note_id("settings") is False)
    r = client.post(f"/user/{NEW_NAME}/settings", data={
        "action": "unknown", "csrf_token": settings_csrf(client, NEW_NAME)})
    check("未知 action -> 400", r.status_code == 400)

    # ===== G. 持久化 =====
    print("[G] 持久化")
    users_path = os.path.join(DATA_DIR, "users.json")
    with open(users_path, encoding="utf-8") as f:
        stored = json.load(f)
    check("users.json 含新用户名且无旧用户名",
          NEW_NAME in stored and USER not in stored)
    check("简洁模式偏好已落盘", "simple_mode" in stored.get(NEW_NAME, {}))
    notes_dir = os.path.join(DATA_DIR, "notes")
    check("旧命名空间目录已清空", not os.path.isdir(os.path.join(notes_dir, USER))
          or not os.listdir(os.path.join(notes_dir, USER)))
    check("新命名空间目录存在笔记", os.path.isdir(os.path.join(notes_dir, NEW_NAME))
          and bool(os.listdir(os.path.join(notes_dir, NEW_NAME))))

    print(f"\n全部通过：{len(passed)} 项检查")


def _comment_migrated(new_name: str) -> bool:
    """评论存储在单个 KV 键；直接读存储后端确认作者与目标键均已迁移。"""
    from app.storage import storage
    table = storage.get("comments:all")
    if not isinstance(table, dict):
        return False
    matched = False
    for target_key, items in table.items():
        if not target_key.startswith("note:"):
            continue
        if not target_key.startswith(f"note:{new_name}:"):
            continue
        for comment in items or []:
            if isinstance(comment, dict) and comment.get("username") == new_name:
                matched = True
    return matched


if __name__ == "__main__":
    try:
        main()
    except AssertionError as e:
        print(f"\n{e}")
        sys.exit(1)
