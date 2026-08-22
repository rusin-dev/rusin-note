"""快捷引用（#87）端到端测试：引用搜索 API、Markdown 渲染链接化、
编辑器自动补全上下文注入，以及 expand_note_refs 扫描器的边界行为。

运行：python refs_test.py
自动使用临时 RUSIN_DATA_DIR，不影响现有数据目录。
"""
import os
import re
import sys
import tempfile
import time

# 隔离数据目录（必须在导入 app 之前设置）
DATA_DIR = tempfile.mkdtemp(prefix="rusin-refs-test-")
os.environ["RUSIN_DATA_DIR"] = DATA_DIR

from app import create_app                      # noqa: E402
from app.utils import expand_note_refs          # noqa: E402

USERNAME = "alice"
PASSWORD = "TestPass1!"


def csrf_of(html: str) -> str:
    m = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', html)
    assert m, "页面中未找到 csrf_token"
    return m.group(1)


def save_note(client, path, content, csrf):
    r = client.post(path, data={"content": content, "csrf_token": csrf})
    assert r.status_code in (200, 302), f"保存 {path} 失败: {r.status_code}"


def main():
    passed = []

    def check(label, cond):
        assert cond, f"FAIL: {label}"
        passed.append(label)
        print(f"  [ok] {label}")

    app = create_app()
    app.config["TESTING"] = True
    client = app.test_client()

    # ===== A. 注册并登录 =====
    print("[A] 准备用户与笔记")
    r = client.get("/register")
    check("注册页可访问", r.status_code == 200)
    r = client.post("/register", data={
        "username": USERNAME, "password": PASSWORD, "confirm": PASSWORD,
        "csrf_token": csrf_of(r.get_data(as_text=True))})
    assert r.status_code in (200, 302), f"注册失败: {r.status_code}"
    r = client.get("/login")
    r = client.post("/login", data={
        "username": USERNAME, "password": PASSWORD,
        "csrf_token": csrf_of(r.get_data(as_text=True))})
    assert r.status_code in (200, 302), f"登录失败: {r.status_code}"

    save_note(client, f"/user/{USERNAME}/todo", "# 我的待办清单\n- [ ] 事项 A",
              csrf_of(client.get(f"/user/{USERNAME}/todo").get_data(as_text=True)))
    time.sleep(0.02)
    save_note(client, f"/user/{USERNAME}/daily-log", "2026-08-22 工作日志",
              csrf_of(client.get(f"/user/{USERNAME}/daily-log").get_data(as_text=True)))
    time.sleep(0.02)
    index_md = "\n".join([
        "#todo 引用在行首",
        "",
        "正文见 #daily-log 与 #todo，不存在的 #missing-ref 不链接，参见#todo 标点前缀。",
        "",
        "行内代码 `#todo` 不替换。",
        "",
        "```c",
        "#include <stdio.h>",
        "```",
        "",
        "    #todo 缩进代码块",
        "",
        "锚点 [跳转](#todo) 不替换。",
        "",
        "反斜杠 \\#todo 不引用。",
        "",
        "[def]: /x#todo",
    ])
    save_note(client, f"/user/{USERNAME}/index", index_md,
              csrf_of(client.get(f"/user/{USERNAME}/index").get_data(as_text=True)))

    # ===== B. 引用搜索 API =====
    print("[B] /user/<u>/refs 搜索 API")
    r = client.get(f"/user/{USERNAME}/refs")
    check("空 q 返回 JSON 列表", r.status_code == 200 and r.is_json)
    items = r.get_json()["items"]
    ids = [it["id"] for it in items]
    check("空 q 返回全部笔记", set(ids) == {"todo", "daily-log", "index"})
    check("最近编辑优先", ids[0] == "index")
    check("返回标题预览", any(it["title"] == "我的待办清单" for it in items))
    check("返回 mtime", all(isinstance(it["mtime"], (int, float)) for it in items))

    r = client.get(f"/user/{USERNAME}/refs?q=todo")
    ids = [it["id"] for it in r.get_json()["items"]]
    # todo 按 ID 命中；index 首行是「#todo 引用在行首」按标题命中；daily-log 不命中
    check("按 ID / 首行标题匹配", "todo" in ids and "index" in ids and "daily-log" not in ids)

    r = client.get(f"/user/{USERNAME}/refs?q=待办")
    ids = [it["id"] for it in r.get_json()["items"]]
    check("按标题模糊匹配（中文）", ids == ["todo"])

    r = client.get(f"/user/{USERNAME}/refs?q=zzz不存在")
    check("无匹配返回空列表", r.get_json()["items"] == [])

    r = app.test_client().get(f"/user/{USERNAME}/refs")
    check("未登录（无会话）访问 401", r.status_code == 401)
    check("refs 路由不被 /user/<u>/<id> 抢走",
          client.get(f"/user/{USERNAME}/refs").status_code == 200)

    # ===== C. Markdown 渲染：#id 链接化 =====
    print("[C] /user/<u>/<id>/md 渲染")
    html = client.get(f"/user/{USERNAME}/index/md").get_data(as_text=True)
    todo_href = f'href="/user/{USERNAME}/todo"'
    check("行首引用渲染为链接而非标题", f'<a {todo_href}' in html and "<h1>todo" not in html)
    check("正文引用链接数量正确（3 处 todo）", html.count(todo_href) == 3)
    check("链接 title 带目标笔记标题", 'title="我的待办清单"' in html)
    check("不存在的引用保持纯文本", f'href="/user/{USERNAME}/missing-ref"' not in html)
    check("行内代码内不替换", "`" not in html or '<code>#todo</code>' in html)
    check("围栏代码块内不替换", "#include" in html and f'href="/user/{USERNAME}/include"' not in html)
    check("缩进代码块内不替换", "#todo 缩进代码块" in html)
    check("Markdown 锚点链接不替换", 'href="#todo"' in html)
    check("转义井号不替换", "\\#" not in html and "反斜杠 #todo 不引用" in html)
    check("链接定义行被 Markdown 吞掉且未被替换", "[def]" not in html)

    # ===== D. 公开笔记（world）引用解析 =====
    print("[D] /world 引用解析")
    for nid in ("wref1", "wref2"):
        save_note(client, f"/world/{nid}", "内容",
                  csrf_of(client.get(f"/world/{nid}").get_data(as_text=True)))
    save_note(client, "/world/wref2", "链接到 #wref1 试试",
              csrf_of(client.get("/world/wref2").get_data(as_text=True)))
    html = client.get("/world/wref2/md").get_data(as_text=True)
    check("world 引用解析到 /world/<id>", 'href="/world/wref1"' in html)

    # ===== E. 编辑器自动补全上下文 =====
    print("[E] 编辑页注入")
    html = client.get(f"/user/{USERNAME}/index").get_data(as_text=True)
    check("下拉框容器存在", 'id="refPopover"' in html)
    check("注入搜索 API 地址", f'"/user/{USERNAME}/refs"' in html)
    check("注入笔记 ID 列表（预览链接化用）", '"todo"' in html and '"daily-log"' in html)

    # ===== F. expand_note_refs 扫描器单元行为 =====
    print("[F] expand_note_refs 边界")

    def resolver(nid):
        return {"abc": 'he said "hi" (ok)', "x": ""}.get(nid)

    out = expand_note_refs("see #abc and #none", "u", "/user/u", resolver)
    check("存在才替换", "and #none" in out and "](/user/u/abc" in out)
    check("title 中的引号/括号被转义", '\\"' not in out and "（ok）" in out)

    out = expand_note_refs("空标题 #x", "u", "/user/u", resolver)
    check("空标题省略 title 部分", out == "空标题 [#x](/user/u/x)")

    out = expand_note_refs("```python\n#abc\n```\nsee #abc", "u", "/user/u", resolver)
    check("围栏代码块跳过", "](/user/u/abc" in out and out.count("](/user/u/abc") == 1)

    out = expand_note_refs("[t](#abc) ![i](#abc) [r][#abc]", "u", "/user/u", resolver)
    check("链接/图片目标不替换", out == "[t](#abc) ![i](#abc) [r][#abc]")

    out = expand_note_refs("abc#abc ##abc 'ab#c'", "u", "/user/u", resolver)
    check("紧邻字符排除（\\w/#/引号）", "](/user/u/abc" not in out)

    out = expand_note_refs("no refs here", "u", "/user/u", resolver)
    check("无井号原文返回", out == "no refs here")

    print(f"\n[refs] 全部 {len(passed)} 项测试通过（数据目录：{DATA_DIR}）")


if __name__ == "__main__":
    try:
        main()
    except AssertionError as e:
        print(e, file=sys.stderr)
        sys.exit(1)
