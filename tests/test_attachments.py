"""笔记附件端到端测试（pytest + logging）。

覆盖三部分：

1. ``app.concurrency.ConcurrencyLimiter``：按 key 隔离、幂等释放、``limit<=0`` 不限、
   拒绝计数，以及「流式下载持有槽位 / 迭代结束或客户端断开即释放」。
2. 附件下载权限：默认**禁止匿名下载**（401 + 登录提示文案，且不占用并发槽位），
   登录后可下载且字节一致、缓存头为 ``private``；
   ``attachments.allow_anonymous_download=true`` 时恢复匿名下载。
3. 单用户并发上限（#191「限制 1 队列」）：默认每账号 1 个下载 + 1 个上传在途，
   超出返回 429（下载带 ``Retry-After``，上传为编辑器可直接展示的 JSON），释放后恢复。

运行：``pytest tests/test_attachments.py``
"""
from __future__ import annotations

import json
import logging

import pytest

from app import attachments as att
from app import config as cfg
from app.concurrency import ConcurrencyLimiter
from support import (
    csrf_from,
    expect,
    register_and_login,
    upload_attachment,
)

logger = logging.getLogger("rusin.tests.attachments")

USER = "attachuser"
OTHER = "attachpeer"
PDF = b"%PDF-1.4\n" + b"rusin attachment payload line\n" * 8


class TestAttachmentDefaults:
    """A0：出厂默认值（#191：单用户上传/下载各限制 1 个在途队列 + 禁止匿名下载）。"""

    def test_default_limits_are_single_queue(self):
        logger.info("=== [A0] DEFAULT_CONFIG 附件默认值 ===")
        defaults = cfg.DEFAULT_CONFIG["attachments"]
        expect(defaults["max_concurrent_downloads"] == 1,
               "同时下载默认限制 1 个队列（#191）")
        expect(defaults["max_concurrent_uploads"] == 1,
               "同时上传默认限制 1 个队列（#191）")
        expect(defaults["allow_anonymous_download"] is False,
               "默认不允许匿名下载附件")
        expect(cfg.MAX_CONCURRENT_ATTACHMENT_DOWNLOADS >= 0
               and cfg.MAX_CONCURRENT_ATTACHMENT_UPLOADS >= 0,
               "生效值解析为合法整数（0 = 不限）")


class TestConcurrencyGuard:
    """A：并发闸门单元行为（进程内计数）。"""

    def test_limit_release_and_idempotency(self):
        logger.info("=== [A1] 上限计数与幂等释放 ===")
        guard = ConcurrencyLimiter("unit-basic")
        first = guard.try_acquire("k", 2)
        second = guard.try_acquire("k", 2)
        expect(first is not None and second is not None, "上限 2 时前两次占用成功")
        expect(guard.try_acquire("k", 2) is None, "第三次占用被拒绝")
        expect(guard.active("k") == 2, "在途计数为 2")
        expect(guard.rejected == 1 and guard.peak == 2, "拒绝次数与峰值正确")

        first.release()
        first.release()  # 模拟生成器 finally + call_on_close 双重释放
        expect(guard.active("k") == 1, "重复释放不会把计数减成负数")
        second.release()
        expect(guard.active("k") == 0, "全部释放后计数归零")

    def test_key_isolation_and_unlimited(self):
        logger.info("=== [A2] 按 key 隔离 / limit<=0 不限 ===")
        guard = ConcurrencyLimiter("unit-keys")
        a = guard.try_acquire("user:a", 1)
        b = guard.try_acquire("user:b", 1)
        expect(a is not None and b is not None, "不同用户互不影响")
        expect(guard.try_acquire("user:a", 1) is None, "同一用户再次占用被拒")

        free = guard.try_acquire("user:c", 0)
        expect(free is not None and free.counted is False, "limit<=0 表示不限，不计数")
        expect(guard.total_active() == 2, "不计数槽位不计入在途数量")

        a.release()
        b.release()
        free.release()
        expect(guard.total_active() == 0, "清理后归零")

    def test_stream_releases_slot(self):
        logger.info("=== [A3] 流式产出持有槽位，迭代结束释放 ===")
        guard = ConcurrencyLimiter("unit-stream")
        slot = guard.try_acquire("user:s", 1)
        chunked = att.stream_attachment(b"abcdef", slot, chunk_size=2)
        expect(guard.active("user:s") == 1, "下载过程中持有槽位")
        expect(list(chunked) == [b"ab", b"cd", b"ef"], "分块产出内容完整")
        expect(guard.active("user:s") == 0, "迭代结束后自动释放")

    def test_stream_releases_on_disconnect(self):
        logger.info("=== [A4] 客户端中途断开（关闭生成器）释放槽位 ===")
        guard = ConcurrencyLimiter("unit-stream-close")
        slot = guard.try_acquire("user:s", 1)
        chunked = att.stream_attachment(b"abcdef", slot, chunk_size=2)
        next(chunked)
        chunked.close()
        expect(guard.active("user:s") == 0, "生成器被关闭后立即释放槽位")


class TestAttachmentAccess:
    """B：上传、匿名禁下载、并发上限（共享 ctx 状态，方法按定义顺序执行）。"""

    def test_upload_and_anonymous_denied(self, ctx):
        logger.info("=== [B1] 上传成功 + 匿名下载被拒 ===")
        register_and_login(ctx.client, USER)
        ctx.csrf = csrf_from(ctx.client, f"/user/{USER}/attachments")

        response = upload_attachment(ctx.client, USER, ctx.csrf, PDF)
        assert response.status_code == 200, \
            f"附件上传失败: {response.status_code} {response.get_data(as_text=True)[:200]}"
        payload = json.loads(response.get_data(as_text=True))
        ctx.url = payload["url"]
        ctx.attachment_id = payload["id"]
        expect(ctx.url == f"/attachment/{USER}/{payload['id']}",
               "上传返回 /attachment/<user>/<id> 形式的 URL")

        response = ctx.anon.get(ctx.url)
        expect(response.status_code == 401, "匿名下载附件 -> 401")
        expect("请先登录后再下载附件" in response.get_data(as_text=True),
               "401 页面展示「需登录」提示")
        expect(att.download_guard.total_active() == 0,
               "匿名请求被拒时不占用并发槽位")

    def test_logged_in_download(self, ctx):
        logger.info("=== [B2] 登录后下载 ===")
        response = ctx.client.get(ctx.url)
        expect(response.status_code == 200 and response.get_data() == PDF,
               "登录用户下载字节一致")
        expect(response.headers.get("Content-Type") == "application/pdf",
               "Content-Type 按元数据推断")
        expect("private" in response.headers.get("Cache-Control", ""),
               "附件为私有缓存（public 会被共享缓存回放给匿名访客）")
        expect(response.headers.get("Content-Length") == str(len(PDF)),
               "显式设置 Content-Length（流式响应）")
        expect(att.download_guard.total_active() == 0, "下载完成后释放并发槽位")

    def test_other_logged_in_user_can_download(self, ctx):
        logger.info("=== [B3] 当前策略：只拦匿名，登录用户凭链接可下载 ===")
        other_client = ctx.app.test_client()
        register_and_login(other_client, OTHER)
        response = other_client.get(ctx.url)
        expect(response.status_code == 200,
               "其他登录用户可下载（如需仅本人可下载，须再加所有权校验）")
        response.close()
        expect(att.download_guard.total_active() == 0, "关闭响应后归还槽位")

    def test_anonymous_allowed_when_configured(self, ctx, monkeypatch):
        logger.info("=== [B4] allow_anonymous_download=true 恢复匿名下载 ===")
        monkeypatch.setattr(cfg, "ATTACHMENTS_ALLOW_ANONYMOUS_DOWNLOAD", True)
        response = ctx.anon.get(ctx.url)
        expect(response.status_code == 200 and response.get_data() == PDF,
               "配置放开后匿名可下载")
        expect(att.download_guard.total_active() == 0, "匿名下载完成后释放槽位")

    def test_download_concurrency_limit(self, ctx, monkeypatch):
        logger.info("=== [B5] 单用户同时下载上限 ===")
        monkeypatch.setattr(cfg, "MAX_CONCURRENT_ATTACHMENT_DOWNLOADS", 1)
        key = att.concurrency_key(USER, None)
        held = att.download_guard.try_acquire(key, 1)
        expect(held is not None, "预占一个下载槽位（模拟慢速下载在途）")

        response = ctx.client.get(ctx.url)
        expect(response.status_code == 429, "超出同时下载上限 -> 429")
        expect("同时下载的附件过多" in response.get_data(as_text=True),
               "429 页面展示并发上限文案")
        expect(response.headers.get("Retry-After") == "1", "429 带 Retry-After")

        held.release()
        restored = ctx.client.get(ctx.url)
        expect(restored.status_code == 200, "槽位释放后恢复下载")
        restored.close()

        monkeypatch.setattr(cfg, "MAX_CONCURRENT_ATTACHMENT_DOWNLOADS", 0)
        blocked = att.download_guard.try_acquire(key, 1)
        try:
            unlimited = ctx.client.get(ctx.url)
            expect(unlimited.status_code == 200, "上限置 0 表示不限并发")
            unlimited.close()
        finally:
            blocked.release()

    def test_inflight_download_holds_slot(self, ctx, monkeypatch):
        logger.info("=== [B6] 未读完的流式响应持有槽位，关闭后归还 ===")
        monkeypatch.setattr(cfg, "MAX_CONCURRENT_ATTACHMENT_DOWNLOADS", 1)
        streamed = ctx.client.get(ctx.url, buffered=False)
        expect(streamed.status_code == 200, "流式下载已开始")
        expect(att.download_guard.total_active() == 1, "响应未结束时占用槽位")
        blocked = ctx.client.get(ctx.url)
        expect(blocked.status_code == 429, "同一用户第二个下载被拒")
        blocked.close()
        streamed.close()
        expect(att.download_guard.total_active() == 0, "关闭响应后释放槽位")
        again = ctx.client.get(ctx.url)
        expect(again.status_code == 200, "随后可正常下载")
        again.close()

    def test_upload_concurrency_limit(self, ctx, monkeypatch):
        logger.info("=== [B7] 单用户同时上传上限（编辑器 JSON 错误） ===")
        monkeypatch.setattr(cfg, "MAX_CONCURRENT_ATTACHMENT_UPLOADS", 1)
        held = att.upload_guard.try_acquire(f"user:{USER}", 1)
        expect(held is not None, "预占一个上传槽位（模拟慢速上传在途）")

        response = upload_attachment(ctx.client, USER, ctx.csrf, PDF)
        expect(response.status_code == 429, "超出同时上传上限 -> 429")
        try:
            message = json.loads(response.get_data(as_text=True)).get("error", "")
        except ValueError:
            message = ""
        expect("同时上传的附件过多" in message,
               "上传接口返回 JSON 错误文案（编辑器 fetch 可直接展示）")
        expect(response.headers.get("Retry-After") == "1", "上传 429 带 Retry-After")
        expect(att.upload_guard.total_active() == 1, "被拒请求不额外占用槽位")

        held.release()
        response = upload_attachment(ctx.client, USER, ctx.csrf, PDF)
        expect(response.status_code == 200, "槽位释放后恢复上传")
        expect(att.upload_guard.total_active() == 0, "上传结束释放槽位")

    def test_invalid_or_missing_attachment(self, ctx):
        logger.info("=== [B8] 非法 / 不存在的附件 ===")
        expect(ctx.client.get(f"/attachment/{USER}/../evil.pdf").status_code == 404,
               "非法 ID -> 404")
        expect(ctx.client.get(f"/attachment/{USER}/zzzz.pdf").status_code == 404,
               "不存在的附件 -> 404")
        expect(ctx.client.get("/attachment/../etc/passwd").status_code in (400, 404),
               "路径穿越被拒")
        expect(att.download_guard.total_active() == 0, "404 路径不泄漏槽位")

    def test_default_single_queue_enforced_e2e(self, ctx, monkeypatch):
        logger.info("=== [B9] 出厂默认 1 队列的端到端行为（#191） ===")
        monkeypatch.setattr(cfg, "MAX_CONCURRENT_ATTACHMENT_DOWNLOADS",
                            cfg.DEFAULT_CONFIG["attachments"]["max_concurrent_downloads"])
        first = ctx.client.get(ctx.url, buffered=False)
        expect(first.status_code == 200, "默认配置下第一个下载成功")
        second = ctx.client.get(ctx.url)
        expect(second.status_code == 429, "同一账号第二个在途下载被拒（1 队列）")
        second.close()
        first.close()
        expect(att.download_guard.total_active() == 0, "第二个请求被拒后不占用槽位")


@pytest.fixture(scope="class")
def rl_client(data_dir):
    """限流真正生效的测试客户端（必须在 create_app 之前打开开关）。"""
    from app import create_app
    from app.extensions import limiter

    limiter.enabled = True
    try:
        limiter.reset()
    except Exception:  # pragma: no cover - 不同版本 API 兜底
        pass
    try:
        application = create_app()
        application.config.update(TESTING=True)
        yield application.test_client()
    finally:
        limiter.enabled = False
        try:
            limiter.reset()
        except Exception:  # pragma: no cover
            pass


class TestAttachmentDownloadRateLimit:
    """C：附件下载路由的独立限流（每 IP 单位时间请求数）。"""

    def test_download_route_is_rate_limited(self, rl_client, monkeypatch):
        logger.info("=== [C1] 附件下载路由限流生效 ===")
        monkeypatch.setattr(cfg, "ATTACHMENT_DOWNLOAD_RATE_MAX", 3)
        monkeypatch.setattr(cfg, "ATTACHMENT_DOWNLOAD_RATE_WINDOW", 60)
        codes = [rl_client.get("/attachment/nobody/none.pdf").status_code
                 for _ in range(6)]
        logger.info("状态码：%s", codes)
        expect(codes.count(429) >= 3, "超过下载限流阈值后持续返回 429")
        expect(all(code in (401, 429) for code in codes),
               "限流计数先于视图执行（未登录同样是 401）")
