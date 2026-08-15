> [!IMPORTANT]
>
> 注：如果您是 rusin-dev（本组织）的成员，想要贡献，请参见[协作指南](https://github.com/rusin-dev/rusin-note/blob/main/contributing.md)，如果您不是本组织的，可以加入或开个 Issue。

<div align="center">
    <a href="https://github.com/rusin-dev/rusin-note"><img width="15%" alt="logo" src="./image/logo.png" /></a>
    <h1><b>Rusin-Note</b></h1>
    <p><em>🖊︎ 一个受 note.ms 启发的轻量级云端剪贴板项目，专为 VPS 部署设计，开箱即用。</em></p>
    <p>
        简体中文 | <a href="https://github.com/rusin-dev/rusin-note/blob/main/README_en.md">English</a> | <a href="https://note.rusin7.com">Demo</a>
    </p>
    <p align="center">
        <a href="https://github.com/rusin-dev/rusin-note/blob/main/LICENSE"><img src="https://img.shields.io/github/license/rusin-dev/rusin-note" alt="License" /></a>
        <a href="https://github.com/rusin-dev/rusin-note/releases"><img src="https://img.shields.io/github/release/rusin-dev/rusin-note" alt="latest version" /></a>
        <a href="https://github.com/rusin-dev/rusin-note/releases"><img src="https://img.shields.io/github/downloads/rusin-dev/rusin-note/total?color=%239F7AEA&logo=github" alt="Downloads" /></a>
        <a href="https://github.com/rusin-dev/rusin-note/stargazers"><img src="https://img.shields.io/github/stars/rusin-dev/rusin-note" alt="Stars" /></a>
        <a href="https://github.com/rusin-dev/rusin-note/network/members"><img src="https://img.shields.io/github/forks/rusin-dev/rusin-note" alt="Forks" /></a>
        <a href="https://github.com/rusin-dev/rusin-note/actions/workflows/check.yml">
        <img src="https://github.com/rusin-dev/rusin-note/actions/workflows/check.yml/badge.svg" alt="CI Build"></a>
        <a href="https://github.com/rusin-dev/rusin-note/actions/workflows/auto-merge.yml">
        <img src="https://github.com/rusin-dev/rusin-note/actions/workflows/auto-merge.yml/badge.svg?branch=main" alt="Auto merge"></a>
        <a href="https://pypi.org/project/pandera/"><img src="https://img.shields.io/pypi/v/pandera.svg" alt="PyPI version shields.io"></a>
        <a href="https://www.repostatus.org/#active"><img src="https://img.shields.io/badge/repo%20status-Active-Green" alt="Project Status: Active – The project has reached a stable, usable state and is being actively developed."></a>
        <a href="https://pypi.python.org/pypi/pandera/"><img src="https://img.shields.io/pypi/pyversions/pandera.svg" alt="PyPI pyversions">
        </a>
    </p>
</div>

## 快速开始

### 要求

python 版本 $\geq 3.10$。

### 本地开发

1. 克隆代码

    ```bash
    git clone https://github.com/rusin-dev/rusin-note.git
    cd rusin-note
    ```

2. 安装依赖
   
   ```bash
   pip install -r requirements.txt
   ```

3. 启动服务

    ```bash
    python3 -m app
    ```

    然后打开 <https://localhost:8080> 查看效果。

### 线上部署

连接你的服务器，然后

1. 克隆代码

    ```bash
    git clone https://github.com/rusin-dev/rusin-note.git
    cd rusin-note
    ```

2. 安装依赖
   
   ```bash
   pip install -r requirements.txt
   ```

3. 启动服务

    ```bash
    python3 -m app

    # 后台运行
    nohup python3 -m app > app.log 2>&1 &
    ```

4. 配置 Nginx（可选）

    创建站点配置

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
        }
    }
    ```

    > 使用 Nginx 反代后，请将 `config.json` 中的 `trust_proxy_headers` 设为 `true`，
    > 服务端才会信任 `X-Real-IP` 头按真实客户端 IP 限流（默认关闭以杜绝伪造头绕过限流）。

    ```bash
    # 启用并重载
    sudo ln -s /etc/nginx/sites-available/rusin-note /etc/nginx/sites-enabled
    sudo nginx -t && sudo systemctl reload nginx
    sudo ufw allow 'Nginx Full'
    ```

## 项目结构

```plaintext
rusin-note:.
│  README_en.md
│  config.json（配置项）
│  Disclaimer.md（免责声明）
│  LICENSE
│  README.md
│  contribute.md（协作指南）
│  
├─app（核心代码）
│  │  __init__.py
│  │  __main__.py（入口：python3 -m app）
│  │  config.py（配置加载与全局常量）
│  │  store.py（用户/会话/分享数据存储）
│  │  auth.py（密码哈希与会话认证）
│  │  notes.py（笔记文件操作与统计）
│  │  ratelimit.py（IP 限流）
│  │  theme.py（暗色模式与 favicon）
│  │  templates.py（页面渲染）
│  │  handlers.py（HTTP 路由处理）
│  │  server.py（服务器启动）
│  │
├─image
│      logo.png
│      
├─.github
│  └─workflows
│          check.yml（测试 PR）
│          auto-merge.yml（自动合并）
│          labeler.yml（自动打标签）
│          
└─notes
```

### 配置项解析

- `max_note_size_kb`：笔记最大大小（单位：**KB**）默认 $512$（即 $0.5$ MB）。
- `sitename`：网页名称。填你的站点名。
- `rate_limit` 速率限制。
   
   - `window_seconds` ： 时间 $t$，默认 $60$；
   - `max_requests` ：请求数 $s$，默认 $30$;

   $t$ 秒内最大请求 $s$ 次。
- `get_rate_limit` GET 请求独立限流。
   - `window_seconds` ：时间 $t$，默认 $60$；
   - `max_requests` ：请求数 $s$，默认 $45$;

   $t$ 秒内 GET 请求最大 $s$ 次（含页面加载、favicon 等）。
- `save_rate_limit` 保存类 POST 独立限流（笔记保存/分享写回）。
   - `window_seconds` ：时间 $t$，默认 $60$；
   - `max_requests` ：请求数 $s$，默认 $120$;

   $t$ 秒内保存笔记最多 $s$ 次，与全局 POST 限流（`rate_limit`）互不干扰，避免频繁保存被误伤。
- `register_rate_limit` 注册速率限制（单IP注册账号限制）。
   - `window_seconds` ：时间 $t$，默认 $120$；
   - `max_requests` ：请求数 $s$，默认 $1$;

   $t$ 秒内单个IP最多注册 $s$ 个账号，防止恶意批量注册。
- `trust_proxy_headers`：是否信任反向代理传递的 `X-Forwarded-For` / `X-Real-IP` 头，默认 `false`。
  
  **安全说明**：默认关闭，限流一律基于 TCP 直连 IP，防止客户端伪造请求头绕过限流。仅当部署在可信反向代理（如 Nginx）之后才置为 `true`。
- `secure_cookies`：会话 Cookie 是否附加 `Secure` 标志，默认 `false`。

  **安全说明**：仅当通过 HTTPS 访问时置为 `true`，否则浏览器会拒绝在 HTTP 下回传 Cookie。
- `id_generation` 随机 url 配置。
   - `length` ：长度，默认 $4$；
   - `use_uppercase` ：是否使用大写字母，默认 `false`；
   - `use_lowercase` ：是否使用小写字母，默认 `true`；
   - `use_digits` ：是否使用数字，默认 `false`；
- `share_token` 分享链接 token 配置。
   - `length` ：长度，默认 $64$；
   - `use_uppercase` ：是否使用大写字母，默认 `true`；
   - `use_lowercase` ：是否使用小写字母，默认 `true`；
   - `use_digits` ：是否使用数字，默认 `true`；
- `session_timeout` 单次会话时间。
   - `enabled` ：是否开启，默认 `false`；
   - `minutes` ：设定时长，（单位：**分钟**）默认 $15$；

    当时间超过设定时，将登出访客账号。
- `note_expiration` 笔记自动清除（剪贴板超过保存时间自动删除）。
   - `enabled` ：是否开启，默认 `false`；
   - `hours` ：保存时长（单位：**小时**）默认 $24$；

    开启后，超过设定小时数未被修改的剪贴板（公开+私有）将被后台线程自动删除，每 30 分钟扫描一次。
- `latex_render` LaTeX 公式渲染。
   - `enabled` ：是否开启，默认 `true`；
   - `cdn` ：KaTeX 静态文件基础目录，默认 jsdelivr（国内可换用 BootCDN：`https://cdn.bootcdn.net/ajax/libs/katex/0.16.11`）；

    开启后，Markdown 只读页面支持 `$...$` 行内公式与 `$$...$$` 块级公式（KaTeX 洛谷同款，客户端渲染，无需服务端依赖）。
- `password_policy`：密码策略，定义访客密码的复杂度要求。  
   - `min_length`：密码最小长度，默认 `8`；  
   - `max_length`：密码最大长度，默认 `128`（硬上限 `128`，防止超长密码进入 PBKDF2 慢哈希消耗 CPU）；  
   - `require_uppercase`：是否必须包含大写字母，默认 `true`；  
   - `require_lowercase`：是否必须包含小写字母，默认 `true`；  
   - `require_digits`：是否必须包含数字，默认 `true`；  
   - `require_special`：是否必须包含特殊符号（不含 `/ \ ( ) " '`），默认 `true`； 
- **多语言**：界面支持简体中文与 English。导航栏右侧提供语言切换链接（`/lang/zh` / `/lang/en`），选择后通过 Cookie（`rusin-lang`）记住偏好；未设置时自动按浏览器 `Accept-Language` 判断，默认中文。切换后全站文本（导航、按钮、提示、错误信息、犇犇预览等）即时切换语言。 
- `benben` 犇犇动态（`/benben`，登录可发布、未登录只读）。
   - `max_length`：单条犇犇最大长度（单位：**字符**），默认 `1024`（约 1KB）；
   - `page_size`：每批加载条数，默认 `50`；
   - `cooldown_seconds`：单个用户两次发布犇犇的最小间隔（单位：**秒**），默认 `3`；
   - `max_height_px`：犇犇内容渲染后的最大显示高度（单位：**px**），默认 `1000`，超出部分在内容区内滚动；

   内容支持 Markdown 与 LaTeX 公式（`$...$` / `$$...$$`，依赖 `latex_render` 开关），发布表单带实时预览（客户端 marked.js 渲染，预览同样过滤危险标签与链接）；渲染时经 bleach 安全清洗防止 XSS；每页显示 `page_size` 条，通过「加载更多」分批加载，加载与发布均受请求速率限制（GET/POST 限流），发布还受单用户冷却限制（`cooldown_seconds`）；每条犇犇头部展示发布者 IP（按 `trust_proxy_headers` 决定是否信任代理头，旧数据无 IP 字段时不显示）。