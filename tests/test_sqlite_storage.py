"""SQLite + JSON 统一存储后端测试（pytest + logging）。

覆盖：``app.storage_sqlite.SqliteBackend`` 的笔记 JSON 落盘 + 索引查询、
通用 KV、图床/附件索引、旧版 ``.txt`` 笔记导入、以及 ``select_backend``
在本地无外部存储时默认选择 sqlite。

运行：``pytest tests/test_sqlite_storage.py``
"""
from __future__ import annotations

import json
import os

from support import expect

from app import config
from app.storage_sqlite import SqliteBackend
from app.storage import select_backend


def _backend(tmp_path) -> SqliteBackend:
    config.DATA_DIR = str(tmp_path)
    return SqliteBackend()


class TestSqliteNotes:
    """A：笔记内容 JSON 化 + 索引化读取。"""

    def test_notes_content_json_and_index(self, tmp_path):
        backend = _backend(tmp_path)
        expect(backend.write_note("alice", "abc", "# Hello World\nbody text"),
               "写入笔记成功")

        path = os.path.join(str(tmp_path), "notes", "alice", "abc.json")
        expect(os.path.isfile(path), "笔记内容以 JSON 文件落盘")
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
        expect(payload.get("content") == "# Hello World\nbody text", "JSON 内含 content")
        expect("created_at" in payload and "updated_at" in payload, "JSON 内含时间戳")

        expect(backend.read_note("alice", "abc") == "# Hello World\nbody text", "读取内容一致")
        expect(backend.note_title("alice", "abc") == "Hello World", "索引返回标题")
        expect(backend.note_size("alice", "abc")
               == len("# Hello World\nbody text".encode("utf-8")), "索引返回字节大小")
        expect(isinstance(backend.note_mtime("alice", "abc"), float), "索引返回修改时间")

        expect(backend.list_notes("alice") == ["abc"], "索引列出笔记")
        expect(backend.list_notes_detailed("alice")[0]["title"] == "Hello World",
               "detailed 列表带标题")
        expect(backend.notes_stats() == (0, 0, 1, len("# Hello World\nbody text".encode("utf-8"))),
               "统计走索引")

    def test_search_and_delete(self, tmp_path):
        backend = _backend(tmp_path)
        backend.write_note("alice", "n1", "# Alpha\nfirst")
        backend.write_note("alice", "n2", "# Beta\nsecond")
        hits = backend.search_notes("alice", "beta", limit=8, scan_limit=100)
        expect([h["id"] for h in hits] == ["n2"], "按标题检索命中")
        expect(backend.search_notes("alice", "n1", 8, 100)[0]["id"] == "n1", "按 ID 检索命中")
        expect(backend.search_notes("alice", "nope", 8, 100) == [], "无匹配返回空")

        expect(backend.write_note("alice", "n1", ""), "空内容删除笔记")
        expect(backend.read_note("alice", "n1") is None, "内容已删除")
        expect(not os.path.exists(os.path.join(str(tmp_path), "notes", "alice", "n1.json")),
               "JSON 文件已删除")
        expect(backend.list_notes("alice") == ["n2"], "索引同步删除")


class TestSqliteCollections:
    """B：通用 KV / 图床 / 附件索引。"""

    def test_kv_json_and_keys(self, tmp_path):
        backend = _backend(tmp_path)
        expect(backend.set("users.json", {"alice": {"salt": "s", "hash": "h"}}), "写入 KV")
        expect(backend.get("users.json") == {"alice": {"salt": "s", "hash": "h"}}, "读取 KV")
        expect(os.path.isfile(os.path.join(str(tmp_path), "users.json")), "KV 以 JSON 落盘")
        expect(backend.list_keys("users") == ["users.json"], "list_keys 命中")
        expect(backend.delete("users.json"), "删除 KV")
        expect(backend.get("users.json") is None and backend.list_keys("users") == [],
               "删除后读空且索引清理")

    def test_arbitrary_kv_key_and_underscore(self, tmp_path):
        backend = _backend(tmp_path)
        backend.set("custom:key", {"v": 1})
        expect(backend.get("custom:key") == {"v": 1}, "任意键可读写")
        expect(backend.list_keys("custom") == ["custom:key"], "任意键可列举")
        backend.set("note_tags", {"u": {}})
        backend.set("noteXtags", {"u": {}})
        expect(backend.list_keys("note_tags") == ["note_tags"], "LIKE 通配符已转义")

    def test_images_and_attachments(self, tmp_path):
        backend = _backend(tmp_path)
        expect(backend.write_image("alice", "a.png", b"\x89PNGdata"), "写入图片")
        expect(backend.read_image("alice", "a.png") == b"\x89PNGdata", "读取图片")
        expect(backend.image_size("alice", "a.png") == 8, "图片大小走索引")
        expect(backend.list_images("alice") == ["a.png"], "图片列表走索引")
        expect(backend.image_usage("alice") == 8, "图片用量走索引")
        expect(backend.delete_image("alice", "a.png"), "删除图片")
        expect(backend.list_images("alice") == [] and backend.image_usage("alice") == 0,
               "图片索引同步清理")

        expect(backend.write_attachment("alice", "b.pdf", b"PDF", "b.pdf", "application/pdf"),
               "写入附件")
        meta = backend.read_attachment_meta("alice", "b.pdf")
        expect(meta and meta["filename"] == "b.pdf"
               and meta["content_type"] == "application/pdf", "附件元数据走索引")
        expect(backend.attachment_size("alice", "b.pdf") == 3, "附件大小走索引")
        expect(backend.list_attachments("alice") == ["b.pdf"], "附件列表走索引")
        expect(backend.attachment_usage("alice") == 3, "附件用量走索引")
        expect(backend.delete_attachment("alice", "b.pdf"), "删除附件")
        expect(backend.list_attachments("alice") == [], "附件索引同步清理")


class TestSqliteMigrationAndSelection:
    """C：旧数据导入与后端默认选择。"""

    def test_legacy_txt_import(self, tmp_path):
        # 直接铺旧版 .txt，且不预先创建 index.db，模拟首次启动导入
        legacy_dir = os.path.join(str(tmp_path), "notes", "alice")
        os.makedirs(legacy_dir, exist_ok=True)
        with open(os.path.join(legacy_dir, "old.txt"), "w", encoding="utf-8") as f:
            f.write("# Legacy\ncontent")
        config.DATA_DIR = str(tmp_path)
        backend = SqliteBackend()
        expect(backend.read_note("alice", "old") == "# Legacy\ncontent", "旧 .txt 导入为 JSON")
        expect(backend.note_title("alice", "old") == "Legacy", "导入后索引含标题")
        expect(not os.path.exists(os.path.join(legacy_dir, "old.txt")), "导入后移除 .txt")

    def test_default_backend_is_sqlite(self, tmp_path, monkeypatch):
        monkeypatch.delenv("RUSIN_STORAGE", raising=False)
        monkeypatch.setenv("RUSIN_DATA_DIR", str(tmp_path))
        config.DATA_DIR = str(tmp_path)
        backend = select_backend()
        expect(backend.kind == "sqlite", "本地无外部存储时默认 sqlite 后端")
