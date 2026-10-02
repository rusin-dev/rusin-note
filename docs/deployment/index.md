# 部署总览

Rusin-Note 支持多种部署方式，请根据运行环境选择对应指南：

| 方式 | 适用场景 | 指南 |
|---|---|---|
| Vercel | 无服务器，推荐（绑定 Neon 即得持久化） | [vercel.md](vercel.md) |
| AWS Lambda | 无服务器，需要信用卡，不推荐 | [aws-lambda.md](aws-lambda.md) |
| VPS / 传统服务器 | 自有服务器，gunicorn + Nginx | [vps.md](vps.md) |
| Zeabur | GitHub 自动部署，需挂载持久化卷 | [zeabur.md](zeabur.md) |

延伸阅读：

- 存储后端（sqlite / file / upstash / postgres / memory）：[storage-backends.md](storage-backends.md)
- 真实客户端 IP 与防 XFF 伪造：[ip-and-proxy.md](ip-and-proxy.md)
- 反向代理 WAF（nginx + ModSecurity + OWASP CRS）：[waf.md](waf.md)

## 获取 SECRET_KEY

部署前先准备一个随机密钥（Flask 会话签名用），任选一种：

- **Windows**：`win+x i` 打开 PowerShell 运行 below，复制生成的密钥：

  ```powershell
  $bytes=New-Object byte[] 48;[System.Security.Cryptography.RNGCryptoServiceProvider]::Create().GetBytes($bytes);[Convert]::ToBase64String($bytes)
  ```

- **Linux / macOS**：`openssl rand -base64 48`
- **Python 通用**：`python3 -c "import secrets; print(secrets.token_hex(32))"`

可持久化后端（file / upstash / postgres）未设置 `RUSIN_SECRET_KEY` 时会自动生成并存储；无服务器平台强烈建议显式设置。

## 常用环境变量

`.env.example` 提供了主要示例：

| 变量 | 说明 |
|---|---|
| `RUSIN_SECRET_KEY` | Flask 密钥，见上节 |
| `RUSIN_DATA_DIR` | 运行数据目录，默认 `data`；自动部署平台建议指向持久化卷（如 `/data`） |
| `RUSIN_STORAGE` | 显式指定存储后端：`sqlite` / `file` / `memory` / `upstash` / `postgres`；未指定时自动识别 |
| `REDIS_URL` | 可选。设置后页面缓存与限流计数切换为共享 Redis（多实例共享），不可达时自动降级 SimpleCache |
| `RUSIN_ADMIN` | 功能开关管理员用户名（逗号分隔，与 config.json `admin_users` 取并集） |
| `RUSIN_TRUSTED_PROXIES` / `RUSIN_IP_ALLOWLIST` / `RUSIN_IP_BLOCKLIST` | IP 相关配置的 env 覆盖，见 [ip-and-proxy.md](ip-and-proxy.md) |

## 代理与 Cookie 默认值

仓库内 `config.json` 默认为无服务器平台开启 `trust_proxy_headers` 与 `secure_cookies`：

- 位于 Nginx / Cloudflare 等反向代理之后，或部署在无服务器平台时：两者保持 `true`，并配好 `trusted_proxies`（详见 [ip-and-proxy.md](ip-and-proxy.md)）。
- 本地开发或 VPS 走 HTTP 且**无反向代理**时：把两者改回 `false`（HTTP 下 Secure Cookie 会被浏览器拒绝，直连时也没有代理头需要采信）。
