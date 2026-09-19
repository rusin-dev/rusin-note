"""首页横幅（仓库根目录 NOTICE.txt 首行）端到端测试（pytest + logging）。

覆盖：NOTICE.txt 内容非空时首页展示首行横幅、仅取第一行、跳过前导空行，
以及空文件 / 文件缺失时首页不渲染横幅。

运行：``pytest tests/test_home_notice.py``
"""
from __future__ import annotations

import logging

from app import config
from app.extensions import cache
from support import expect

logger = logging.getLogger("rusin.tests.notice")


class TestHomeNotice:
    """首页横幅渲染：匿名首页走缓存，取页面前先清缓存保证读到新文件。"""

    def _home(self, ctx) -> str:
        cache.clear()
        return ctx.anon.get("/").get_data(as_text=True)

    def test_first_line_shown(self, ctx, monkeypatch):
        logger.info("=== 非空 NOTICE.txt 展示首行 ===")
        path = ctx.data_dir / "NOTICE.txt"
        path.write_text("第一行横幅\n第二行不应出现\n", encoding="utf-8")
        monkeypatch.setattr(config, "NOTICE_FILE", str(path))
        html = self._home(ctx)
        expect('class="home-notice"' in html, "首页渲染横幅容器")
        expect("第一行横幅" in html, "横幅展示 NOTICE.txt 第一行")
        expect("第二行不应出现" not in html, "横幅只取第一行")

    def test_leading_blank_lines_skipped(self, ctx, monkeypatch):
        logger.info("=== 跳过前导空行 ===")
        path = ctx.data_dir / "NOTICE.txt"
        path.write_text("\n\n  真正的公告\n", encoding="utf-8")
        monkeypatch.setattr(config, "NOTICE_FILE", str(path))
        html = self._home(ctx)
        expect("真正的公告" in html, "横幅展示首个非空行")

    def test_empty_file_hidden(self, ctx, monkeypatch):
        logger.info("=== 空内容不展示横幅 ===")
        path = ctx.data_dir / "NOTICE.txt"
        path.write_text("   \n\n", encoding="utf-8")
        monkeypatch.setattr(config, "NOTICE_FILE", str(path))
        html = self._home(ctx)
        expect('class="home-notice"' not in html, "空文件不渲染横幅")

    def test_missing_file_hidden(self, ctx, monkeypatch):
        logger.info("=== 文件缺失不展示横幅 ===")
        monkeypatch.setattr(config, "NOTICE_FILE", str(ctx.data_dir / "no-such-notice.txt"))
        html = self._home(ctx)
        expect('class="home-notice"' not in html, "缺失文件不渲染横幅")

    def test_notice_escaped(self, ctx, monkeypatch):
        logger.info("=== 横幅文本转义 ===")
        path = ctx.data_dir / "NOTICE.txt"
        path.write_text("<script>alert(1)</script>\n", encoding="utf-8")
        monkeypatch.setattr(config, "NOTICE_FILE", str(path))
        html = self._home(ctx)
        expect("<script>alert(1)</script>" not in html, "横幅内脚本被转义")
        expect("&lt;script&gt;" in html, "横幅文本按 HTML 转义输出")
