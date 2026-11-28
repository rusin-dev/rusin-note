"""安全加固回归：高熵 ID、/new 防覆盖、安全响应头、附件下载策略。"""
from __future__ import annotations

import logging

from app.core import config
from app.core import notes as notes_mod
from app.core.notes import generate_random_id, generate_unique_note_id, write_note
from app.apps.attachments.service import generate_attachment_id
from app.apps.images.service import generate_image_id
from app.core.store import get_user
from support import (
    csrf_of, expect, register_and_login, upload_attachment,
)

logger = logging.getLogger("rusin.tests.hardening")


class TestIdEntropy:
    def test_ids_are_long_and_unique(self):
        logger.info("=== [A] 资源 ID 高熵 ===")
        expect(config.ID_LENGTH >= 12, "默认 ID 长度至少 12")
        expect(len(set(generate_random_id() for _ in range(200))) == 200,
               "200 个笔记 ID 无重复")
        image_id = generate_image_id("png")
        attachment_id = generate_attachment_id("doc.pdf")
        expect(image_id.endswith(".png") and len(image_id) == config.ID_LENGTH + 4,
               "图床 ID 为长随机串 + 扩展名")
        expect(attachment_id.endswith(".pdf") and len(attachment_id) == config.ID_LENGTH + 4,
               "附件 ID 为长随机串 + 扩展名")


class TestNewNoteCollision:
    def test_new_id_skips_existing_note(self, ctx, monkeypatch):
        logger.info("=== [B] /new 生成 ID 避开已有笔记 ===")
        register_and_login(ctx.client, "collide_user")
        write_note("collide_user", "COLLIDEID", "旧内容")
        seq = iter(["COLLIDEID", "FRESHID"])
        monkeypatch.setattr(notes_mod, "generate_random_id", lambda: next(seq))
        expect(generate_unique_note_id("collide_user") == "FRESHID",
               "跳过已占用的 ID，返回未占用 ID")
        expect(get_user("collide_user") is not None, "用户仍存在")


class TestResponseHeaders:
    def test_basic_security_headers(self, ctx):
        logger.info("=== [C] 基础安全响应头 ===")
        resp = ctx.client.get("/")
        expect(resp.headers.get("X-Content-Type-Options") == "nosniff", "nosniff 已设置")
        expect(resp.headers.get("X-Frame-Options") == "SAMEORIGIN", "防点击劫持头已设置")
        expect("strict-origin" in resp.headers.get("Referrer-Policy", ""), "Referrer-Policy 已设置")


class TestAttachmentDisposition:
    def _download(self, ctx, filename, content, mime, username="att_policy"):
        register_and_login(ctx.client, username)
        csrf = csrf_of(ctx.client.get(f"/user/{username}/attachments").get_data(as_text=True))
        resp = upload_attachment(ctx.client, username, csrf, content,
                                 filename=filename, mime=mime)
        payload = resp.get_json()
        return ctx.client.get(payload["url"])

    def test_pdf_inline_text_attachment(self, ctx):
        logger.info("=== [D] PDF 内联、其他类型强制下载 ===")
        pdf = self._download(ctx, "doc.pdf", b"%PDF-1.4\npayload\n", "application/pdf")
        expect(pdf.headers.get("Content-Disposition", "").startswith("inline"),
               "PDF 允许内联预览")
        expect(pdf.headers.get("X-Content-Type-Options") == "nosniff", "附件响应 nosniff")
        txt = self._download(ctx, "notes.txt", b"plain text\n", "text/plain", username="att_txt")
        expect(txt.headers.get("Content-Disposition", "").startswith("attachment"),
               "文本附件强制下载（不在同源渲染）")
