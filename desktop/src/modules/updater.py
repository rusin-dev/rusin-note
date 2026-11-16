"""客户端更新检查：向站点 /downloads/manifest.json 查询最新版本。

安装包站点自托管，与网页版 /downloads 落地页同源，因此更新检查直接读该站点的
下载清单，不再依赖 GitHub Releases。版本信息来自构建流水线生成的
data/metadata.json，PyInstaller 打包需携带数据目录：--add-data "data;data"
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import requests

_METADATA_RELATIVE_PATH = Path("data") / "metadata.json"

CHANNELS = ("stable", "beta")
MANIFEST_PATH = "/downloads/manifest.json"
_USER_AGENT = "rusin-note-desktop-updater"


def _metadata_path() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / _METADATA_RELATIVE_PATH # pyright: ignore[reportAttributeAccessIssue]
    return Path(__file__).resolve().parents[2] / _METADATA_RELATIVE_PATH


def _load_metadata() -> dict:
    with open(_metadata_path(), encoding="utf-8") as f:
        return json.load(f)


def get_current_version() -> str:
    """本地 metadata.json 中记录的版本"""
    return _load_metadata()["version"]


def get_current_channel() -> str:
    """本地 metadata.json 中记录的更新渠道（stable / beta）"""
    return _load_metadata()["channel"]


def fetch_manifest(
    site_url: str,
    channel: str | None = None,
    timeout: float = 10.0,
) -> dict:
    """取站点下载清单;渠道不匹配或清单缺版本号时抛 LookupError。"""
    channel = channel or get_current_channel()
    if channel not in CHANNELS:
        raise ValueError(f"未知渠道 {channel!r}，可选：{CHANNELS}")
    response = requests.get(
        site_url.rstrip("/") + MANIFEST_PATH,
        headers={"User-Agent": _USER_AGENT},
        timeout=timeout,
    )
    response.raise_for_status()
    manifest = response.json()
    if not isinstance(manifest, dict):
        raise LookupError("站点下载清单格式不正确")
    if manifest.get("channel") != channel:
        raise LookupError(f"站点没有 {channel} 渠道的发布")
    if not str(manifest.get("version") or "").strip():
        raise LookupError("站点下载清单缺少版本号")
    return manifest


def get_latest_version(
    site_url: str,
    channel: str | None = None,
    timeout: float = 10.0,
) -> str:
    """站点上指定渠道的最新版本号"""
    return str(fetch_manifest(site_url, channel=channel, timeout=timeout)["version"]).strip()


def _parse_version(value: str) -> tuple[tuple[int, ...], str]:
    # 先剥离预发布标记，否则 "2.0.0-rc.1" 的点号会把 rc.1 当成数字段
    text = str(value).strip().lstrip("vV").split("+", 1)[0]
    core, _, prerelease = text.partition("-")
    numbers = []
    for chunk in core.split("."):
        digits = re.match(r"^\d+", chunk)
        numbers.append(int(digits.group(0)) if digits else 0)
    return tuple(numbers), prerelease


def _prerelease_key(value: str) -> tuple:
    """预发布标识按点分段比较，数字段排在字母段之前（semver 规则）"""
    parts = []
    for chunk in value.split("."):
        if chunk.isdigit():
            parts.append((0, int(chunk), ""))
        else:
            parts.append((1, 0, chunk))
    return tuple(parts)


def is_newer(candidate: str, current: str) -> bool:
    """candidate 是否比 current 新：先比数字段，再按预发布规则比较。"""
    candidate_numbers, candidate_pre = _parse_version(candidate)
    current_numbers, current_pre = _parse_version(current)
    length = max(len(candidate_numbers), len(current_numbers))
    candidate_numbers += (0,) * (length - len(candidate_numbers))
    current_numbers += (0,) * (length - len(current_numbers))
    if candidate_numbers != current_numbers:
        return candidate_numbers > current_numbers
    if candidate_pre == current_pre:
        return False
    if not candidate_pre:
        return True
    if not current_pre:
        return False
    return _prerelease_key(candidate_pre) > _prerelease_key(current_pre)