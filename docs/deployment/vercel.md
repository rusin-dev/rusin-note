# Vercel（无服务器推荐方式）

> 开始前的准备（SECRET_KEY、环境变量、代理与 Cookie 默认值）见 [部署总览](index.md)。

[Vercel Demo](https://rusin-note.vercel.app)

[![Deploy to Vercel](https://vercel.com/button)](https://vercel.com/new/clone?repository-url=https%3A%2F%2Fgithub.com%2Frusin-dev%2Frusin-note&&env=RUSIN_SECRET_KEY)

1. 点击以上按钮，框架等不用更改，保持默认即可。然后给仓库起个名，点击 `Create`。
2. 到 `Add Environment Variables` 这项时在 `Value` 一栏粘贴刚刚的 `SECRET_KEY`，然后点击下面的 `Deploy`，等待首次部署完成。
3. 半分钟后 Vercel 显示 `Congratulations!` 时下滑，点击 `Continue to Dashboard`。
4. 存储后端 **Neon（PostgreSQL）**：在 Vercel 项目面板左侧导航栏的 `Storage`，点右上角 `Create Database`，在 `Marketplace Database Providers` 下找到 `Neon` 并点击，然后点右下角 `Continue`，再下滑点击 `Continue`，然后点击 `Create`，接着点击 `Connect`。
5. 点击 Vercel 项目面板左侧导航栏的 `Deployments`，切换到 Deployments 页面后点击右上角三个点，然后 `Create Deployment`，点击 `main` 分支的图标，最后点 `Deploy to Production` 即可。
6. 部署完成后，你可以绑定自己的域名避免 Vercel 默认域名无法访问的问题。

> Vercel 绑定 Neon 后会自动注入 `DATABASE_URL`，应用据此切换到 `postgres` 后端（多实例共享、冷启动不丢）。详见 [存储后端说明](storage-backends.md)。

## 可选：共享 Redis（缓存 + 限流）

设置 `REDIS_URL`（Redis 连接串，如 Upstash 或自建 Redis）后，页面缓存切换为共享 Redis、限流计数也在多实例间共享；不设置时页面缓存会先尝试 `cache.redis_url`（仓库默认 `redis://localhost:6379/0`，无服务器平台上通常不可达），不可达即回退进程内 SimpleCache，限流按实例内存计数。

> 提示：无服务器平台默认 `trust_proxy_headers: true`、`secure_cookies: true`（已写入 `config.json`）。本地开发如需关闭请自行修改。真实客户端 IP 与 `trusted_proxies` 配置见 [真实客户端 IP 与防 XFF 伪造](ip-and-proxy.md)。
