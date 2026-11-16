"""桌面客户端下载页（/downloads）端到端测试（pytest + logging）。

覆盖：落地页渲染与平台卡片、功能开关 404、安装包流式下载与 Range 续传、
清单缺失/损坏的空状态、清单校验（非法 id/平台/后缀/sha256）、路径穿越与
体积上限防护、客户端更新检查端点、导航与首页入口随开关显隐。

运行：``pytest tests/test_downloads.py``
"""
from __future__ import annotations

import hashlib
import json
import logging
import os

from app.core import config
from app.core.extensions import cache
from app.core.feature_flags import FEATURE_KEYS, set_flags
from support import expect

logger = logging.getLogger("rusin.tests.downloads")

PAYLOAD = b"RUSIN-DESKTOP-INSTALLER-BYTES\x00\x01\x02" * 64
SHA256 = hashlib.sha256(PAYLOAD).hexdigest()


def _write_manifest(data_dir, artifacts, **extra) -> None:
    """在数据目录的 downloads/ 下写入清单与产物文件。"""
    root = data_dir / config.DOWNLOADS_DIR
    root.mkdir(parents=True, exist_ok=True)
    for artifact in artifacts:
        name = artifact.get("file")
        if name and "/" not in name and "\\" not in name and not os.path.isabs(name):
            (root / name).write_bytes(artifact.get("_payload", PAYLOAD))
    manifest = {"version": "0.1.0", "channel": "stable", "released_at": "2026-11-15",
                "notes": "首个版本", "artifacts": artifacts}
    manifest.update(extra)
    (root / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    cache.clear()


def _clear_downloads(data_dir) -> None:
    """清空 downloads 目录（data_dir 为类级共享，用例间需显式重置）。"""
    root = data_dir / config.DOWNLOADS_DIR
    if root.is_dir():
        for path in root.iterdir():
            if path.is_file():
                path.unlink()
    cache.clear()


def _artifact(aid="windows-x64", platform="windows", file="rusin-note-desktop-0.1.0-windows-x64.exe",
              arch="x64", sha256=SHA256, **extra) -> dict:
    item = {"id": aid, "platform": platform, "arch": arch, "file": file, "sha256": sha256}
    item.update(extra)
    return item


def _set_flag(enabled: bool) -> None:
    set_flags({**{key: True for key in FEATURE_KEYS}, "downloads": enabled})
    cache.clear()


class TestDownloadsPage:
    """落地页：匿名可读，按清单渲染平台卡片。"""

    def test_page_renders_artifacts(self, ctx):
        logger.info("=== 落地页渲染平台卡片 ===")
        _write_manifest(ctx.data_dir, [
            _artifact(),
            _artifact("macos-arm64", "macos", "rusin-note-desktop-0.1.0-macos-arm64.dmg", "arm64"),
            _artifact("linux-x64", "linux", "rusin-note-desktop-0.1.0-linux-x64.AppImage", "x64"),
        ])
        response = ctx.anon.get("/downloads")
        expect(response.status_code == 200, "匿名访问 /downloads 返回 200")
        html = response.get_data(as_text=True)
        expect('class="dl-tagline"' in html, "渲染 Hero 渐变标题")
        expect(html.count('class="dl-platform"') == 3, "三个平台各渲染一张卡片")
        expect("/downloads/file/windows-x64" in html, "卡片指向产物下载路由")
        expect("/downloads/file/macos-arm64" in html, "macOS 产物链接存在")
        expect("/downloads/file/linux-x64" in html, "Linux 产物链接存在")
        expect("0.1.0" in html, "展示版本号")
        expect(SHA256 in html, "展示 SHA256 校验值")
        expect("首个版本" in html, "展示更新说明")
        expect("downloads_faq_q1" not in html, "FAQ 文案已翻译（无裸 key 泄漏）")

    def test_empty_state_without_manifest(self, ctx):
        logger.info("=== 清单缺失走空状态 ===")
        _clear_downloads(ctx.data_dir)
        response = ctx.anon.get("/downloads")
        expect(response.status_code == 200, "无清单时页面仍 200")
        html = response.get_data(as_text=True)
        expect('class="dl-empty"' in html, "渲染空状态容器")
        expect('class="dl-platform"' not in html, "无产物时不渲染平台卡片")

    def test_broken_manifest_is_empty_state(self, ctx):
        logger.info("=== 清单损坏不 500 ===")
        root = ctx.data_dir / config.DOWNLOADS_DIR
        root.mkdir(parents=True, exist_ok=True)
        (root / "manifest.json").write_text("{ 这不是 JSON", encoding="utf-8")
        cache.clear()
        response = ctx.anon.get("/downloads")
        expect(response.status_code == 200, "损坏清单降级为空状态而非 500")
        expect('class="dl-empty"' in response.get_data(as_text=True), "渲染空状态")

    def test_feature_flag_off_404(self, ctx):
        logger.info("=== 功能开关停用后 404 ===")
        _write_manifest(ctx.data_dir, [_artifact()])
        _set_flag(False)
        try:
            expect(ctx.anon.get("/downloads").status_code == 404, "停用后落地页 404")
            expect(ctx.anon.get("/downloads/file/windows-x64").status_code == 404, "停用后下载 404")
            expect(ctx.anon.get("/downloads/manifest.json").status_code == 404, "停用后清单端点 404")
            expect("/downloads" not in ctx.anon.get("/").get_data(as_text=True), "首页入口随开关隐藏")
        finally:
            _set_flag(True)

    def test_nav_entry_present(self, ctx):
        logger.info("=== 导航栏入口 ===")
        _write_manifest(ctx.data_dir, [_artifact()])
        html = ctx.anon.get("/downloads").get_data(as_text=True)
        expect('href="/downloads"' in html, "导航栏含下载页入口")


class TestDownloadsFile:
    """安装包下载：流式发送、断点续传、安全头。"""

    def test_download_bytes_and_headers(self, ctx):
        logger.info("=== 下载内容与响应头 ===")
        _write_manifest(ctx.data_dir, [_artifact()])
        response = ctx.anon.get("/downloads/file/windows-x64")
        expect(response.status_code == 200, "下载返回 200")
        expect(response.data == PAYLOAD, "下载字节与源文件一致")
        expect(response.headers["Content-Type"] == "application/octet-stream", "MIME 为 octet-stream")
        expect("attachment" in response.headers["Content-Disposition"], "Content-Disposition 为附件")
        expect("rusin-note-desktop-0.1.0-windows-x64.exe" in response.headers["Content-Disposition"],
               "下载文件名取自清单")
        expect(response.headers["X-Content-Type-Options"] == "nosniff", "带 nosniff 头")
        expect(response.headers["Content-Length"] == str(len(PAYLOAD)), "Content-Length 正确")
        expect(response.headers.get("Accept-Ranges") == "bytes", "支持 Range 续传")

    def test_range_request(self, ctx):
        logger.info("=== Range 断点续传 ===")
        _write_manifest(ctx.data_dir, [_artifact()])
        response = ctx.anon.get("/downloads/file/windows-x64", headers={"Range": "bytes=0-15"})
        expect(response.status_code == 206, "Range 请求返回 206")
        expect(response.data == PAYLOAD[:16], "只返回请求的字节区间")
        expect(response.headers["Content-Range"] == f"bytes 0-15/{len(PAYLOAD)}", "Content-Range 正确")

    def test_unknown_artifact_404(self, ctx):
        logger.info("=== 未登记产物 404 ===")
        _write_manifest(ctx.data_dir, [_artifact()])
        expect(ctx.anon.get("/downloads/file/nope").status_code == 404, "未知 id 返回 404")
        expect(ctx.anon.get("/downloads/file/WINDOWS-X64").status_code == 404, "id 大小写敏感")

    def test_missing_file_404(self, ctx):
        logger.info("=== 清单登记但文件缺失 ===")
        root = ctx.data_dir / config.DOWNLOADS_DIR
        _write_manifest(ctx.data_dir, [_artifact()])
        (root / "rusin-note-desktop-0.1.0-windows-x64.exe").unlink()
        cache.clear()
        expect(ctx.anon.get("/downloads/file/windows-x64").status_code == 404, "文件缺失返回 404")
        expect('class="dl-platform"' not in ctx.anon.get("/downloads").get_data(as_text=True),
               "缺失文件不在落地页展示")


class TestDownloadsManifestValidation:
    """清单是管理员提供的外部输入：非法条目丢弃，穿越/超限拒绝。"""

    def test_traversal_rejected(self, ctx):
        logger.info("=== 相对路径穿越被拒 ===")
        outside = ctx.data_dir / "secret.txt"
        outside.write_bytes(b"TOP-SECRET")
        _write_manifest(ctx.data_dir, [_artifact(file="../secret.txt")])
        expect(ctx.anon.get("/downloads/file/windows-x64").status_code == 404, "穿越产物不可下载")
        expect(b"TOP-SECRET" not in ctx.anon.get("/downloads").get_data(as_text=True).encode(),
               "落地页不泄漏目录外文件")

    def test_absolute_path_rejected(self, ctx):
        logger.info("=== 绝对路径被拒 ===")
        outside = ctx.data_dir / "outside.bin"
        outside.write_bytes(b"OUTSIDE")
        _write_manifest(ctx.data_dir, [_artifact(file=str(outside))])
        expect(ctx.anon.get("/downloads/file/windows-x64").status_code == 404, "绝对路径产物被丢弃")

    def test_symlink_escape_rejected(self, ctx):
        logger.info("=== 符号链接越界被拒 ===")
        root = ctx.data_dir / config.DOWNLOADS_DIR
        root.mkdir(parents=True, exist_ok=True)
        outside = ctx.data_dir / "outside.bin"
        outside.write_bytes(b"OUTSIDE")
        link = root / "link.exe"
        try:
            link.symlink_to(outside)
        except (OSError, NotImplementedError):
            logger.info("  [SKIP] 当前平台无符号链接权限")
            return
        _write_manifest(ctx.data_dir, [_artifact(file="link.exe")])
        expect(ctx.anon.get("/downloads/file/windows-x64").status_code == 404, "越界符号链接被拒")

    def test_oversize_rejected(self, ctx, monkeypatch):
        logger.info("=== 超出体积上限被拒 ===")
        _write_manifest(ctx.data_dir, [_artifact()])
        monkeypatch.setattr(config, "DOWNLOADS_MAX_FILE_BYTES", 16)
        cache.clear()
        expect(ctx.anon.get("/downloads/file/windows-x64").status_code == 404, "超限产物不可下载")
        expect('class="dl-platform"' not in ctx.anon.get("/downloads").get_data(as_text=True),
               "超限产物不在落地页展示")

    def test_invalid_entries_dropped(self, ctx):
        logger.info("=== 非法 id / 平台 / 后缀 / sha256 ===")
        _write_manifest(ctx.data_dir, [
            _artifact("bad id", "windows", "a.exe"),
            _artifact("ok-win", "windows", "a.exe"),
            _artifact("bad-platform", "android", "b.exe"),
            _artifact("bad-suffix", "windows", "c.txt"),
            _artifact("bad-sha", "windows", "d.exe", sha256="zz" * 32),
            _artifact("dup", "linux", "e.AppImage"),
            _artifact("dup", "linux", "f.AppImage"),
        ])
        html = ctx.anon.get("/downloads").get_data(as_text=True)
        expect("/downloads/file/ok-win" in html, "合法条目保留")
        expect("/downloads/file/bad-platform" not in html, "非法平台被丢弃")
        expect("/downloads/file/bad-suffix" not in html, "非法后缀被丢弃")
        expect("zz" * 32 not in html, "非法 sha256 被清空")
        expect(html.count('data-id="dup"') == 1, "重复 id 只保留首条")
        expect(ctx.anon.get("/downloads/file/bad%20id").status_code == 404, "非法 id 不可下载")

    def test_manifest_endpoint(self, ctx):
        logger.info("=== 客户端更新检查端点 ===")
        _write_manifest(ctx.data_dir, [_artifact()])
        response = ctx.anon.get("/downloads/manifest.json")
        expect(response.status_code == 200, "清单端点返回 200")
        data = response.get_json()
        expect(data["version"] == "0.1.0", "版本号正确")
        expect(data["channel"] == "stable", "渠道正确")
        expect(len(data["artifacts"]) == 1, "产物数量正确")
        artifact = data["artifacts"][0]
        expect(artifact["size"] == len(PAYLOAD), "size 为实测字节数")
        expect(artifact["sha256"] == SHA256, "sha256 透传")
        expect(artifact["url"].endswith("/downloads/file/windows-x64"), "url 为绝对地址")
        expect(artifact["url"].startswith("http"), "url 带 scheme")

    def test_manifest_bad_version_and_channel(self, ctx):
        logger.info("=== 非法版本号/渠道归一化 ===")
        _write_manifest(ctx.data_dir, [_artifact()], version="<script>", channel="nightly")
        data = ctx.anon.get("/downloads/manifest.json").get_json()
        expect(data["version"] == "", "非法版本号被清空")
        expect(data["channel"] == "stable", "非法渠道回退 stable")