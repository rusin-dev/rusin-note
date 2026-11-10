"""主笔记所见即所得编辑器的本地资源与页面契约测试。"""
from __future__ import annotations

from html.parser import HTMLParser
from urllib.parse import urlsplit

import pytest

from support import create_note, expect, register_and_login


USER = "wysiwyg"


class _EditorPageParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.assets = []
        self.ids = set()
        self.content_textareas = 0

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if values.get("id"):
            self.ids.add(values["id"])
        if tag == "textarea" and values.get("name") == "content":
            self.content_textareas += 1
        if tag == "script" and values.get("src"):
            self.assets.append(values["src"])
        if tag == "link" and values.get("href"):
            rel = set((values.get("rel") or "").split())
            if rel & {"stylesheet", "preload"}:
                self.assets.append(values["href"])


@pytest.fixture(scope="class")
def editor_page(ctx):
    register_and_login(ctx.client, USER)
    note_id = create_note(ctx.client, USER, "# 富文本标题\n\n**粗体** 与 $x^2$。")
    response = ctx.client.get(f"/user/{USER}/{note_id}")
    expect(response.status_code == 200, "主笔记编辑页可访问")
    parser = _EditorPageParser()
    parser.feed(response.get_data(as_text=True))
    return ctx.client, parser


class TestWysiwygEditor:
    def test_editor_page_has_no_third_party_asset_urls(self, editor_page):
        """把任何编辑器依赖改回 CDN 都会破坏离线部署并触发此测试。"""
        _, parser = editor_page
        external = [url for url in parser.assets
                    if urlsplit(url).scheme or urlsplit(url).netloc]
        expect(parser.assets, "编辑页声明了静态资源")
        expect(not external, f"编辑页静态资源全部同源，外部地址：{external}")

    def test_local_editor_assets_are_retrievable(self, editor_page):
        """删除任一本地运行时资源都必须产生可见的 404，而不是静默回退 CDN。"""
        client, _ = editor_page
        paths = (
            "/static/vendor/vditor/index.min.js",
            "/static/vendor/vditor/index.css",
            "/static/editor/markdown-editor.js",
            "/static/editor/markdown-editor.css",
        )
        for path in paths:
            response = client.get(path)
            expect(response.status_code == 200 and len(response.data) > 0,
                   f"本地编辑器资源可加载：{path}")

    def test_editor_provides_rich_mount_and_source_fallback(self, editor_page):
        """移除富文本挂载点或原始表单回退都会破坏双模式编辑契约。"""
        _, parser = editor_page
        expect("richTextEditor" in parser.ids, "页面提供富文本编辑器挂载点")
        expect(parser.content_textareas == 1, "页面保留 Markdown 源码与表单回退")
