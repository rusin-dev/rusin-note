"""笔记文件夹功能端到端测试：编辑页底部文件夹输入（datalist 补全）、列表页
文件夹云、?folder= 与 ?tag= 组合筛选、缓存键隔离、移动/取消归类、删除笔记
联动清理、功能开关门控与 file 后端持久化。

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

from app import create_app                      # noqa: E402
from app.extensions import cache, limiter       # noqa: E402
from app.feature_flags import FEATURE_KEYS, set_flags  # noqa: E402
from app.folders import (                       # noqa: E402
    get_note_folder, get_user_note_folders, list_user_folders, parse_folder_input,
)

USER = "keeper"
OTHER = "viewer3"
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


def new_note(client, username):
    """走 /user/<u>/new 拿到随机笔记 ID 的编辑页地址"""
    r = client.get(f"/user/{username}/new")
    assert r.status_code == 302, f"新建笔记失败: {r.status_code}"
    return r.headers["Location"]


def create_note(client, username, content, tags=None, folder=None):
    """新建笔记并保存内容 / 标签 / 文件夹，返回笔记 ID"""
    loc = new_note(client, username)
    note_id = loc.rstrip("/").rsplit("/", 1)[-1]
    r = save_note(client, username, note_id, content, tags=tags, folder=folder)
    assert r.status_code == 302, f"保存笔记失败: {r.status_code}"
    return note_id


def save_note(client, username, note_id, content, tags=None, folder=None):
    data = {"content": content, "csrf_token": edit_csrf(client, username, note_id)}
    if tags is not None:
        data["tags"] = tags
    if folder is not None:
        data["folder"] = folder
    return client.post(f"/user/{username}/{note_id}", data=data)


def edit_csrf(client, username, note_id):
    return csrf_of(client.get(f"/user/{username}/{note_id}").get_data(as_text=True))


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

    # ===== A. 解析规则（模块级） =====
    print("[A] parse_folder_input 解析规则")
    check("去空白后保留合法名", parse_folder_input("  工作 ") == "工作")
    check("空输入返回空串", parse_folder_input("   ") == "")
    check("非法字符返回空串", parse_folder_input("a/b") == "" and parse_folder_input("a b") == "")
    check("超长名称返回空串（>32 字符）", parse_folder_input("x" * 33) == "")
    check("32 字符名称保留", parse_folder_input("x" * 32) == "x" * 32)
    check("中文名称合法", parse_folder_input("项目资料") == "项目资料")

    # ===== B. 编辑页文件夹输入与回显 =====
    print("[B] 编辑页底部文件夹输入")
    register_and_login(client, USER)
    html = client.get(new_note(client, USER)).get_data(as_text=True)
    check("编辑页含文件夹输入框", 'id="noteFolder"' in html and 'name="folder"' in html)
    check("初始值为空", 'value=""' in html.split("noteFolder", 1)[1][:400])

    note1 = create_note(client, USER, "第一篇", tags="重要", folder="工作")
    check("模块层读到归属", get_note_folder(USER, note1) == "工作")
    html = client.get(f"/user/{USER}/{note1}").get_data(as_text=True)
    check("编辑页回显文件夹", 'value="工作"' in html)
    check("已有文件夹进入 datalist 补全", '<option value="工作">' in html)

    # ===== C. 列表页：文件夹云 + 组合筛选 =====
    print("[C] 列表页文件夹云与组合筛选")
    note2 = create_note(client, USER, "第二篇", tags="随笔", folder="生活")
    note3 = create_note(client, USER, "第三篇", tags="重要")

    check("文件夹云按数量统计", list_user_folders(USER) == [("工作", 1), ("生活", 1)])

    # 先访问未过滤页（写入缓存），再逐级筛选：验证缓存键含 folder/tag 参数
    html_all = client.get(f"/user/{USER}").get_data(as_text=True)
    check("未过滤页包含全部三篇", note1 in html_all and note2 in html_all and note3 in html_all)
    check("云中含文件夹与标签筛选链接", "?folder=工作" in html_all and "?tag=重要" in html_all)
    check("笔记项展示文件夹徽片", 'class="note-folder"' in html_all)

    html_f = client.get(f"/user/{USER}?folder=工作").get_data(as_text=True)
    check("文件夹筛选仅命中第一篇（缓存键隔离生效）",
          note1 in html_f and note2 not in html_f and note3 not in html_f)
    html_t = client.get(f"/user/{USER}?tag=重要").get_data(as_text=True)
    check("标签筛选命中一、三篇", note1 in html_t and note2 not in html_t and note3 in html_t)
    html_ft = client.get(f"/user/{USER}?folder=工作&tag=重要").get_data(as_text=True)
    check("组合筛选仅命中交集", note1 in html_ft and note2 not in html_ft and note3 not in html_ft)
    html_none = client.get(f"/user/{USER}?folder=nosuch").get_data(as_text=True)
    check("未知文件夹提示无匹配", "该文件夹下没有笔记" in html_none and note1 not in html_none)

    # ===== D. 移动与取消归类 =====
    print("[D] 移动文件夹与取消归类")
    r = save_note(client, USER, note2, "第二篇", folder="工作")
    assert r.status_code == 302
    check("笔记移动到新文件夹", get_note_folder(USER, note2) == "工作")
    check("原文件夹随引用清空而消失", list_user_folders(USER) == [("工作", 2)])
    html = client.get(f"/user/{USER}").get_data(as_text=True)
    check("列表页不再显示空文件夹", "生活" not in html)

    r = save_note(client, USER, note2, "第二篇", folder="")
    assert r.status_code == 302
    check("空输入取消归类", get_note_folder(USER, note2) == "")

    # ===== E. 删除笔记联动清理 =====
    print("[E] 删除笔记联动清理")
    r = save_note(client, USER, note1, "", folder="工作")
    assert r.status_code == 302
    check("删除笔记后归属被清理", get_note_folder(USER, note1) == "")
    check("归属表不再含该笔记", note1 not in get_user_note_folders(USER))

    # ===== F. 功能开关门控 =====
    print("[F] 功能开关 note_folders")
    set_flags({k: (k != "note_folders") for k in FEATURE_KEYS})
    cache.clear()  # 管理页保存开关时会 cache.clear()，这里等价模拟
    html = client.get(new_note(client, USER)).get_data(as_text=True)
    check("停用后编辑页无文件夹输入", 'id="noteFolder"' not in html and 'name="folder"' not in html)
    check("停用后标签栏不受影响", 'id="noteTags"' in html)
    html = client.get(f"/user/{USER}").get_data(as_text=True)
    check("停用后列表页无文件夹链接", "?folder=" not in html and 'class="note-folder"' not in html)
    check("停用后标签筛选不受影响", "?tag=重要" in html)

    note4 = create_note(client, USER, "无文件夹时代", folder="ignored")
    check("停用时不保存归属", get_note_folder(USER, note4) == "")

    set_flags({k: True for k in FEATURE_KEYS})
    cache.clear()
    html = client.get(f"/user/{USER}/{note4}").get_data(as_text=True)
    check("重新启用后文件夹输入恢复", 'id="noteFolder"' in html)

    # ===== G. 用户隔离 =====
    print("[G] 用户间文件夹隔离")
    client.get("/logout")
    register_and_login(client, OTHER)
    note5 = create_note(client, OTHER, "别人的笔记", folder="工作")
    check("归属按用户隔离存储", get_note_folder(OTHER, note5) == "工作"
          and note5 not in get_user_note_folders(USER))
    html = client.get(f"/user/{OTHER}").get_data(as_text=True)
    check("他人列表页只含自己的笔记与文件夹",
          "工作" in html and note5 in html and note3 not in html)

    # ===== H. 持久化（file 后端落盘 note_folders.json）=====
    print("[H] 持久化")
    folders_path = os.path.join(DATA_DIR, "note_folders.json")
    check("note_folders.json 已落盘", os.path.exists(folders_path))
    with open(folders_path, encoding="utf-8") as f:
        stored = json.load(f)
    check("落盘结构为 {用户: {笔记: 文件夹}}",
          stored.get(USER) in (None, {}) and stored.get(OTHER, {}).get(note5) == "工作")

    print(f"\n全部通过：{len(passed)} 项检查")


if __name__ == "__main__":
    try:
        main()
    except AssertionError as e:
        print(f"\n{e}")
        sys.exit(1)
