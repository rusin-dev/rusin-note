"""笔记标签功能端到端测试：编辑页底部标签栏、列表页标签云与 ?tag= 筛选、
解析规则、删除笔记联动清理、功能开关门控与 file 后端持久化。

运行：python tags_test.py
自动使用临时 RUSIN_DATA_DIR，不影响现有数据目录。
"""
import json
import os
import re
import sys
import tempfile

# 隔离数据目录（必须在导入 app 之前设置）
DATA_DIR = tempfile.mkdtemp(prefix="rusin-tags-test-")
os.environ["RUSIN_DATA_DIR"] = DATA_DIR

from app import create_app                      # noqa: E402
from app.extensions import cache, limiter       # noqa: E402
from app.feature_flags import FEATURE_KEYS, set_flags  # noqa: E402
from app.tags import get_note_tags, get_user_note_tags, parse_tag_input  # noqa: E402

USER = "tagger"
OTHER = "viewer2"
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


def save_note(client, username, note_id, content, tags=None):
    """POST 保存笔记内容与标签，返回响应"""
    data = {"content": content, "csrf_token": edit_csrf(client, username, note_id)}
    if tags is not None:
        data["tags"] = tags
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
    print("[A] parse_tag_input 解析规则")
    check("英文/中文逗号分隔", parse_tag_input("a, b，c") == ["a", "b", "c"])
    check("去重并保持顺序", parse_tag_input("a, a，a, b") == ["a", "b"])
    check("非法项被丢弃", parse_tag_input("ok, bad/slash, bad space, <x>") == ["ok"])
    check("中文标签合法", parse_tag_input("工作, ideas") == ["工作", "ideas"])
    check("超长标签被丢弃（>24 字符）", parse_tag_input("x" * 25) == [])
    check("24 字符标签保留", parse_tag_input("x" * 24) == ["x" * 24])
    check("最多保留 10 个标签", len(parse_tag_input(",".join(f"t{i}" for i in range(15)))) == 10)
    check("空输入返回空列表", parse_tag_input("") == [])

    # ===== B. 编辑页标签栏与保存回显 =====
    print("[B] 编辑页底部标签栏")
    register_and_login(client, USER)
    loc = new_note(client, USER)
    note1 = loc.rstrip("/").rsplit("/", 1)[-1]
    html = client.get(loc).get_data(as_text=True)
    check("编辑页含标签输入栏", 'id="noteTags"' in html and 'name="tags"' in html)
    check("输入栏回显当前标签（初始为空）", 'value=""' in html.split("noteTags", 1)[1][:400])

    r = save_note(client, USER, note1, "第一篇笔记", tags="工作, ideas")
    assert r.status_code == 302, f"保存笔记失败: {r.status_code}"
    check("模块层读到标签", get_note_tags(USER, note1) == ["工作", "ideas"])
    html = client.get(f"/user/{USER}/{note1}").get_data(as_text=True)
    check("编辑页回显已存标签", 'value="工作, ideas"' in html)

    # ===== C. 列表页：标签云 + 筛选 =====
    print("[C] 列表页标签云与 ?tag= 筛选")
    loc2 = new_note(client, USER)
    note2 = loc2.rstrip("/").rsplit("/", 1)[-1]
    r = save_note(client, USER, note2, "第二篇笔记", tags="工作")
    assert r.status_code == 302, f"保存第二篇失败: {r.status_code}"

    html = client.get(f"/user/{USER}").get_data(as_text=True)
    check("标签云展示标签与计数", "?tag=工作" in html and "ideas" in html)
    check("每条笔记项展示其标签", html.count("?tag=工作") >= 3)  # 云 1 次 + 两条笔记各 1 次
    check("「全部」链接存在", ">全部<" in html)

    # 先访问未过滤页（写入缓存），再访问筛选页：验证缓存键含 tag 参数
    html_all = client.get(f"/user/{USER}").get_data(as_text=True)
    check("未过滤页包含两篇笔记", note1 in html_all and note2 in html_all)
    html_work = client.get(f"/user/{USER}?tag=工作").get_data(as_text=True)
    check("筛选页命中两篇笔记（缓存键隔离生效）",
          note1 in html_work and note2 in html_work)
    html_ideas = client.get(f"/user/{USER}?tag=ideas").get_data(as_text=True)
    check("ideas 筛选仅命中第一篇", note1 in html_ideas and note2 not in html_ideas)
    html_none = client.get(f"/user/{USER}?tag=nosuch").get_data(as_text=True)
    check("未知标签提示无匹配", "该标签下没有笔记" in html_none and note1 not in html_none)

    # ===== D. 更新与删除联动 =====
    print("[D] 标签更新与笔记删除联动")
    r = save_note(client, USER, note1, "第一篇笔记", tags="solo")
    assert r.status_code == 302
    check("覆盖更新标签", get_note_tags(USER, note1) == ["solo"])
    html = client.get(f"/user/{USER}").get_data(as_text=True)
    check("列表页反映新标签", "solo" in html)

    r = save_note(client, USER, note1, "第一篇笔记", tags="")
    assert r.status_code == 302
    check("空输入清除标签", get_note_tags(USER, note1) == [])

    # 重新打标签后删除笔记（POST 空内容），标签应被删除钩子清理
    save_note(client, USER, note1, "待删除", tags="ghost")
    assert get_note_tags(USER, note1) == ["ghost"]
    r = save_note(client, USER, note1, "", tags="ghost")
    assert r.status_code == 302
    check("删除笔记后标签条目被清理", get_note_tags(USER, note1) == [])
    check("标签表不再含该笔记", note1 not in get_user_note_tags(USER))
    html = client.get(f"/user/{USER}").get_data(as_text=True)
    check("ghost 标签随笔记消失", "ghost" not in html)

    # ===== E. 功能开关门控 =====
    print("[E] 功能开关 note_tags")
    set_flags({k: (k != "note_tags") for k in FEATURE_KEYS})
    cache.clear()  # 管理页保存开关时会 cache.clear()，这里等价模拟
    loc3 = new_note(client, USER)
    note3 = loc3.rstrip("/").rsplit("/", 1)[-1]
    html = client.get(loc3).get_data(as_text=True)
    check("停用后编辑页无标签栏", 'id="noteTags"' not in html)
    html = client.get(f"/user/{USER}").get_data(as_text=True)
    check("停用后列表页无标签云", 'class="tag-cloud"' not in html and "?tag=" not in html)
    r = save_note(client, USER, note3, "无标签时代的笔记", tags="ignored")
    assert r.status_code == 302
    check("停用时不保存标签", get_note_tags(USER, note3) == [])

    set_flags({k: True for k in FEATURE_KEYS})
    cache.clear()
    html = client.get(f"/user/{USER}/{note3}").get_data(as_text=True)
    check("重新启用后标签栏恢复", 'id="noteTags"' in html)

    # ===== F. 用户隔离 =====
    print("[F] 用户间标签隔离")
    client.get("/logout")
    register_and_login(client, OTHER)
    loc4 = new_note(client, OTHER)
    note4 = loc4.rstrip("/").rsplit("/", 1)[-1]
    save_note(client, OTHER, note4, "别人的笔记", tags="工作")
    check("标签按用户隔离存储", get_note_tags(OTHER, note4) == ["工作"]
          and note4 not in get_user_note_tags(USER))
    html = client.get(f"/user/{OTHER}").get_data(as_text=True)
    check("他人列表页只含自己的笔记与标签",
          "工作" in html and note4 in html and note2 not in html and note1 not in html)

    # ===== G. 持久化（file 后端落盘 note_tags.json）=====
    print("[G] 持久化")
    tags_path = os.path.join(DATA_DIR, "note_tags.json")
    check("note_tags.json 已落盘", os.path.exists(tags_path))
    with open(tags_path, encoding="utf-8") as f:
        stored = json.load(f)
    check("落盘结构为 {用户: {笔记: [标签]}}",
          stored.get(USER, {}).get(note2) == ["工作"]
          and stored.get(OTHER, {}).get(note4) == ["工作"])

    print(f"\n全部通过：{len(passed)} 项检查")


if __name__ == "__main__":
    try:
        main()
    except AssertionError as e:
        print(f"\n{e}")
        sys.exit(1)
