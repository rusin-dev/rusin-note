"""笔记图床功能端到端测试（pytest + logging）。

覆盖：魔数校验、multipart 上传、公开读取与缓存头、大小/配额/格式校验链、
笔记保留字、bleach img 白名单与危险协议拦截、管理页列表与删除、功能开关
门控（服务不裂图）、用户隔离与 file 后端落盘。

运行：``pytest tests/test_images.py``
"""
from __future__ import annotations

import io
import json
import logging
import os

from app import config as cfg
from app.feature_flags import FEATURE_KEYS, set_flags
from app.images import generate_image_id, sniff_image_format, validate_image_id
from app.notes import validate_note_id
from support import (
    create_note,
    csrf_from,
    csrf_of,
    expect,
    logout,
    register_and_login,
    upload_image,
)

logger = logging.getLogger("rusin.tests.images")

USER = "picasso"
OTHER = "viewer5"

PNG = b"\x89PNG\r\n\x1a\n" + b"IHDR" + os.urandom(64)
JPEG = b"\xff\xd8\xff\xe0" + b"JFIF" + os.urandom(60)
GIF = b"GIF89a" + os.urandom(60)
WEBP = b"RIFF" + b"\x24\x00\x00\x00" + b"WEBPVP8 " + os.urandom(40)
FAKE = b"#!/bin/sh\necho not-an-image\n" + os.urandom(48)


class TestImageSniffing:
    """A：魔数嗅探与 ID 校验（模块级纯函数）。"""

    def test_sniff_formats(self):
        logger.info("=== [A] 图片格式嗅探 ===")
        expect(sniff_image_format(PNG) == "png", "识别 PNG")
        expect(sniff_image_format(JPEG) == "jpg", "识别 JPEG（统一为 jpg）")
        expect(sniff_image_format(GIF) == "gif", "识别 GIF")
        expect(sniff_image_format(WEBP) == "webp", "识别 WebP")
        expect(sniff_image_format(FAKE) is None, "非图片内容返回 None")
        expect(sniff_image_format(b"\x89PNG") is None, "过短数据返回 None")
        expect(sniff_image_format(b"<svg onload=alert(1)>") is None, "SVG 文本返回 None")

    def test_image_id(self):
        image_id = generate_image_id("png")
        expect(validate_image_id(image_id) and image_id.endswith(".png"),
               "生成的 ID 合法且带扩展名")
        expect(validate_image_id("../evil.png") is False
               and validate_image_id("a.png.exe") is False
               and validate_image_id("") is False, "非法 ID 被拒")


class TestImageE2E:
    """B-H：上传、读取、校验、渲染、管理与隔离。"""

    def test_upload_and_public_read(self, ctx):
        logger.info("=== [B] 上传与读取 ===")
        register_and_login(ctx.client, USER)
        ctx.note_id = create_note(ctx.client, USER, "")
        ctx.csrf = csrf_from(ctx.client, f"/user/{USER}/images")

        response = upload_image(ctx.client, USER, ctx.csrf, PNG)
        assert response.status_code == 200, \
            f"上传失败: {response.status_code} {response.get_data(as_text=True)[:200]}"
        payload = json.loads(response.get_data(as_text=True))
        expect(payload["url"].startswith(f"/image/{USER}/") and validate_image_id(payload["name"]),
               "上传返回 JSON url/name")
        ctx.image_url = payload["url"]
        ctx.image_name = payload["name"]

        response = ctx.anon.get(ctx.image_url)
        expect(response.status_code == 200 and response.get_data() == PNG,
               "匿名可读取图片且字节一致")
        expect(response.headers.get("Content-Type") == "image/png"
               and "max-age=86400" in response.headers.get("Cache-Control", ""),
               "Content-Type 与长缓存头")
        expect(ctx.anon.get(f"/image/{USER}/../evil.png").status_code == 404, "非法图片 ID -> 404")
        expect(ctx.anon.get(f"/image/{USER}/zzzz.png").status_code == 404, "不存在图片 -> 404")
        disk = os.path.join(ctx.data_dir, "images", USER, payload["name"])
        expect(os.path.isfile(disk) and open(disk, "rb").read() == PNG,
               "file 后端二进制落盘一致")

    def test_upload_validation_chain(self, ctx):
        logger.info("=== [C] 上传校验链 ===")
        response = upload_image(ctx.client, USER, ctx.csrf, FAKE, filename="trojan.png")
        expect(response.status_code == 400 and "PNG / JPEG" in response.get_data(as_text=True),
               "伪装扩展名的非图片 -> 400")
        response = upload_image(ctx.client, USER, ctx.csrf, b"", filename="empty.png")
        expect(response.status_code == 400, "空文件 -> 400")

        old_size = cfg.MAX_IMAGE_SIZE_BYTES
        try:
            cfg.MAX_IMAGE_SIZE_BYTES = 8
            response = upload_image(ctx.client, USER, ctx.csrf, PNG)
        finally:
            cfg.MAX_IMAGE_SIZE_BYTES = old_size
        expect(response.status_code == 400, "超单图大小 -> 400")

        old_total = cfg.MAX_IMAGE_TOTAL_BYTES
        try:
            cfg.MAX_IMAGE_TOTAL_BYTES = 1  # 已有用量立即超配额
            response = upload_image(ctx.client, USER, ctx.csrf, PNG)
        finally:
            cfg.MAX_IMAGE_TOTAL_BYTES = old_total
        try:
            quota_err = json.loads(response.get_data(as_text=True)).get("error", "")
        except ValueError:
            quota_err = ""
        expect(response.status_code == 400 and quota_err.startswith("图床空间不足"),
               "超用户配额 -> 400")

        anon_client = ctx.app.test_client()
        anon_csrf = csrf_of(anon_client.get("/login").get_data(as_text=True))
        response = anon_client.post(f"/user/{USER}/images", data={
            "file": (io.BytesIO(PNG), "x.png", "image/png"),
            "csrf_token": anon_csrf,
        }, content_type="multipart/form-data")
        expect(response.status_code == 401, "未登录上传 -> 401")

    def test_reserved_route(self, ctx):
        logger.info("=== [D] 路由与保留字 ===")
        expect(validate_note_id("images") is False, "images 成为保留笔记 ID")
        response = ctx.client.get(f"/user/{USER}/images")
        expect(response.status_code == 200 and "image-grid" in response.get_data(as_text=True),
               "/user/<u>/images 是管理页而非笔记")

    def test_markdown_bleach(self, ctx):
        logger.info("=== [E] Markdown 渲染 ===")
        response = ctx.client.post(f"/user/{USER}/{ctx.note_id}", data={
            "content": f"# 带图笔记\n\n![截图]({ctx.image_url})\n\n![x](javascript:alert(1))\n",
            "csrf_token": ctx.csrf,
        })
        assert response.status_code == 302
        html = ctx.client.get(f"/user/{USER}/{ctx.note_id}.md").get_data(as_text=True)
        expect(f'<img alt="截图" src="{ctx.image_url}"' in html, "合法图片渲染为 img 标签")
        expect("javascript:" not in html, "javascript: 协议被 bleach 拦截")

    def test_admin_page_and_delete(self, ctx):
        logger.info("=== [F] 管理页 ===")
        html = ctx.client.get(f"/user/{USER}/images").get_data(as_text=True)
        expect(ctx.image_name in html and "已用" in html, "列表展示图片与用量")
        response = ctx.client.post(f"/user/{USER}/images/delete", data={
            "image_id": ctx.image_name, "csrf_token": ctx.csrf,
        })
        assert response.status_code == 302, f"删除失败: {response.status_code}"
        expect(ctx.anon.get(ctx.image_url).status_code == 404, "删除后图片不可访问")

    def test_feature_flag_gating(self, ctx):
        logger.info("=== [G] 功能开关 note_images ===")
        response = upload_image(ctx.client, USER, ctx.csrf, GIF)
        assert response.status_code == 200
        gif_url = json.loads(response.get_data(as_text=True))["url"]
        ctx.gif_url = gif_url

        set_flags({k: (k != "note_images") for k in FEATURE_KEYS})
        cache_html = ctx.client.get(f"/user/{USER}/{ctx.note_id}").get_data(as_text=True)
        expect('const IMAGES_API = "";' in cache_html, "停用后编辑器不上传（IMAGES_API 为空）")
        expect(upload_image(ctx.client, USER, ctx.csrf, PNG).status_code == 404,
               "停用后上传路由 -> 404")
        expect(ctx.client.get(f"/user/{USER}/images").status_code == 404, "停用后管理页 -> 404")
        expect(ctx.anon.get(gif_url).status_code == 200, "停用后已传图片仍可访问（不裂图）")

        set_flags({k: True for k in FEATURE_KEYS})
        cache_html = ctx.client.get(f"/user/{USER}/{ctx.note_id}").get_data(as_text=True)
        expect(f'const IMAGES_API = "/user/{USER}/images";' in cache_html, "重新启用后恢复上传")

    def test_user_isolation(self, ctx):
        logger.info("=== [H] 用户隔离 ===")
        logout(ctx.client)
        register_and_login(ctx.client, OTHER)
        create_note(ctx.client, OTHER, "")
        other_csrf = csrf_from(ctx.client, f"/user/{OTHER}/images")
        response = upload_image(ctx.client, OTHER, other_csrf, WEBP,
                                filename="d.webp", mime="image/webp")
        assert response.status_code == 200
        other_url = json.loads(response.get_data(as_text=True))["url"]
        expect(ctx.anon.get(other_url).status_code == 200
               and ctx.anon.get(other_url).get_data() == WEBP, "他人图片正常存取")
        html = ctx.client.get(f"/user/{OTHER}/images").get_data(as_text=True)
        expect(other_url.split("/")[-1] in html and ctx.image_url.split("/")[-1] not in html,
               "管理页只含自己的图片")
