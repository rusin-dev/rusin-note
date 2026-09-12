"""笔记文件夹树状图端到端测试：多级文件夹名校验与规范化、树构建、编辑页保存
嵌套路径、列表页树状标记与嵌套顺序、?folder= 子树筛选、功能开关门控与
file 后端持久化。

运行：python folders_test.py
自动使用临时 RUSIN_DATA_DIR，不影响现有数据目录。
"""
import json
import os
import re
import sys
import tempfile

# 隔离数据目录（必须在导入 app 之前设置）
DATA_DIR = tempfile.mkdtemp(prefix="rusin-folders-test-")
os.environ["RUSIN_DATA_DIR"] = DATA_DIR

from app import create_app                                        # noqa: E402
from app.config import MAX_FOLDER_DEPTH, MAX_FOLDER_NAME_LENGTH   # noqa: E402
from app.extensions import cache, limiter                         # noqa: E402
from app.feature_flags import FEATURE_KEYS, set_flags             # noqa: E402
from app.folders import (                                         # noqa: E402
    build_folder_tree,
    folder_in_subtree,
    get_note_folder,
    parse_folder_input,
    valid_folder,
)

USER = "folderer"
OTHER = "viewer9"
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


def create_note(client, username, content, folder=""):
    r = client.get(f"/user/{username}/new")
    loc = r.headers["Location"]
    note_id = loc.rstrip("/").rsplit("/", 1)[-1]
    data = {"content": content,
            "csrf_token": csrf_of(client.get(loc).get_data(as_text=True))}
    if folder:
        data["folder"] = folder
    r = client.post(loc, data=data)
    assert r.status_code == 302, "保存笔记失败"
    return note_id


def list_order(client, username, query=""):
    """解析列表页笔记链接的出现顺序（排除 /new、/images、/settings 等入口）"""
    html = client.get(f"/user/{username}{query}").get_data(as_text=True)
    ids = re.findall(rf'href="/user/{username}/([a-z0-9]+)"', html)
    return [i for i in ids if i not in ("new", "images", "attachments", "settings")]


def main():
    passed = []

    def check(label, cond):
        assert cond, f"FAIL: {label}"
        passed.append(label)
        print(f"  [ok] {label}")

    # ===== A. 校验与规范化（纯函数） =====
    print("[A] 文件夹路径校验 / 规范化")
    check("合法单段", valid_folder("工作") and valid_folder("a-b_c"))
    check("合法多级", valid_folder("工作/项目A/需求") and valid_folder("a/b"))
    check("拒绝空段与首尾斜杠", not valid_folder("a//b") and not valid_folder("/a")
          and not valid_folder("a/") and not valid_folder("/"))
    check("拒绝超长", not valid_folder("a" * (MAX_FOLDER_NAME_LENGTH + 1)))
    check("拒绝超深", not valid_folder("/".join(["a"] * (MAX_FOLDER_DEPTH + 1)))
          and valid_folder("/".join(["a"] * MAX_FOLDER_DEPTH)))
    check("规范化去空白/合并斜杠", parse_folder_input("  工作 / 项目A ")
          == "工作/项目A" and parse_folder_input("a//b") == "a/b"
          and parse_folder_input("/a/") == "a")
    check("非法输入归为空", parse_folder_input("a b") == "" and parse_folder_input("") == "")
    check("子树匹配", folder_in_subtree("工作/项目A", "工作")
          and folder_in_subtree("工作", "工作")
          and not folder_in_subtree("工作A", "工作")
          and folder_in_subtree("任意", ""))

    # ===== B. 树构建（纯函数，保持传入顺序） =====
    print("[B] build_folder_tree 结构")
    items = [
        {"id": "n1", "folder": "工作/项目A"},
        {"id": "n2", "folder": "工作/项目B"},
        {"id": "n3", "folder": "工作"},
        {"id": "n4", "folder": ""},
        {"id": "n5", "folder": "生活"},
    ]
    t = build_folder_tree(items)
    check("total 与未归类分离", t["total"] == 5 and [x["id"] for x in t["notes"]] == ["n4"])
    check("同层按名称升序", [c["name"] for c in t["children"]] == ["工作", "生活"])
    work = t["children"][0]
    check("子树计数含自身与后代", work["count"] == 3 and [x["id"] for x in work["notes"]] == ["n3"])
    check("中间层与完整 path", [g["name"] for g in work["children"]] == ["项目A", "项目B"]
          and work["children"][0]["path"] == "工作/项目A")
    check("组内保持传入顺序", [x["id"] for x in work["children"][0]["notes"]] == ["n1"])

    # ===== C. 端到端：保存与列表树渲染 =====
    print("[C] 编辑页保存嵌套路径 + 列表页树")
    app = create_app()
    app.config["TESTING"] = True
    limiter.enabled = False
    cache.clear()
    client = app.test_client()
    register_and_login(client, USER)

    na = create_note(client, USER, "A", folder="工作/项目A")
    nb = create_note(client, USER, "B", folder="工作")
    nc = create_note(client, USER, "C", folder="")
    check("嵌套路径读回", get_note_folder(USER, na) == "工作/项目A"
          and get_note_folder(USER, nb) == "工作")
    html = client.get(f"/user/{USER}").get_data(as_text=True)
    check("渲染树容器", 'class="folder-tree"' in html and "tree-children" in html)
    check("含文件夹名与未归类", "项目A" in html and "未归类" in html)
    check("树节点用 button 折叠", html.count('class="tree-toggle"') >= 3)
    check("未归类节点无筛选链接", "folder=__uncat__" not in html)

    # 顺序：工作 组（n b 在前，na 在后？组内按 items 传入顺序 = 置顶/时间序）
    # 这里仅断言树形下仍能取到全部笔记链接，且不重复
    order = list_order(client, USER)
    check("树形下笔记链接齐全", sorted(order) == sorted([na, nb, nc]) and len(order) == 3)

    # ===== D. ?folder= 子树筛选 =====
    print("[D] ?folder= 子树筛选")
    check("父文件夹含子文件夹笔记", sorted(list_order(client, USER, "?folder=工作"))
          == sorted([na, nb]))
    check("子文件夹只含自身笔记", list_order(client, USER, "?folder=%E5%B7%A5%E4%BD%9C/%E9%A1%B9%E7%9B%AEA")
          == [na])
    check("未归类不匹配工作子树", nc not in list_order(client, USER, "?folder=工作"))
    html = client.get(f"/user/{USER}?folder=%E5%B7%A5%E4%BD%9C").get_data(as_text=True)
    check("筛选时有面包屑", "folder-breadcrumb" in html)

    # ===== E. 规范化落盘（非法输入不归类） =====
    print("[E] 非法输入处理")
    nd = create_note(client, USER, "D", folder="a//b")
    check("非法路径片段被规范化保存", get_note_folder(USER, nd) == "a/b")

    # ===== F. 用户隔离 =====
    print("[F] 用户隔离")
    csrf = csrf_of(client.get("/").get_data(as_text=True))
    client.post("/logout", data={"csrf_token": csrf})
    register_and_login(client, OTHER)
    own = create_note(client, OTHER, "别人的", folder="他人/私有")
    html = client.get(f"/user/{OTHER}").get_data(as_text=True)
    check("他人列表只含自己笔记", own in html and na not in html)
    check("他人文件夹树独立", "他人" in html and "工作" not in html)

    # ===== G. 功能开关门控 =====
    print("[G] 功能开关 note_folders")
    set_flags({k: (k != "note_folders") for k in FEATURE_KEYS})
    cache.clear()
    html = client.get(f"/user/{OTHER}").get_data(as_text=True)
    check("停用后不渲染树", 'class="folder-tree"' not in html)
    check("停用后无文件夹筛选链接", "?folder=" not in html)
    set_flags({k: True for k in FEATURE_KEYS})
    cache.clear()
    html = client.get(f"/user/{OTHER}").get_data(as_text=True)
    check("重新启用后树恢复", 'class="folder-tree"' in html)

    # ===== H. 持久化（file 后端 note_folders.json） =====
    print("[H] 持久化")
    path = os.path.join(DATA_DIR, "note_folders.json")
    check("note_folders.json 已落盘", os.path.exists(path))
    with open(path, encoding="utf-8") as f:
        stored = json.load(f)
    check("落盘结构为 {用户: {笔记: 路径}}",
          stored.get(USER, {}).get(na) == "工作/项目A"
          and stored.get(USER, {}).get(nd) == "a/b")

    print(f"\n全部通过：{len(passed)} 项检查")


if __name__ == "__main__":
    try:
        main()
    except AssertionError as e:
        print(f"\n{e}")
        sys.exit(1)
