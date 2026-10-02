"""反向代理 WAF（nginx + ModSecurity + OWASP CRS）供给流程 端到端测试。

覆盖四部分：

1. 启用判定：``waf.enabled=false`` / ``SERVERLESS`` 时完全跳过（不落盘、不联网）。
2. CRS 下载：SHA256 不匹配即拒绝并保留现场、非 https 地址拒绝、tar 路径穿越 /
   软链 / 压缩炸弹防护、幂等（锁定版本一致时不重复下载）。
3. 配置渲染：``SecRuleEngine`` 随 mode 切换、Include 顺序（排除规则必须在 CRS
   之前）、``crs_setup_version`` 必须写入、``custom.conf`` 不被覆盖、
   nginx 短标记的指令注入防护。
4. 供给编排：引擎缺失时不抛异常、反代信任链告警（否则全站限流会误伤）、
   ``format_status`` 可直接打印。

全程离线：``waf._fetch`` 与 ``waf._run`` 由 monkeypatch 替换，不触网、不调子进程。

运行：``pytest tests/test_waf.py``
"""
from __future__ import annotations

import hashlib
import io
import json
import logging
import os
import shutil
import subprocess
import sys
import tarfile

import pytest

from app.core import config, ip_utils
from app.core import waf
from support import expect

logger = logging.getLogger("rusin.tests.waf")

CRS_VERSION = "4.29.0"
CRS_URL = ("https://github.com/coreruleset/coreruleset/releases/download/"
           f"v{CRS_VERSION}/coreruleset-{CRS_VERSION}-minimal.tar.gz")


# ---------------------------------------------------------------------------
# 构造离线替身
# ---------------------------------------------------------------------------
def _add_file(tf: tarfile.TarFile, name: str, text: str) -> None:
    data = text.encode("utf-8")
    info = tarfile.TarInfo(name)
    info.size = len(data)
    tf.addfile(info, io.BytesIO(data))


def build_crs_tar(version: str = CRS_VERSION, setup_version: str = "4290") -> bytes:
    """构造一个结构与官方 minimal 包一致的假 CRS tar.gz"""
    top = f"coreruleset-{version}"
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        _add_file(tf, f"{top}/LICENSE", "Apache-2.0\n")
        _add_file(tf, f"{top}/crs-setup.conf.example",
                  "# template\nSecAction \\\n"
                  f'    "id:900990, setvar:tx.crs_setup_version={setup_version}"\n')
        _add_file(tf, f"{top}/rules/REQUEST-901-INITIALIZATION.conf", "# init\n")
        _add_file(tf, f"{top}/rules/REQUEST-942-APPLICATION-ATTACK-SQLI.conf", "# sqli\n")
        _add_file(tf, f"{top}/rules/RESPONSE-955-WEB-SHELLS.conf", "# outbound\n")
    return buf.getvalue()


def build_evil_tar(kind: str) -> bytes:
    """构造含危险成员的 tar.gz：路径穿越 / 软链 / 非常规文件"""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        _add_file(tf, "coreruleset-evil/rules/REQUEST-901-INITIALIZATION.conf", "# ok\n")
        if kind == "traversal":
            _add_file(tf, "coreruleset-evil/rules/../../escaped.conf", "SecRuleEngine Off\n")
        elif kind == "symlink":
            link = tarfile.TarInfo("coreruleset-evil/rules/evil.conf")
            link.type = tarfile.SYMTYPE
            link.linkname = "/etc/passwd"
            tf.addfile(link)
        elif kind == "device":
            dev = tarfile.TarInfo("coreruleset-evil/rules/zero")
            dev.type = tarfile.CHRTYPE
            dev.devmajor, dev.devminor = 1, 3
            tf.addfile(dev)
    return buf.getvalue()


def build_tar(entries: dict) -> bytes:
    """按 {名字: 内容} 构造 tar.gz（用于文件数 / 体积上限测试）"""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for name, text in entries.items():
            _add_file(tf, name, text)
    return buf.getvalue()


@pytest.fixture
def clean_waf(data_dir):
    """每个测试方法一个干净的 waf 目录"""
    waf.reset_state()
    shutil.rmtree(waf.waf_root(), ignore_errors=True)
    yield waf.waf_root()
    shutil.rmtree(waf.waf_root(), ignore_errors=True)


@pytest.fixture
def waf_on(monkeypatch, clean_waf):
    """打开 WAF 并把下载/探测替换成离线替身，返回替身控制器"""
    payload = {"blob": build_crs_tar(), "fetches": [], "run": (0, "nginx: test is successful")}
    monkeypatch.setattr(config, "WAF_ENABLED", True)
    monkeypatch.setattr(config, "WAF_AUTO_DOWNLOAD", True)
    monkeypatch.setattr(config, "WAF_CRS_VERSION", CRS_VERSION)
    monkeypatch.setattr(config, "WAF_CRS_URL", CRS_URL)
    monkeypatch.setattr(config, "WAF_CRS_SHA256", hashlib.sha256(payload["blob"]).hexdigest())
    monkeypatch.setattr(config, "WAF_VERIFY_CHECKSUM", True)
    monkeypatch.setattr(config, "WAF_MODE", "on")
    monkeypatch.setattr(config, "SERVERLESS", False)
    monkeypatch.setattr(config, "WAF_VALIDATE_CONFIG", True)
    monkeypatch.setattr(config, "WAF_AUTO_RELOAD", False)
    monkeypatch.setattr(config, "WAF_DEFAULT_EXCLUSIONS", True)
    monkeypatch.setattr(config, "WAF_RESPONSE_INSPECTION", False)
    monkeypatch.setattr(config, "TRUST_PROXY_HEADERS", True)
    monkeypatch.setattr(config, "TRUSTED_PROXIES", ["loopback", "private"])
    monkeypatch.setattr(config, "WAF_UPSTREAM", "127.0.0.1")
    ip_utils.clear_caches()

    def fake_fetch(url, timeout, max_bytes):
        payload["fetches"].append(url)
        if not waf._is_https_url(url):
            return None
        blob = payload["blob"]
        return blob if len(blob) <= max_bytes else None

    def fake_run(cmd, timeout=waf.PROBE_TIMEOUT):
        payload.setdefault("cmds", []).append(list(cmd))
        return payload["run"]

    monkeypatch.setattr(waf, "_fetch", fake_fetch)
    monkeypatch.setattr(waf, "_run", fake_run)
    return payload


def fake_engine(installed: bool = True, modsecurity: bool = True):
    return waf.EngineInfo(engine="nginx-modsecurity", nginx_path="/usr/sbin/nginx",
                          nginx_version="1.24.0", modsecurity=modsecurity,
                          hints=[] if installed else waf._install_hints())


# ---------------------------------------------------------------------------
class TestAvailability:
    """开关与平台判定：不该动的时候一个字节都不能写。"""

    def test_disabled_by_default(self, monkeypatch, clean_waf):
        logger.info("=== waf.enabled=false：跳过供给 ===")
        monkeypatch.setattr(config, "WAF_ENABLED", False)
        monkeypatch.setattr(config, "SERVERLESS", False)
        status = waf.provision_waf()
        expect(status["skipped"] == "disabled", "标记为 disabled")
        expect(not os.path.isdir(waf.waf_root()), "未创建 waf 目录")
        expect("未启用" in waf.format_status(status)[0], "状态行提示未启用及开启方式")

    def test_skipped_on_serverless(self, monkeypatch, clean_waf):
        logger.info("=== 无服务器环境：只读盘 + 平台自带 WAF ===")
        monkeypatch.setattr(config, "WAF_ENABLED", True)
        monkeypatch.setattr(config, "SERVERLESS", True)
        status = waf.provision_waf()
        expect(status["skipped"] == "serverless", "标记为 serverless")
        expect(not os.path.isdir(waf.waf_root()), "未创建 waf 目录")
        expect(status["warnings"], "给出跳过原因告警")

    def test_env_override_enables(self, clean_waf):
        logger.info("=== RUSIN_WAF=1 可临时开启（子进程验证，避免 reload 污染其它测试）===")
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        code = "from app.core import config; print(config.WAF_ENABLED, config.WAF_MODE)"
        for env_extra, expected in (({"RUSIN_WAF": "1"}, "True"), ({}, "False")):
            env = dict(os.environ, RUSIN_DATA_DIR=str(clean_waf))
            env.pop("RUSIN_WAF", None)
            env.update(env_extra)
            proc = subprocess.run([sys.executable, "-c", code], capture_output=True,
                                  text=True, env=env, cwd=root, timeout=60)
            expect(proc.returncode == 0, f"子进程正常退出（{env_extra or '无环境变量'}）")
            expect(proc.stdout.strip().startswith(expected),
                   f"RUSIN_WAF={env_extra.get('RUSIN_WAF', '未设置')} → WAF_ENABLED={expected}")


# ---------------------------------------------------------------------------
class TestDownload:
    """CRS 下载与解压防护。"""

    def test_happy_path(self, waf_on, clean_waf):
        logger.info("=== 正常下载：校验通过并落盘 ===")
        result = waf.download_crs()
        expect(result["ok"] and result["reason"] == "downloaded", "下载成功")
        expect(result["version"] == CRS_VERSION, f"版本记录为 {CRS_VERSION}")
        expect(os.path.isfile(os.path.join(waf.crs_rules_dir(),
                                          "REQUEST-901-INITIALIZATION.conf")), "规则文件已就位")
        state = waf.read_state()
        expect(state["crs_version"] == CRS_VERSION, "state.json 记录版本")
        expect(state["crs_setup_version"] == "4290", "从随包模板提取 crs_setup_version")
        expect(len(state["sha256"]) == 64, "state.json 记录校验和")
        expect(len(waf_on["fetches"]) == 1, "只发起一次下载")

    def test_idempotent(self, waf_on, clean_waf):
        logger.info("=== 幂等：锁定版本已装则不再下载 ===")
        waf.download_crs()
        before = len(waf_on["fetches"])
        result = waf.download_crs()
        expect(result["reason"] == "already-installed", "第二次直接跳过")
        expect(len(waf_on["fetches"]) == before, "未再发起网络请求")

    def test_force_redownload(self, waf_on, clean_waf):
        logger.info("=== --waf-refresh：强制重新下载 ===")
        waf.download_crs()
        before = len(waf_on["fetches"])
        result = waf.download_crs(force=True)
        expect(result["reason"] == "downloaded", "强制重装成功")
        expect(len(waf_on["fetches"]) == before + 1, "重新发起了一次下载")

    def test_checksum_mismatch_rejected(self, monkeypatch, waf_on, clean_waf):
        logger.info("=== SHA256 不匹配：拒绝安装 ===")
        monkeypatch.setattr(config, "WAF_CRS_SHA256", "0" * 64)
        result = waf.download_crs()
        expect(not result["ok"], "下载被拒绝")
        expect("SHA256" in result["reason"], "原因说明校验失败")
        expect(not os.path.isdir(waf.crs_root()), "未留下任何规则文件")
        expect(waf.read_state() == {}, "未写入 state.json")

    def test_empty_checksum_rejected(self, monkeypatch, waf_on, clean_waf):
        logger.info("=== 未配置校验和时默认拒绝（防止静默接受任意内容）===")
        monkeypatch.setattr(config, "WAF_CRS_SHA256", "")
        result = waf.download_crs()
        expect(not result["ok"] and "crs_sha256" in result["reason"], "空校验和被拒绝")

    def test_verify_disabled_accepts_any_hash(self, monkeypatch, waf_on, clean_waf):
        logger.info("=== verify_checksum=false：不校验也能装（内网镜像场景）===")
        monkeypatch.setattr(config, "WAF_VERIFY_CHECKSUM", False)
        monkeypatch.setattr(config, "WAF_CRS_SHA256", "0" * 64)
        result = waf.download_crs()
        expect(result["ok"], "校验和不匹配也放行（这是显式关闭校验的后果）")
        expect(waf.read_state()["sha256"] == hashlib.sha256(waf_on["blob"]).hexdigest(),
               "state.json 仍记录真实校验和，便于事后审计")

    def test_auto_download_off(self, monkeypatch, waf_on, clean_waf):
        logger.info("=== auto_download=false：不联网 ===")
        monkeypatch.setattr(config, "WAF_AUTO_DOWNLOAD", False)
        result = waf.download_crs()
        expect(result["reason"] == "auto-download-disabled", "跳过下载")
        expect(not waf_on["fetches"], "未发起网络请求")

    def test_non_https_rejected(self, waf_on, clean_waf):
        logger.info("=== 仅放行 https ===")
        expect(waf._fetch("http://example.com/crs.tar.gz", 5, 1024) is None, "明文 http 被拒")
        expect(waf._fetch("file:///etc/passwd", 5, 1024) is None, "file:// 被拒")
        expect(not waf._is_https_url("nginx -t -c /etc/nginx"), "非 URL 输入不会被当成 https")

    @pytest.mark.parametrize("kind", ["traversal", "symlink", "device"])
    def test_dangerous_tar_rejected(self, monkeypatch, waf_on, clean_waf, kind):
        logger.info("=== 危险压缩包成员：%s ===", kind)
        blob = build_evil_tar(kind)
        waf_on["blob"] = blob
        monkeypatch.setattr(config, "WAF_CRS_SHA256", hashlib.sha256(blob).hexdigest())
        result = waf.download_crs()
        expect(not result["ok"], "安装被拒绝")
        expect("安装失败" in result["reason"], f"原因说明解压防护生效（{kind}）")
        expect(not os.path.isfile(os.path.join(str(clean_waf), "escaped.conf")),
               "未写出解压区外的文件")

    def test_unpacked_size_capped(self, monkeypatch, waf_on, clean_waf):
        logger.info("=== 解压体积上限（压缩炸弹防护）===")
        blob = build_tar({"crs/rules/REQUEST-901-INITIALIZATION.conf": "x" * 4096})
        waf_on["blob"] = blob
        monkeypatch.setattr(config, "WAF_CRS_SHA256", hashlib.sha256(blob).hexdigest())
        monkeypatch.setattr(waf, "MAX_UNPACKED_BYTES", 1024)
        result = waf.download_crs()
        expect(not result["ok"] and "上限" in result["reason"], "超过解压体积上限即拒绝")

    def test_file_count_capped(self, monkeypatch, waf_on, clean_waf):
        logger.info("=== 文件数上限 ===")
        entries = {f"crs/rules/REQUEST-90{i}-X.conf": "# r\n" for i in range(5)}
        blob = build_tar(entries)
        waf_on["blob"] = blob
        monkeypatch.setattr(config, "WAF_CRS_SHA256", hashlib.sha256(blob).hexdigest())
        monkeypatch.setattr(waf, "MAX_FILE_COUNT", 2)
        result = waf.download_crs()
        expect(not result["ok"] and "文件数" in result["reason"], "超过文件数上限即拒绝")

    def test_not_a_crs_archive(self, monkeypatch, waf_on, clean_waf):
        logger.info("=== 下载到的不是 CRS：拒绝 ===")
        blob = build_tar({"README.md": "hello\n"})
        waf_on["blob"] = blob
        monkeypatch.setattr(config, "WAF_CRS_SHA256", hashlib.sha256(blob).hexdigest())
        result = waf.download_crs()
        expect(not result["ok"] and "rules/" in result["reason"], "缺少 rules/ 目录即拒绝")

    def test_download_failure_keeps_previous(self, monkeypatch, waf_on, clean_waf):
        logger.info("=== 升级失败不破坏已装规则集 ===")
        waf.download_crs()
        monkeypatch.setattr(config, "WAF_CRS_VERSION", "4.30.0")
        monkeypatch.setattr(waf, "_fetch", lambda url, timeout, max_bytes: None)
        result = waf.download_crs()
        expect(not result["ok"], "新版本下载失败")
        expect(waf.installed_crs_version() == CRS_VERSION, "旧版本规则集完好保留")

    def test_update_check_hints_only(self, monkeypatch, waf_on, clean_waf):
        logger.info("=== 上游版本查询：只提示，不自动切版本 ===")
        body = json.dumps({"tag_name": "v9.9.9"}).encode()
        monkeypatch.setattr(waf, "_fetch", lambda url, timeout, max_bytes: body)
        expect(waf.check_crs_update() == "9.9.9", "发现更新版本并返回")
        expect(waf.installed_crs_version() in (None, CRS_VERSION), "未擅自改动锁定版本")
        monkeypatch.setattr(config, "WAF_CRS_URL", "https://example.com/crs.tar.gz")
        expect(waf.check_crs_update() is None, "非 github 源不做查询")


# ---------------------------------------------------------------------------
class TestRender:
    """配置渲染：顺序、模式与注入防护。"""

    def test_modsecurity_conf(self, monkeypatch, waf_on, clean_waf):
        logger.info("=== modsecurity.conf ===")
        waf.download_crs()
        waf.render_configs()
        text = open(os.path.join(waf.waf_root(), "modsecurity.conf"), encoding="utf-8").read()
        expect("SecRuleEngine On" in text, "mode=on 时引擎为拦截模式")
        expect(f"SecRequestBodyLimit {config.WAF_BODY_LIMIT_BYTES}" in text,
               "请求体上限与应用上传上限一致（否则会先于应用回 413）")
        expect(f"SecRequestBodyNoFilesLimit {config.WAF_BODY_LIMIT_BYTES}" in text,
               "无文件请求体上限同值（笔记正文是 urlencoded 表单，沿用默认 128KB 会让保存大笔记 413）")
        expect("SecResponseBodyAccess Off" in text, "默认不做出站响应体检测")
        expect("SecAuditLog " in text, "配置了审计日志")
        includes = [line.split("/")[-1].rstrip('"') for line in text.splitlines()
                    if line.startswith("Include ")]
        expect(includes == ["crs-setup.conf", "exclusions.conf", "*.conf", "custom.conf"],
               "Include 顺序：setup → 排除 → CRS → 自定义")
        expect(text.index("SecDefaultAction") < text.index("Include "),
               "异常评分模式的 SecDefaultAction 在规则加载之前")

    def test_detection_only_mode(self, monkeypatch, waf_on, clean_waf):
        logger.info("=== mode=detectiononly：只记录不拦截 ===")
        monkeypatch.setattr(config, "WAF_MODE", "detectiononly")
        waf.download_crs()
        text = waf.render_modsecurity_conf()
        expect("SecRuleEngine DetectionOnly" in text, "引擎切到检测模式")
        expect("SecRuleEngine On" not in text, "不会同时出现拦截模式")

    def test_response_inspection_toggle(self, monkeypatch, waf_on, clean_waf):
        logger.info("=== response_inspection=true：开启出站检测 ===")
        monkeypatch.setattr(config, "WAF_RESPONSE_INSPECTION", True)
        text = waf.render_modsecurity_conf()
        expect("SecResponseBodyAccess On" in text, "出站检测已开启")
        expect("SecResponseBodyMimeType" in text, "限定响应 MIME 类型")

    def test_crs_setup_conf(self, waf_on, clean_waf):
        logger.info("=== crs-setup.conf ===")
        waf.download_crs()
        text = waf.render_crs_setup_conf()
        expect(f"ver:'OWASP_CRS/{CRS_VERSION}'" in text, "版本号与锁定的 CRS 一致")
        expect("id:900000" in text and "blocking_paranoia_level" in text, "设置拦截等级")
        expect("id:900110" in text and "inbound_anomaly_score_threshold" in text, "设置异常分阈值")
        expect("tx.crs_setup_version=4290" in text,
               "写入 crs_setup_version（缺失会让 CRS 901001 直接 500 罢工）")
        expect(text.index("id:900110") < text.index("id:900990"), "setup_version 声明在最后")

    def test_exclusions(self, monkeypatch, waf_on, clean_waf):
        logger.info("=== 内容型端点误报排除 ===")
        text = waf.render_exclusions_conf()
        expect("id:1000" in text, "笔记正文端点已排除")
        expect("ctl:ruleRemoveByTag=attack-sqli" in text, "排除 SQLi 注入类规则")
        expect("ctl:ruleRemoveByTag=attack-xss" in text, "排除 XSS 注入类规则")
        expect("REQUEST_FILENAME" in text, "按路径（不含查询串）匹配")
        expect("attack-protocol" not in text, "协议强制类规则未被排除")
        monkeypatch.setattr(config, "WAF_DEFAULT_EXCLUSIONS", False)
        off = waf.render_exclusions_conf()
        expect("id:1000" not in off and "default_exclusions=false" in off,
               "关掉开关后不生成任何排除规则")

    def test_custom_conf_not_overwritten(self, waf_on, clean_waf):
        logger.info("=== custom.conf 只生成一次 ===")
        written = waf.render_configs()
        custom = os.path.join(waf.waf_root(), "custom.conf")
        expect(any(p.endswith("custom.conf") for p in written), "首次生成 custom.conf")
        with open(custom, "w", encoding="utf-8") as f:
            f.write('SecRule REMOTE_ADDR "@ipMatch 10.0.0.0/8" "id:1100,phase:1,pass,nolog"\n')
        waf.render_configs()
        text = open(custom, encoding="utf-8").read()
        expect("id:1100" in text, "用户自定义规则未被覆盖")

    def test_render_idempotent(self, waf_on, clean_waf):
        logger.info("=== 重复渲染不重复落盘 ===")
        waf.download_crs()
        first = waf.render_configs()
        expect(len(first) >= 5, "首次生成全部配置文件")
        expect(waf.render_configs() == [], "内容未变化时不再写盘")

    def test_nginx_conf_contents(self, waf_on, clean_waf):
        logger.info("=== nginx 配置 ===")
        site = waf.render_site_conf()
        expect("modsecurity on;" in site, "站点开启 ModSecurity")
        expect("modsecurity_rules_file" in site, "指向生成的 modsecurity.conf")
        expect(f"client_max_body_size {config.WAF_BODY_LIMIT_BYTES};" in site,
               "nginx 请求体上限与 ModSecurity 一致")
        expect("proxy_set_header X-Real-IP" in site and "X-Forwarded-For" in site,
               "透传真实客户端 IP（否则应用限流只看到反代地址）")
        expect("proxy_buffering off;" in site, "附件流式下载不被缓冲掐断")
        expect(f"proxy_pass http://{config.WAF_UPSTREAM}:{config.WAF_UPSTREAM_PORT};" in site,
               "回源地址正确")
        standalone = waf.render_standalone_conf()
        expect("events {" in standalone and "http {" in standalone, "standalone 配置结构完整")
        expect("client_body_temp_path" in standalone, "临时目录指向数据目录（非 root 可写）")
        expect("include" in standalone and "rusin-note.conf" in standalone, "复用同一份 server 块")

    def test_nginx_token_injection_guard(self, monkeypatch, waf_on, clean_waf):
        logger.info("=== 配置值注入防护 ===")
        monkeypatch.setattr(config, "WAF_LISTEN", "80;\n    return 444; #")
        monkeypatch.setattr(config, "WAF_SERVER_NAME", 'evil"; root /tmp; #')
        monkeypatch.setattr(config, "WAF_UPSTREAM", "127.0.0.1;\n evil")
        site = waf.render_site_conf()
        expect("return 444" not in site, "listen 注入被拦下")
        expect(site.count("listen 80;") == 1, "listen 回退为默认值")
        expect('evil"' not in site, "server_name 注入被拦下")
        expect("proxy_pass http://127.0.0.1:8080;" in site, "upstream 回退为默认值")

    def test_unicode_mapping_optional(self, monkeypatch, waf_on, clean_waf):
        logger.info("=== unicode.mapping 缺失时给出说明而不是硬引用 ===")
        monkeypatch.setattr(waf, "_unicode_mapping_path", lambda: None)
        text = waf.render_modsecurity_conf()
        expect("SecUnicodeMapFile" not in text, "未找到就不写该指令（否则 nginx -t 直接失败）")
        expect("unicode.mapping" in text, "留下说明注释")
        monkeypatch.setattr(waf, "_unicode_mapping_path", lambda: "/etc/modsecurity/unicode.mapping")
        expect("SecUnicodeMapFile" in waf.render_modsecurity_conf(), "找到时写入指令")


# ---------------------------------------------------------------------------
class TestProvision:
    """供给编排与运维提示。"""

    def test_ready_with_engine(self, monkeypatch, waf_on, clean_waf):
        logger.info("=== 引擎就绪：下载 + 生成 + 校验 ===")
        monkeypatch.setattr(waf, "detect_engine", lambda: fake_engine(installed=True))
        status = waf.provision_waf()
        expect(status["ready"] is True, "标记为就绪")
        expect(status["crs"]["ok"] and status["crs"]["version"] == CRS_VERSION, "CRS 已安装")
        expect(status["engine"]["installed"] is True, "引擎探测结果已记录")
        expect(status["validate"]["ok"] is True, "nginx -t 校验通过")
        expect(any("-t" in cmd for cmd in waf_on.get("cmds", [])), "确实执行了 nginx -t 校验")
        expect(status["next_steps"], "给出启用命令")
        expect(status["warnings"] == [], "配置正确时无告警")
        expect(os.path.isdir(os.path.join(waf.waf_root(), "log")), "创建了审计日志目录")

    def test_engine_missing_never_raises(self, monkeypatch, waf_on, clean_waf):
        logger.info("=== 引擎缺失：只提示安装，不抛异常 ===")
        monkeypatch.setattr(waf, "detect_engine", lambda: fake_engine(installed=False,
                                                                     modsecurity=False))
        status = waf.provision_waf()
        expect(status["ready"] is False, "未就绪")
        expect(status["crs"]["ok"] is True, "规则集仍然下载好了，装完引擎即可用")
        expect(status["engine"]["hints"], "给出安装命令提示")
        expect(any("nginx -t" in step for step in status["next_steps"]), "给出后续校验命令")
        expect("validate" not in status, "引擎缺失时不执行校验")

    def test_validate_failure_reported(self, monkeypatch, waf_on, clean_waf):
        logger.info("=== nginx -t 失败：把错误带出来 ===")
        monkeypatch.setattr(waf, "detect_engine", lambda: fake_engine(installed=True))
        waf_on["run"] = (1, 'nginx: [emerg] unknown directive "modsecurity" in site.conf:2')
        status = waf.provision_waf()
        expect(status["validate"]["ok"] is False, "校验失败被记录")
        expect(status["ready"] is False, "未标记就绪")
        expect(any("load_module" in w for w in status["warnings"]), "提示动态模块加载方式")

    def test_validate_disabled_still_gives_steps(self, monkeypatch, waf_on, clean_waf):
        logger.info("=== 引擎已装但关闭 validate_config：不能误报「未检测到引擎」===")
        monkeypatch.setattr(waf, "detect_engine", lambda: fake_engine(installed=True))
        monkeypatch.setattr(config, "WAF_VALIDATE_CONFIG", False)
        status = waf.provision_waf()
        expect("validate" not in status, "未执行校验")
        expect(status["warnings"] == [], "没有引擎缺失类告警")
        expect(any("nginx -t -c" in step for step in status["next_steps"]), "仍给出启用命令")
        expect(status["ready"] is True, "CRS 就位 + 引擎可用即视为就绪")

    def test_auto_reload_opt_in(self, monkeypatch, waf_on, clean_waf):
        logger.info("=== auto_reload 默认关闭，显式开启才 reload ===")
        monkeypatch.setattr(waf, "detect_engine", lambda: fake_engine(installed=True))
        status = waf.provision_waf()
        expect("reload" not in status, "默认不碰系统 nginx 进程")
        monkeypatch.setattr(config, "WAF_AUTO_RELOAD", True)
        waf.reset_state()
        status = waf.provision_waf()
        expect(status["reload"]["ok"] is True, "显式开启后执行 reload")
        expect(any("-s" in cmd for cmd in waf_on.get("cmds", [])), "调用了 nginx -s reload")

    def test_proxy_trust_warning(self, monkeypatch, waf_on, clean_waf):
        logger.info("=== 反代信任链：配错会让全站限流误伤 ===")
        monkeypatch.setattr(waf, "detect_engine", lambda: fake_engine(installed=True))
        monkeypatch.setattr(config, "TRUST_PROXY_HEADERS", False)
        status = waf.provision_waf()
        expect(any("trust_proxy_headers" in w for w in status["warnings"]),
               "提醒开启 trust_proxy_headers，否则所有用户被算成同一个 IP")
        expect(status["ready"] is True, "仍属可用状态（只是要提醒）")

        monkeypatch.setattr(config, "TRUST_PROXY_HEADERS", True)
        monkeypatch.setattr(config, "TRUSTED_PROXIES", ["10.0.0.0/8"])
        monkeypatch.setattr(config, "WAF_UPSTREAM", "203.0.113.7")
        ip_utils.clear_caches()
        status = waf.provision_waf()
        expect(any("trusted_proxies" in w for w in status["warnings"]),
               "回源地址不在可信代理内时提醒补白名单")

        monkeypatch.setattr(config, "WAF_UPSTREAM", "127.0.0.1")
        monkeypatch.setattr(config, "TRUSTED_PROXIES", ["loopback", "private"])
        ip_utils.clear_caches()
        status = waf.provision_waf()
        expect(status["warnings"] == [], "回源为回环地址且在可信代理内时无告警")

    def test_detection_only_warning(self, monkeypatch, waf_on, clean_waf):
        logger.info("=== detectiononly 模式提醒 ===")
        monkeypatch.setattr(waf, "detect_engine", lambda: fake_engine(installed=True))
        monkeypatch.setattr(config, "WAF_MODE", "detectiononly")
        status = waf.provision_waf()
        expect(any("detectiononly" in w for w in status["warnings"]), "提醒当前不拦截")

    def test_provision_survives_download_failure(self, monkeypatch, waf_on, clean_waf):
        logger.info("=== 下载失败也要把配置和提示产出来 ===")
        monkeypatch.setattr(waf, "detect_engine", lambda: fake_engine(installed=True))
        monkeypatch.setattr(waf, "_fetch", lambda url, timeout, max_bytes: None)
        status = waf.provision_waf()
        expect(status["crs"]["ok"] is False, "记录下载失败")
        expect(any("CRS 规则集未就位" in w for w in status["warnings"]), "给出告警")
        expect(status["files"], "配置文件仍然生成，修好网络即可用")

    def test_format_status_printable(self, monkeypatch, waf_on, clean_waf):
        logger.info("=== 启动输出 ===")
        monkeypatch.setattr(waf, "detect_engine", lambda: fake_engine(installed=True))
        lines = waf.format_status(waf.provision_waf())
        expect(all(isinstance(line, str) and line for line in lines), "全部为非空字符串")
        expect(any("CRS" in line for line in lines), "包含 CRS 版本信息")
        expect(any("audit.log" in line for line in lines), "告知审计日志位置")

    def test_status_before_provision(self, monkeypatch, clean_waf):
        logger.info("=== 未供给过时也能查状态（不触发下载）===")
        monkeypatch.setattr(config, "WAF_ENABLED", False)
        monkeypatch.setattr(waf, "detect_engine", lambda: fake_engine(installed=False))
        status = waf.waf_status()
        expect(status["skipped"] == "not-provisioned", "标记未供给")
        expect(status["crs"]["reason"] == "not-provisioned", "CRS 状态为未供给")
