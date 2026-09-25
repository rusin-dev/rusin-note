"""客户端 IP 安全解析 / 防 XFF 伪造 / IP 限速与名单 端到端测试（pytest + logging）。

覆盖四部分：

1. ``ip_utils.parse_ip``：IP 字面量规范化与非法值丢弃（端口、IPv6、超长输入）。
2. ``ip_utils.analyze_client_ip``：直连公网忽略代理头、可信代理才采信、
   XFF 从右往左解析、伪造左侧项不被采信、Cloudflare 多级代理、通配兼容模式。
3. ``ip_utils.ip_in_any``：CIDR / 预设名 / 非法 IP 匹配。
4. 应用层：黑名单 403、白名单免限流、伪造代理头无法绕过限流、全局 IP 兜底限流。

运行：``pytest tests/test_ip_limiter.py``
"""
from __future__ import annotations

import logging
from collections import Counter

import pytest

from app import config
from app import ip_utils
from app.extensions import limiter
from app.ip_utils import (
    MAX_XFF_ENTRIES,
    analyze_client_ip,
    clear_caches,
    ip_in_any,
    note_ignored_proxy_headers,
    parse_ip,
)
from support import expect

logger = logging.getLogger("rusin.tests.ip")


def _use_proxy_policy(monkeypatch, *, trust=True, trusted=("loopback",), hops=1):
    """临时替换可信代理策略并清空解析缓存。"""
    monkeypatch.setattr(config, "TRUST_PROXY_HEADERS", trust)
    monkeypatch.setattr(config, "TRUSTED_PROXIES", list(trusted))
    monkeypatch.setattr(config, "PROXY_HOPS", hops)
    clear_caches()


def _reset_limiter():
    try:
        limiter.reset()
    except Exception:  # pragma: no cover - 不同版本 API 兜底
        pass


@pytest.fixture(scope="class")
def rl_client(data_dir):
    """限流真正生效的测试客户端。

    注意：Flask-Limiter 在 ``enabled=False`` 时 ``init_app`` 会直接返回，
    中间件与默认限流都不会注册（conftest 的 ``app`` fixture 正是借此关闭限流）。
    因此必须在 ``create_app()`` **之前** 打开开关，测试结束后恢复。
    """
    from app import create_app

    limiter.enabled = True
    _reset_limiter()
    try:
        application = create_app()
        application.config.update(TESTING=True)
        yield application.test_client()
    finally:
        limiter.enabled = False
        _reset_limiter()


class TestParseIp:
    """IP 字面量解析：只接受合法 IP，其余一律丢弃。"""

    def test_valid_forms(self):
        logger.info("=== 合法 IP 写法归一化 ===")
        expect(parse_ip("1.2.3.4") == "1.2.3.4", "普通 IPv4")
        expect(parse_ip("  1.2.3.4  ") == "1.2.3.4", "去除首尾空白")
        expect(parse_ip("1.2.3.4:8080") == "1.2.3.4", "IPv4:port 去掉端口")
        expect(parse_ip("[2001:db8::1]:443") == "2001:db8::1", "[IPv6]:port 去掉端口与方括号")
        expect(parse_ip("2001:db8::1") == "2001:db8::1", "纯 IPv6")
        expect(parse_ip("::ffff:1.2.3.4") == "1.2.3.4", "IPv4-mapped IPv6 归一到 IPv4")
        expect(parse_ip("::1") == "::1", "IPv6 回环")

    def test_invalid_forms(self):
        logger.info("=== 非法值一律返回 None ===")
        expect(parse_ip("") is None, "空字符串")
        expect(parse_ip(None) is None, "None")
        expect(parse_ip("not-an-ip") is None, "任意字符串")
        expect(parse_ip("1.2.3.4, 5.6.7.8") is None, "逗号分隔未拆分的值整体非法")
        expect(parse_ip("999.1.1.1") is None, "越界 IPv4")
        expect(parse_ip("x" * 100) is None, "超长输入直接丢弃")
        expect(parse_ip("1.2.3.4:") is None or parse_ip("1.2.3.4:") == "1.2.3.4", "空端口写法")


class TestClientIpResolution:
    """代理头采信策略：这是防 XFF 伪造的核心。"""

    def test_headers_ignored_when_proxy_trust_disabled(self, monkeypatch):
        logger.info("=== 未开启代理头信任：伪造头完全无效 ===")
        _use_proxy_policy(monkeypatch, trust=False, trusted=("loopback",))
        headers = {
            "X-Forwarded-For": "1.1.1.1",
            "X-Real-IP": "2.2.2.2",
            "CF-Connecting-IP": "3.3.3.3",
        }
        result = analyze_client_ip("9.9.9.9", headers)
        expect(result.ip == "9.9.9.9", "直接使用 TCP 直连 IP")
        expect(result.source == "remote", "来源标记为 remote")
        expect(result.headers_present and result.headers_ignored, "标记代理头被忽略")

    def test_headers_ignored_when_peer_untrusted(self, monkeypatch):
        logger.info("=== 对端不在可信代理列表：伪造头被忽略 ===")
        _use_proxy_policy(monkeypatch, trust=True, trusted=("10.0.0.0/8",))
        headers = {
            "X-Forwarded-For": "1.1.1.1",
            "X-Real-IP": "2.2.2.2",
            "CF-Connecting-IP": "3.3.3.3",
        }
        result = analyze_client_ip("203.0.113.9", headers)
        expect(result.ip == "203.0.113.9", "公网直连时忽略全部代理头")
        expect(not result.proxy_trusted, "标记对端不是可信代理")
        expect(result.headers_ignored, "标记为疑似伪造")

    def test_xff_rightmost_wins_for_trusted_proxy(self, monkeypatch):
        logger.info("=== 可信代理：XFF 从右往左取，伪造的左侧项不被采信 ===")
        _use_proxy_policy(monkeypatch, trust=True, trusted=("loopback",))
        headers = {"X-Forwarded-For": "9.9.9.9, 8.8.8.8, 5.5.5.5"}
        result = analyze_client_ip("127.0.0.1", headers)
        expect(result.ip == "5.5.5.5", "取代理追加的最右项作为真实客户端")
        expect(result.source == "xff", "来源标记为 xff")

    def test_x_real_ip_beats_suspect_xff(self, monkeypatch):
        logger.info("=== 代理透传 XFF 时，X-Real-IP 优先于可疑的 XFF 最右项 ===")
        _use_proxy_policy(monkeypatch, trust=True, trusted=("loopback",))
        headers = {"X-Forwarded-For": "9.9.9.9", "X-Real-IP": "5.5.5.5"}
        result = analyze_client_ip("127.0.0.1", headers)
        expect(result.ip == "5.5.5.5", "使用反代写入的 X-Real-IP")

    def test_cloudflare_multi_hop_skips_trusted_proxies(self, monkeypatch):
        logger.info("=== 多级代理（Cloudflare → Nginx）：逐层跳过可信代理 ===")
        _use_proxy_policy(monkeypatch, trust=True, trusted=("loopback", "cloudflare"))
        # 最右项为 Cloudflare 边缘地址（由 Nginx 追加），左侧 5.5.5.5 才是真实客户端
        headers = {"X-Forwarded-For": "9.9.9.9, 5.5.5.5, 172.64.1.1"}
        result = analyze_client_ip("127.0.0.1", headers)
        expect(result.ip == "5.5.5.5", "跳过可信的 CF 边缘地址后取到真实客户端")

    def test_cf_connecting_ip_requires_cloudflare_preset(self, monkeypatch):
        logger.info("=== CF-Connecting-IP 仅在启用 cloudflare 预设时采信 ===")
        _use_proxy_policy(monkeypatch, trust=True, trusted=("loopback",))
        headers = {"X-Forwarded-For": "172.64.1.1", "CF-Connecting-IP": "5.5.5.5"}
        expect(analyze_client_ip("127.0.0.1", headers).ip == "172.64.1.1",
               "未启用 CF 预设时不采信 CF-Connecting-IP")
        _use_proxy_policy(monkeypatch, trust=True, trusted=("cloudflare",))
        result = analyze_client_ip("172.64.1.1", headers)
        expect(result.ip == "5.5.5.5", "启用 CF 预设后采信 CF-Connecting-IP")
        expect(result.source == "cf-connecting-ip", "来源标记为 cf-connecting-ip")

    def test_invalid_xff_entries_dropped(self, monkeypatch):
        logger.info("=== XFF 中的非法条目被丢弃 ===")
        _use_proxy_policy(monkeypatch, trust=True, trusted=("loopback",))
        headers = {"X-Forwarded-For": "garbage, , 5.5.5.5"}
        expect(analyze_client_ip("127.0.0.1", headers).ip == "5.5.5.5",
               "非法条目不影响合法条目的解析")
        expect(analyze_client_ip("127.0.0.1", {"X-Forwarded-For": "x" * 400}).ip == "127.0.0.1",
               "超长 XFF 整段忽略，回退直连 IP")

    def test_xff_entry_cap(self, monkeypatch):
        logger.info("=== XFF 条目数上限：只解析前 %d 项 ===", MAX_XFF_ENTRIES)
        _use_proxy_policy(monkeypatch, trust=True, trusted=("*",), hops=1)
        entries = ", ".join(f"10.0.0.{i}" for i in range(1, 21))
        result = analyze_client_ip("127.0.0.1", {"X-Forwarded-For": entries})
        expect(result.ip == f"10.0.0.{MAX_XFF_ENTRIES}",
               "条目被截断到上限，未解析的伪造项不会被采信")

    def test_wildcard_legacy_hop_mode(self, monkeypatch):
        logger.info("=== 通配兼容模式：按跳数从右取值 ===")
        _use_proxy_policy(monkeypatch, trust=True, trusted=("*",), hops=2)
        headers = {"X-Forwarded-For": "1.1.1.1, 5.5.5.5, 6.6.6.6"}
        expect(analyze_client_ip("127.0.0.1", headers).ip == "5.5.5.5",
               "hops=2 时取右数第 2 项")

    def test_spoof_warning_is_throttled(self, monkeypatch):
        logger.info("=== 伪造告警按 IP 节流 ===")
        clear_caches()
        captured: list = []

        class _FakeLogger:
            def warning(self, *args, **kwargs):
                captured.append(args)

        monkeypatch.setattr(ip_utils, "logger", _FakeLogger())
        note_ignored_proxy_headers("1.1.1.1", "9.9.9.9")
        note_ignored_proxy_headers("1.1.1.1", "9.9.9.9")
        note_ignored_proxy_headers("2.2.2.2", "9.9.9.9")
        expect(len(captured) == 2, "同一 IP 只告警一次，不同 IP 各自记录")


class TestIpLists:
    """黑/白名单匹配（CIDR + 预设名）。"""

    def test_matches(self, monkeypatch):
        logger.info("=== IP/CIDR/预设匹配 ===")
        clear_caches()
        expect(ip_in_any("127.0.0.1", ["loopback"]), "loopback 预设命中 127.0.0.1")
        expect(ip_in_any("::1", ["loopback"]), "loopback 预设命中 ::1")
        expect(ip_in_any("10.1.2.3", ["private"]), "private 预设命中 RFC1918")
        expect(ip_in_any("192.168.1.7", ["192.168.1.0/24"]), "CIDR 命中")
        expect(not ip_in_any("192.168.2.7", ["192.168.1.0/24"]), "CIDR 外不命中")
        expect(not ip_in_any("1.1.1.1", ["nonsense-config"]), "非法配置项被忽略")

    def test_invalid_ip_never_matches(self):
        logger.info("=== 非法 IP 永不命中名单 ===")
        expect(not ip_in_any("not-an-ip", ["0.0.0.0/0"]), "非法 IP 直接判为不命中")


class TestIpBlocklist:
    """黑名单：请求直接 403。"""

    def test_blocked_ip_gets_403(self, ctx, monkeypatch):
        logger.info("=== 黑名单 IP 访问被拒绝 ===")
        monkeypatch.setattr(config, "IP_BLOCKLIST", ["127.0.0.0/8"])
        response = ctx.anon.get("/")
        expect(response.status_code == 403, "黑名单 IP 收到 403")
        expect("封禁" in response.get_data(as_text=True), "返回封禁提示文案")

    def test_unrelated_ip_not_blocked(self, ctx, monkeypatch):
        logger.info("=== 无关网段不受影响 ===")
        monkeypatch.setattr(config, "IP_BLOCKLIST", ["203.0.113.0/24"])
        expect(ctx.anon.get("/").status_code == 200, "非黑名单 IP 正常访问")


class TestIpRateLimit:
    """限流层：伪造代理头无法绕过，白名单豁免，全局兜底限流生效。"""

    def test_forged_proxy_headers_cannot_bypass_limit(self, rl_client, monkeypatch):
        logger.info("=== 伪造代理头无法绕过限流 ===")
        # 对端（127.0.0.1）不在可信代理列表内 → 所有代理头被忽略
        _use_proxy_policy(monkeypatch, trust=True, trusted=("192.168.0.0/16",))
        _reset_limiter()
        total = config.GET_RATE_MAX + 5
        codes = []
        for i in range(total):
            codes.append(rl_client.get("/login", headers={
                "X-Forwarded-For": f"10.0.0.{i % 250 + 1}",
                "X-Real-IP": f"10.0.0.{i % 250 + 1}",
                "CF-Connecting-IP": f"10.0.0.{i % 250 + 1}",
            }).status_code)
        logger.info("状态码分布：%s", Counter(codes))
        expect(429 in codes, f"同一直连 IP 请求 {total} 次后触发 429（伪造头无效）")
        expect(codes.count(429) >= 4, "限流对后续伪造请求持续生效")

    def test_allowlist_exempts_from_rate_limit(self, rl_client, monkeypatch):
        logger.info("=== 白名单 IP 免限流 ===")
        _use_proxy_policy(monkeypatch, trust=True, trusted=("loopback",))
        monkeypatch.setattr(config, "IP_ALLOWLIST", ["127.0.0.0/8"])
        _reset_limiter()
        total = config.GET_RATE_MAX + 15
        codes = [rl_client.get("/login").status_code for _ in range(total)]
        expect(all(code == 200 for code in codes),
               f"白名单 IP 连续请求 {total} 次不触发 429")

    def test_application_limit_applies(self, rl_client, monkeypatch):
        logger.info("=== 全站每 IP 总请求上限（应用级作用域）生效 ===")
        if not config.IP_RATE_ENABLED:  # pragma: no cover - 配置关闭时跳过
            pytest.skip("ip_rate_limit 已关闭")
        _use_proxy_policy(monkeypatch, trust=False)
        _reset_limiter()
        total = config.IP_RATE_MAX + 1
        codes = [rl_client.get("/").status_code for _ in range(total)]
        logger.info("末尾状态码：%s", codes[-3:])
        expect(codes[-1] == 429,
               f"同一 IP 累计请求 {total} 次后触发全站 IP 限流")
