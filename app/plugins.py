"""插件系统：zip 打包 → 运行时解压安装 → 蓝图加载 → 上游更新检查

插件包为 ``*.plugin.zip``，放入运行时目录（RUSIN_DATA_DIR）即可，结构：

    + desc.json          元信息（name/version/namespace/upstream_repo/auth_token…）
    + icon.ico           图标（可选，文件名须与 desc.icon 一致）
    + src/
      + __init__.py      必须定义 APP_ROUTER / OVERRIDE / ENV_VARIBLES
      + app.py           必须包含 Blueprint 实例（APP_ROUTER 可指向其它文件）
      + templates/       模板（以蓝图名为命名空间隔离，避免与主程序重名覆盖）
      + static/          静态文件（由蓝图 static_folder 提供）

加载流程：

    Phase 1  扫描运行时目录的 *.plugin.zip → 解压校验（auth_token、命名空间
             冲突、写入区域白名单）→ 安装到 plugins/<namespace>/ 并回写
             desc.json（含 auth_token 与 last_update）→ 删除 zip → 导入
             模块、注册蓝图
    Phase 2  后台线程定期检查各插件 last_update，距今超过 3 天则请求
             upstream_repo（3s 超时）；拿到新 zip 后重跑 Phase 1，新插件
             热注册，已加载插件更新文件后提示重启生效

安全约定：
- 无服务器环境（只读文件系统）不启用插件系统。
- zip 解压做路径穿越 / 炸弹（总解压体积与文件数上限）防护。
- 插件根目录只允许 desc.json、desc.icon 指定的图标与 src/，其余视为
  未声明的写入区域，直接拒绝（除非显式列入 OVERRIDE）。
- desc.json 缺少 auth_token 时必须以 ``--skip-auth`` 启动参数（或环境变量
  RUSIN_PLUGIN_SKIP_AUTH=1）放行，否则拒绝安装。
- 命名空间重复且插件未声明 OVERRIDE 时报错拒绝覆盖。
"""
import importlib.util
import json
import os
import re
import shutil
import sys
import tempfile
import threading
import time
import urllib.request
import uuid
from datetime import datetime

from flask import Blueprint, Flask, request, send_from_directory
from werkzeug.utils import safe_join

from . import config
from .logger import create_logger

logger = create_logger("plugins")

# ---------- 常量 ----------
PLUGIN_ZIP_SUFFIX = ".plugin.zip"      # 插件包固定后缀
PLUGINS_DIR = "plugins"                # 安装根目录（位于 RUSIN_DATA_DIR 下）
NAMESPACE_RE = re.compile(r"^[a-zA-Z0-9_\-]+$")   # 与笔记 ID / 用户名同一套路径安全约定
ROUTER_RE = re.compile(r"^[a-zA-Z0-9_\-]+\.py$")
DEFAULT_ROUTER = "app.py"              # src/ 下默认承载 Blueprint 的文件
# 解压防护：单插件总解压体积 / 文件数 / 更新下载体积上限
MAX_UNPACKED_BYTES = 100 * 1024 * 1024
MAX_FILE_COUNT = 5000
MAX_DOWNLOAD_BYTES = 100 * 1024 * 1024
FETCH_TIMEOUT = 3                      # 上游请求超时（秒）

_install_lock = threading.RLock()      # 安装 / 扫描共用（Phase 1 与更新线程互斥）
_loaded: dict = {}                     # namespace -> LoadedPlugin（进程级，导入一次）
_override_map: dict = {}               # "/static/dst.css" -> (namespace, "static/src.css")
_update_thread_started = False


class PluginError(Exception):
    """插件安装 / 加载失败（消息直接进错误日志）"""


class LoadedPlugin:
    """已成功导入的插件（模块只导入一次，蓝图可注册到多个 app 实例）"""

    __slots__ = ("namespace", "name", "version", "desc", "directory",
                 "blueprints", "override")

    def __init__(self, namespace, name, version, directory, blueprints, override):
        self.namespace = namespace
        self.name = name
        self.version = version
        self.directory = directory
        self.blueprints = blueprints      # list[Blueprint]
        self.override = override          # dict 或 False


def plugins_available() -> bool:
    """插件系统是否可用：配置开启且非无服务器（无服务器只读盘且无运行时目录投放渠道）"""
    return config.PLUGINS_ENABLED and not config.SERVERLESS


def plugins_root() -> str:
    return config.data_path(PLUGINS_DIR)


def list_plugins() -> list:
    """已加载插件清单（调试用）"""
    return [
        {"namespace": p.namespace, "name": p.name, "version": p.version,
         "blueprints": [bp.name for bp in p.blueprints]}
        for p in _loaded.values()
    ]


# ---------- 工具 ----------
def _skip_auth_requested() -> bool:
    """是否通过 --skip-auth 启动参数或环境变量显式放行无 auth_token 的插件"""
    if "--skip-auth" in sys.argv:
        return True
    return os.environ.get("RUSIN_PLUGIN_SKIP_AUTH", "").strip().lower() in ("1", "true", "yes")


def _format_last_update(ts: float) -> str:
    t = time.localtime(ts)
    return f"{t.tm_year}/{t.tm_mon}/{t.tm_mday}"


def _parse_last_update(value) -> float:
    """解析 last_update（"2026/8/21" 或 ISO "2026-08-21[...]"），失败按 0 处理（视为过期）"""
    if not value:
        return 0.0
    try:
        text = str(value).strip()
        if "/" in text:
            parts = [int(p) for p in text.split("/")[:3]]
            while len(parts) < 3:
                parts.append(1)
            return datetime(*parts).timestamp()
        return datetime.fromisoformat(text[:10]).timestamp()
    except (TypeError, ValueError):
        return 0.0


def _safe_rel_path(path: str) -> str | None:
    """校验插件声明的相对路径（OVERRIDE 映射、icon 等）：拒绝绝对路径与穿越"""
    if not isinstance(path, str) or not path.strip():
        return None
    normalized = path.replace("\\", "/").strip().strip("/")
    if not normalized or ":" in normalized.split("/", 1)[0]:
        return None
    parts = [p for p in normalized.split("/") if p not in ("", ".")]
    if not parts or any(p == ".." for p in parts):
        return None
    return "/".join(parts)


def _read_desc(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        desc = json.load(f)
    if not isinstance(desc, dict):
        raise PluginError("desc.json 内容必须是对象")
    return desc


def _write_desc(directory: str, desc: dict) -> None:
    with open(os.path.join(directory, "desc.json"), "w", encoding="utf-8") as f:
        json.dump(desc, f, ensure_ascii=False, indent=2)


# ---------- Phase 1：解压与安装 ----------
def _safe_extract(zip_path: str, dest: str) -> None:
    """带防护的解压：拒绝绝对路径 / .. 穿越，限制总解压体积与文件数"""
    import zipfile
    total = 0
    count = 0
    with zipfile.ZipFile(zip_path, "r") as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            name = info.filename.replace("\\", "/")
            parts = [p for p in name.split("/") if p not in ("", ".")]
            # ntpath / posixpath 双重判断，兼容 Windows 盘符路径
            if (os.path.isabs(name) or not parts
                    or any(p == ".." for p in parts)
                    or ":" in parts[0]):
                raise PluginError(f"压缩包内含不安全路径: {info.filename!r}")
            count += 1
            if count > MAX_FILE_COUNT:
                raise PluginError(f"压缩包文件数超过上限 {MAX_FILE_COUNT}")
            total += info.file_size
            if total > MAX_UNPACKED_BYTES:
                raise PluginError(f"压缩包解压体积超过上限 {MAX_UNPACKED_BYTES} 字节")
            target = os.path.join(dest, *parts)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            written = 0
            with zf.open(info) as src, open(target, "wb") as out:
                while True:
                    chunk = src.read(65536)
                    if not chunk:
                        break
                    written += len(chunk)
                    if written > MAX_UNPACKED_BYTES:
                        raise PluginError(f"文件 {info.filename!r} 解压超限（疑似压缩炸弹）")
                    out.write(chunk)


def _locate_plugin_root(extract_dir: str) -> str:
    """定位插件根（兼容 GitHub archive 风格的多余顶层目录）"""
    if os.path.isfile(os.path.join(extract_dir, "desc.json")):
        return extract_dir
    entries = [e for e in os.listdir(extract_dir) if not e.startswith(".")]
    if len(entries) == 1:
        candidate = os.path.join(extract_dir, entries[0])
        if os.path.isdir(candidate) and os.path.isfile(os.path.join(candidate, "desc.json")):
            return candidate
    raise PluginError("压缩包缺少 desc.json（插件说明文件必须位于根目录）")


def _probe_init(src_dir: str, namespace: str) -> dict:
    """执行 src/__init__.py，读取 APP_ROUTER / OVERRIDE / ENV_VARIBLES 声明"""
    init_path = os.path.join(src_dir, "__init__.py")
    if not os.path.isfile(init_path):
        raise PluginError("src/__init__.py 缺失（必须定义 APP_ROUTER / OVERRIDE / ENV_VARIBLES）")
    spec = importlib.util.spec_from_file_location(f"_plugin_probe_{namespace}", init_path)
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as e:
        raise PluginError(f"src/__init__.py 执行失败: {e}") from e

    router = getattr(module, "APP_ROUTER", DEFAULT_ROUTER)
    if not isinstance(router, str) or not ROUTER_RE.match(router.strip()):
        raise PluginError(f"APP_ROUTER 必须是形如 '{DEFAULT_ROUTER}' 的 .py 文件名")
    router = router.strip()

    override = getattr(module, "OVERRIDE", False)
    if override is not False:
        if not isinstance(override, dict) or not isinstance(override.get("source", {}), dict):
            raise PluginError("OVERRIDE 必须为 False 或含 source 映射的对象")
        source = {}
        for dst, src in override.get("source", {}).items():
            dst_rel, src_rel = _safe_rel_path(dst), _safe_rel_path(src)
            if not dst_rel or not src_rel:
                raise PluginError(f"OVERRIDE.source 含非法路径: {dst!r} -> {src!r}")
            source[dst_rel] = src_rel
        # 只要是 dict（含空对象）即视为已声明 OVERRIDE，允许覆盖同名空间
        override = {"source": source}

    env_vars = getattr(module, "ENV_VARIBLES", [])
    if not isinstance(env_vars, list) or not all(isinstance(v, str) for v in env_vars):
        raise PluginError("ENV_VARIBLES 必须是环境变量名字符串列表")

    return {"router": router, "override": override, "env_vars": env_vars}


def _install_from_zip(zip_path: str, known_namespaces: set) -> bool:
    """解压并安装单个插件包；成功返回 True。失败记错误日志并保留 zip 供修复后重试"""
    staging = os.path.join(plugins_root(), f".tmp-{uuid.uuid4().hex}")
    try:
        os.makedirs(staging, exist_ok=True)
        _safe_extract(zip_path, staging)
        root = _locate_plugin_root(staging)

        desc = _read_desc(os.path.join(root, "desc.json"))
        namespace = str(desc.get("namespace") or "").strip()
        if not NAMESPACE_RE.match(namespace):
            raise PluginError(f"desc.json 的 namespace 非法: {namespace!r}（须匹配 {NAMESPACE_RE.pattern}）")
        name = str(desc.get("name") or "").strip() or namespace
        version = str(desc.get("version") or "").strip()

        # 写入区域检查：插件根目录只允许 desc.json、声明的图标与 src/
        icon = _safe_rel_path(desc.get("icon") or "") or ""
        for entry in os.listdir(root):
            if entry == "desc.json" or entry == icon:
                continue
            if entry == "src" and os.path.isdir(os.path.join(root, "src")):
                continue
            raise PluginError(f"插件试图写入未声明的区域: {entry!r}（根目录仅允许 desc.json、图标与 src/）")

        init_decl = _probe_init(os.path.join(root, "src"), namespace)
        router_path = os.path.join(root, "src", init_decl["router"])
        if not os.path.isfile(router_path):
            raise PluginError(f"APP_ROUTER 指向的文件不存在: src/{init_decl['router']}")

        # auth_token 检查：缺失时必须显式 --skip-auth 放行
        auth_token = str(desc.get("auth_token") or "").strip()
        if not auth_token and not _skip_auth_requested():
            raise PluginError("desc.json 缺少 auth_token，拒绝安装："
                              "如确认信任该插件，请以 --skip-auth 启动参数"
                              "（或环境变量 RUSIN_PLUGIN_SKIP_AUTH=1）放行")

        # 命名空间冲突检查：已存在时，同源（upstream_repo 一致，即上游自我更新）
        # 直接放行；不同来源的插件抢占同一命名空间则必须声明 OVERRIDE
        target = os.path.join(plugins_root(), namespace)
        is_update = os.path.isdir(target)
        if is_update:
            same_origin = False
            try:
                existing = _read_desc(os.path.join(target, "desc.json"))
                same_origin = bool(existing.get("upstream_repo")) and \
                    existing.get("upstream_repo") == desc.get("upstream_repo")
            except Exception:
                pass
            if not same_origin and init_decl["override"] is False:
                raise PluginError(f"命名空间 {namespace!r} 重复（已存在其它插件），"
                                  f"且未声明 OVERRIDE，拒绝覆盖")
            if not same_origin:
                logger.warning(f"[插件] 命名空间 {namespace} 已存在，按 OVERRIDE 声明执行覆盖")
        elif namespace in known_namespaces:
            raise PluginError(f"命名空间 {namespace!r} 与本次待安装插件重复")
        known_namespaces.add(namespace)

        # 落盘：staging 与 plugins 同目录（同文件系统），rename 原子生效；
        # 覆盖更新先改名备份旧目录，失败可回滚，避免更新中途失败丢失插件
        if is_update:
            backup = os.path.join(plugins_root(), f".old-{uuid.uuid4().hex}")
            os.rename(target, backup)
            try:
                os.rename(root, target)
            except OSError:
                os.rename(backup, target)
                raise
            shutil.rmtree(backup, ignore_errors=True)
        else:
            os.rename(root, target)
        shutil.rmtree(staging, ignore_errors=True)

        # 回写 desc.json：保留 auth_token，加入更新时间（Phase 2 据此判断是否检查上游）
        stored = dict(desc)
        stored["auth_token"] = auth_token
        stored["last_update"] = _format_last_update(time.time())
        _write_desc(target, stored)

        # 解压完成，删除插件包
        try:
            os.remove(zip_path)
        except OSError as e:
            logger.error(f"[插件] 删除插件包失败 {zip_path}: {e}")

        logger.info(f"[插件] {name} {version}（namespace={namespace}）安装成功"
                    f"{'（覆盖更新，重启后完全生效）' if is_update and namespace in _loaded else ''}")
        return True
    except PluginError as e:
        logger.error(f"[插件] 安装失败 {os.path.basename(zip_path)}: {e}")
        shutil.rmtree(staging, ignore_errors=True)
        return False
    except Exception as e:
        logger.error(f"[插件] 安装异常 {os.path.basename(zip_path)}: {e}")
        shutil.rmtree(staging, ignore_errors=True)
        return False


def install_plugin_archives() -> int:
    """Phase 1 安装：扫描运行时目录下所有 *.plugin.zip 并安装，返回成功数"""
    if not plugins_available():
        return 0
    installed = 0
    with _install_lock:
        os.makedirs(plugins_root(), exist_ok=True)
        known = set()
        if os.path.isdir(plugins_root()):
            known.update(e for e in os.listdir(plugins_root())
                         if os.path.isdir(os.path.join(plugins_root(), e)))
        for fname in sorted(os.listdir(config.DATA_DIR)):
            if not fname.endswith(PLUGIN_ZIP_SUFFIX):
                continue
            zip_path = os.path.join(config.DATA_DIR, fname)
            if not os.path.isfile(zip_path):
                continue
            if _install_from_zip(zip_path, known):
                installed += 1
    return installed


# ---------- 模块导入与蓝图注册 ----------
def _import_plugin(namespace: str, directory: str) -> LoadedPlugin:
    """导入插件包与 APP_ROUTER 模块，收集其中的 Blueprint 实例"""
    src_dir = os.path.join(directory, "src")
    pkg_name = f"rusin_plugin_{namespace}"
    spec = importlib.util.spec_from_file_location(
        pkg_name, os.path.join(src_dir, "__init__.py"),
        submodule_search_locations=[src_dir])
    if spec is None or spec.loader is None:
        raise PluginError("无法构造 __init__.py 导入规格")
    pkg = importlib.util.module_from_spec(spec)
    sys.modules[pkg_name] = pkg
    try:
        spec.loader.exec_module(pkg)
    except Exception as e:
        sys.modules.pop(pkg_name, None)
        raise PluginError(f"src/__init__.py 导入失败: {e}") from e

    decl = {"router": str(getattr(pkg, "APP_ROUTER", DEFAULT_ROUTER) or DEFAULT_ROUTER),
            "override": getattr(pkg, "OVERRIDE", False),
            "env_vars": getattr(pkg, "ENV_VARIBLES", [])}
    router_file = decl["router"].strip()
    if not ROUTER_RE.match(router_file):
        raise PluginError(f"APP_ROUTER 非法: {router_file!r}")

    missing = [v for v in decl["env_vars"] if isinstance(v, str) and not os.environ.get(v)]
    if missing:
        logger.warning(f"[插件] {namespace} 声明的环境变量未设置: {', '.join(missing)}")

    router_path = os.path.join(src_dir, router_file)
    mod_name = f"{pkg_name}.{router_file[:-3]}"
    spec2 = importlib.util.spec_from_file_location(mod_name, router_path)
    router_mod = importlib.util.module_from_spec(spec2)
    sys.modules[mod_name] = router_mod
    try:
        spec2.loader.exec_module(router_mod)
    except Exception as e:
        sys.modules.pop(mod_name, None)
        raise PluginError(f"src/{router_file} 导入失败: {e}") from e

    blueprints = [v for v in vars(router_mod).values() if isinstance(v, Blueprint)]
    if not blueprints:
        raise PluginError(f"src/{router_file} 中未找到 Blueprint 实例"
                          f"（插件必须提供蓝图用于加载）")

    desc = _read_desc(os.path.join(directory, "desc.json"))
    return LoadedPlugin(namespace, desc.get("name", namespace), desc.get("version", ""),
                        directory, blueprints, decl["override"])


def _discover_and_load() -> list:
    """扫描 plugins/ 目录，导入尚未加载的插件；返回本次新导入的插件列表"""
    newly = []
    if not os.path.isdir(plugins_root()):
        return newly
    for entry in sorted(os.listdir(plugins_root())):
        directory = os.path.join(plugins_root(), entry)
        if not os.path.isdir(directory) or entry.startswith("."):
            continue
        if entry in _loaded:
            continue
        if not os.path.isfile(os.path.join(directory, "desc.json")):
            continue
        try:
            _loaded[entry] = _import_plugin(entry, directory)
            newly.append(_loaded[entry])
            logger.info(f"[插件] {entry} 加载成功"
                        f"（blueprints: {', '.join(bp.name for bp in _loaded[entry].blueprints)}）")
        except Exception as e:
            logger.error(f"[插件] {entry} 加载失败: {e}")
    _rebuild_override_map()
    return newly


def _rebuild_override_map() -> None:
    """汇总所有插件的 OVERRIDE.source：请求路径 -> (命名空间, 插件内相对路径)"""
    mapping = {}
    for plugin in _loaded.values():
        if plugin.override is False:
            continue
        source = plugin.override.get("source", {}) if isinstance(plugin.override, dict) else {}
        for dst, src in source.items():
            mapping[f"/{dst.lstrip('/')}"] = (plugin.namespace, src)
    _override_map.clear()
    _override_map.update(mapping)


def _register_on_app(app: Flask, plugin: LoadedPlugin) -> bool:
    """把插件的蓝图注册到 app；蓝图名与主程序 / 其它插件冲突时跳过并报错"""
    registered = app.extensions.setdefault("rusin_plugins", set())
    if plugin.namespace in registered:
        return True
    ok = True
    for bp in plugin.blueprints:
        if bp.name in app.blueprints:
            logger.error(f"[插件] 蓝图名 {bp.name!r} 与已注册蓝图冲突，"
                         f"插件 {plugin.namespace} 的该蓝图未加载（请插件作者改名）")
            ok = False
            continue
        # Flask 蓝图静态路由默认挂 /static/（各插件会互相覆盖、且与主站冲突），
        # 强制改写为 /<蓝图名>/static/ 实现命名空间隔离
        if bp.static_folder is not None:
            bp.static_url_path = f"/{bp.name}/static"
        try:
            app.register_blueprint(bp)
        except Exception as e:
            logger.error(f"[插件] 注册蓝图 {bp.name} 失败: {e}")
            ok = False
    if ok:
        registered.add(plugin.namespace)
    return ok


def _register_override_hook(app: Flask) -> None:
    """OVERRIDE 静态复写：命中映射的请求直接回插件文件（如主站 /static/dst.css）"""
    if "rusin_plugin_override" in app.extensions:
        return
    app.extensions["rusin_plugin_override"] = True

    @app.before_request
    def _plugin_override():
        hit = _override_map.get(request.path)
        if not hit:
            return None
        namespace, rel = hit
        src_dir = safe_join(plugins_root(), namespace, "src")
        if not src_dir:
            return None
        return send_from_directory(src_dir, rel)


def register_plugin_blueprints(app: Flask) -> None:
    """入口（由 views.register_blueprints 调用）：Phase 1 安装 + 蓝图注册。

    必须在 world_short 的 catch-all（/<id>）之前调用，否则插件的单段
    路由会被短链抢匹配。
    """
    if not plugins_available():
        return
    try:
        install_plugin_archives()
    except Exception as e:
        logger.error(f"[插件] Phase 1 安装扫描失败: {e}")
    with _install_lock:
        _discover_and_load()
        for plugin in _loaded.values():
            _register_on_app(app, plugin)
    _register_override_hook(app)


# ---------- Phase 2：上游更新检查 ----------
def _fetch_url(url: str):
    """请求 url（3s 超时），返回响应体；异常返回 None"""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "rusin-note-plugin-updater"})
        with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT) as resp:
            return resp.read(MAX_DOWNLOAD_BYTES + 1)
    except Exception:
        return None


def _download_plugin_zip(repo: str):
    """从上游仓库拉插件包：先试 repo 本身，GitHub 仓库再试 main/master 归档"""
    if not isinstance(repo, str) or not repo.strip():
        return None
    urls = [repo.strip()]
    base = repo.strip().rstrip("/")
    if "github.com" in base:
        urls += [f"{base}/archive/refs/heads/main.zip",
                 f"{base}/archive/refs/heads/master.zip"]
    for url in urls:
        data = _fetch_url(url)
        if data and len(data) <= MAX_DOWNLOAD_BYTES and data[:4] == b"PK\x03\x04":
            return data
    return None


def check_updates_once() -> int:
    """Phase 2 单轮检查：距 last_update 超过阈值（默认 3 天）的插件请求上游。

    拿到新包则落为 <namespace>.plugin.zip 交回 Phase 1。返回下载数。
    无论成功与否都刷新 last_update，避免每轮重复请求。
    """
    downloaded = 0
    root = plugins_root()
    if not os.path.isdir(root):
        return 0
    now = time.time()
    with _install_lock:
        for entry in sorted(os.listdir(root)):
            directory = os.path.join(root, entry)
            desc_path = os.path.join(directory, "desc.json")
            if not os.path.isdir(directory) or not os.path.isfile(desc_path):
                continue
            try:
                desc = _read_desc(desc_path)
            except Exception as e:
                logger.error(f"[插件] 读取 {entry}/desc.json 失败: {e}")
                continue
            if now - _parse_last_update(desc.get("last_update")) < config.PLUGIN_UPDATE_STALE_SECONDS:
                continue
            repo = desc.get("upstream_repo")
            if repo:
                data = _download_plugin_zip(repo)
                if data:
                    zip_path = config.data_path(f"{entry}{PLUGIN_ZIP_SUFFIX}")
                    try:
                        with open(zip_path, "wb") as f:
                            f.write(data)
                        downloaded += 1
                        logger.info(f"[插件] {entry} 从上游 {repo} 拉到更新包")
                    except OSError as e:
                        logger.error(f"[插件] {entry} 更新包写入失败: {e}")
                else:
                    logger.warning(f"[插件] {entry} 上游 {repo} 未提供可用更新包（3s 超时或非 zip）")
            desc["last_update"] = _format_last_update(now)
            try:
                _write_desc(directory, desc)
            except OSError as e:
                logger.error(f"[插件] {entry} 回写 last_update 失败: {e}")
    return downloaded


def _update_loop(app: Flask) -> None:
    while True:
        time.sleep(config.PLUGIN_UPDATE_CHECK_INTERVAL)
        try:
            if check_updates_once() > 0:
                # 全部检查完毕后重跑 Phase 1，新插件热注册
                install_plugin_archives()
                with _install_lock:
                    newly = _discover_and_load()
                for plugin in newly:
                    _hot_register(app, plugin)
        except Exception as e:
            logger.error(f"[插件] 更新检查线程异常: {e}")


def _hot_register(app: Flask, plugin: LoadedPlugin) -> None:
    """运行中热注册：Flask 默认禁止首个请求后调用 setup 方法，这里临时放开
    （仅追加路由；Werkzeug 2.2+ 的 Map 更新自带锁）。失败提示重启生效。"""
    if not getattr(app, "_got_first_request", False):
        _register_on_app(app, plugin)
        return
    try:
        app._got_first_request = False
        if _register_on_app(app, plugin):
            logger.info(f"[插件] {plugin.namespace} 已热加载")
    except Exception as e:
        logger.error(f"[插件] {plugin.namespace} 热注册失败（重启后生效）: {e}")
    finally:
        app._got_first_request = True


def start_update_thread(app: Flask) -> None:
    """启动 Phase 2 更新检查守护线程（一次性；SERVERLESS / TESTING 不启动）"""
    global _update_thread_started
    if not plugins_available() or _update_thread_started:
        return
    _update_thread_started = True
    threading.Thread(target=_update_loop, args=(app,),
                     daemon=True, name="rusin-plugin-updater").start()
    logger.info("[插件] 更新检查线程已启动（每 %d 小时检查一次，超过 %d 天未更新才请求上游）",
                config.PLUGIN_UPDATE_CHECK_INTERVAL // 3600,
                config.PLUGIN_UPDATE_STALE_SECONDS // 86400)
