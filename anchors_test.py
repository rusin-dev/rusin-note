"""Markdown 标题锚点功能端到端测试（服务端可验证部分）：
head 脚本注入（私有 md 页 / world md 页 / 编辑页）、功能开关门控、
服务端渲染保持不变（锚点纯客户端实现，不放宽 bleach 白名单）。

JS 行为（slug 生成、悬浮锚点、页内 #链接解析、深链定位）由浏览器实测覆盖。
运行：python anchors_test.py
自动使用临时 RUSIN_DATA_DIR，不影响现有数据目录。
"""
import os
import re
import sys
import tempfile

# 隔离数据目录（必须在导入 app 之前设置）
DATA_DIR = tempfile.mkdtemp(prefix="rusin-anchors-test-")
os.environ["RUSIN_DATA_DIR"] = DATA_DIR

from app import create_app                      # noqa: E402
from app.extensions import cache, limiter       # noqa: E402
from app.feature_flags import FEATURE_KEYS, feature_enabled, set_flags  # noqa: E402
from app.utils import render_markdown_html      # noqa: E402

USER = "writer"
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


def create_note(client, content, world=False):
    """创建一篇笔记（world 公开笔记无需登录），返回笔记 ID"""
    loc = client.get("/world" if world else f"/user/{USER}/new").headers["Location"]
    note_id = loc.rstrip("/").rsplit("/", 1)[-1]
    csrf = csrf_of(client.get(loc).get_data(as_text=True))
    r = client.post(loc, data={"content": content, "csrf_token": csrf})
    assert r.status_code == 302, f"保存笔记失败: {r.status_code}"
    return note_id


MD_CONTENT = "# 顶层标题\n\n[跳到第二节](#第二节 小节)\n\n## 第二节 小节\n\n### 重复\n\n### 重复\n\n正文"


def main():
    passed = []

    def check(label, cond):
        assert cond, f"FAIL: {label}"
        passed.append(label)
        print(f"  [ok] {label}")

    app = create_app()
    app.config["TESTING"] = True
    limiter.enabled = False
    client = app.test_client()

    # ===== A. 注册表与默认值 =====
    print("[A] 功能注册")
    check("heading_anchors 已注册", "heading_anchors" in FEATURE_KEYS)
    check("默认启用", feature_enabled("heading_anchors") is True)

    # ===== B. 服务端渲染保持不变（纯客户端方案） =====
    print("[B] 服务端渲染不变")
    html = render_markdown_html("# Title\n\ntext")
    check("标题服务端输出不带 id（bleach 白名单未放宽）",
          "<h1>Title</h1>" in html and "<h1 id" not in html)
    frag_html = render_markdown_html("[x](#some-heading)")
    check("页内 #链接的 href 服务端保留（ bleach 放行片段链接）",
          'href="#some-heading"' in frag_html)

    # ===== C. 私有笔记 md 页注入 =====
    print("[C] 私有笔记 md 页")
    register_and_login(client, USER)
    note_id = create_note(client, MD_CONTENT)
    html = client.get(f"/user/{USER}/{note_id}.md").get_data(as_text=True)
    check("md 页注入 HeadingAnchors 脚本", "window.HeadingAnchors = (function()" in html)
    check("注入悬浮锚点样式", ".heading-anchor" in html)
    check("锚点提示文案本地化（zh）", "跳转到此标题" in html)
    check("锚点图标使用 fa-link", "fa-link" in html)
    check("slug 生成含 Unicode 属性正则", "\\p{L}" in html)
    edit_html = client.get(f"/user/{USER}/{note_id}").get_data(as_text=True)
    check("编辑页同样注入脚本", "window.HeadingAnchors = (function()" in edit_html)

    # ===== D. world 公开笔记 md 页注入 =====
    print("[D] world 公开笔记 md 页")
    world_id = create_note(client, MD_CONTENT, world=True)
    html = client.get(f"/world/{world_id}.md").get_data(as_text=True)
    check("world md 页注入脚本", "window.HeadingAnchors = (function()" in html)

    # ===== E. 功能开关门控 =====
    print("[E] 功能开关 heading_anchors")
    set_flags({k: (k != "heading_anchors") for k in FEATURE_KEYS})
    cache.clear()  # 管理页保存开关时会 cache.clear()，这里等价模拟
    html = client.get(f"/user/{USER}/{note_id}.md").get_data(as_text=True)
    check("停用后 md 页无脚本", "window.HeadingAnchors = (function()" not in html)
    edit_html = client.get(f"/user/{USER}/{note_id}").get_data(as_text=True)
    check("停用后编辑页无脚本", "window.HeadingAnchors = (function()" not in edit_html)

    set_flags({k: True for k in FEATURE_KEYS})
    cache.clear()
    html = client.get(f"/user/{USER}/{note_id}.md").get_data(as_text=True)
    check("重新启用后脚本恢复", "window.HeadingAnchors = (function()" in html)

    # ===== F. /count 呈现功能卡 =====
    print("[F] /count 功能状态")
    count_html = client.get("/count").get_data(as_text=True)
    check("/count 呈现 Markdown 标题锚点", "Markdown 标题锚点" in count_html)

    print(f"\n全部通过：{len(passed)} 项检查")


if __name__ == "__main__":
    try:
        main()
    except AssertionError as e:
        print(f"\n{e}")
        sys.exit(1)
