"""登录首页互动落地页端到端测试（pytest + logging）。

覆盖：登录后首页各落地区块（Hero/数据亮点/功能卡片/使用指南/FAQ/CTA 横幅）、
热力图与最近编辑保留、功能开关对入口卡片的过滤、匿名访问仍为站点入口页。

运行：``pytest tests/test_home_landing.py``
"""
from __future__ import annotations

import logging

from app.core.extensions import cache
from app.core.feature_flags import FEATURE_KEYS, set_flags
from support import create_note, expect, register_and_login

logger = logging.getLogger("rusin.tests.home_landing")

USER = "lpuser"


class TestHomeLanding:
    def test_landing_sections(self, ctx):
        logger.info("=== [A] 落地页各区块渲染 ===")
        register_and_login(ctx.client, USER)
        create_note(ctx.client, USER, "落地页测试笔记")
        html = ctx.client.get("/").get_data(as_text=True)
        expect("lp-hero" in html and "lp-tagline" in html, "Hero 区块渲染")
        expect("一处安放你的笔记" in html, "Hero 大标题文案")
        expect('href="/user/{}/new"'.format(USER) in html, "CTA 新建笔记按钮")
        expect("lp-stats" in html and "笔记总数" in html, "数据亮点区块")
        expect("常用功能" in html and "如何使用" in html, "功能区与指南标题")
        expect(html.count('class="lp-step"') >= 3, "使用指南三个步骤")
        expect('class="lp-faq"' in html and "常见问题" in html, "FAQ 折叠区块")
        expect("lp-band" in html and "准备好开始了吗" in html, "底部 CTA 横幅")
        expect("hm-cell" in html, "热力图保留")
        expect("wb-note" in html, "最近编辑保留")
        expect("/user/{}/shares/".format(USER) in html and "/user/{}/settings".format(USER) in html,
               "分享管理与设置入口卡片")

    def test_gated_cards(self, ctx):
        logger.info("=== [B] 开关关闭时入口卡片隐藏 ===")
        set_flags({k: (k not in ("notes_import_export", "benben", "orgs")) for k in FEATURE_KEYS})
        cache.clear()
        html = ctx.client.get("/").get_data(as_text=True)
        expect("导入与导出" not in html, "导入导出卡片随开关隐藏")
        expect('href="/benben"' not in html, "犇犇卡片随开关隐藏")
        expect("/org/mine" not in html, "组织卡片随开关隐藏")
        set_flags({k: True for k in FEATURE_KEYS})
        cache.clear()

    def test_anonymous_unchanged(self, ctx):
        logger.info("=== [C] 匿名访问仍为站点入口页 ===")
        anon = ctx.app.test_client()
        cache.clear()
        html = anon.get("/").get_data(as_text=True)
        expect("home-hero" in html, "匿名 Hero 保留")
        expect("lp-hero" not in html and "lp-band" not in html, "落地页区块不出现在匿名页")
