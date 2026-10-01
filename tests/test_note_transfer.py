"""笔记批量导入 / 导出端到端测试（pytest + logging）。

覆盖：ZIP 导出结构与 manifest、跨用户导入还原内容与文件夹/标签、同名冲突
跳过不覆盖、Markdown 标记包导入、无标记纯文本作为单篇导入、坏文件与超限
拒绝、匿名 401 与功能开关停用 404。

运行：``pytest tests/test_note_transfer.py``
"""
from __future__ import annotations

import io
import json
import logging
import zipfile
from urllib.parse import parse_qs, urlparse

import app.apps.notes.service as transfer
from app.core.extensions import cache
from app.core.feature_flags import FEATURE_KEYS, set_flags
from app.core.folders import get_note_folder
from app.core.tags import get_note_tags
from support import create_note, csrf_of, expect, list_order, register_and_login, logout

logger = logging.getLogger("rusin.tests.transfer")

ALICE = "alice_tx"
BOB = "bob_tx"
CAROL = "carol_tx"


def _export(client, username, fmt=None):
    url = f"/user/{username}/export" + (f"?format={fmt}" if fmt else "")
    return client.get(url)


def _import(client, username, filename, data, mime="application/zip"):
    html = client.get(f"/user/{username}").get_data(as_text=True)
    return client.post(f"/user/{username}/import", data={
        "csrf_token": csrf_of(html),
        "file": (io.BytesIO(data), filename, mime),
    }, content_type="multipart/form-data")


def _query(resp):
    return parse_qs(urlparse(resp.headers["Location"]).query)


class TestExport:
    def test_zip_structure(self, ctx):
        logger.info("=== [A] ZIP 导出结构 ===")
        register_and_login(ctx.client, ALICE)
        n1 = create_note(ctx.client, ALICE, "# 第一篇\nhello alpha", folder="docs/a")
        n2 = create_note(ctx.client, ALICE, "# 第二篇\nbeta")
        resp = _export(ctx.client, ALICE)
        expect(resp.status_code == 200, "导出返回 200")
        page = ctx.client.get(f"/user/{ALICE}").get_data(as_text=True)
        expect(f'href="/user/{ALICE}/export"' in page and 'class="tool-form"' in page,
               "列表页渲染导出按钮与导入表单")
        expect(resp.mimetype == "application/zip", "MIME 为 zip")
        cd = resp.headers.get("Content-Disposition", "")
        expect("attachment" in cd and ALICE in cd, "响应头触发下载且含用户名")
        zf = zipfile.ZipFile(io.BytesIO(resp.data))
        names = zf.namelist()
        expect(f"notes/{n1}.md" in names and f"notes/{n2}.md" in names, "每篇笔记一个 md 条目")
        manifest = json.loads(zf.read("manifest.json"))
        expect(manifest["count"] == 2 and manifest["app"] == "rusin-note", "manifest 记录数正确")
        entry = {m["id"]: m for m in manifest["notes"]}
        expect(entry[n1]["folder"] == "docs/a", "manifest 含文件夹归属")

    def test_md_bundle(self, ctx):
        logger.info("=== [B] Markdown 单文件导出 ===")
        resp = _export(ctx.client, ALICE, fmt="md")
        expect(resp.status_code == 200, "MD 导出返回 200")
        text = resp.data.decode("utf-8")
        expect(text.count("rusin-note-id") == 2, "MD 含两篇笔记的 ID 标记")

    def test_anonymous_forbidden(self, ctx):
        logger.info("=== [C] 匿名导出 401 ===")
        logout(ctx.client)
        resp = ctx.client.get(f"/user/{ALICE}/export")
        expect(resp.status_code == 401, "未登录导出被拒绝")


class TestImport:
    def test_zip_roundtrip_restores_metadata(self, ctx):
        logger.info("=== [D] ZIP 跨用户导入还原 ===")
        register_and_login(ctx.client, ALICE)
        n1 = create_note(ctx.client, ALICE, "# 标题甲\n内容甲", folder="docs/a")
        html = ctx.client.get(f"/user/{ALICE}/{n1}").get_data(as_text=True)
        ctx.client.post(f"/user/{ALICE}/{n1}", data={
            "content": "# 标题甲\n内容甲", "folder": "docs/a", "tags": "k1,k2",
            "csrf_token": csrf_of(html),
        })
        zip_bytes = _export(ctx.client, ALICE).data

        logout(ctx.client)
        register_and_login(ctx.client, BOB)
        resp = _import(ctx.client, BOB, "backup.zip", zip_bytes)
        expect(resp.status_code == 302, "导入后重定向")
        q = _query(resp)
        expect(q.get("imported") == ["1"] and "import_err" not in q, f"导入 1 篇: {q}")
        body = ctx.client.get(f"/user/{BOB}/{n1}").get_data(as_text=True)
        expect("内容甲" in body, "内容还原（沿用原 ID）")
        expect(get_note_folder(BOB, n1) == "docs/a", "文件夹还原")
        expect(sorted(get_note_tags(BOB, n1)) == ["k1", "k2"], "标签还原")

    def test_conflict_skipped_not_overwritten(self, ctx):
        logger.info("=== [E] 同名冲突跳过不覆盖 ===")
        zip_bytes = _export(ctx.client, BOB).data
        resp = _import(ctx.client, BOB, "backup.zip", zip_bytes)
        q = _query(resp)
        expect(q.get("imported") == ["0"] and q.get("skipped") == ["1"],
               f"重复导入被跳过: {q}")
        ids = list_order(ctx.client, BOB)
        body = ctx.client.get(f"/user/{BOB}/{ids[0]}").get_data(as_text=True)
        expect("内容甲" in body, "原笔记仍在（未覆盖也未复制）")

    def test_md_bundle_import(self, ctx):
        logger.info("=== [F] MD 标记包导入 ===")
        md_bytes = _export(ctx.client, BOB, fmt="md").data  # 当前会话仍是 BOB
        logout(ctx.client)
        register_and_login(ctx.client, CAROL)
        resp = _import(ctx.client, CAROL, "notes.md", md_bytes, mime="text/markdown")
        q = _query(resp)
        expect(q.get("imported") == ["1"], f"MD 包按标记拆分导入: {q}")

    def test_plain_txt_single_note(self, ctx):
        logger.info("=== [G] 纯文本作为单篇导入 ===")
        resp = _import(ctx.client, CAROL, "random.txt", b"just plain text\nline2",
                       mime="text/plain")
        q = _query(resp)
        expect(q.get("imported") == ["1"], f"无标记文本导入 1 篇: {q}")

    def test_bad_inputs(self, ctx):
        logger.info("=== [H] 坏文件与超限 ===")
        resp = _import(ctx.client, CAROL, "broken.zip", b"not a zip at all")
        expect(_query(resp).get("import_err") == ["not_a_zip"], "坏 zip 报错")
        resp = _import(ctx.client, CAROL, "evil.exe", b"MZ...")
        expect(_query(resp).get("import_err") == ["unsupported_type"], "不支持的类型报错")
        resp = _import(ctx.client, CAROL, "", b"whatever")
        expect(_query(resp).get("import_err") == ["no_file"], "未选文件报错")
        saved = transfer.MAX_FILE_BYTES
        try:
            transfer.MAX_FILE_BYTES = 16
            resp = _import(ctx.client, CAROL, "big.txt", b"x" * 64, mime="text/plain")
            expect(_query(resp).get("import_err") == ["too_large"], "超过文件大小上限报错")
        finally:
            transfer.MAX_FILE_BYTES = saved

    def test_feature_flag_gating(self, ctx):
        logger.info("=== [I] 功能开关 notes_import_export ===")
        set_flags({k: (k != "notes_import_export") for k in FEATURE_KEYS})
        cache.clear()
        expect(_export(ctx.client, CAROL).status_code == 404, "停用后导出 404")
        set_flags({k: True for k in FEATURE_KEYS})
        cache.clear()
        expect(_export(ctx.client, CAROL).status_code == 200, "重新启用后恢复")
