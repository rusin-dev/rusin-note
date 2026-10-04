"""反向代理 WAF 供给：OWASP CRS 自动下载 + nginx/ModSecurity 配置生成

Flask 进程内没有可用的开源 WAF 引擎，业界轻量方案是
**nginx + ModSecurity(libmodsecurity) + OWASP CoreRuleSet**。本模块负责其中
可以自动化的部分，由 ``python -m app`` 启动时调用：

    Phase 1  下载 CRS 规则集（纯文本 ``.conf``，版本 + SHA256 双锁定）到
             ``<RUSIN_DATA_DIR>/waf/crs/``
    Phase 2  生成 ModSecurity 主配置、CRS 调优文件、误报排除、nginx 站点配置
             （standalone ``nginx.conf`` 与 conf.d 片段两份）
    Phase 3  探测本机 nginx / modsecurity 模块，跑 ``nginx -t`` 校验，
             打印安装与启用命令

安全约定（与 ``app/core/plugins.py`` 同一套思路）：
- **只下载并解压文本规则**：不下载任何二进制、不执行下载内容、不安装系统包，
  默认也不 reload nginx（``waf.auto_reload`` 显式开启才执行，且需要 root）。
- 下载仅放行 ``https``；SHA256 不匹配直接丢弃（保留已装好的规则集不动）。
- tar 解压做路径穿越 / 软链 / 硬链 / 设备文件 / 解压体积与文件数上限防护，
  且不复用压缩包内的权限位（避免 setuid 之类）。
- 无服务器环境（只读盘、平台自带 WAF）与 ``waf.enabled=false`` 时完全跳过。

生成的目录结构（均在 ``RUSIN_DATA_DIR`` 下，默认 ``data/waf/``）::

    crs/rules/*.conf        OWASP CRS 规则集（下载，勿改）
    modsecurity.conf        引擎主配置（生成，每次启动覆盖）
    crs-setup.conf          CRS 调优：等级 / 阈值（生成，每次启动覆盖）
    exclusions.conf         内容型端点的误报排除（生成，每次启动覆盖）
    custom.conf             自定义规则（首次生成后**不再覆盖**）
    nginx/nginx.conf        独立运行的完整配置（生成，可 nginx -c 直接跑）
    nginx/rusin-note.conf   server 块片段（生成，可 include 进 conf.d）
    log/ tmp/ store/        ModSecurity 审计日志与临时目录
    state.json              CRS 版本 / 校验和 / 下载时间

配置项见 ``config.json`` 的 ``waf`` 段与 ``app/core/config.py`` 的 ``WAF_*``。
端到端测试：``pytest tests/test_waf.py``
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tarfile
import threading
import time
import urllib.request
import uuid
from dataclasses import dataclass, field
from urllib.parse import urlparse

from app.core import config
from app.core.logger import create_logger

logger = create_logger("waf")

# ---------- 常量 ----------
CRS_DIR = "crs"                     # 规则集安装目录（位于 waf_root 下）
STATE_FILE = "state.json"
CUSTOM_FILE = "custom.conf"         # 用户自定义规则，生成后不覆盖
DOWNLOAD_TIMEOUT = 30               # 规则集下载超时（秒，~280KB）
PROBE_TIMEOUT = 8                   # nginx -V 探测超时（秒）
NGINX_TIMEOUT = 30                  # nginx -t / -s reload 超时（要加载全部 CRS 规则，小机器偏慢）
UPDATE_CHECK_TIMEOUT = 5            # 上游版本查询超时（秒）
MAX_DOWNLOAD_BYTES = 20 * 1024 * 1024
MAX_UNPACKED_BYTES = 60 * 1024 * 1024
MAX_FILE_COUNT = 3000
USER_AGENT = "rusin-note-waf"

GENERATED_HEADER = (
    "# 本文件由 rusin-note 自动生成（python -m app），每次启动会被覆盖。\n"
    "# 自定义规则请写入同目录 custom.conf（不会被覆盖），或改 config.json 的 waf 段。\n"
)

# 内容型端点只关掉「注入类」检测：正文粘贴 SQL/JS/shell 是本站核心用法，
# 且渲染前都经 bleach 清洗；协议强制(920)/方法强制(911)/扫描器识别(913) 全程生效
_EXCLUDED_TAGS = ("attack-sqli", "attack-xss", "attack-rce", "attack-php", "attack-lfi")
_DEFAULT_EXCLUSIONS = (
    (1000, r"^/user/[^/]+/[^/]+/?$", "笔记正文保存 / 导入导出 / 图床 / 附件上传"),
    (1001, r"^/world/[^/]+/?$", "世界（公开）笔记正文编辑"),
    (1002, r"^/org/[^/]+/notes/", "组织笔记正文新建 / 编辑"),
    (1003, r"^/benben/?$", "犇犇动态正文"),
    (1004, r"^/comments/", "评论正文"),
    (1005, r"^/user/[^/]+/todos/", "工作台待办文本"),
    (1006, r"^/user/[^/]+/shares/?$", "分享链接备注"),
)

_provision_lock = threading.Lock()
_last_status: dict | None = None


class WafError(Exception):
    """WAF 供给失败（消息直接进日志与告警列表）"""


# ---------- 路径 ----------
def waf_available() -> bool:
    """WAF 供给是否启用：配置开启且非无服务器（只读盘 + 平台自带 WAF）"""
    return bool(config.WAF_ENABLED) and not config.SERVERLESS


def waf_root() -> str:
    return config.data_path("waf")


def crs_root() -> str:
    return os.path.join(waf_root(), CRS_DIR)


def crs_rules_dir() -> str:
    return os.path.join(crs_root(), "rules")


def _abs(path: str) -> str:
    """转成 nginx / ModSecurity 都能吃的绝对路径（统一正斜杠）"""
    return os.path.abspath(path).replace("\\", "/")


def _q(path: str) -> str:
    """给配置里的路径加引号（含空格也能用），并剔除引号本身防注入"""
    return '"%s"' % _abs(path).replace('"', "")


def _nginx_token(value: str, fallback: str, what: str) -> str:
    """校验要写进 nginx 配置的短标记（listen / server_name / upstream）。

    这些值来自 config.json，若含分号或换行就能注入任意 nginx 指令，
    因此只放行字母数字与 ``. - : _ * [ ]``，非法值回退默认并告警。
    """
    text = str(value or "").strip()
    if re.fullmatch(r"[A-Za-z0-9._:\-*\[\]]+", text):
        return text
    logger.warning("[WAF] %s 配置值非法（%r），已回退为 %s", what, text, fallback)
    return fallback


# ---------- 引擎探测 ----------
@dataclass
class EngineInfo:
    """本机 WAF 引擎探测结果（只读探测，不做任何安装动作）"""
    engine: str = "nginx-modsecurity"
    nginx_path: str | None = None
    nginx_version: str = ""
    modsecurity: bool = False
    hints: list = field(default_factory=list)

    @property
    def installed(self) -> bool:
        return bool(self.nginx_path) and self.modsecurity


def _run(cmd: list, timeout: int = PROBE_TIMEOUT):
    """执行只读探测命令，返回 (returncode, 合并输出)；任何异常都吞掉"""
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              timeout=timeout, check=False)
    except (OSError, subprocess.SubprocessError) as e:
        return None, f"{type(e).__name__}: {e}"
    # nginx 把 -V / -t 的结果写到 stderr
    return proc.returncode, f"{proc.stdout or ''}{proc.stderr or ''}"


def _install_hints() -> list:
    """按平台给出引擎安装命令（只打印，绝不代为执行）"""
    system = os.name
    if system == "nt":
        return ["Windows 无官方 ModSecurity 模块：请在 Linux 主机或容器内启用反代 WAF，"
                "本机可先用 waf.mode=detectiononly 生成配置备用"]
    if os.path.isfile("/etc/debian_version"):
        return ["sudo apt-get update && sudo apt-get install -y nginx libnginx-mod-http-modsecurity"]
    if os.path.isfile("/etc/redhat-release"):
        return ["sudo dnf install -y nginx nginx-mod-modsecurity"]
    if os.path.isfile("/etc/alpine-release"):
        return ["sudo apk add nginx nginx-mod-http-modsecurity"]
    return ["请通过系统包管理器安装 nginx 与 ModSecurity 模块"
            "（Debian/Ubuntu: libnginx-mod-http-modsecurity；RHEL: nginx-mod-modsecurity）"]


def detect_engine() -> EngineInfo:
    """探测 nginx 与其 modsecurity 模块（``nginx -V`` 输出里找关键字）"""
    info = EngineInfo()
    nginx = shutil.which("nginx")
    if not nginx:
        info.hints.extend(_install_hints())
        return info
    info.nginx_path = nginx
    rc, output = _run([nginx, "-V"])
    match = re.search(r"nginx/([\d.]+)", output or "") if rc is not None else None
    info.nginx_version = match.group(1) if match else ""
    info.modsecurity = "modsecurity" in (output or "").lower()
    if not info.modsecurity:
        info.hints.extend(_install_hints())
        info.hints.append("已找到 nginx 但未编译/加载 ModSecurity 模块；"
                          "若模块是动态加载，请在 nginx 主配置里加 "
                          "load_module modules/ngx_http_modsecurity_module.so;")
    return info


# ---------- 状态 ----------
def _state_path() -> str:
    return os.path.join(waf_root(), STATE_FILE)


def read_state() -> dict:
    try:
        with open(_state_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_state(state: dict) -> None:
    tmp = f"{_state_path()}.{uuid.uuid4().hex}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    os.replace(tmp, _state_path())


def installed_crs_version() -> str | None:
    """已安装 CRS 版本（规则目录不存在时视为未安装）"""
    if not os.path.isfile(os.path.join(crs_rules_dir(), "REQUEST-901-INITIALIZATION.conf")):
        return None
    return str(read_state().get("crs_version") or "") or None


# ---------- 下载 ----------
def _is_https_url(url: str) -> bool:
    """仅放行 https（拒绝 file:// 等本地协议与明文 http）"""
    try:
        return urlparse(url).scheme == "https"
    except ValueError:
        return False


def _fetch(url: str, timeout: int, max_bytes: int) -> bytes | None:
    """拉取 url 内容；协议非法 / 超时 / 超限 / 任何异常都返回 None"""
    if not _is_https_url(url):
        logger.error("[WAF] 拒绝非 https 下载地址：%s", url)
        return None
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            chunks, total = [], 0
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    logger.error("[WAF] 下载体积超过上限 %d 字节：%s", max_bytes, url)
                    return None
                chunks.append(chunk)
            return b"".join(chunks)
    except Exception as e:
        logger.error("[WAF] 下载失败 %s: %s", url, e)
        return None


def _safe_extract_tar(tar_path: str, dest: str) -> None:
    """带防护的 tar.gz 解压：拒绝绝对路径 / .. 穿越 / 链接与设备文件，限制体积与文件数"""
    total = 0
    count = 0
    with tarfile.open(tar_path, "r:gz") as tf:
        for member in tf.getmembers():
            name = member.name.replace("\\", "/")
            parts = [p for p in name.split("/") if p not in ("", ".")]
            if not parts or os.path.isabs(name) or any(p == ".." for p in parts) \
                    or ":" in parts[0]:
                raise WafError(f"压缩包内含不安全路径: {member.name!r}")
            if member.issym() or member.islnk():
                raise WafError(f"压缩包内含链接文件（可能指向解压区外）: {member.name!r}")
            if not (member.isfile() or member.isdir()):
                raise WafError(f"压缩包内含非常规文件: {member.name!r}")
            target = os.path.join(dest, *parts)
            if member.isdir():
                os.makedirs(target, exist_ok=True)
                continue
            count += 1
            if count > MAX_FILE_COUNT:
                raise WafError(f"压缩包文件数超过上限 {MAX_FILE_COUNT}")
            total += member.size
            if total > MAX_UNPACKED_BYTES:
                raise WafError(f"压缩包解压体积超过上限 {MAX_UNPACKED_BYTES} 字节")
            os.makedirs(os.path.dirname(target), exist_ok=True)
            written = 0
            src = tf.extractfile(member)
            if src is None:
                raise WafError(f"无法读取压缩包成员: {member.name!r}")
            with src, open(target, "wb") as out:
                while True:
                    chunk = src.read(65536)
                    if not chunk:
                        break
                    written += len(chunk)
                    if written > MAX_UNPACKED_BYTES:
                        raise WafError(f"文件 {member.name!r} 解压超限（疑似压缩炸弹）")
                    out.write(chunk)


def _locate_crs_root(extract_dir: str) -> str:
    """定位 CRS 根（兼容 GitHub release 的顶层版本目录）"""
    if os.path.isdir(os.path.join(extract_dir, "rules")):
        return extract_dir
    entries = [e for e in os.listdir(extract_dir) if not e.startswith(".")]
    if len(entries) == 1:
        candidate = os.path.join(extract_dir, entries[0])
        if os.path.isdir(os.path.join(candidate, "rules")):
            return candidate
    raise WafError("压缩包内未找到 CRS rules/ 目录（下载内容不是 CoreRuleSet？）")


def _read_setup_version(root: str) -> str:
    """从 CRS 自带的 crs-setup.conf.example 里读出 tx.crs_setup_version 数值。

    CRS 的 901001 规则要求该变量必须存在，否则整套规则直接 500 罢工；
    版本号编码在 4.x 与 3.x 不同，因此以随包模板为准而非自行推算。
    """
    example = os.path.join(root, "crs-setup.conf.example")
    try:
        with open(example, "r", encoding="utf-8", errors="replace") as f:
            match = re.search(r"tx\.crs_setup_version=(\d+)", f.read())
        if match:
            return match.group(1)
    except OSError:
        pass
    digits = re.findall(r"\d+", config.WAF_CRS_VERSION)[:3]
    while len(digits) < 3:
        digits.append("0")
    major, minor, patch = (int(d) for d in digits)
    return str(major * 1000 + minor * 10 + patch if major >= 4
               else major * 100 + minor * 10 + patch)


def download_crs(force: bool = False) -> dict:
    """Phase 1：确保 CRS 规则集就位。返回 {ok, version, reason, bytes}。

    已装版本与配置锁定版本一致时直接跳过（URL 是版本锁定的，重复下载无意义）；
    校验和不匹配一律拒绝并保留原规则集。
    """
    result = {"ok": False, "version": None, "reason": "", "bytes": 0}
    if not config.WAF_AUTO_DOWNLOAD and not force:
        result["reason"] = "auto-download-disabled"
        return result
    url = config.WAF_CRS_URL
    if not url:
        result["reason"] = "crs_url 未配置"
        return result

    installed = installed_crs_version()
    if installed == config.WAF_CRS_VERSION and not force:
        result.update(ok=True, version=installed, reason="already-installed")
        return result

    data = _fetch(url, DOWNLOAD_TIMEOUT, MAX_DOWNLOAD_BYTES)
    if data is None:
        result["reason"] = "下载失败（详见日志）"
        return result
    result["bytes"] = len(data)

    digest = hashlib.sha256(data).hexdigest()
    if config.WAF_VERIFY_CHECKSUM:
        expected = config.WAF_CRS_SHA256
        if not expected:
            result["reason"] = "waf.crs_sha256 为空，已拒绝下载（请锁定校验和）"
            logger.error("[WAF] %s", result["reason"])
            return result
        if digest != expected:
            result["reason"] = f"SHA256 校验失败（期望 {expected[:12]}…，实际 {digest[:12]}…）"
            logger.error("[WAF] %s：已丢弃下载内容，保留原有规则集", result["reason"])
            return result
    else:
        logger.warning("[WAF] waf.verify_checksum=false：未校验下载内容（%s）", digest[:16])

    os.makedirs(waf_root(), exist_ok=True)
    staging = os.path.join(waf_root(), f".tmp-{uuid.uuid4().hex}")
    tar_path = staging + ".tar.gz"
    try:
        with open(tar_path, "wb") as f:
            f.write(data)
        os.makedirs(staging, exist_ok=True)
        _safe_extract_tar(tar_path, staging)
        root = _locate_crs_root(staging)
        setup_version = _read_setup_version(root)

        # 原子换装：先把旧目录改名，换装失败可回滚，避免规则集半残
        target = crs_root()
        backup = None
        if os.path.isdir(target):
            backup = os.path.join(waf_root(), f".old-{uuid.uuid4().hex}")
            os.rename(target, backup)
        try:
            os.rename(root, target)
        except OSError:
            if backup:
                os.rename(backup, target)
            raise
        if backup:
            shutil.rmtree(backup, ignore_errors=True)

        _write_state({
            "crs_version": config.WAF_CRS_VERSION,
            "sha256": digest,
            "source_url": url,
            "crs_setup_version": setup_version,
            "downloaded_at": int(time.time()),
        })
        result.update(ok=True, version=config.WAF_CRS_VERSION, reason="downloaded")
        logger.info("[WAF] OWASP CRS %s 规则集安装完成（%d 字节，sha256=%s…）",
                    config.WAF_CRS_VERSION, len(data), digest[:12])
        return result
    except (WafError, OSError, tarfile.TarError) as e:
        result["reason"] = f"安装失败: {e}"
        logger.error("[WAF] CRS 安装失败: %s", e)
        return result
    finally:
        shutil.rmtree(staging, ignore_errors=True)
        try:
            os.remove(tar_path)
        except OSError:
            pass


def _version_tuple(value: str) -> tuple:
    return tuple(int(p) for p in re.findall(r"\d+", str(value))[:3]) or (0,)


def check_crs_update() -> str | None:
    """查询上游最新 CRS 版本，仅提示不自动升级。

    校验和是人工锁定的安全边界，自动切版本等于放弃它——所以这里只在
    发现新版时记一条日志，由管理员改 waf.crs_version / crs_url / crs_sha256。
    """
    match = re.match(r"^https://github\.com/([^/]+)/([^/]+)/releases/download/",
                     config.WAF_CRS_URL)
    if not match:
        return None
    api = f"https://api.github.com/repos/{match.group(1)}/{match.group(2)}/releases/latest"
    data = _fetch(api, UPDATE_CHECK_TIMEOUT, 512 * 1024)
    if not data:
        return None
    try:
        tag = str(json.loads(data.decode("utf-8", "replace")).get("tag_name") or "")
    except ValueError:
        return None
    latest = tag.lstrip("vV").strip()
    if not latest:
        return None
    try:
        if _version_tuple(latest) > _version_tuple(config.WAF_CRS_VERSION):
            logger.info("[WAF] 上游 CRS 已更新到 %s（当前锁定 %s）：如要升级请同步修改 "
                        "waf.crs_version / crs_url / crs_sha256", latest, config.WAF_CRS_VERSION)
            return latest
    except Exception:
        pass
    return None


# ---------- 配置渲染 ----------
def _unicode_mapping_path() -> str | None:
    """找 libmodsecurity 自带的 unicode.mapping（CRS 的 t:utf8toUnicode 需要它）"""
    candidates = [
        "/etc/modsecurity/unicode.mapping",
        "/usr/local/modsecurity/unicode.mapping",
        "/etc/nginx/modsecurity/unicode.mapping",
        os.path.join(waf_root(), "unicode.mapping"),
    ]
    for path in candidates:
        if os.path.isfile(path):
            return path
    return None


def render_modsecurity_conf() -> str:
    body_limit = config.WAF_BODY_LIMIT_BYTES
    engine = "On" if config.WAF_MODE == "on" else "DetectionOnly"
    lines = [
        GENERATED_HEADER.rstrip("\n"),
        "",
        "# ---- 引擎 ----",
        f"SecRuleEngine {engine}",
        "SecRequestBodyAccess On",
        f"SecRequestBodyLimit {body_limit}",
        # 笔记正文是 urlencoded「无文件请求体」，此值须与 SecRequestBodyLimit 同值，否则大笔记先进 Flask 就被 413
        f"SecRequestBodyNoFilesLimit {body_limit}",
        "SecRequestBodyLimitAction Reject",
        "SecArgumentSeparator &",
        "SecCookieFormat 0",
        "SecPcreMatchLimit 100000",
        "SecPcreMatchLimitRecursion 100000",
        f"SecTmpDir {_q(os.path.join(waf_root(), 'tmp'))}",
        f"SecDataDir {_q(os.path.join(waf_root(), 'store'))}",
    ]
    mapping = _unicode_mapping_path()
    if mapping:
        lines.append(f"SecUnicodeMapFile {_q(mapping)} 201209")
    else:
        lines.append("# 未找到 libmodsecurity 的 unicode.mapping，t:utf8toUnicode 会退化；")
        lines.append("# 如需完整 UTF-8 归一化，把该文件放到 /etc/modsecurity/ 下再重启。")
    if config.WAF_RESPONSE_INSPECTION:
        lines += [
            "",
            "# ---- 出站响应体检测（waf.response_inspection=true）----",
            "SecResponseBodyAccess On",
            "SecResponseBodyMimeType text/plain text/html application/json",
            f"SecResponseBodyLimit {body_limit}",
            "SecResponseBodyLimitAction ProcessPartial",
        ]
    else:
        lines += [
            "",
            "# 出站响应体检测默认关闭：本站渲染用户 Markdown/代码，误报多且耗 CPU。",
            "SecResponseBodyAccess Off",
        ]
    lines += [
        "",
        "# ---- 审计日志（只记被拦截或 4xx/5xx 的请求）----",
        "SecDebugLevel 0",
        "SecAuditEngine RelevantOnly",
        'SecAuditLogRelevantStatus "^(?:5|4(?!04))"',
        "SecAuditLogParts ABIJDEFHZ",
        "SecAuditLogType Serial",
        f"SecAuditLog {_q(os.path.join(waf_root(), 'log', 'audit.log'))}",
        "",
        "# ---- CRS 异常评分模式：规则只打分，阻断由 CRS 的 949110/959100 决定 ----",
        'SecDefaultAction "phase:1,log,auditlog,pass"',
        'SecDefaultAction "phase:2,log,auditlog,pass"',
        "",
        "# ---- 规则加载顺序（不可调换：排除规则必须在 CRS 之前生效）----",
        f"Include {_q(os.path.join(waf_root(), 'crs-setup.conf'))}",
        f"Include {_q(os.path.join(waf_root(), 'exclusions.conf'))}",
        f"Include {_q(os.path.join(crs_rules_dir(), '*.conf'))}",
        f"Include {_q(os.path.join(waf_root(), CUSTOM_FILE))}",
        "",
    ]
    return "\n".join(lines)


def render_crs_setup_conf() -> str:
    state = read_state()
    setup_version = str(state.get("crs_setup_version") or _read_setup_version(crs_root()))
    ver = config.WAF_CRS_VERSION or "4.0.0"
    head = f"    tag:'OWASP_CRS',\\\n    ver:'OWASP_CRS/{ver}',\\\n"

    def action(rule_id: int, setvars: str) -> str:
        body = ",\\\n".join(f"    {v}" for v in setvars.split("|"))
        return (f"SecAction \\\n    \"id:{rule_id},\\\n    phase:1,\\\n    pass,\\\n"
                f"    t:none,\\\n    nolog,\\\n{head}{body}\"")

    parts = [
        GENERATED_HEADER.rstrip("\n"),
        "",
        f"# CRS 检测/拦截等级（waf.paranoia_level={config.WAF_PARANOIA_LEVEL}）",
        action(900000, f"setvar:tx.blocking_paranoia_level={config.WAF_PARANOIA_LEVEL}"),
        action(900001, f"setvar:tx.detection_paranoia_level={config.WAF_PARANOIA_LEVEL}"),
        "",
        "# 异常分阈值：单条 CRITICAL 记 5 分，达到阈值即触发阻断",
        action(900110,
               f"setvar:tx.inbound_anomaly_score_threshold={config.WAF_INBOUND_THRESHOLD}|"
               f"setvar:tx.outbound_anomaly_score_threshold={config.WAF_OUTBOUND_THRESHOLD}"),
        "",
        "# nginx 拿不到异常分变量，按 CRS 建议用 reporting_level=5 记进审计日志",
        action(900115, "setvar:tx.reporting_level=5"),
        "",
        "# 必须最后声明：CRS 的 901001 规则检查该变量，缺失则整套规则拒绝工作",
        action(900990, f"setvar:tx.crs_setup_version={setup_version}"),
        "",
    ]
    return "\n".join(parts)


def render_exclusions_conf() -> str:
    lines = [
        GENERATED_HEADER.rstrip("\n"),
        "",
        "# 内容型端点的注入类误报排除。",
        "# 本站的核心用法就是把 SQL / JS / shell 片段当笔记存起来，这些正文渲染前",
        "# 都会经 bleach 清洗（utils.render_markdown_html），不是可执行输入；",
        "# 不排除的话「粘贴一段代码」会被 CRS 判成攻击直接 403。",
        "# 注意：只关掉注入类 tag，协议强制(920)/方法强制(911)/扫描器识别(913)",
        "# 以及全部出站规则仍然生效。关掉本节：waf.default_exclusions=false。",
        "",
    ]
    if not config.WAF_DEFAULT_EXCLUSIONS:
        lines += ["# waf.default_exclusions=false：未生成任何排除规则。", ""]
        return "\n".join(lines)
    ctl = "".join(f",\\\n    ctl:ruleRemoveByTag={tag}" for tag in _EXCLUDED_TAGS)
    for rule_id, pattern, comment in _DEFAULT_EXCLUSIONS:
        lines += [
            f"# {comment}",
            "SecRule REQUEST_FILENAME \"@rx %s\" \\" % pattern,
            f"    \"id:{rule_id},\\",
            "    phase:1,\\",
            "    pass,\\",
            "    nolog,\\",
            "    t:none,\\",
            "    tag:'rusin-note-exclusion'%s\"" % ctl,
            "",
        ]
    return "\n".join(lines)


def _proxy_location() -> str:
    upstream = _nginx_token(config.WAF_UPSTREAM, "127.0.0.1", "waf.upstream")
    port = max(1, min(65535, int(config.WAF_UPSTREAM_PORT or 8080)))
    return "\n".join([
        "    location / {",
        f"        proxy_pass http://{upstream}:{port};",
        "        proxy_http_version 1.1;",
        "        proxy_set_header Host              $host;",
        "        proxy_set_header X-Real-IP         $remote_addr;",
        "        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;",
        "        proxy_set_header X-Forwarded-Proto $scheme;",
        "        # 附件下载是流式长连接（app/core/concurrency.py 的单用户并发闸门），",
        "        # 关缓冲 + 放宽超时，避免 nginx 提前掐断慢速下载",
        "        proxy_buffering off;",
        "        proxy_request_buffering off;",
        "        proxy_read_timeout 300s;",
        "        proxy_send_timeout 300s;",
        "    }",
    ])


def render_site_conf() -> str:
    listen = _nginx_token(config.WAF_LISTEN, "80", "waf.listen")
    server_name = _nginx_token(config.WAF_SERVER_NAME, "_", "waf.server_name")
    return "\n".join([
        GENERATED_HEADER.rstrip("\n"),
        "# 可作为 server 块 include 进现有 nginx（conf.d/*.conf），",
        "# 也可由同目录 nginx.conf 独立运行。",
        "",
        "server {",
        f"    listen {listen};",
        f"    server_name {server_name};",
        "",
        "    modsecurity on;",
        f"    modsecurity_rules_file {_q(os.path.join(waf_root(), 'modsecurity.conf'))};",
        "",
        f"    client_max_body_size {config.WAF_BODY_LIMIT_BYTES};",
        "",
        _proxy_location(),
        "}",
        "",
    ])


def render_standalone_conf() -> str:
    root = _abs(waf_root())
    return "\n".join([
        GENERATED_HEADER.rstrip("\n"),
        f"# 独立运行：sudo nginx -c {root}/nginx/nginx.conf",
        f"# 只校验：      nginx -t -c {root}/nginx/nginx.conf",
        "# 若 ModSecurity 是动态模块且发行版未自动加载，取消下一行注释并改成实际路径：",
        "#load_module modules/ngx_http_modsecurity_module.so;",
        "",
        "worker_processes auto;",
        f'pid        "{root}/nginx.pid";',
        f'error_log  "{root}/log/nginx-error.log" warn;',
        "",
        "events {",
        "    worker_connections 1024;",
        "}",
        "",
        "http {",
        f'    access_log "{root}/log/nginx-access.log";',
        "",
        "    # 独立运行时系统临时目录未必可写，统一指到数据目录下",
        f'    client_body_temp_path "{root}/tmp/client_body";',
        f'    proxy_temp_path       "{root}/tmp/proxy";',
        f'    fastcgi_temp_path     "{root}/tmp/fastcgi";',
        f'    uwsgi_temp_path       "{root}/tmp/uwsgi";',
        f'    scgi_temp_path        "{root}/tmp/scgi";',
        "",
        f'    include "{root}/nginx/rusin-note.conf";',
        "}",
        "",
    ])


CUSTOM_TEMPLATE = """# 自定义 ModSecurity / CRS 规则（本文件由 rusin-note 生成一次，之后不会覆盖）
#
# 加载时机在 CRS 规则之后，适合做「按命中结果再放行」的调优；
# 需要在 CRS 之前生效的排除规则请写进 exclusions.conf 的同类位置，
# 或直接把规则加到 config.json 的 waf 段之外的部署脚本里。
#
# 规则 id 请使用 1100-9999（1000-1099 已被自动生成的排除规则占用）。
# 例：放行监控探活
# SecRule REMOTE_ADDR "@ipMatch 10.0.0.0/8" \\
#     "id:1100,phase:1,pass,nolog,ctl:ruleEngine=Off"
"""


def _write_if_changed(path: str, text: str) -> bool:
    """内容不同才落盘（避免每次启动都改动 mtime）"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            if f.read() == text:
                return False
    except OSError:
        pass
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.{uuid.uuid4().hex}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)
    return True


def render_configs() -> list:
    """Phase 2：生成全部配置文件，返回本次实际写入的路径列表"""
    root = waf_root()
    for sub in ("log", "tmp", "store", "nginx"):
        os.makedirs(os.path.join(root, sub), exist_ok=True)

    targets = [
        (os.path.join(root, "modsecurity.conf"), render_modsecurity_conf()),
        (os.path.join(root, "crs-setup.conf"), render_crs_setup_conf()),
        (os.path.join(root, "exclusions.conf"), render_exclusions_conf()),
        (os.path.join(root, "nginx", "rusin-note.conf"), render_site_conf()),
        (os.path.join(root, "nginx", "nginx.conf"), render_standalone_conf()),
    ]
    written = []
    for path, text in targets:
        if _write_if_changed(path, text):
            written.append(_abs(path))
    # 用户自定义规则文件：只在缺失时创建，绝不覆盖
    custom = os.path.join(root, CUSTOM_FILE)
    if not os.path.isfile(custom):
        _write_if_changed(custom, CUSTOM_TEMPLATE)
        written.append(_abs(custom))
    return written


# ---------- 校验与生效 ----------
def validate_nginx(engine: EngineInfo) -> tuple:
    """跑 ``nginx -t -c <standalone>``（只读校验，不改系统状态）"""
    if not engine.nginx_path:
        return False, "未找到 nginx，跳过校验"
    conf = _abs(os.path.join(waf_root(), "nginx", "nginx.conf"))
    rc, output = _run([engine.nginx_path, "-t", "-c", conf, "-p", _abs(waf_root())],
                      timeout=NGINX_TIMEOUT)
    text = (output or "").strip()
    if rc == 0:
        return True, "nginx -t 通过"
    if "unknown directive" in text.lower() and "modsecurity" in text.lower():
        text += ("\n提示：nginx 未加载 ModSecurity 模块。安装模块包，或在 nginx.conf 顶部"
                 "取消 load_module 那行注释（路径见 `nginx -V` 输出）。")
    return False, text


def reload_nginx(engine: EngineInfo) -> tuple:
    """``nginx -s reload``：仅在 waf.auto_reload=true 时调用（需要 root）。

    不带 ``-c``，因此 reload 的是系统默认配置那个实例——对应「把
    ``nginx/rusin-note.conf`` 链进 /etc/nginx/conf.d/」的用法；若是用
    ``nginx -c <standalone>`` 独立跑的实例，请自行 reload。
    """
    if not engine.nginx_path:
        return False, "未找到 nginx"
    rc, output = _run([engine.nginx_path, "-s", "reload"], timeout=NGINX_TIMEOUT)
    return rc == 0, (output or "").strip()


# ---------- 主流程 ----------
def _proxy_trust_warnings() -> list:
    """反代后应用能否看到真实客户端 IP —— 这直接决定限流是否会误伤全站"""
    warnings = []
    if not config.TRUST_PROXY_HEADERS:
        warnings.append(
            "config.json 的 trust_proxy_headers=false：经 nginx 反代后应用只会看到 "
            f"{config.WAF_UPSTREAM}，全站每 IP 限流会把所有用户算成同一个人并集体 429。"
            "请把 trust_proxy_headers 置 true，并确认 trusted_proxies 覆盖反代地址。")
        return warnings
    from app.core.ip_utils import ip_in_any
    upstream = config.WAF_UPSTREAM
    if upstream and not ip_in_any(upstream, config.TRUSTED_PROXIES):
        warnings.append(
            f"waf.upstream={upstream} 不在 trusted_proxies 内：应用会丢弃 nginx 传来的 "
            "X-Forwarded-For / X-Real-IP，限流与审计日志将只记录反代地址。"
            "请把该地址或网段加入 trusted_proxies。")
    return warnings


def provision_waf(force_download: bool = False) -> dict:
    """启动时的 WAF 供给入口：下载规则集 + 生成配置 + 探测校验。

    任何失败都不抛出——WAF 是纵深防御的可选一层，不能因为它挂掉就不让应用启动。
    """
    global _last_status
    with _provision_lock:
        status = {
            "enabled": bool(config.WAF_ENABLED),
            "available": waf_available(),
            "mode": config.WAF_MODE,
            "crs": {}, "engine": {}, "files": [],
            "warnings": [], "next_steps": [], "ready": False,
        }
        _last_status = status
        if not status["enabled"]:
            status["skipped"] = "disabled"
            return status
        if config.SERVERLESS:
            status["skipped"] = "serverless"
            status["warnings"].append("无服务器环境（只读文件系统、平台自带 WAF），已跳过 WAF 供给")
            return status

        try:
            os.makedirs(waf_root(), exist_ok=True)
            status["crs"] = download_crs(force=force_download)
            if not status["crs"].get("ok"):
                status["warnings"].append(f"CRS 规则集未就位：{status['crs'].get('reason')}")
            if status["crs"].get("reason") == "already-installed":
                state = read_state()
                if time.time() - float(state.get("downloaded_at") or 0) > config.WAF_UPDATE_STALE_SECONDS:
                    check_crs_update()

            status["files"] = render_configs()
            engine = detect_engine()
            status["engine"] = {
                "engine": engine.engine,
                "nginx_path": engine.nginx_path,
                "nginx_version": engine.nginx_version,
                "modsecurity": engine.modsecurity,
                "installed": engine.installed,
                "hints": list(engine.hints),
            }
            status["warnings"].extend(_proxy_trust_warnings())

            conf = _abs(os.path.join(waf_root(), "nginx", "nginx.conf"))
            site = _abs(os.path.join(waf_root(), "nginx", "rusin-note.conf"))
            enable_steps = [
                f"sudo nginx -t -c {conf}",
                "sudo systemctl reload nginx   "
                f"（或把 {site} 链到 /etc/nginx/conf.d/ 后 reload）",
            ]
            if not engine.installed:
                status["warnings"].extend(engine.hints)
                status["next_steps"].append(f"装好引擎后校验：nginx -t -c {conf}")
            elif config.WAF_VALIDATE_CONFIG:
                ok, message = validate_nginx(engine)
                status["validate"] = {"ok": ok, "message": message}
                if not ok:
                    status["warnings"].append(f"nginx -t 校验未通过：{message}")
                elif config.WAF_AUTO_RELOAD:
                    ok, message = reload_nginx(engine)
                    status["reload"] = {"ok": ok, "message": message}
                    if not ok:
                        status["warnings"].append(f"nginx reload 失败：{message}")
                else:
                    status["next_steps"].extend(enable_steps)
            else:
                status["next_steps"].extend(enable_steps)

            if config.WAF_MODE != "on":
                status["warnings"].append("waf.mode=detectiononly：只写审计日志不拦截，"
                                          "观察 data/waf/log/audit.log 无误报后再改成 on")
            # 校验/reload 失败即视为未就绪：配置生成了但引擎跑不起来，不能报「ready」
            checked_ok = status.get("validate", {}).get("ok", True)
            reloaded_ok = status.get("reload", {}).get("ok", True)
            status["ready"] = bool(status["crs"].get("ok") and engine.installed
                                   and checked_ok and reloaded_ok)
            if status["ready"]:
                logger.info("[WAF] 就绪：CRS %s，mode=%s，规则目录 %s",
                            status["crs"].get("version"), config.WAF_MODE, _abs(crs_rules_dir()))
            for warning in status["warnings"]:
                logger.warning("[WAF] %s", warning)
        except Exception as e:      # 供给失败不影响应用启动
            logger.error("[WAF] 供给异常: %s", e)
            status["warnings"].append(f"WAF 供给异常：{type(e).__name__}: {e}")
        _last_status = status
        return status


def waf_status() -> dict:
    """最近一次供给结果（未供给过则现场探测一次引擎，不触发下载）"""
    if _last_status is not None:
        return _last_status
    engine = detect_engine()
    return {
        "enabled": bool(config.WAF_ENABLED),
        "available": waf_available(),
        "mode": config.WAF_MODE,
        "crs": {"ok": bool(installed_crs_version()),
                "version": installed_crs_version(), "reason": "not-provisioned"},
        "engine": {"engine": engine.engine, "nginx_path": engine.nginx_path,
                   "nginx_version": engine.nginx_version,
                   "modsecurity": engine.modsecurity,
                   "installed": engine.installed, "hints": list(engine.hints)},
        "files": [], "warnings": [], "next_steps": [], "ready": False,
        "skipped": "not-provisioned",
    }


def format_status(status: dict) -> list:
    """把供给结果转成 ``python -m app`` 直接可打印的几行文本"""
    if status.get("skipped") == "disabled":
        return ["WAF：未启用（config.json 的 waf.enabled=false，或设 RUSIN_WAF=1 临时开启）"]
    lines = []
    crs = status.get("crs") or {}
    engine = status.get("engine") or {}
    lines.append("WAF：nginx + ModSecurity + OWASP CRS %s（mode=%s）"
                 % (crs.get("version") or "未安装", status.get("mode")))
    if engine.get("installed"):
        lines.append("      引擎就绪：nginx %s（%s）"
                     % (engine.get("nginx_version") or "?", engine.get("nginx_path")))
    elif engine.get("nginx_path"):
        lines.append("      引擎缺 ModSecurity 模块：%s" % engine.get("nginx_path"))
    else:
        lines.append("      未检测到 nginx")
    for hint in engine.get("hints") or []:
        lines.append("      安装：%s" % hint)
    for path in status.get("files") or []:
        lines.append("      已生成：%s" % path)
    audit = _abs(os.path.join(waf_root(), "log", "audit.log"))
    lines.append("      审计日志：%s" % audit)
    for warning in status.get("warnings") or []:
        lines.append("      [注意] %s" % warning)
    for step in status.get("next_steps") or []:
        lines.append("      下一步：%s" % step)
    return lines


def reset_state() -> None:
    """清空进程内状态（测试用）"""
    global _last_status
    _last_status = None


if __name__ == "__main__":
    # gunicorn / Lambda 部署手动供给：python -m app.core.waf [--refresh]
    import sys

    _force = any(a in sys.argv for a in ("--refresh", "--waf-refresh"))
    _status = provision_waf(force_download=_force)
    for _line in format_status(_status):
        print(_line)
    sys.exit(0 if _status.get("ready") or _status.get("skipped") == "disabled" else 1)
