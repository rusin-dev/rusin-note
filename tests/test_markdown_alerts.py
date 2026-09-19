"""GitHub 风格提示卡片（[!NOTE] / [!WARNING] ...）端到端测试（pytest + logging）。

覆盖：服务端 Markdown 渲染把 ``> [!TYPE]`` 引用块转换为可折叠 <details>
卡片、默认展开 / ``-`` 折叠 / ``+`` 展开记号、``[!INFO]`` 别名、未知类型
保持普通引用块、卡片内 Markdown 与 XSS 清洗、功能开关门控、只读笔记页集成。

运行：``pytest tests/test_markdown_alerts.py``
"""
from __future__ import annotations

import logging

from app.feature_flags import FEATURE_KEYS, set_flags
from app.utils import render_markdown_html
from support import create_note, expect, register_and_login

logger = logging.getLogger("rusin.tests.alerts")

USER = "alice"


class TestAlertRendering:
    """A/B：纯渲染函数（不依赖 HTTP）。"""

    def test_default_open_and_labels(self):
        logger.info("=== [A] 类型、标题、图标与默认展开 ===")
        for kind, label, icon in (
            ("NOTE", "说明", "fa-circle-info"),
            ("TIP", "提示", "fa-lightbulb"),
            ("IMPORTANT", "重要", "fa-circle-exclamation"),
            ("WARNING", "警告", "fa-triangle-exclamation"),
            ("CAUTION", "注意", "fa-circle-xmark"),
        ):
            html = render_markdown_html(f"> [!{kind}]\n> body text")
            expect(f'class="md-alert md-alert-{kind.lower()}"' in html,
                   f"{kind} 生成对应卡片类名")
            expect("<details" in html and " open" in html, f"{kind} 默认展开")
            expect(f'fa-solid {icon}' in html and 'aria-hidden="true"' in html,
                   f"{kind} 带有图标 {icon}")
            expect(f'</i>{label}</summary>' in html,
                   f"{kind} 标题为「{label}」且图标在标题内")

    def test_collapsed_and_explicit_open(self):
        logger.info("=== [B] 折叠记号 - / + ===")
        collapsed = render_markdown_html("> [!WARNING]-\n> hidden")
        # 仅比较开始标签，避免 `open` 作为 body 文本出现时误判
        start = collapsed.split(">", 1)[0]
        expect("<details" in collapsed and " open" not in start,
               "- 记号默认折叠（<details> 无 open 属性）")
        expanded = render_markdown_html("> [!WARNING]+\n> shown")
        expect(" open" in expanded.split(">", 1)[0], "+ 记号显式展开")

    def test_info_alias_and_inline_content(self):
        logger.info("=== [C] INFO 别名与同行内容 ===")
        html = render_markdown_html("> [!INFO]\n> aliased")
        expect("md-alert-note" in html and "说明" in html, "[!INFO] 归一为 note")
        inline = render_markdown_html("> [!NOTE] same line content")
        expect("same line content" in inline and "[!NOTE]" not in inline,
               "标记同行内容保留且标记被移除")

    def test_unknown_and_bold_marker_untouched(self):
        logger.info("=== [D] 非卡片引用块保持不变 ===")
        unknown = render_markdown_html("> [!UNKNOWN]\n> nope")
        expect("<details" not in unknown and "<blockquote>" in unknown,
               "未注册类型仍是普通引用块")
        expect("[!UNKNOWN]" in unknown, "未注册类型标记原样保留")
        bold = render_markdown_html("> **[!NOTE]** bold")
        expect("<details" not in bold, "加粗写法不识别为卡片")
        plain = render_markdown_html("> 普通引用")
        expect("<details" not in plain and "<blockquote>" in plain,
               "普通引用块不受影响")

    def test_markdown_inside_and_xss(self):
        logger.info("=== [E] 卡片内 Markdown 与 XSS 清洗 ===")
        html = render_markdown_html(
            "> [!NOTE]\n> A **bold** and `code`.\n>\n> - one\n> - two\n>\n"
            "> <script>alert(1)</script>[x](javascript:alert(1))"
        )
        expect("<strong>bold</strong>" in html and "<code>code</code>" in html,
               "卡片内行内格式正常渲染")
        expect("<ul>" in html and "<li>one</li>" in html, "卡片内列表正常渲染")
        expect("<script>" not in html, "脚本标签被 bleach 清除")
        expect("javascript:" not in html, "危险链接协议被清除")

    def test_nested_cards(self):
        logger.info("=== [F] 卡片嵌套 ===")
        html = render_markdown_html("> [!NOTE]\n> outer\n>\n> > [!TIP]\n> > inner")
        expect(html.count("<details") == 2 and "md-alert-note" in html
               and "md-alert-tip" in html, "嵌套卡片均被转换")

    def test_feature_flag_gating(self):
        logger.info("=== [G] 功能开关 markdown_alerts ===")
        try:
            set_flags({key: (key != "markdown_alerts") for key in FEATURE_KEYS})
            html = render_markdown_html("> [!WARNING]\n> off")
            expect("<details" not in html and "<blockquote>" in html,
                   "停用后不再生成卡片")
        finally:
            set_flags({key: True for key in FEATURE_KEYS})


class TestAlertE2E:
    """H：只读笔记页集成。"""

    def test_note_readonly_page(self, ctx):
        logger.info("=== [H] 只读笔记页渲染卡片 ===")
        register_and_login(ctx.client, USER)
        content = (
            "# 卡片演示\n\n"
            "> [!IMPORTANT]\n> 这是一条重要说明，含 **加粗** 文本。\n\n"
            "段落\n\n"
            "> [!WARNING]-\n> 默认折叠的警告\n"
        )
        note_id = create_note(ctx.client, USER, content)
        html = ctx.client.get(f"/user/{USER}/{note_id}.md").get_data(as_text=True)
        expect("md-alert md-alert-important" in html, "只读页渲染 important 卡片")
        expect("md-alert md-alert-warning" in html, "只读页渲染 warning 卡片")
        expect("这是一条重要说明" in html and "<strong>加粗</strong>" in html,
               "卡片正文正常渲染")
        expect('fa-solid fa-circle-exclamation' in html
               and 'fa-solid fa-triangle-exclamation' in html, "卡片标题带有对应图标")
        expect('md-alert-important' in html and '重要' in html
               and 'md-alert-warning' in html and '警告' in html, "卡片标题本地化")
        expect("[!IMPORTANT]" not in html and "[!WARNING]" not in html,
               "标记已被消费")
