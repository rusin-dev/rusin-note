"""评论板访问控制：私密笔记不可被他人/匿名探测，公开笔记匿名可评论。"""
from __future__ import annotations

import logging

from app.core.notes import write_note
from support import (
    create_note, csrf_of, expect, register_and_login,
)

logger = logging.getLogger("rusin.tests.comment_privacy")

OWNER = "cm_owner"
OTHER = "cm_other"
PUBLIC_ID = "publiccm1"


def _csrf(client) -> str:
    return csrf_of(client.get("/login").get_data(as_text=True))


class TestCommentPrivacy:
    def test_private_note_hidden_from_others(self, ctx):
        logger.info("=== [A] 私密笔记评论板仅本人可见 ===")
        register_and_login(ctx.client, OWNER)
        note_id = create_note(ctx.client, OWNER, "private body")
        url = f"/comments/note/{OWNER}/{note_id}"
        expect(ctx.client.get(url).status_code == 200, "本人可访问")
        anon = ctx.app.test_client()
        expect(anon.get(url).status_code == 404, "匿名访问返回 404")
        other = ctx.app.test_client()
        register_and_login(other, OTHER)
        expect(other.get(url).status_code == 404, "其他登录用户访问返回 404")

    def test_private_note_anonymous_comment_rejected(self, ctx):
        logger.info("=== [B] 私密笔记不可匿名评论 ===")
        owner = "cm_owner2"
        register_and_login(ctx.client, owner)
        note_id = create_note(ctx.client, owner, "private body")
        anon = ctx.app.test_client()
        url = f"/comments/note/{owner}/{note_id}"
        resp = anon.post(url, data={"content": "spam", "csrf_token": _csrf(anon)})
        expect(resp.status_code == 404, "匿名评论返回 404")
        expect("spam" not in ctx.client.get(url).get_data(as_text=True),
               "评论未写入私密笔记评论板")

    def test_missing_note_still_404(self, ctx):
        logger.info("=== [C] 不存在的笔记保持 404 ===")
        anon = ctx.app.test_client()
        resp = anon.get(f"/comments/note/{OWNER}/doesnotexist")
        expect(resp.status_code == 404, "不存在笔记返回 404（与无权限一致）")

    def test_public_note_allows_anonymous_comment(self, ctx):
        logger.info("=== [D] 公开笔记匿名可见可评论 ===")
        write_note("public", PUBLIC_ID, "public body")
        anon = ctx.app.test_client()
        url = f"/comments/note/public/{PUBLIC_ID}"
        page = anon.get(url)
        expect(page.status_code == 200, "公开笔记评论板匿名可读")
        resp = anon.post(url, data={
            "content": "hello from anon",
            "csrf_token": csrf_of(page.get_data(as_text=True)),
        })
        expect(resp.status_code == 302, "匿名评论成功")
        expect("hello from anon" in anon.get(url).get_data(as_text=True),
               "匿名评论可见")
