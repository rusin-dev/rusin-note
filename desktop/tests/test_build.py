"""release/build.py 构建脚本测试（不实际跑 PyInstaller，只验证产物与清单逻辑）"""
import hashlib
import importlib.util
import json
import sys
import tarfile
import tomllib
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("release_build", ROOT / "release" / "build.py")
build = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(build)


class TestPlatformKeys:
    @pytest.mark.parametrize("sys_platform, expected", [
        ("win32", "windows"), ("darwin", "macos"), ("linux", "linux"),
    ])
    def test_platform_key(self, monkeypatch, sys_platform, expected):
        monkeypatch.setattr(build.sys, "platform", sys_platform)
        assert build.platform_key() == expected

    @pytest.mark.parametrize("machine, expected", [
        ("AMD64", "x64"), ("x86_64", "x64"), ("arm64", "arm64"),
        ("aarch64", "arm64"), ("i686", "i686"), ("", "unknown"),
    ])
    def test_arch_key(self, monkeypatch, machine, expected):
        monkeypatch.setattr(build.platform, "machine", lambda: machine)
        assert build.arch_key() == expected

    @pytest.mark.parametrize("plat, suffix", [
        ("windows", "-setup.exe"), ("macos", ".zip"), ("linux", ".tar.gz"),
    ])
    def test_archive_suffix(self, monkeypatch, plat, suffix):
        monkeypatch.setattr(build, "platform_key", lambda: plat)
        assert build.archive_suffix() == suffix

    @pytest.mark.parametrize("plat, expected", [
        ("windows", True), ("macos", False), ("linux", False),
    ])
    def test_installer_only_on_windows(self, monkeypatch, plat, expected):
        monkeypatch.setattr(build, "platform_key", lambda: plat)
        assert build.windows_installer() is expected

    def test_artifact_name(self):
        assert build.artifact_name("1.2.3", "windows", "x64", "-setup.exe") == (
            "rusin-note-desktop-1.2.3-windows-x64-setup.exe"
        )
        assert build.artifact_name("1.2.3", "macos", "arm64", ".zip") == (
            "rusin-note-desktop-1.2.3-macos-arm64.zip"
        )


class TestVersionAndHash:
    def test_project_version_matches_pyproject(self):
        with open(ROOT / "pyproject.toml", "rb") as f:
            expected = tomllib.load(f)["project"]["version"]
        assert build.project_version() == expected

    def test_sha256_of(self, tmp_path):
        payload = b"rusin-note" * 5000
        path = tmp_path / "artifact.zip"
        path.write_bytes(payload)
        assert build.sha256_of(path) == hashlib.sha256(payload).hexdigest()

    def test_sha256_of_empty_file(self, tmp_path):
        path = tmp_path / "empty"
        path.write_bytes(b"")
        assert build.sha256_of(path) == hashlib.sha256(b"").hexdigest()

    def test_write_metadata(self, tmp_path, monkeypatch):
        monkeypatch.setattr(build, "ROOT", tmp_path)
        build.write_metadata("9.9.9", "beta")
        data = json.loads((tmp_path / "data" / "metadata.json").read_text(encoding="utf-8"))
        assert data == {"version": "9.9.9", "channel": "beta"}


def _fake_onedir(tmp_path: Path, name: str = "rusin-note-desktop") -> Path:
    built = tmp_path / name
    (built / "sub").mkdir(parents=True)
    (built / "rusin-note-desktop.exe").write_bytes(b"binary")
    (built / "sub" / "lib.dll").write_bytes(b"dll")
    return built


class TestMakeArtifact:
    def test_windows_compiles_installer(self, tmp_path, monkeypatch):
        """Windows 分发 Inno Setup 安装包（含桌面/开始菜单快捷方式），不再 zip。"""
        monkeypatch.setattr(build, "platform_key", lambda: "windows")
        built = _fake_onedir(tmp_path)
        target = tmp_path / "out" / "rusin-note-desktop-1.0.0-windows-x64-setup.exe"

        def fake_make_installer(src, tgt, version):
            assert src == built
            assert version == "1.0.0"
            tgt.parent.mkdir(parents=True, exist_ok=True)
            tgt.write_bytes(b"setup-exe")
            return tgt

        monkeypatch.setattr(build, "make_installer", fake_make_installer)
        build.make_artifact(built, target, "1.0.0")
        assert target.read_bytes() == b"setup-exe"
        assert target.suffix == ".exe"

    def test_linux_still_archives(self, tmp_path, monkeypatch):
        monkeypatch.setattr(build, "platform_key", lambda: "linux")
        built = _fake_onedir(tmp_path)
        target = tmp_path / "out" / "app.tar.gz"
        build.make_artifact(built, target, "1.0.0")
        with tarfile.open(target) as tar:
            assert any(m.name.endswith("rusin-note-desktop.exe") for m in tar.getmembers())


class TestMakeInstaller:
    def test_invokes_iscc_with_expected_args(self, tmp_path, monkeypatch):
        """ISCC 编译命令应带上版本、源目录与产物名（供 Inno Setup 脚本使用）。"""
        monkeypatch.setattr(build, "platform_key", lambda: "windows")
        built = _fake_onedir(tmp_path)
        target = tmp_path / "out" / "rusin-note-desktop-1.0.0-windows-x64-setup.exe"
        monkeypatch.setattr(build, "find_iscc", lambda: "ISCC")

        commands: list[list[str]] = []

        def fake_run(command, **kwargs):
            commands.append(command)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"setup")
            return None

        monkeypatch.setattr(build.subprocess, "run", fake_run)
        build.make_installer(built, target, "1.0.0")

        assert commands, "应调用 ISCC 编译"
        command = commands[0]
        assert command[0] == "ISCC"
        assert f"/DAppVersion=1.0.0" in command
        assert f"/DSourceDir={built}" in command
        assert f"/O{target.parent}" in command
        assert f"/F{target.stem}" in command

    def test_missing_iscc_raises(self, monkeypatch):
        monkeypatch.setattr(build, "find_iscc", _raise_missing_iscc)
        with pytest.raises(FileNotFoundError):
            build.make_installer(Path("built"), Path("out/setup.exe"), "1.0.0")


def _raise_missing_iscc():
    raise FileNotFoundError("未找到 Inno Setup 的 ISCC.exe")


class TestMakeArchive:
    def test_windows_zip_keeps_top_level_dir(self, tmp_path, monkeypatch):
        monkeypatch.setattr(build, "platform_key", lambda: "windows")
        built = _fake_onedir(tmp_path)
        target = tmp_path / "out" / "app.zip"
        build.make_archive(built, target)
        with zipfile.ZipFile(target) as bundle:
            names = sorted(bundle.namelist())
        assert names == [
            "rusin-note-desktop/rusin-note-desktop.exe",
            "rusin-note-desktop/sub/lib.dll",
        ]

    def test_linux_tar_gz(self, tmp_path, monkeypatch):
        monkeypatch.setattr(build, "platform_key", lambda: "linux")
        built = _fake_onedir(tmp_path)
        target = tmp_path / "out" / "app.tar.gz"
        build.make_archive(built, target)
        with tarfile.open(target) as tar:
            names = sorted(m.name for m in tar.getmembers() if m.isfile())
        assert names == [
            "rusin-note-desktop/rusin-note-desktop.exe",
            "rusin-note-desktop/sub/lib.dll",
        ]

    def test_macos_packages_app_bundle(self, tmp_path, monkeypatch):
        monkeypatch.setattr(build, "platform_key", lambda: "macos")
        built = _fake_onedir(tmp_path, "rusin-note-desktop.app")
        target = tmp_path / "out" / "app.zip"
        build.make_archive(tmp_path / "rusin-note-desktop", target)
        with zipfile.ZipFile(target) as bundle:
            assert all(n.startswith("rusin-note-desktop.app/") for n in bundle.namelist())

    def test_macos_missing_bundle_raises(self, tmp_path, monkeypatch):
        monkeypatch.setattr(build, "platform_key", lambda: "macos")
        with pytest.raises(FileNotFoundError):
            build.make_archive(tmp_path / "rusin-note-desktop", tmp_path / "app.zip")


def _partial(plat: str, arch: str, version: str = "1.0.0", channel: str = "stable") -> dict:
    return {
        "version": version,
        "channel": channel,
        "released_at": "2026-01-02",
        "notes": "首个版本",
        "artifacts": [{
            "id": f"{plat}-{arch}",
            "platform": plat,
            "arch": arch,
            "file": build.artifact_name(version, plat, arch, ".zip"),
            "sha256": "a" * 64,
        }],
    }


class TestMergeManifests:
    def test_orders_platforms_and_writes_manifest(self, tmp_path):
        for plat, arch in [("linux", "x64"), ("macos", "arm64"), ("windows", "x64")]:
            (tmp_path / f"manifest-{plat}-{arch}.json").write_text(
                json.dumps(_partial(plat, arch)), encoding="utf-8"
            )
        merged = build.merge_manifests(tmp_path)
        assert [a["id"] for a in merged["artifacts"]] == [
            "windows-x64", "macos-arm64", "linux-x64",
        ]
        assert merged["version"] == "1.0.0"
        assert merged["channel"] == "stable"
        assert merged["released_at"] == "2026-01-02"
        assert merged["notes"] == "首个版本"
        on_disk = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
        assert on_disk == merged

    def test_dedupes_same_artifact_id(self, tmp_path):
        (tmp_path / "manifest-windows-x64.json").write_text(
            json.dumps(_partial("windows", "x64")), encoding="utf-8"
        )
        (tmp_path / "manifest-windows-x64-copy.json").write_text(
            json.dumps(_partial("windows", "x64")), encoding="utf-8"
        )
        merged = build.merge_manifests(tmp_path)
        assert len(merged["artifacts"]) == 1

    def test_version_mismatch_raises(self, tmp_path):
        (tmp_path / "manifest-windows-x64.json").write_text(
            json.dumps(_partial("windows", "x64", version="1.0.0")), encoding="utf-8"
        )
        (tmp_path / "manifest-linux-x64.json").write_text(
            json.dumps(_partial("linux", "x64", version="2.0.0")), encoding="utf-8"
        )
        with pytest.raises(ValueError):
            build.merge_manifests(tmp_path)

    def test_no_partials_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            build.merge_manifests(tmp_path)

    def test_main_merge_returns_zero(self, tmp_path, capsys):
        (tmp_path / "manifest-windows-x64.json").write_text(
            json.dumps(_partial("windows", "x64")), encoding="utf-8"
        )
        assert build.main(["--merge", str(tmp_path)]) == 0
        assert "1 个平台产物" in capsys.readouterr().out

    def test_merged_manifest_matches_site_schema(self, tmp_path):
        """清单字段须与网页版 app/apps/downloads/service.py 的校验规则一致。"""
        (tmp_path / "manifest-windows-x64.json").write_text(
            json.dumps(_partial("windows", "x64", version="1.2.3")), encoding="utf-8"
        )
        merged = build.merge_manifests(tmp_path)
        assert set(merged) == {"version", "channel", "released_at", "notes", "artifacts"}
        for item in merged["artifacts"]:
            assert set(item) == {"id", "platform", "arch", "file", "sha256"}
            assert item["id"] == f"{item['platform']}-{item['arch']}"
            assert item["file"].endswith((".zip", ".tar.gz", ".exe", "-setup.exe"))
            assert len(item["sha256"]) == 64
            assert all(c in "0123456789abcdef" for c in item["sha256"])