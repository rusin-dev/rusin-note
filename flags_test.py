"""功能开关（#90）端到端测试：/admin/features 滑块管理页、路由级 404 强制、
/count 数据汇总页功能状态呈现与持久化。

运行：python flags_test.py
自动使用临时 RUSIN_DATA_DIR 并将测试用户设为管理员，不影响现有数据目录。
"""
import json
import os
import re
import sys
import tempfile

# 隔离数据目录 + 指定管理员（必须在导入 app 之前设置）
DATA_DIR = tempfile.mkdtemp(prefix="rusin-flags-test-")
os.environ["RUSIN_DATA_DIR"] = DATA_DIR
os.environ["RUSIN_ADMIN"] = "boss"

from app import create_app                      # noqa: E402
from app.extensions import limiter              # noqa: E402
from app.feature_flags import (                 # noqa: E402
    FEATURE_KEYS, feature_enabled, get_all_features,
)

ADMIN = "boss"
MEMBER = "bob"
PASSWORD = "TestPass1!"

# 需要在测试中切换的四个路由级功能（note_refs/latex 等渲染类开关保持默认）
TOGGLE_KEYS = ["world_notes", "benben", "share_links", "open_register"]


def csrf_of(html: str) -> str:
    m = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', html)
    assert m, "页面中未找到 csrf_token"
    return m.group(1)


def register_and_login(client, username):
    r = client.get("/register")
    assert r.status_code == 200, f"注册页不可访问: {r.status_code}"
    r = client.post("/register", data={
        "username": username, "password": PASSWORD, "confirm": PASSWORD,
        "csrf_token": csrf_of(r.get_data(as_text=True))})
    assert r.status_code in (200, 302), f"注册 {username} 失败: {r.status_code}"
    r = client.get("/login")
    r = client.post("/login", data={
        "username": username, "password": PASSWORD,
        "csrf_token": csrf_of(r.get_data(as_text=True))})
    assert r.status_code in (200, 302), f"登录 {username} 失败: {r.status_code}"


def post_flags(client, state: dict):
    """以管理员身份提交 /admin/features 滑块表单"""
    r = client.get("/admin/features")
    assert r.status_code == 200, f"管理页不可访问: {r.status_code}"
    data = {"csrf_token": csrf_of(r.get_data(as_text=True))}
    for key in FEATURE_KEYS:
        if state.get(key, False):
            data[f"flag_{key}"] = "1"
    r = client.post("/admin/features", data=data)
    assert r.status_code == 302, f"保存开关失败: {r.status_code}"


def main():
    passed = []

    def check(label, cond):
        assert cond, f"FAIL: {label}"
        passed.append(label)
        print(f"  [ok] {label}")

    app = create_app()
    app.config["TESTING"] = True
    limiter.enabled = False  # 测试内多次注册，关闭限流计数
    client = app.test_client()

    # ===== A. 模块级行为 =====
    print("[A] feature_flags 模块")
    check("未注册键一律返回 False", feature_enabled("no_such_feature") is False)
    names = [f["key"] for f in get_all_features()]
    check("注册表完整且带启用状态", names == FEATURE_KEYS and
          all(isinstance(f["enabled"], bool) for f in get_all_features()))

    # ===== B. 管理员与访问控制 =====
    print("[B] 管理页访问控制")
    register_and_login(client, MEMBER)
    r = client.get("/admin/features")
    check("非管理员访问管理页 -> 404", r.status_code == 404)
    client.get("/logout")
    r = client.get("/admin/features")
    check("未登录访问管理页 -> 404", r.status_code == 404)
    register_and_login(client, ADMIN)
    r = client.get("/admin/features")
    html = r.get_data(as_text=True)
    check("管理员访问管理页 -> 200 且含滑块表单",
          r.status_code == 200 and "flag_benben" in html and "ff-switch" in html)

    # ===== C. 停用主要功能：路由 404 + 页面入口隐藏 =====
    print("[C] 停用 world_notes / benben / share_links / open_register")
    # 先在功能开启时准备一篇笔记 + 一条分享链接
    r = client.get(f"/user/{ADMIN}/new")
    loc = r.headers["Location"]
    note_path = loc
    csrf = csrf_of(client.get(loc).get_data(as_text=True))
    r = client.post(note_path, data={"content": "被分享的笔记", "csrf_token": csrf})
    assert r.status_code == 302, "准备笔记失败"
    note_id = note_path.rstrip("/").rsplit("/", 1)[-1]
    csrf = csrf_of(client.get(f"/user/{ADMIN}/shares").get_data(as_text=True))
    r = client.post(f"/user/{ADMIN}/shares", data={
        "note_id": note_id, "csrf_token": csrf})
    assert r.status_code == 302, "准备分享失败"
    m = re.search(r'/share/([A-Za-z0-9]+)', client.get(f"/user/{ADMIN}/shares").get_data(as_text=True))
    assert m, "分享链接未生成"
    token = m.group(1)

    off_state = {k: (k not in TOGGLE_KEYS) for k in FEATURE_KEYS}
    post_flags(client, off_state)

    check("GET /benben -> 404", client.get("/benben").status_code == 404)
    # POST 需带合法 csrf_token 才能穿过 CSRF 校验、到达 require_feature
    csrf = csrf_of(client.get("/login").get_data(as_text=True))
    check("POST /benben -> 404",
          client.post("/benben", data={"content": "x", "csrf_token": csrf}).status_code == 404)
    check("GET /world -> 404", client.get("/world").status_code == 404)
    check("GET /world/<id> -> 404", client.get("/world/abcd").status_code == 404)
    check("短链 /<id> -> 404", client.get("/abcd").status_code == 404)
    check("GET /register -> 404", client.get("/register").status_code == 404)
    check("GET /share/<token> -> 404", client.get(f"/share/{token}").status_code == 404)
    check("GET /user/<u>/shares -> 404",
          client.get(f"/user/{ADMIN}/shares").status_code == 404)
    check("登录不受 open_register 影响", client.get("/login").status_code == 200)

    home_html = client.get("/").get_data(as_text=True)
    check("首页不再出现 /benben 入口", 'href="/benben"' not in home_html)
    check("首页不再出现 /register 入口", 'href="/register"' not in home_html)

    count_html = client.get("/count").get_data(as_text=True)
    check("/count 呈现已停用状态", "已停用" in count_html and "ff-off" in count_html)
    check("/count 隐藏犇犇统计卡", "犇犇动态" not in count_html.split("功能状态")[0])
    check("/count 提供管理员入口", "/admin/features" in count_html)

    # ===== D. 重新启用：立即恢复 =====
    print("[D] 重新启用全部功能")
    post_flags(client, {k: True for k in FEATURE_KEYS})
    check("GET /benben -> 200", client.get("/benben").status_code == 200)
    check("GET /register -> 200", client.get("/register").status_code == 200)
    check("GET /world -> 302", client.get("/world").status_code == 302)
    check("GET /share/<token> -> 200", client.get(f"/share/{token}").status_code == 200)
    check("GET /user/<u>/shares -> 200", client.get(f"/user/{ADMIN}/shares").status_code == 200)
    home_html = client.get("/").get_data(as_text=True)
    check("首页恢复 /benben 入口", 'href="/benben"' in home_html)

    # ===== E. 持久化（file 后端落盘 feature_flags.json）=====
    print("[E] 持久化")
    flags_path = os.path.join(DATA_DIR, "feature_flags.json")
    check("feature_flags.json 已落盘", os.path.exists(flags_path))
    with open(flags_path, encoding="utf-8") as f:
        stored = json.load(f)
    check("落盘内容为全部启用", stored == {k: True for k in FEATURE_KEYS})

    print(f"\n全部通过：{len(passed)} 项检查")


if __name__ == "__main__":
    try:
        main()
    except AssertionError as e:
        print(f"\n{e}")
        sys.exit(1)
