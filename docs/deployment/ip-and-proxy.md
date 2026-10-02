# 真实客户端 IP 与防 XFF 伪造

> 限流的键是「真实客户端 IP」。反向代理部署（VPS / Vercel / Cloudflare）务必阅读本页。开始前的准备见 [部署总览](index.md)。

`X-Forwarded-For`（XFF）、`X-Real-IP`、`CF-Connecting-IP` 都是**客户端可随意伪造的请求头**。若无条件采信，攻击者每次请求换一个假 IP 就能让限流完全失效。为此本项目的解析规则如下（实现见 `app/core/ip_utils.py`）：

1. **对端校验**：只有 TCP 直连对端（`remote_addr`）命中 `trusted_proxies` 列表时才采信代理头；直接从公网访问时，所有代理头一律忽略，按直连 IP 计数。
2. **严格解析**：头部值必须是合法 IP（支持 `1.2.3.4:80`、`[2001:db8::1]:443`、`::ffff:1.2.3.4`），非法值直接丢弃——避免用任意字符串制造海量限流桶；单个头部超过 256 字节会被**整段丢弃**（不解析），XFF 超过 16 项只保留前 16 项。
3. **从右往左取 XFF**：XFF 是「左旧右新」追加的列表，右侧条目由可信代理写入，左侧可能是伪造的历史值。多级代理下逐层跳过可信代理地址，取第一个不可信的合法 IP。
4. **疑似伪造留痕**：携带了代理头但直连对端不可信时，日志会输出 `检测到疑似伪造的代理头已忽略`（同一 IP 每 5 分钟最多一条），便于发现扫描行为与配置错误。

## 部署要点

```nginx
# Nginx 必须「改写」XFF（追加自身看到的上游地址）或设置 X-Real-IP，
# 否则客户端自带的 XFF 会被原样透传
proxy_set_header X-Real-IP $remote_addr;
proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
```

- 同机 / 同私有网络的 Nginx、Caddy：`trusted_proxies` 用默认的 `["loopback", "private"]` 即可。
- Cloudflare（或 Cloudflare → Nginx）：追加 `"cloudflare"` 预设，此时会额外采信由 Cloudflare 强制覆写的 `CF-Connecting-IP`。
- 应用端口**直接暴露公网**（含 Docker 直接映射端口时对端可能显示为网关私网地址）时，请把 `trusted_proxies` 收窄为具体反向代理 IP（或只保留 `["loopback"]`）——`private` 预设意味着该网段内任意主机都可伪造代理头。
- 内网负载均衡但地址是公网 IP、或使用了名为 `private` 预设之外的网段：把对应 IP/CIDR 显式加进 `trusted_proxies`，否则代理头会被忽略，导致所有用户共用同一个限流桶（表现为「正常访问被限流」）。
- 启动时会输出当前策略（`IP 策略：…` / `全站 IP 限流：…` / 黑白名单条数）到应用日志（`data/log/*.log`，无服务器环境回退 stderr），可据此确认配置是否符合预期。

> 本项目不使用 Werkzeug 的 `ProxyFix`：它会用可伪造的 XFF 直接改写 `request.remote_addr`，使「可信代理」校验失去意义。

## 相关配置项

`trust_proxy_headers`、`trusted_proxies`、`proxy_hops`、`ip_allowlist`、`ip_blocklist` 及对应环境变量
（`RUSIN_TRUSTED_PROXIES`、`RUSIN_PROXY_HOPS`、`RUSIN_IP_ALLOWLIST`、`RUSIN_IP_BLOCKLIST`）的完整说明见
[配置项详解](../configuration.md)。
