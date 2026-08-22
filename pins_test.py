"""笔记置顶功能端到端测试：列表页图钉开关、置顶排序（置顶组内置顶时间
倒序、其余修改时间倒序）、筛选视图下的置顶与筛选参数回传、删除笔记联动
清理、功能开关门控与 file 后端持久化。

运行：python pins_test.py
自动使用临时 RUSIN_DATA_DIR，不影响现有数据目录。
"""
import json
import os
import re
import sys
import tempfile
import time

# 隔离数据目录（必须在导入 app 之前设置）
DATA_DIR = tempfile.mkdtemp(prefix="rusin-pins-test-")
os.environ["RUSIN_DATA_DIR"] = DATA_DIR

from app import create_app                      # noqa: E402
from app.extensions import cache, limiter       # noqa: E402
from app.feature_flags import FEATURE_KEYS, set_flags  # noqa: E402
from app.pins import get_user_pins, is_pinned, set_note_pinned, toggle_note_pin  # noqa: E402
from app.tags import set_note_tags              # noqa: E402

USER = "pinner"
OTHER = "viewer4"
PASSWORD = "TestPass1!"


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


def create_note(client, username, content):
    r = client.get(f"/user/{username}/new")
    loc = r.headers["Location"]
    note_id = loc.rstrip("/").rsplit("/", 1)[-1]
    r = client.post(loc, data={"content": content,
                               "csrf_token": csrf_of(client.get(loc).get_data(as_text=True))})
    assert r.status_code == 302, "保存笔记失败"
    return note_id


def set_file_mtime(username, note_id, ts):
    """file 后端：显式设置笔记 mtime，保证排序断言确定性"""
    os.utime(os.path.join(DATA_DIR, "notes", username, f"{note_id}.txt"), (ts, ts))


def list_order(client, username, query=""):
    """解析列表页笔记链接的出现顺序（排除 /new 入口）"""
    html = client.get(f"/user/{username}{query}").get_data(as_text=True)
    ids = re.findall(rf'href="/user/{username}/([a-z0-9]+)"', html)
    return [i for i in ids if i != "new"]


def pin(client, username, note_id, tag=None, folder=None, csrf=None):
    data = {"csrf_token": csrf or csrf_of(client.get(f"/user/{username}").get_data(as_text=True))}
    if tag:
        data["tag"] = tag
    if folder:
        data["folder"] = folder
    return client.post(f"/user/{username}/{note_id}/pin", data=data)


def main():
    passed = []

    def check(label, cond):
        assert cond, f"FAIL: {label}"
        passed.append(label)
        print(f"  [ok] {label}")

    app = create_app()
    app.config["TESTING"] = True
    limiter.enabled = False  # 测试内多次注册/保存，关闭限流计数
    client = app.test_client()

    # ===== A. 模块级行为 =====
    print("[A] pins 模块")
    set_note_pinned(USER, "mod1", True)
    check("置顶写入并读到时间戳", isinstance(get_user_pins(USER).get("mod1"), float))
    check("is_pinned 查询", is_pinned(USER, "mod1") is True and is_pinned(USER, "mod2") is False)
    check("toggle 切换两态", toggle_note_pin(USER, "mod1") is False and toggle_note_pin(USER, "mod1") is True)
    check("取消置顶后条目清除", toggle_note_pin(USER, "mod1") is False and "mod1" not in get_user_pins(USER))
    set_note_pinned(USER, "mod1", False)  # 清理模块级测试残留

    # ===== B. 列表排序基础（修改时间倒序） =====
    print("[B] 列表排序与图钉开关")
    register_and_login(client, USER)
    n1 = create_note(client, USER, "最旧")
    n2 = create_note(client, USER, "居中")
    n3 = create_note(client, USER, "最新")
    set_file_mtime(USER, n1, 1000)
    set_file_mtime(USER, n2, 2000)
    set_file_mtime(USER, n3, 3000)
    check("默认按修改时间倒序", list_order(client, USER) == [n3, n2, n1])
    html = client.get(f"/user/{USER}").get_data(as_text=True)
    check("列表页含图钉开关", 'class="pin-form"' in html and "/pin" in html)
    check("初始无置顶行", '<li class="pinned-row">' not in html)

    # ===== C. 置顶浮动 =====
    print("[C] 置顶浮动到最前")
    r = pin(client, USER, n1)
    assert r.status_code == 302, f"置顶请求失败: {r.status_code}"
    check("模块层读到置顶", is_pinned(USER, n1) is True)
    check("最旧笔记置顶后排在最前", list_order(client, USER) == [n1, n3, n2])
    html = client.get(f"/user/{USER}").get_data(as_text=True)
    check("置顶行高亮与图钉激活态", '<li class="pinned-row">' in html and "pin-btn pinned" in html)

    # ===== D. 置顶组内按置顶时间倒序 =====
    print("[D] 置顶组内按置顶时间倒序")
    r = pin(client, USER, n2)
    assert r.status_code == 302
    check("后置顶的排更前", list_order(client, USER) == [n2, n1, n3])

    # ===== E. 取消置顶 =====
    print("[E] 取消置顶恢复排序")
    r = pin(client, USER, n2)
    assert r.status_code == 302
    check("取消后回到修改时间序", list_order(client, USER) == [n1, n3, n2])
    check("模块层确认取消", is_pinned(USER, n2) is False)

    # ===== F. 筛选视图下的置顶与参数回传 =====
    print("[F] 筛选视图下的置顶")
    set_note_tags(USER, n1, ["alpha"])
    set_note_tags(USER, n3, ["alpha"])
    set_note_tags(USER, n2, ["beta"])
    html = client.get(f"/user/{USER}?tag=alpha").get_data(as_text=True)
    check("筛选视图内置顶仍浮前", list_order(client, USER, "?tag=alpha") == [n1, n3])
    r = pin(client, USER, n3, tag="alpha")
    assert r.status_code == 302
    check("切换后重定向保留筛选参数",
          r.headers["Location"].startswith(f"/user/{USER}") and "tag=alpha" in r.headers["Location"])
    check("筛选视图内后置顶的排更前", list_order(client, USER, "?tag=alpha") == [n3, n1])

    # ===== G. 删除笔记联动清理 =====
    print("[G] 删除笔记联动清理")
    r = client.post(f"/user/{USER}/{n1}", data={
        "content": "", "csrf_token": csrf_of(client.get(f"/user/{USER}/{n1}").get_data(as_text=True))})
    assert r.status_code == 302
    check("删除笔记后置顶条目被清理", is_pinned(USER, n1) is False and n1 not in get_user_pins(USER))
    check("列表不再含该笔记", n1 not in list_order(client, USER))

    # ===== H. 功能开关门控 =====
    print("[H] 功能开关 note_pins")
    set_flags({k: (k != "note_pins") for k in FEATURE_KEYS})
    cache.clear()  # 管理页保存开关时会 cache.clear()，这里等价模拟
    html = client.get(f"/user/{USER}").get_data(as_text=True)
    check("停用后列表页无图钉开关", 'class="pin-form"' not in html and '<li class="pinned-row">' not in html)
    check("停用后排序退回修改时间倒序", list_order(client, USER) == [n3, n2])
    csrf = csrf_of(client.get(f"/user/{USER}/{n3}").get_data(as_text=True))
    r = client.post(f"/user/{USER}/{n3}/pin", data={"csrf_token": csrf})
    check("停用时 POST /pin -> 404", r.status_code == 404)
    check("停用时不改变置顶状态", is_pinned(USER, n3) is True)

    set_flags({k: True for k in FEATURE_KEYS})
    cache.clear()
    html = client.get(f"/user/{USER}").get_data(as_text=True)
    check("重新启用后图钉开关恢复", 'class="pin-form"' in html)

    # ===== I. 边界与用户隔离 =====
    print("[I] 边界与用户隔离")
    csrf = csrf_of(client.get(f"/user/{USER}/{n3}").get_data(as_text=True))
    r = client.post(f"/user/{USER}/zzzz/pin", data={"csrf_token": csrf})
    check("置顶不存在的笔记 -> 404", r.status_code == 404)

    client.get("/logout")
    register_and_login(client, OTHER)
    own = create_note(client, OTHER, "别人的笔记")
    r = pin(client, OTHER, own)
    assert r.status_code == 302
    check("置顶按用户隔离存储", is_pinned(OTHER, own) is True
          and set(get_user_pins(OTHER)) == {own}
          and set(get_user_pins(USER)) == {n3})
    html = client.get(f"/user/{OTHER}").get_data(as_text=True)
    check("他人列表页只含自己的笔记", own in html and n3 not in html)

    # ===== J. 持久化（file 后端落盘 note_pins.json）=====
    print("[J] 持久化")
    pins_path = os.path.join(DATA_DIR, "note_pins.json")
    check("note_pins.json 已落盘", os.path.exists(pins_path))
    with open(pins_path, encoding="utf-8") as f:
        stored = json.load(f)
    check("落盘结构为 {用户: {笔记: 置顶时间}}",
          isinstance(stored.get(USER, {}).get(n3), float)
          and isinstance(stored.get(OTHER, {}).get(own), float))

    print(f"\n全部通过：{len(passed)} 项检查")


if __name__ == "__main__":
    try:
        main()
    except AssertionError as e:
        print(f"\n{e}")
        sys.exit(1)
