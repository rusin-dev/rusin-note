# VPS / 传统服务器

> 开始前的准备（SECRET_KEY、环境变量、代理与 Cookie 默认值）见 [部署总览](index.md)。本地/VPS 默认使用 `sqlite` 后端，详见 [存储后端说明](storage-backends.md)。

连接你的服务器，然后：

## 1. 克隆代码

```bash
git clone https://github.com/rusin-dev/rusin-note.git
cd rusin-note
```

## 2. 安装依赖

```bash
pip install -r requirements.txt
```

## 3. 启动服务

```bash
python3 -m app

# 后台运行
nohup python3 -m app > app.log 2>&1 &

# 生产环境推荐（Linux，gunicorn；需另行安装：pip install gunicorn）
# 监听端口取环境变量 PORT，未设置时请自行写成 8080（须与下方 Nginx 反代目标一致）
gunicorn 'app.wsgi:app' -b 0.0.0.0:${PORT:-8080} --workers 2 --threads 4
```

## 4. 配置 Nginx（可选）

创建站点配置：

```bash
sudo nano /etc/nginx/sites-available/rusin-note
```

复制以下内容：

```nginx
server {
    listen 80;
    server_name _ your_domain.com;

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        # 让 Nginx 补写 XFF（追加它看到的上游 IP），避免客户端自带的 XFF 被透传
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}
```

> 使用 Nginx/Cloudflare 反代后，请将 `config.json` 中的 `trust_proxy_headers` 设为 `true`，
> 并确认 `trusted_proxies` 包含反代来源网段（默认 `["loopback", "private"]` 覆盖同机 Nginx；
> 使用 Cloudflare 时追加 `"cloudflare"` 预设）。服务端会先用 `trusted_proxies` 校验直连对端，
> 再按「XFF 从右往左、跳过可信代理」的规则取真实客户端 IP，客户端伪造的 XFF 左侧项不会被采信；
> 对端不在可信列表时，所有代理头一律忽略（按直连 IP 限流）。详见 [真实客户端 IP 与防 XFF 伪造](ip-and-proxy.md)。

> 注意：仓库内 `config.json` 默认为无服务器平台开启 `trust_proxy_headers` 与
> `secure_cookies`。位于 Nginx/Cloudflare 之后时两者保持 `true` 并配好 `trusted_proxies`；
> 本地 / VPS 走 HTTP 且**无反向代理**时才把两者改回 `false`（HTTP 下 Secure Cookie
> 会被浏览器拒绝，直连时也没有代理头需要采信）。

```bash
# 启用并重载
sudo ln -s /etc/nginx/sites-available/rusin-note /etc/nginx/sites-enabled
sudo nginx -t && sudo systemctl reload nginx
sudo ufw allow 'Nginx Full'
```

## 5. 启用 WAF（可选）

需要 nginx + ModSecurity + OWASP CRS 前置拦截攻击流量，见 [反向代理 WAF](waf.md)。
