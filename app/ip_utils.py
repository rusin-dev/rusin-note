"""客户端 IP 解析与可信代理校验（防 X-Forwarded-For 伪造）

限流、发帖冷却、评论冷却都依赖「真实客户端 IP」。而 ``X-Forwarded-For``
（XFF）、``X-Real-IP``、``CF-Connecting-IP`` 都是**请求头**，客户端可以随意
伪造；如果无条件采信，攻击者只要每次请求换一个假 IP 就能让限流彻底失效
（同时用任意字符串制造海量限流桶，造成内存放大）。本模块集中处理该问题：

1. **对端校验**：只有「TCP 直连对端（``remote_addr``）属于可信代理网段」时才
   采信代理头；公网直连时所有代理头一律忽略，直接用 TCP 源 IP。这是防伪造的
   根本手段。
2. **严格解析**：头部值必须能被 ``ipaddress`` 解析为合法 IP（支持
   ``1.2.3.4:80`` / ``[2001:db8::1]:443`` / ``::ffff:1.2.3.4`` 等写法），
   非法值一律丢弃，绝不把任意字符串当作限流键。超长头部直接放弃解析。
3. **从右往左取 XFF**：XFF 是「左旧右新」追加的列表，右侧条目由可信代理写入，
   左侧可能是客户端伪造的历史值。多级代理（如 Cloudflare → Nginx）下逐层跳过
   可信代理地址，取第一个不可信的合法 IP 作为真实客户端。
4. **兼容模式**：``trusted_proxies`` 配置为 ``"*"``（或留空）时退化为
   「从右数第 ``proxy_hops`` 项」，保留旧行为并输出告警——该模式下无法校验代理
   头来源，存在伪造风险，仅推荐在无法枚举代理网段时临时使用。

`config.json` 相关配置：

- ``trust_proxy_headers``：总开关，默认 ``false``（最安全）。
- ``trusted_proxies``：可信代理列表，元素可以是 IP / CIDR，也可以是预设名
  ``loopback`` / ``private`` / ``cloudflare``，或 ``"*"``（信任任意对端）。
- ``proxy_hops``：兼容模式下的代理跳数，默认 1。
- ``ip_allowlist`` / ``ip_blocklist``：限流白名单（免限流）与黑名单（直接 403）。
"""
from __future__ import annotations

import ipaddress
import threading
import time
from typing import Iterable, Mapping, NamedTuple

from . import config
from .logger import create_logger

logger = create_logger("ip")

# 单个头部值最大长度：超过则整段丢弃（防超长头部拖慢解析）
MAX_HEADER_VALUE_LEN = 256
# 单个 IP 字面量最大长度（IPv6 含 zone id 也远小于该值）
MAX_IP_TOKEN_LEN = 64
# XFF 最多解析的条目数：多余部分丢弃（防「上千个伪造条目」拖慢解析）
MAX_XFF_ENTRIES = 16
# 疑似伪造代理头的告警节流：同一 IP 每 5 分钟最多记一条
SPOOF_LOG_INTERVAL = 300.0

# 常用可信代理预设：可用字符串名引用，避免用户手抄网段
PROXY_PRESETS: dict[str, tuple[str, ...]] = {
    # 同机反向代理（Nginx / Caddy 直连 127.0.0.1）与各类平台的本地转发
    "loopback": ("127.0.0.0/8", "::1/128"),
    # 私有网段：容器网络、云厂商内网负载均衡、CGNAT（100.64.0.0/10）等
    "private": (
        "10.0.0.0/8",
        "172.16.0.0/12",
        "192.168.0.0/16",
        "100.64.0.0/10",
        "169.254.0.0/16",
        "fc00::/7",
        "fe80::/10",
    ),
    # Cloudflare 官方回源地址段（https://www.cloudflare.com/ips/）
    "cloudflare": (
        "173.245.48.0/20",
        "103.21.244.0/22",
        "103.22.200.0/22",
        "103.31.4.0/22",
        "141.101.64.0/18",
        "108.162.192.0/18",
        "190.93.240.0/20",
        "188.114.96.0/20",
        "197.234.240.0/22",
        "198.41.128.0/17",
        "162.158.0.0/15",
        "104.16.0.0/13",
        "104.24.0.0/14",
        "172.64.0.0/13",
        "131.0.72.0/22",
        "2400:cb00::/32",
        "2606:4700::/32",
        "2803:f800::/32",
        "2405:b500::/32",
        "2405:8100::/32",
        "2a06:98c0::/29",
        "2c0f:f248::/32",
    ),
}

# 信任任意对端的写法（等价于旧的「无条件信任代理头」，有伪造风险）
TRUST_ALL_TOKENS = frozenset({"*", "any", "all"})

FALLBACK_IP = "0.0.0.0"


class ClientIP(NamedTuple):
    """一次请求的客户端 IP 解析结果。"""

    ip: str
    source: str            # remote / xff / x-real-ip / cf-connecting-ip
    proxy_trusted: bool    # 直连对端是否为可信代理
    headers_present: bool  # 请求是否携带了代理头
    headers_ignored: bool  # 代理头因对端不可信而被忽略（疑似伪造）


class ProxySpec(NamedTuple):
    """可信代理配置解析结果。"""

    networks: tuple            # ipaddress network 对象
    trust_all: bool            # 是否信任任意对端
    cloudflare: bool           # 是否包含 Cloudflare（用于采信 CF-Connecting-IP）


def parse_ip(value: str | None) -> str | None:
    """把头部/环境中的字面量规范化为标准 IP 字符串，非法值返回 ``None``。

    支持 ``1.2.3.4``、``1.2.3.4:8080``、``[2001:db8::1]:443``、
    ``::ffff:1.2.3.4``（IPv4-mapped 归一到 IPv4）等常见写法。
    """
    if not value:
        return None
    token = value.strip()
    if not token or len(token) > MAX_IP_TOKEN_LEN:
        return None
    if token.startswith("["):
        end = token.find("]")
        if end <= 1:
            return None
        token = token[1:end]
    elif token.count(":") == 1 and "." in token:
        # IPv4:port（IPv6 至少含两个冒号，不会被误切）
        token = token.split(":", 1)[0]
    try:
        parsed = ipaddress.ip_address(token)
    except ValueError:
        return None
    mapped = getattr(parsed, "ipv4_mapped", None)
    if mapped is not None:
        parsed = mapped
    return str(parsed)


def _to_tokens(values) -> tuple[str, ...]:
    """把配置项（字符串 / 列表）统一成去空白的字符串元组。"""
    if not values:
        return ()
    if isinstance(values, str):
        values = values.replace(";", ",").split(",")
    tokens = []
    for item in values:
        if isinstance(item, str):
            text = item.strip()
            if text:
                tokens.append(text)
    return tuple(tokens)


def _expand(tokens: Iterable[str]) -> tuple[tuple, bool, bool]:
    """展开预设名并解析 CIDR，返回 (networks, trust_all, cloudflare)。"""
    networks: list = []
    trust_all = False
    cloudflare = False
    for index, token in enumerate(tokens, start=1):
        key = token.lower()
        if key in TRUST_ALL_TOKENS:
            trust_all = True
            continue
        if key in PROXY_PRESETS:
            if key == "cloudflare":
                cloudflare = True
            for item in PROXY_PRESETS[key]:
                networks.append(ipaddress.ip_network(item, strict=False))
            continue
        try:
            networks.append(ipaddress.ip_network(token, strict=False))
        except ValueError:
            # 不回显配置项原文（CodeQL py/clear-text-logging-sensitive-data）：
            # 无效项可能是误粘贴到 IP 列表里的密钥，写进日志等于明文外泄；
            # 只记录位置与长度，运维足以定位到具体是第几项。
            logger.warning("忽略无法解析的 IP/CIDR 配置项：第 %d/%d 项（长度 %d）",
                           index, len(tokens), len(token))
    return tuple(networks), trust_all, cloudflare


# 解析结果缓存：配置在启动时固定，避免每个请求重复解析 CIDR
_cache_lock = threading.Lock()
_proxy_spec_cache: dict[tuple[str, ...], ProxySpec] = {}
_network_cache: dict[tuple[str, ...], tuple] = {}


def trusted_proxy_spec(values) -> ProxySpec:
    """解析 ``trusted_proxies`` 配置（带缓存）。"""
    key = _to_tokens(values)
    with _cache_lock:
        cached = _proxy_spec_cache.get(key)
        if cached is not None:
            return cached
    networks, trust_all, cloudflare = _expand(key)
    spec = ProxySpec(networks=networks, trust_all=trust_all, cloudflare=cloudflare)
    with _cache_lock:
        _proxy_spec_cache[key] = spec
    return spec


def _networks(values) -> tuple:
    """解析任意 IP/CIDR 列表（带缓存），用于黑/白名单匹配。"""
    key = _to_tokens(values)
    with _cache_lock:
        cached = _network_cache.get(key)
        if cached is not None:
            return cached
    networks, _, _ = _expand(key)
    with _cache_lock:
        _network_cache[key] = networks
    return networks


def ip_in(ip: str, networks: tuple) -> bool:
    """判断 IP 是否落在任一网段内（IP 非法或网段为空时返回 ``False``）。"""
    if not networks:
        return False
    try:
        parsed = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return any(parsed in network for network in networks)


def ip_in_any(ip: str, values) -> bool:
    """判断 IP 是否命中配置的 IP/CIDR 列表（支持预设名，带缓存）。"""
    return ip_in(ip, _networks(values))


def _split_xff(raw: str | None) -> tuple[str, ...]:
    """拆分 XFF 并只保留合法 IP（保持左→右顺序）。

    超长头部直接放弃解析（不写日志：该头部可由客户端任意伪造，写日志会被
    用来刷日志文件）。
    """
    if not raw or len(raw) > MAX_HEADER_VALUE_LEN:
        return ()
    entries: list[str] = []
    for item in raw.split(","):
        if len(entries) >= MAX_XFF_ENTRIES:
            break
        parsed = parse_ip(item)
        if parsed:
            entries.append(parsed)
    return tuple(entries)


def _header_ip(headers: Mapping, name: str) -> str | None:
    raw = headers.get(name)
    if not raw or len(raw) > MAX_HEADER_VALUE_LEN:
        return None
    return parse_ip(raw)


def analyze_client_ip(remote_addr: str | None,
                      headers: Mapping) -> ClientIP:
    """解析真实客户端 IP，返回结果与来源诊断信息。

    见模块文档：只有对端是可信代理时才采信代理头；XFF 从右往左解析。
    """
    remote = parse_ip(remote_addr) or FALLBACK_IP
    xff = _split_xff(headers.get("X-Forwarded-For"))
    x_real = _header_ip(headers, "X-Real-IP")
    cf_ip = _header_ip(headers, "CF-Connecting-IP")
    # 只要请求带有任一代理头就标记存在（即便取值非法/超长），便于识别伪造尝试
    headers_present = any(
        headers.get(name) for name in ("X-Forwarded-For", "X-Real-IP", "CF-Connecting-IP")
    )

    # 未开启代理头信任：一律使用 TCP 直连 IP（伪造头完全无效）
    if not config.TRUST_PROXY_HEADERS:
        return ClientIP(remote, "remote", False, headers_present, headers_present)

    spec = trusted_proxy_spec(config.TRUSTED_PROXIES)

    # 兼容模式：无法枚举代理网段，退化为按跳数从右取值（有伪造风险）
    if spec.trust_all:
        if xff:
            hops = max(1, int(config.PROXY_HOPS or 1))
            index = max(0, len(xff) - hops)
            return ClientIP(xff[index], "xff", True, headers_present, False)
        for source, value in (("cf-connecting-ip", cf_ip), ("x-real-ip", x_real)):
            if value:
                return ClientIP(value, source, True, headers_present, False)
        return ClientIP(remote, "remote", True, headers_present, False)

    # 严格模式：TCP 对端必须是可信代理，否则丢弃全部代理头
    if not ip_in(remote, spec.networks):
        return ClientIP(remote, "remote", False, headers_present, headers_present)

    # 多级代理：最右项由可信代理写入 → 从右往左跳过可信代理，取第一个不可信 IP
    if xff and ip_in(xff[-1], spec.networks):
        for candidate in reversed(xff[:-1]):
            if not ip_in(candidate, spec.networks):
                return ClientIP(candidate, "xff", True, headers_present, False)

    # 仅 Cloudflare 场景采信 CF-Connecting-IP（CF 会强制覆写该头）
    if spec.cloudflare and cf_ip:
        return ClientIP(cf_ip, "cf-connecting-ip", True, headers_present, False)
    # Nginx 等反代常用 X-Real-IP 记录其对端地址
    if x_real:
        return ClientIP(x_real, "x-real-ip", True, headers_present, False)
    # 代理已追加的 XFF 最右项（单层代理场景）
    if xff:
        return ClientIP(xff[-1], "xff", True, headers_present, False)
    return ClientIP(remote, "remote", True, headers_present, False)


def resolve_client_ip(remote_addr: str | None, headers: Mapping) -> str:
    """``analyze_client_ip`` 的简版：只取 IP 字符串。"""
    return analyze_client_ip(remote_addr, headers).ip


_suspicious_seen: dict[str, float] = {}


def note_ignored_proxy_headers(client_ip: str, remote_addr: str | None) -> None:
    """记录「带代理头但直连对端不可信」的疑似伪造行为（节流输出）。"""
    now = time.time()
    last = _suspicious_seen.get(client_ip, 0.0)
    if now - last < SPOOF_LOG_INTERVAL:
        return
    _suspicious_seen[client_ip] = now
    if len(_suspicious_seen) > 4096:  # 防内存膨胀：清理陈旧条目，极端刷量时整体重置
        for key, stamp in list(_suspicious_seen.items()):
            if now - stamp > SPOOF_LOG_INTERVAL:
                _suspicious_seen.pop(key, None)
        if len(_suspicious_seen) > 8192:
            _suspicious_seen.clear()
    logger.warning(
        "检测到疑似伪造的代理头已忽略（TCP 对端 %s 不在可信代理列表内，"
        "按直连 IP %s 处理）；请检查 trusted_proxies 配置",
        remote_addr, client_ip,
    )


def clear_caches() -> None:
    """清空解析缓存（配置热更新 / 测试隔离用）。"""
    with _cache_lock:
        _proxy_spec_cache.clear()
        _network_cache.clear()
    _suspicious_seen.clear()


def log_ip_policy() -> None:
    """启动时输出 IP 限速 / 可信代理策略，便于部署排障与安全审计。

    日志写入独立日志文件（``create_logger``，无服务器环境回退 stderr）；
    存在伪造风险的配置用 WARNING 级别，同样会出现在 stderr 上。
    """
    if not config.TRUST_PROXY_HEADERS:
        logger.info("IP 策略：忽略全部代理头，限流使用 TCP 直连 IP（最安全）")
    else:
        spec = trusted_proxy_spec(config.TRUSTED_PROXIES)
        if spec.trust_all:
            logger.warning(
                "IP 策略：trusted_proxies 为通配（信任任意对端），代理头可被伪造，"
                "仅建议在无法枚举代理网段时使用；请改为具体 IP/CIDR 或预设名"
                "（loopback/private/cloudflare）")
        elif not spec.networks:
            logger.warning(
                "IP 策略：trusted_proxies 为空，代理头不会被采信，将按直连 IP 限流")
        else:
            logger.info("IP 策略：仅信任来自 %d 个网段的代理头（XFF 从右往左解析）",
                        len(spec.networks))
            if spec.cloudflare:
                logger.info("IP 策略：已启用 Cloudflare 预设，采信 CF-Connecting-IP")
            if "private" in {token.lower() for token in _to_tokens(config.TRUSTED_PROXIES)}:
                logger.info(
                    "IP 策略：trusted_proxies 含 private 预设（RFC1918/CGNAT/链路本地），"
                    "该网段内任意主机都可伪造代理头；若应用端口直接暴露公网（含 Docker "
                    "直接映射端口），请收窄为具体反向代理 IP")
    if config.IP_RATE_ENABLED:
        logger.info("全站 IP 限流：每 %d 秒最多 %d 次（应用级作用域）",
                    config.IP_RATE_WINDOW, config.IP_RATE_MAX)
    else:
        logger.info("全站 IP 限流：已关闭")
    if config.IP_BLOCKLIST:
        logger.info("IP 黑名单：%d 条", len(config.IP_BLOCKLIST))
    if config.IP_ALLOWLIST:
        logger.info("IP 白名单：%d 条（免限流）", len(config.IP_ALLOWLIST))
