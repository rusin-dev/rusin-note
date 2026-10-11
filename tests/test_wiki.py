"""内置 Web wiki 端到端测试（pytest + logging）。

覆盖：
- 功能开关 gating（停用时 /docs 与管理路由 404）
- 管理员创建/编辑页面，访客公开浏览（Markdown 渲染 + bleach 清洗）
- /docs 首页（home slug 页面 / 无页面时的目录树）
- 权限：匿名与普通登录用户访问管理路由一律 404
- slug 校验（层级深度 / 非法字符 / 空格 / 路径穿越）
- 层级页面与侧边栏目录树
- 移动页面级联迁移子页面
- 删除规则（有子页面时拒绝）
- 版本历史 + 回滚（修订数上限）
- 单页大小上限 / 全站页面数上限

运行：``pytest tests/test_wiki.py``
"""
from __future__ import annotations

import logging
import time

import pytest

from app.core import config as app_config
from app.core.auth import hash_token
from app.core.feature_flags import feature_enabled, set_flags
from app.core.store import register_user, store_session
from app.apps.wiki.service import (
    get_page,
    get_revisions,
    list_pages,
    save_page,
    validate_slug,
)
from support import expect, register_and_login

logger = logging.getLogger("rusin.tests.wiki")

ADMIN = "wiki_admin"     # 测试内注册并加入 ADMIN_USERS（"admin" 是保留用户名）
OUTSIDER = "wiki_bob"    # 普通登录用户
ADMIN_TOKEN = "wiki-admin-token"


@pytest.fixture(autouse=True, scope="class")
def wiki_enabled(ctx):
    set_flags({"wiki": True})
    assert feature_enabled("wiki"), "wiki 功能未启用"
    yield


@pytest.fixture(autouse=True, scope="class")
def csrf_disabled(ctx):
    """wiki 测试直接使用 HTTP 表单，CSRF 校验关闭；表单含 csrf_token 由专项断言覆盖。"""
    ctx.app.config["WTF_CSRF_ENABLED"] = False


@pytest.fixture(autouse=True, scope="class")
def admin_user(ctx):
    """把测试管理员写入 ADMIN_USERS，并直接构造会话 Cookie。"""
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(app_config, "ADMIN_USERS", app_config.ADMIN_USERS | {ADMIN})
        register_user(ADMIN, {"salt": "0011" * 8, "hash": "pbkdf2_sha256$1$deadbeef"})
        store_session(hash_token(ADMIN_TOKEN), {"username": ADMIN, "created_at": time.time()})
        yield


def _admin_client(ctx):
    ctx.client.set_cookie("rusin_session", ADMIN_TOKEN)
    return ctx.client


def _post(client, path, data):
    return client.post(path, data=dict(data), follow_redirects=False)


class TestWiki:
    """wiki 公开浏览与管理员维护（同一测试类内共享页面数据）。"""

    def test_flag_gating(self, ctx):
        logger.info("=== 1. 功能开关 gating ===")
        set_flags({"wiki": False})
        expect(ctx.anon.get("/docs").status_code == 404, "停用后 /docs 返回 404")
        expect(ctx.anon.get("/admin/wiki").status_code == 404, "停用后 /admin/wiki 返回 404")
        set_flags({"wiki": True})
        expect(ctx.anon.get("/docs").status_code == 200, "启用后 /docs 可访问")

    def test_admin_only(self, ctx):
        logger.info("=== 2. 管理路由权限 ===")
        expect(ctx.anon.get("/admin/wiki").status_code == 404, "匿名访问管理页 404")
        register_and_login(ctx.anon, OUTSIDER)
        expect(ctx.anon.get("/admin/wiki").status_code == 404, "普通用户访问管理页 404")
        expect(_post(ctx.anon, "/admin/wiki/edit", {"slug": "hack", "title": "x", "content": "y"}).status_code == 404,
               "普通用户创建页面 404")
        expect(get_page("hack") is None, "普通用户未能写入页面")

    def test_create_and_public_view(self, ctx):
        logger.info("=== 3. 管理员创建页面 + 公开浏览 ===")
        admin = _admin_client(ctx)
        resp = _post(admin, "/admin/wiki/edit", {
            "slug": "guide",
            "title": "使用指南",
            "content": "# 你好\n\n这是 **wiki** 正文。<script>alert(1)</script>",
        })
        expect(resp.status_code == 302, f"创建页面重定向（实际 {resp.status_code}）")
        page = get_page("guide")
        expect(page is not None and page["title"] == "使用指南", "页面已落库")

        resp = ctx.anon.get("/docs/guide")
        html = resp.get_data(as_text=True)
        expect(resp.status_code == 200, "访客可浏览页面")
        expect("使用指南" in html, "页面标题渲染")
        expect("<strong>wiki</strong>" in html, "Markdown 已渲染为 HTML")
        expect("<script>alert(1)</script>" not in html, "脚本被 bleach 清洗")

    def test_edit_creates_revision(self, ctx):
        logger.info("=== 4. 编辑生成修订 ===")
        admin = _admin_client(ctx)
        resp = _post(admin, "/admin/wiki/edit/guide", {
            "title": "使用指南 v2",
            "content": "第二版正文",
        })
        expect(resp.status_code == 302, "保存编辑重定向")
        page = get_page("guide")
        expect(page["title"] == "使用指南 v2", "标题已更新")
        expect("第二版正文" in page["content"], "内容已更新")
        revs = get_revisions("guide")
        expect(len(revs) == 1, f"旧版本进入修订历史（实际 {len(revs)}）")
        expect("你好" in revs[0]["content"], "修订保存的是旧内容")

        html = ctx.anon.get("/docs/guide").get_data(as_text=True)
        expect("第二版正文" in html, "公开页立即反映新内容（缓存已失效）")

    def test_docs_home(self, ctx):
        logger.info("=== 5. /docs 首页 ===")
        html = ctx.anon.get("/docs").get_data(as_text=True)
        expect("/docs/guide" in html, "无 home 页时 /docs 展示目录树")
        admin = _admin_client(ctx)
        _post(admin, "/admin/wiki/edit", {"slug": "home", "title": "文档中心", "content": "欢迎来到文档站"})
        html = ctx.anon.get("/docs").get_data(as_text=True)
        expect("欢迎来到文档站" in html, "存在 home 页时 /docs 渲染其内容")

    def test_slug_validation(self, ctx):
        logger.info("=== 6. slug 校验 ===")
        expect(validate_slug("ok-slug"), "合法 slug 通过")
        expect(validate_slug("a/b/c/d"), "四级 slug 通过")
        expect(not validate_slug("a/b/c/d/e"), "超过层级上限拒绝")
        expect(not validate_slug("../etc"), "路径穿越拒绝")
        expect(not validate_slug("-lead"), "非字母数字开头拒绝")
        expect(not validate_slug("has space"), "空格拒绝")
        expect(not validate_slug(""), "空 slug 拒绝")
        expect(not validate_slug("a" * 201), "超长 slug 拒绝")

        admin = _admin_client(ctx)
        resp = _post(admin, "/admin/wiki/edit", {"slug": "bad slug!", "title": "x", "content": "y"})
        expect(resp.status_code == 400, "HTTP 创建非法 slug 返回 400")

    def test_hierarchy_and_sidebar(self, ctx):
        logger.info("=== 7. 层级页面与侧边栏 ===")
        admin = _admin_client(ctx)
        _post(admin, "/admin/wiki/edit", {"slug": "deploy", "title": "部署", "content": "部署总览"})
        _post(admin, "/admin/wiki/edit", {"slug": "deploy/vercel", "title": "Vercel 部署", "content": "Vercel 步骤"})
        expect(ctx.anon.get("/docs/deploy/vercel").status_code == 200, "子页面可浏览")
        html = ctx.anon.get("/docs/deploy/vercel").get_data(as_text=True)
        expect("/docs/deploy" in html, "侧边栏包含父页面链接")
        expect(ctx.anon.get("/docs/no-such-page").status_code == 404, "不存在的页面 404")

    def test_move_cascade(self, ctx):
        logger.info("=== 8. 移动页面级联子页面 ===")
        admin = _admin_client(ctx)
        resp = _post(admin, "/admin/wiki/move/deploy", {"new_slug": "ops"})
        expect(resp.status_code == 302, f"移动重定向（实际 {resp.status_code}）")
        expect(get_page("ops") is not None, "父页面已迁移")
        expect(get_page("ops/vercel") is not None, "子页面级联迁移")
        expect(get_page("deploy") is None, "旧 slug 已移除")
        expect(ctx.anon.get("/docs/ops/vercel").status_code == 200, "新 URL 可访问")
        expect(ctx.anon.get("/docs/deploy/vercel").status_code == 404, "旧 URL 404（缓存已清除）")

        resp = _post(admin, "/admin/wiki/move/ops", {"new_slug": "ops/vercel"})
        expect(resp.status_code == 400, "移动到已存在 slug 返回 400")

    def test_delete_rules(self, ctx):
        logger.info("=== 9. 删除规则 ===")
        admin = _admin_client(ctx)
        resp = _post(admin, "/admin/wiki/delete/ops", {})
        expect(resp.status_code == 400, "有子页面时删除返回 400")
        expect(get_page("ops") is not None, "父页面仍存在")
        resp = _post(admin, "/admin/wiki/delete/ops/vercel", {})
        expect(resp.status_code == 302, "叶子页面删除重定向")
        expect(get_page("ops/vercel") is None, "页面已删除")
        expect(get_revisions("ops/vercel") == [], "修订历史一并清除")
        expect(ctx.anon.get("/docs/ops/vercel").status_code == 404, "删除后 URL 404（缓存已清除）")

    def test_history_and_rollback(self, ctx):
        logger.info("=== 10. 版本历史与回滚 ===")
        admin = _admin_client(ctx)
        _post(admin, "/admin/wiki/edit", {"slug": "rev", "title": "版本页", "content": "第一版"})
        _post(admin, "/admin/wiki/edit/rev", {"title": "版本页", "content": "第二版"})
        revs = get_revisions("rev")
        expect(len(revs) == 1 and "第一版" in revs[0]["content"], "保存了第一版修订")

        html = admin.get("/admin/wiki/history/rev").get_data(as_text=True)
        expect("第一版" in html or revs[0]["id"] in html, "历史页列出修订")

        resp = _post(admin, f"/admin/wiki/rollback/rev", {"rev_id": revs[0]["id"]})
        expect(resp.status_code == 302, "回滚重定向")
        page = get_page("rev")
        expect("第一版" in page["content"], "内容已回滚到第一版")
        expect(len(get_revisions("rev")) == 2, "回滚前的第二版也进入修订历史")
        expect(ctx.anon.get("/docs/rev").get_data(as_text=True).find("第一版") >= 0,
               "公开页展示回滚后内容")

        resp = _post(admin, "/admin/wiki/rollback/rev", {"rev_id": "nonexistent"})
        expect(resp.status_code == 404, "回滚不存在的修订 404")

    def test_revision_cap(self, ctx, monkeypatch):
        logger.info("=== 11. 修订数上限 ===")
        from app.core import config as app_config
        monkeypatch.setattr(app_config, "WIKI_MAX_REVISIONS", 3)
        save_page("capped", "上限页", "v0", ADMIN)
        for i in range(1, 6):
            save_page("capped", "上限页", f"v{i}", ADMIN)
        revs = get_revisions("capped")
        expect(len(revs) == 3, f"修订裁剪到上限（实际 {len(revs)}）")
        expect("v4" in revs[0]["content"], "保留的是最近的修订")

    def test_size_and_count_limits(self, ctx, monkeypatch):
        logger.info("=== 12. 大小与数量上限 ===")
        from app.core import config as app_config
        monkeypatch.setattr(app_config, "WIKI_MAX_PAGE_KB", 1)
        ok, err = save_page("big", "超大页", "x" * 2048, ADMIN)
        expect(not ok and err == "too_large", "超过单页大小上限拒绝")

        monkeypatch.setattr(app_config, "WIKI_MAX_PAGE_KB", 512)
        monkeypatch.setattr(app_config, "WIKI_MAX_PAGES", len(list_pages()))
        ok, err = save_page("overflow", "溢出页", "内容", ADMIN)
        expect(not ok and err == "too_many_pages", "超过页面数上限拒绝")

    def test_admin_index_lists_pages(self, ctx):
        logger.info("=== 13. 管理页目录与 CSRF ===")
        admin = _admin_client(ctx)
        html = admin.get("/admin/wiki").get_data(as_text=True)
        expect("/admin/wiki/edit/guide" in html, "管理页列出页面编辑链接")
        expect("使用指南 v2" in html, "管理页显示页面标题")
        form_html = admin.get("/admin/wiki/edit/guide").get_data(as_text=True)
        expect('name="csrf_token"' in form_html, "编辑表单包含 csrf_token")
        new_html = admin.get("/admin/wiki/edit").get_data(as_text=True)
        expect('name="csrf_token"' in new_html, "新建表单包含 csrf_token")
