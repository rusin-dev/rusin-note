"""桌面客户端安装包清单：读取 <DATA_DIR>/downloads/manifest.json 并校验产物。

安装包站点自托管：构建流水线产出安装包与 manifest.json，管理员整体投放到
数据目录的 downloads/ 下，落地页据此渲染下载卡片。清单是管理员提供的外部
输入，文件名/平台/体积一律校验，产物路径做 realpath 越界防护。

清单缺失或损坏按「暂无安装包」处理（artifacts 为空），不让下载页 500。
服务层无进程内缓存：清单只有几 KB，每次重读保证管理员投放后立即生效
（落地页的展示延迟由视图层 @cache.cached 的 TTL 决定）。
"""
from __future__ import annotations

import json
import os
import re

from app.core import config
from app.core.logger import create_logger

logger = create_logger("downloads")

PLATFORMS = ("windows", "macos", "linux")
CHANNELS = ("stable", "beta")

# 产物 id 出现在 URL 里（/downloads/file/<id>），只允许小写字母数字与 _-
_ARTIFACT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_\-]{0,63}$")
# 安装包文件名：首字符必须字母数字（排除 . 开头的隐藏文件与 .. 穿越）
_FILE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._\-]{0,180}$")
_ALLOWED_SUFFIXES = (
    ".exe", ".msi", ".dmg", ".pkg", ".zip",
    ".appimage", ".deb", ".rpm", ".tar.gz",
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_VERSION_RE = re.compile(r"^[0-9A-Za-z][0-9A-Za-z.\-+]{0,31}$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def downloads_root() -> str:
    """安装包目录的绝对真实路径（目录不存在也返回路径，由调用方判断）"""
    return os.path.realpath(config.data_path(config.DOWNLOADS_DIR))


def _read_raw() -> dict:
    path = os.path.join(downloads_root(), "manifest.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return {}
    except (IOError, OSError, ValueError) as e:
        logger.error(f"[错误] 读取安装包清单失败: {e}")
        return {}
    return data if isinstance(data, dict) else {}


def _clean_artifact(raw: dict) -> dict | None:
    """校验单条产物记录；非法返回 None（丢弃该条，不影响其余产物）"""
    if not isinstance(raw, dict):
        return None
    aid = str(raw.get("id") or "").strip()
    platform = str(raw.get("platform") or "").strip().lower()
    filename = str(raw.get("file") or "").strip()
    if not _ARTIFACT_ID_RE.match(aid) or platform not in PLATFORMS:
        return None
    if not _FILE_RE.match(filename) or ".." in filename:
        return None
    if not filename.lower().endswith(_ALLOWED_SUFFIXES):
        return None
    sha256 = str(raw.get("sha256") or "").strip().lower()
    arch = str(raw.get("arch") or "").strip()[:24]
    return {
        "id": aid,
        "platform": platform,
        "arch": arch,
        "file": filename,
        "sha256": sha256 if _SHA256_RE.match(sha256) else "",
        "url": f"/downloads/file/{aid}",
    }


def read_manifest() -> dict:
    """规范化清单：{version, channel, released_at, notes, artifacts}。

    artifacts 只包含磁盘上真实存在、体积在上限内的产物，并附带实测 size。
    """
    raw = _read_raw()
    version = str(raw.get("version") or "").strip()
    channel = str(raw.get("channel") or "stable").strip().lower()
    released_at = str(raw.get("released_at") or "").strip()
    notes = str(raw.get("notes") or "").strip()[:2000]
    items = raw.get("artifacts")
    artifacts = []
    seen = set()
    for item in items if isinstance(items, list) else []:
        clean = _clean_artifact(item)
        if clean is None or clean["id"] in seen:
            continue
        path = resolve_file(clean)
        if path is None:
            continue
        clean["size"] = os.path.getsize(path)
        seen.add(clean["id"])
        artifacts.append(clean)
    return {
        "version": version if _VERSION_RE.match(version) else "",
        "channel": channel if channel in CHANNELS else "stable",
        "released_at": released_at if _DATE_RE.match(released_at) else "",
        "notes": notes,
        "artifacts": artifacts,
    }


def get_artifact(artifact_id: str) -> dict | None:
    """按 id 取产物（含实测 size）；未登记或文件不可用返回 None"""
    if not isinstance(artifact_id, str) or not _ARTIFACT_ID_RE.match(artifact_id):
        return None
    for artifact in read_manifest()["artifacts"]:
        if artifact["id"] == artifact_id:
            return artifact
    return None


def resolve_file(artifact: dict) -> str | None:
    """产物绝对路径；越出安装包目录、不是普通文件或超出体积上限返回 None。

    文件名取自清单而非 URL，但清单可能被误配成绝对路径或含 .. 的相对路径，
    符号链接也可能指向目录外，故仍做 realpath 越界校验。
    """
    root = downloads_root()
    path = os.path.realpath(os.path.join(root, artifact["file"]))
    if path != root and not path.startswith(root + os.sep):
        logger.warning("安装包路径越界被拒绝: %s", artifact["file"])
        return None
    if not os.path.isfile(path):
        return None
    try:
        if os.path.getsize(path) > config.DOWNLOADS_MAX_FILE_BYTES:
            logger.warning("安装包超出体积上限被拒绝: %s", artifact["file"])
            return None
    except OSError:
        return None
    return path