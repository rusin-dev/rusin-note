"""桌面客户端安装包清单：读取并校验清单，产出落地页与更新检查所需的数据。

清单支持两种来源：

* **本地投放**（VPS）：读 ``<DATA_DIR>/downloads/manifest.json``，产物文件必须位于
  同一目录内（realpath 越界防护），体积以实测为准；
* **远程清单**（GitHub Releases 等）：由 ``downloads.github_repo`` 或
  ``downloads.manifest_url`` 指定。清单与安装包同处一个 Release，安装包地址默认按
  清单地址的**同目录**推导（``.../releases/latest/download``），清单也可显式给出
  ``url``。远程模式带进程内 TTL 缓存，拉取失败时回退到上一次成功结果。

清单是管理员提供的外部输入：文件名/平台/体积一律校验；远程地址只允许 https 且
主机在可信列表内（github.com / *.githubusercontent.com），避免清单被篡改后变成
任意跳转。清单缺失或损坏按「暂无安装包」处理（artifacts 为空），不让下载页 500。
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
import urllib.parse
import urllib.request

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

# 远程清单只有几 KB：超限即视为异常，避免被超大响应拖垮
_MANIFEST_MAX_BYTES = 256 * 1024
_MANIFEST_TIMEOUT_SECONDS = 8
# 允许的安装包下载主机：清单来自外部输入，不能让它把用户跳到任意地址
_TRUSTED_ASSET_HOSTS = (
    "github.com",
    "objects.githubusercontent.com",
    "githubusercontent.com",
)

_remote_cache: dict[str, tuple[float, dict]] = {}
_remote_lock = threading.Lock()


def downloads_root() -> str:
    """本地安装包目录的绝对真实路径（目录不存在也返回路径，由调用方判断）"""
    return os.path.realpath(config.data_path(config.DOWNLOADS_DIR))


def remote_enabled() -> bool:
    """是否从远程清单读取（配置了 github_repo / manifest_url）"""
    return bool(getattr(config, "DOWNLOADS_MANIFEST_URL", ""))


def _asset_base() -> str:
    """安装包基址＝清单地址所在目录。

    ``https://github.com/o/r/releases/latest/download/manifest.json``
    → ``https://github.com/o/r/releases/latest/download``
    """
    return config.DOWNLOADS_MANIFEST_URL.rstrip("/").rsplit("/", 1)[0]


def reset_remote_cache() -> None:
    """清空远程清单缓存（测试用；进程内多实例各有一份）"""
    with _remote_lock:
        _remote_cache.clear()


def _fetch_remote(url: str) -> dict:
    """拉取远程清单；失败时用上一次成功结果兜底，都没有则返回 {}"""
    ttl = max(0, int(getattr(config, "DOWNLOADS_MANIFEST_CACHE_SECONDS", 300)))
    now = time.monotonic()
    with _remote_lock:
        cached = _remote_cache.get(url)
    if cached and ttl and now - cached[0] < ttl:
        return cached[1]

    request = urllib.request.Request(
        url,
        headers={"User-Agent": "rusin-note-downloads", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=_MANIFEST_TIMEOUT_SECONDS) as response:
            payload = response.read(_MANIFEST_MAX_BYTES + 1)
        if len(payload) > _MANIFEST_MAX_BYTES:
            raise ValueError(f"清单超过 {_MANIFEST_MAX_BYTES} 字节上限")
        data = json.loads(payload.decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("清单不是 JSON 对象")
    except Exception as e:  # noqa: BLE001 - 网络/解析失败都按「暂无安装包」降级
        logger.warning("[警告] 拉取远程安装包清单失败（%s）: %s", url, e)
        return cached[1] if cached else {}

    with _remote_lock:
        _remote_cache[url] = (now, data)
    return data


def _read_raw() -> dict:
    if remote_enabled():
        return _fetch_remote(config.DOWNLOADS_MANIFEST_URL)
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


def _safe_asset_url(value: str) -> str:
    """校验清单给出的下载地址：仅 https、无凭据、主机在可信列表内；非法返回空串"""
    try:
        parsed = urllib.parse.urlsplit(value)
    except ValueError:
        return ""
    if parsed.scheme != "https" or parsed.username or parsed.password:
        return ""
    host = (parsed.hostname or "").lower()
    if host not in _TRUSTED_ASSET_HOSTS:
        return ""
    return value


def _declared_size(value) -> int:
    """清单声明的体积（远程模式）；非法或超限按 0 处理，仅用于展示"""
    try:
        size = int(value)
    except (TypeError, ValueError):
        return 0
    return size if 0 <= size <= config.DOWNLOADS_MAX_FILE_BYTES else 0


def _clean_artifact(raw: dict, asset_base: str = "") -> dict | None:
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

    remote_url = ""
    if asset_base:
        declared = raw.get("url")
        if isinstance(declared, str) and declared.strip():
            remote_url = _safe_asset_url(declared.strip())
            if not remote_url:
                logger.warning("安装包地址不被信任，已丢弃: %s", filename)
                return None
        else:
            remote_url = f"{asset_base}/{urllib.parse.quote(filename)}"

    return {
        "id": aid,
        "platform": platform,
        "arch": arch,
        "file": filename,
        "sha256": sha256 if _SHA256_RE.match(sha256) else "",
        "url": f"/downloads/file/{aid}",
        "remote_url": remote_url,
    }


def read_manifest() -> dict:
    """规范化清单：{version, channel, released_at, notes, artifacts}。

    本地模式只保留磁盘上真实存在、体积在上限内的产物（附实测 size）；
    远程模式以清单声明为准，只校验字段格式与下载地址。
    """
    remote = remote_enabled()
    asset_base = _asset_base() if remote else ""
    raw = _read_raw()
    version = str(raw.get("version") or "").strip()
    channel = str(raw.get("channel") or "stable").strip().lower()
    released_at = str(raw.get("released_at") or "").strip()
    notes = str(raw.get("notes") or "").strip()[:2000]
    items = raw.get("artifacts")
    artifacts = []
    seen = set()
    for item in items if isinstance(items, list) else []:
        clean = _clean_artifact(item, asset_base=asset_base)
        if clean is None or clean["id"] in seen:
            continue
        if remote:
            clean["size"] = _declared_size(item.get("size"))
        else:
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
    """本地产物绝对路径；越出安装包目录、不是普通文件或超出体积上限返回 None。

    文件名取自清单而非 URL，但清单可能被误配成绝对路径或含 .. 的相对路径，
    符号链接也可能指向目录外，故仍做 realpath 越界校验。
    远程产物（remote_url 非空）没有本地文件，直接返回 None。
    """
    if artifact.get("remote_url"):
        return None
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
