"""安全加固回归：高熵 ID、/new 防覆盖、安全响应头、附件下载策略。"""
from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor

from app.core import config
from app.core import notes as notes_mod
from app.core.notes import (
    generate_random_id, generate_unique_note_id, validate_username, write_note,
)
from app.apps.attachments.service import generate_attachment_id
from app.apps.images.service import generate_image_id
from app.core.storage import UpstashBackend
from app.core.store import get_user
from app.apps.notifications import service as notifications_service
from support import (
    csrf_of, expect, register, register_and_login, upload_attachment,
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


class TestSecretKeyRace:
    def test_concurrent_first_init_same_key(self, ctx):
        logger.info("=== [B0] SECRET_KEY 并发首次初始化一致 ===")
        from app import _load_or_create_secret_key
        from app.core.storage import storage
        storage.set("secret_key", "")
        with ThreadPoolExecutor(max_workers=4) as pool:
            keys = list(pool.map(lambda _: _load_or_create_secret_key(), range(8)))
        expect(len(set(keys)) == 1, "并发初始化只产生一把密钥")
        expect(storage.get("secret_key") == keys[0], "落盘密钥与进程使用一致")


class TestSessionExpiry:
    def test_expired_session_rejected_and_purged(self, ctx):
        logger.info("=== [B1] 默认启用会话超时 ===")
        from app.core import auth
        from app.core.store import reload_sessions, store_session
        expect(config.SESSION_TIMEOUT_ENABLED is True, "默认开启会话超时")
        old = time.time() - config.SESSION_TIMEOUT_SECONDS - 5
        token = auth.create_session("sess_user")
        store_session(auth.hash_token(token),
                      {"username": "sess_user", "created_at": old})
        reload_sessions()
        expect(auth.get_session_user(token) is None, "超时会话被拒绝")
        token2 = auth.create_session("sess_user2")
        store_session(auth.hash_token(token2),
                      {"username": "sess_user2", "created_at": old})
        reload_sessions()
        expect(auth.purge_expired_sessions() >= 1, "清理任务删除过期会话")


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


class TestLimits:
    def test_form_memory_matches_body_limit(self, ctx):
        logger.info("=== [E] 表单内存上限与请求体上限一致 ===")
        expect(ctx.app.config["MAX_FORM_MEMORY_SIZE"]
               == ctx.app.config["MAX_CONTENT_LENGTH"], "两个上限同值")

    def test_username_length_bounded(self, ctx):
        logger.info("=== [F] 用户名长度有上限 ===")
        expect(not validate_username("a" * 33), "33 字符用户名非法")
        resp = register(ctx.client, "a" * 33)
        expect(resp.status_code == 400, "超长用户名注册被拒")

    def test_note_under_limit_can_save(self, ctx):
        logger.info("=== [G] 接近上限的笔记可保存（不再被 500KB 表单上限拦截） ===")
        register_and_login(ctx.client, "big_note_user")
        location = ctx.client.get("/user/big_note_user/new").headers["Location"]
        content = "A" * (500 * 1024)
        resp = ctx.client.post(location, data={
            "content": content,
            "csrf_token": csrf_of(ctx.client.get(location).get_data(as_text=True)),
        })
        expect(resp.status_code == 302, "500KB 笔记保存成功")


class TestUpstashGuard:
    def test_lock_release_only_own_token(self, ctx, monkeypatch):
        logger.info("=== [H] Upstash 锁只释放自己的 token ===")
        backend = UpstashBackend("https://example.invalid", "token")
        calls = []

        def fake_request(method, path, body=None, timeout=10.0):
            calls.append((method, path))
            if path.startswith("setnx/"):
                return 1
            if path.startswith("get/"):
                return "someone-else"
            return 1

        monkeypatch.setattr(backend, "_request", fake_request)
        with backend.lock("demo"):
            pass
        expect(not any(method == "DELETE" for method, _ in calls),
               "锁已被他人重新获取时不做 DEL")

    def test_list_keys_escapes_glob(self, ctx, monkeypatch):
        logger.info("=== [I] Upstash KEYS 前缀 glob 转义 ===")
        backend = UpstashBackend("https://example.invalid", "token")
        seen = {}

        def fake_request(method, path, body=None, timeout=10.0):
            seen["path"] = path
            return []

        monkeypatch.setattr(backend, "_request", fake_request)
        backend.list_keys("note:a_b*")
        expect("%5C*" in seen["path"], "星号已转义")
        expect(seen["path"].endswith("**"), "末尾保留未转义的匹配通配符")

    def test_notification_url_rejects_backslash(self, data_dir):
        logger.info("=== [J] 通知 URL 拒绝 /\\ 站外跳转 ===")
        notifications_service.add("notif_user", "system", "t", url="/\\evil.example")
        items = notifications_service.list_for_user("notif_user")
        expect(items and items[0]["url"] == "", "反斜杠变体被清空")
        notifications_service.add("notif_user", "system", "t2", url="/user/ok")
        items = notifications_service.list_for_user("notif_user")
        expect(items[0]["url"] == "/user/ok", "正常站内路径保留")


class TestWriteGate:
    def test_note_save_rejects_when_slot_exhausted(self, ctx, monkeypatch):
        logger.info("=== [K] 单用户并发写闸门 ===")
        from app.core.concurrency import write_guard
        register_and_login(ctx.client, "gate_user")
        location = ctx.client.get("/user/gate_user/new").headers["Location"]
        csrf = csrf_of(ctx.client.get(location).get_data(as_text=True))
        monkeypatch.setattr(config, "MAX_CONCURRENT_WRITES", 1)
        slot = write_guard.try_acquire("gate_user", 1)
        try:
            resp = ctx.client.post(location, data={"content": "x", "csrf_token": csrf})
            expect(resp.status_code == 429, "已有在途写请求时返回 429")
        finally:
            slot.release()


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
