"""桌面端构建与发布产物生成。

用法（在 desktop/ 下）：
    uv run python release/build.py                 # 构建当前平台
    uv run python release/build.py --merge dist/downloads   # 合并各平台清单

产物落在 dist/downloads/，整目录投放到网页版数据目录的 downloads/ 下即可被
/downloads 落地页读取。每个平台先产出 manifest-<platform>-<arch>.json，
三平台构建完成后用 --merge 合成 manifest.json。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
import sys
import tarfile
import tomllib
import zipfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "release" / "rusin-note-desktop.spec"
DIST = ROOT / "dist"
WORK = ROOT / "build"
OUTPUT = DIST / "downloads"
APP_NAME = "rusin-note-desktop"
PLATFORM_ORDER = ("windows", "macos", "linux")
CHANNELS = ("stable", "beta")


def platform_key() -> str:
    return {"win32": "windows", "darwin": "macos"}.get(sys.platform, "linux")


def arch_key() -> str:
    machine = platform.machine().lower()
    if machine in ("x86_64", "amd64", "x64"):
        return "x64"
    if machine in ("arm64", "aarch64"):
        return "arm64"
    return "".join(ch for ch in machine if ch.isalnum() or ch in "-_") or "unknown"


def archive_suffix() -> str:
    return ".tar.gz" if platform_key() == "linux" else ".zip"


def artifact_name(version: str, plat: str, arch: str, suffix: str) -> str:
    return f"{APP_NAME}-{version}-{plat}-{arch}{suffix}"


def project_version() -> str:
    with open(ROOT / "pyproject.toml", "rb") as f:
        return tomllib.load(f)["project"]["version"]


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_metadata(version: str, channel: str) -> None:
    """打包前写入版本信息，随包携带供更新检查读取。"""
    path = ROOT / "data" / "metadata.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"version": version, "channel": channel}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def run_pyinstaller() -> Path:
    command = [
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
        "--distpath", str(DIST), "--workpath", str(WORK), str(SPEC),
    ]
    subprocess.run(command, check=True, cwd=str(ROOT))
    return DIST / APP_NAME


def make_archive(built: Path, target: Path) -> Path:
    """把 onedir 产物压成免安装包；macOS 打包 .app，其余打包整个目录。"""
    plat = platform_key()
    if plat == "macos":
        source = built.with_name(built.name + ".app")
        if not source.is_dir():
            raise FileNotFoundError(f"未找到 macOS 应用 bundle: {source}")
    else:
        source = built
    target.parent.mkdir(parents=True, exist_ok=True)
    if str(target).endswith(".tar.gz"):
        with tarfile.open(target, "w:gz") as tar:
            tar.add(source, arcname=source.name)
    else:
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as bundle:
            for path in sorted(source.rglob("*")):
                if path.is_file():
                    bundle.write(path, arcname=str(path.relative_to(source.parent)))
    return target


def build(version: str, channel: str, notes: str, released_at: str) -> Path:
    plat, arch = platform_key(), arch_key()
    write_metadata(version, channel)
    built = run_pyinstaller()
    name = artifact_name(version, plat, arch, archive_suffix())
    artifact = make_archive(built, OUTPUT / name)
    partial = {
        "version": version,
        "channel": channel,
        "released_at": released_at,
        "notes": notes,
        "artifacts": [{
            "id": f"{plat}-{arch}",
            "platform": plat,
            "arch": arch,
            "file": name,
            "sha256": sha256_of(artifact),
        }],
    }
    manifest_path = OUTPUT / f"manifest-{plat}-{arch}.json"
    manifest_path.write_text(
        json.dumps(partial, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"产物: {artifact}")
    print(f"清单: {manifest_path}")
    return artifact


def merge_manifests(directory: Path) -> dict:
    """合并各平台分清单为 manifest.json（站点落地页读取的就是它）。"""
    partials = sorted(directory.glob("manifest-*.json"))
    if not partials:
        raise FileNotFoundError(f"{directory} 下没有 manifest-*.json")
    merged: dict = {}
    artifacts: dict[str, dict] = {}
    for path in partials:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not merged:
            merged = {k: data[k] for k in ("version", "channel", "released_at", "notes")}
        elif any(merged[k] != data[k] for k in ("version", "channel")):
            raise ValueError(f"{path.name} 的版本/渠道与其它平台不一致")
        for item in data.get("artifacts", []):
            artifacts[item["id"]] = item
    merged["artifacts"] = [
        artifacts[key]
        for key in sorted(
            artifacts,
            key=lambda k: (
                PLATFORM_ORDER.index(artifacts[k]["platform"])
                if artifacts[k]["platform"] in PLATFORM_ORDER else len(PLATFORM_ORDER),
                k,
            ),
        )
    ]
    (directory / "manifest.json").write_text(
        json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return merged


def main(argv: list[str] | None = None) -> int:
    # Windows 控制台默认 GBK，中文进度输出会变乱码
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="构建 rusin-note 桌面端并生成下载清单")
    parser.add_argument("--version", default=None, help="默认取 pyproject.toml 的 version")
    parser.add_argument("--channel", default="stable", choices=CHANNELS)
    parser.add_argument("--notes", default="", help="更新说明（展示在下载页）")
    parser.add_argument("--released-at", default=None, help="发布日期 YYYY-MM-DD，默认今天")
    parser.add_argument("--merge", metavar="DIR", default=None, help="只合并该目录下的分清单")
    args = parser.parse_args(argv)

    if args.merge:
        merged = merge_manifests(Path(args.merge))
        print(f"已合并 {len(merged['artifacts'])} 个平台产物 → {Path(args.merge) / 'manifest.json'}")
        return 0

    version = args.version or project_version()
    released_at = args.released_at or date.today().isoformat()
    build(version, args.channel, args.notes, released_at)
    return 0


if __name__ == "__main__":
    sys.exit(main())