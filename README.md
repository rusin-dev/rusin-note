> [!IMPORTANT]
>
> 注：如果您是 rusin-dev（本组织）的成员，想要贡献，请参见[协作指南](https://github.com/rusin-dev/rusin-note?tab=contributing-ov-file)并查看 [todo](https://github.com/rusin-dev/rusin-note/blob/main/todo.md)，如果您不是本组织的，可以加入或开个 Issue。

<div align="center">
    <a href="https://github.com/rusin-dev/rusin-note"><img width="15%" alt="logo" src="./image/logo.png" /></a>
    <h1><b>Rusin-Note</b></h1>
    <p><em>🖊︎ 一个受 note.ms 启发的轻量级云端剪贴板项目，支持 VPS 与无服务器（Serverless）部署，开箱即用。</em></p>
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

![屏幕截图](https://github.com/rusin-dev/rusin-note/blob/main/image/screenshots1.png)

## 产品特性

- **开箱即用的云端剪贴板**：基于 Flask 的轻量实现，可部署在 VPS 或 Vercel / AWS Lambda 等无服务器平台，用浏览器即可快速保存和访问文本内容。
- **公开与私有笔记**：支持随机短路径公开笔记，也支持访客账号下的私有笔记列表，兼顾临时分享和个人留存。
- **安全分享链接**：可为用户笔记生成带随机 token 的分享链接，并支持分享内容写回，便于跨设备协作。
- **Markdown 与 LaTeX 渲染**：只读页面和犇犇动态支持 Markdown、KaTeX 公式与 Pygments 代码高亮（代码块自动带行号），适合保存代码片段、说明文档和数学内容。编辑页实时渲染可手动开关。
- **大纲预览**：只读页自动提取 `h1`-`h6` 标题生成目录——宽屏显示右侧大纲栏、窄屏显示悬浮按钮 + 侧滑抽屉，点击平滑定位到对应章节，滚动时自动高亮当前所在章节；编辑页实时预览栏头部也有「大纲」下拉，随输入实时更新。纯客户端实现，无标题时自动隐藏。
- **笔记快捷引用（`#` 引用）**：参考 GitHub Issues——在自己的私有笔记编辑页输入 `#` 会弹出自动补全列表（按笔记 ID 与首行标题模糊匹配、最近编辑优先），选中即插入 `#笔记ID`；渲染后自动变成指向该笔记的链接（悬停可见标题预览）。公开笔记中的 `#ID` 同样会解析为公开笔记链接。代码块内的 `#include` 等内容不受影响。
- **笔记图床**：编辑器支持粘贴/拖拽上传图片，自动压缩存储，笔记中以 Markdown 语法引用，公开可读无需登录。
- **笔记附件**：支持上传任意文件类型（可执行文件除外），默认单文件 10MB、每用户 10MB 配额（可在 `config.json` 调整），附件管理页支持拖拽上传，笔记中以链接形式引用。
- **犇犇动态**：内置轻量动态流，登录用户可发布内容，未登录用户可浏览，支持实时预览、分页加载和发布冷却。
- **功能开关（Feature Flags）**：管理员在 `/admin/features` 用滑块开关启用/停用站点功能（公开笔记、犇犇、分享链接、开放注册、快捷引用、笔记标签、笔记文件夹、笔记置顶、笔记图床、笔记附件、Markdown 标题锚点、LaTeX、代码高亮、头像），保存后立即生效、无需重启；启用的功能会在 `/count` 数据汇总页呈现，停用的功能入口自动隐藏、路由直接 404。
- **多语言界面**：内置简体中文与 English，可手动切换，也可按浏览器语言自动选择。
- **部署友好**：配置集中在 `config.json`，支持笔记过期清理、会话超时、密码策略、反向代理真实 IP、HTTPS Cookie 等常见部署选项。无服务器部署时数据可接入外部 KV 存储（Vercel KV / Upstash），冷启动不丢数据。
- **基础防护完善**：包含 CSRF 防护、请求限流、保存限流、注册限流、内容安全清洗和代理头信任开关，降低公开部署风险。

## 快速开始

### 要求

python 版本 $\geq$ 3.10。

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

#### 方式一：Vercel（无服务器，推荐）

[![Deploy to Vercel](https://vercel.com/button)](https://vercel.com/new/clone?repository-url=https%3A%2F%2Fgithub.com%2Frusin-dev%2Frusin-note&&env=RUSIN_SECRET_KEY)

项目已内置 Vercel 配置（`vercel.json` + `api/index.py`），零配置即可部署：

1. 在 [Vercel](https://vercel.com) 导入本仓库（Framework Preset 选择 **Other** 即可，Python 运行时自动识别）。
2. 存储后端二选一：
   - **Neon（PostgreSQL）（推荐）**：在 Vercel 的 Storage / Marketplace 绑定 [Neon](https://vercel.com/marketplace/neon)，Vercel 会自动注入 `DATABASE_URL` 环境变量（Vercel KV 已停服，这是目前 Vercel 官方推荐的持久化方案）；
   - **Upstash Redis**：在 Vercel Marketplace 安装 Upstash Redis，手动把 `KV_REST_API_URL` 与 `KV_REST_API_TOKEN` 填入项目环境变量。
   - 两者都设置时优先用 Upstash。
3. 在项目设置中新增环境变量 `RUSIN_SECRET_KEY`（任意随机长字符串，用于会话/CSRF 签名，**必填**；不设置则每次冷启动随机，登录态会失效）。
4. 部署完成后，数据（笔记、用户、会话、分享、犇犇）全部存于 Neon/Upstash，多实例共享、冷启动不丢。

可选：设置 `REDIS_URL`（Redis 连接串，如 Upstash 或自建 Redis）后，页面缓存切换为共享 Redis、限流计数也在多实例间共享；不设置时页面缓存用进程内 SimpleCache、限流按实例内存计数（Zeabur 上的用法见下方章节）。

> 提示：无服务器平台默认 `trust_proxy_headers: true`、`secure_cookies: true`（已写入 `config.json`）。本地开发如需关闭请自行修改。

#### 方式二：AWS Lambda（无服务器）

项目根目录提供 `lambda_handler.py`（基于 Mangum 适配 WSGI）：

1. 打包仓库上传（包含 `templates/`、`config.json` 等）；
2. 处理程序设为 `lambda_handler.handler`，配 API Gateway 代理集成；
3. 环境变量与 Vercel 相同（`KV_REST_API_URL` / `KV_REST_API_TOKEN` / `RUSIN_SECRET_KEY`）；
4. 内存建议 ≥ 512MB（Markdown 渲染需要）。

#### 方式三：VPS / 传统服务器

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

    > 使用 Nginx/Cloudflare 反代后，请将 `config.json` 中的 `trust_proxy_headers` 设为 `true`，
    > 服务端才会信任代理头按真实客户端 IP 限流（默认关闭以杜绝伪造头绕过限流）。
    > 代理头可信度从高到低：`CF-Connecting-IP`（Cloudflare 直连）→ `X-Real-IP`（Nginx）→ `X-Forwarded-For` 最右一项（Nginx 追加的真客户端），客户端伪造的 XFF 左侧项不会被采信。

    > 注意：仓库内 `config.json` 默认已为无服务器平台开启 `trust_proxy_headers` 与
    > `secure_cookies`，VPS 部署请按需改回 `false`（HTTP 环境下 Secure Cookie 会被浏览器拒绝）。

    ```bash
    # 启用并重载
    sudo ln -s /etc/nginx/sites-available/rusin-note /etc/nginx/sites-enabled
    sudo nginx -t && sudo systemctl reload nginx
    sudo ufw allow 'Nginx Full'
    ```

#### Zeabur VPS 自动部署

使用 Zeabur 从 GitHub 自动部署时，应用目录会在每次部署时重新构建。为了避免剪贴板、用户、分享链接和犇犇动态被清空，请把运行数据写入持久化卷：

1. 在 Zeabur 项目中打开当前服务。
2. 进入 `Storage` / `Volumes`，新增一个 Volume。
3. 将 Volume 挂载路径设置为 `/data`。
4. 进入 `Environment Variables`，新增环境变量 `RUSIN_DATA_DIR=/data`。
5. 重新部署服务。

不要将 Volume 挂载到项目根目录，否则可能覆盖部署出来的应用代码。设置完成后，运行数据会保存在 `/data` 下：

```plaintext
/data/notes/
/data/users.json
/data/sessions.json
/data/shares.json
/data/benben.json
/data/log/
```

#### Zeabur 启用 Redis（页面缓存 + 共享限流）

Zeabur 是 PaaS 平台，不需要也不建议在容器里 `apt install redis`（构建产物每次重新部署会重建，装了也存不住）；标准做法是添加一个托管 Redis 服务，Zeabur 会自动把连接信息注入到其他服务：

1. 在 Zeabur 项目中打开 **Market** / **Marketplace**，搜索并添加 **Redis** 服务（内置 `redis/redis-stack-server` 镜像，Zeabur 会为它生成随机密码）。
2. 添加完成后，Zeabur 会自动向项目内其他服务注入 `REDIS_CONNECTION_STRING`、`REDIS_HOST`、`REDIS_PORT`、`REDIS_PASSWORD` 等变量（也可在 Redis 服务的「操作指南/Instructions」里查看连接信息）。
3. 回到本服务，进入 **Variables / 环境变量**，新增变量（跨服务引用，自动拼出带密码的连接串）：

   ```plaintext
   REDIS_URL = ${REDIS_CONNECTION_STRING}
   ```

   等价于 `redis://:密码@服务名:6379`。
4. 重新部署服务。启动时应用会主动 `PING` Redis：连通则页面缓存（首页/笔记/犇犇等）切换为 Redis 共享后端、限流计数也存入 Redis（多实例共享）；未连通则日志输出 `Redis 缓存不可达，已降级到 SimpleCache` 并退回进程内缓存，不影响功能。

> 说明：Redis 只负责缓存与限流；剪贴板、用户、分享、犇犇等业务数据仍由上面挂载的 `/data` 卷（`file` 后端）保存，两者互不影响。若追求数据多实例共享 / 不丢，可改用 `postgres` 或 `upstash` 后端（见下节）。

### 存储后端说明（无服务器关键）

存储层（`app/storage.py`）提供四种后端，由 `RUSIN_STORAGE` 环境变量显式指定，未指定时自动识别：

| 后端 | 启用方式 | 说明 |
|---|---|---|
| `file` | 默认（本地/VPS） | 数据写入 `RUSIN_DATA_DIR`（默认当前目录），布局与上表一致 |
| `upstash` | 设置 `KV_REST_API_URL` + `KV_REST_API_TOKEN`（Upstash Redis 的 REST 接口） | 数据存于外部 KV，多实例共享、冷启动不丢；纯 HTTPS 请求，任意支持 Python 的无服务器平台可用 |
| `postgres` | 设置 `DATABASE_URL`（Neon / 任意 PostgreSQL，Vercel 绑定 Neon 后自动注入） | 数据存于 PostgreSQL 表（`storage_kv` / `storage_notes`），多实例共享、冷启动不丢；跨实例互斥用 PG advisory lock |
| `memory` | `RUSIN_STORAGE=memory`（无服务器平台未配置上述存储时自动启用） | 纯内存，重启/冷启动清空，适合体验或临时部署 |

自动识别优先级：显式 `RUSIN_STORAGE` > `KV_REST_API_URL`+`KV_REST_API_TOKEN`（upstash）> `DATABASE_URL`（postgres）> 无服务器平台（memory）> 本地（file）。

- 犇犇动态已从纯内存改为持久化（外部存储可用时重启不丢，最多保留 `benben.max_posts` 条，默认 200）。
- 无服务器环境（检测到 `VERCEL` / `NETLIFY` / `AWS_LAMBDA_FUNCTION_NAME` 环境变量）不启动后台守护线程，清理任务改为请求内机会式执行；日志回退到 stderr（进入平台日志流）。
- `RUSIN_SECRET_KEY` 在无服务器平台必须设置；未设置时若后端可持久化（file/upstash/postgres）会自动生成并存储，否则退回随机密钥（重启后登录态失效）。
- 环境变量清单见 `.env.example`。

## 插件系统

插件以 zip 包形式分发：把 `*.plugin.zip` 投放到运行时目录（`RUSIN_DATA_DIR`）即可，服务启动时自动解压安装并加载其中的 Flask 蓝图，安装完成后插件包自动删除。**无服务器部署（只读文件系统）不支持插件系统。**

### 插件包结构

```plaintext
+ desc.json          元信息
+ icon.ico           图标（可选，文件名须与 desc.icon 一致）
+ src/
  + __init__.py      必须定义 APP_ROUTER / OVERRIDE / ENV_VARIBLES
  + app.py           必须包含 Blueprint 实例（APP_ROUTER 可指向其它 .py 文件）
  + templates/       模板（以蓝图名为命名空间，避免与主站/其它插件重名覆盖）
  + static/          静态文件（访问路径 /<蓝图名>/static/<文件名>）
```

`desc.json` 示例：

```json
{
  "name": "示范插件",
  "version": "v0.1",
  "upstream_repo": "https://github.com/rusin-dev/template-plug",
  "icon": "icon.ico",
  "namespace": "template_plug",
  "auth_token": "sk-ccccddddddd"
}
```

- `namespace`：命名空间（`^[a-zA-Z0-9_\-]+$`），也是安装目录 `plugins/<namespace>` 与冲突检查的依据；
- `upstream_repo`：上游仓库，用于自动更新（可直接指向 zip 文件；GitHub 仓库地址会自动尝试 `main` / `master` 归档）；
- `auth_token`：认证令牌。**缺失时插件会被拒绝安装**，如确认信任须以 `--skip-auth` 启动参数（或环境变量 `RUSIN_PLUGIN_SKIP_AUTH=1`）显式放行。

`src/__init__.py` 模板：

```python
APP_ROUTER = "app.py"    # 承载 Blueprint 的文件（缺省 app.py）
OVERRIDE = False         # 复写主站静态文件的声明，形如
# OVERRIDE = {"source": {"static/dst.css": "static/src.css"}}
ENV_VARIBLES = []        # 声明依赖的环境变量名（缺失时启动日志警告）
```

### 加载与更新流程

- **Phase 1（安装）**：启动时扫描运行时目录的 `*.plugin.zip`，解压校验后安装到 `plugins/<namespace>/`，并把 `auth_token` 与 `last_update` 回写进 `desc.json`，随后删除插件包。校验项：zip 路径穿越与解压体积防护、根目录只允许 `desc.json` / 图标 / `src/`、auth_token 检查、命名空间冲突检查（不同来源的插件抢占同一命名空间必须声明 `OVERRIDE`，同源更新不受限制）、`src/app.py` 必须含 Blueprint（缺失记错误日志、插件不加载，不影响主站启动）。
- **Phase 2（更新）**：后台线程（默认每 6 小时）逐个检查 `plugins/*/desc.json`，`last_update` 距今超过 3 天则请求 `upstream_repo`（3 秒超时）；拿到新包后落为 `<namespace>.plugin.zip` 并重跑 Phase 1——新插件热加载，已加载插件更新文件后提示重启生效。

### 配置与安全

- config.json `plugins` 段：`enabled`（总开关，默认 `true`）、`update_interval_hours`（更新检查周期，默认 6）、`update_stale_days`（触发上游检查的间隔天数，默认 3）。
- 插件是在服务进程内执行的 Python 代码，**只安装可信来源的插件**：auth_token 机制即为服务端校验插件来源预留（缺失时须显式 `--skip-auth` 放行）。
- 插件蓝图在短链 catch-all 之前注册，插件的单段路由不会被 `/<id>` 抢匹配；蓝图名与主程序或其它插件冲突时该蓝图拒绝加载并在日志报错。
- 插件自己的 POST 表单需自行包含 `{{ csrf_token() }}`（全站启用 CSRF 防护）。

## 项目结构

```plaintext
rusin-note:.
│  config.json（配置项）
│  contributing.md（协作指南）
│  Disclaimer-en.md（英文免责声明）
│  Disclaimer.md（免责声明）
│  favicon.ico
│  README.md
│  README_en.md
│  requirements.txt（Python 依赖）
│  zbpack.json（打包配置）
│  vercel.json（Vercel 无服务器部署配置）
│  lambda_handler.py（AWS Lambda 入口）
│  .env.example（环境变量示例）
│
├─api（无服务器入口）
│      index.py（Vercel Python 入口）
│
├─app（核心代码）
│  │  __init__.py
│  │  __main__.py（入口：python3 -m app）
│  │  auth.py（密码哈希与会话认证）
│  │  background.py（后台清理任务）
│  │  config.py（配置加载与全局常量）
│  │  extensions.py（Flask 扩展实例）
│  │  i18n.py（多语言支持）
│  │  logger.py（日志记录）
│  │  middleware.py（请求钩子与限流辅助）
│  │  notes.py（笔记操作与统计）
│  │  plugins.py（插件系统：zip 安装 / 蓝图加载 / 上游更新）
│  │  storage.py（存储层：file / memory / upstash / postgres 后端）
│  │  store.py（用户/会话/分享/犇犇数据存储）
│  │  theme.py（主题与静态资源辅助）
│  │  utils.py（通用工具函数）
│  │  wsgi.py（WSGI 入口）
│  │
│  └─views（蓝图与路由）
│          __init__.py（蓝图注册）
│          _helpers.py（视图辅助函数）
│          auth.py（登录与注册）
│          benben.py（犇犇动态）
│          home.py（首页）
│          share.py（分享页面）
│          static_routes.py（静态与说明页面）
│          user.py（用户与用户笔记）
│          world.py（公开笔记）
│          world_short.py（短链接公开笔记）
│
├─templates（Jinja2 模板）
│  │  base.html（基础布局）
│  │  count.html（统计页面）
│  │  disclaimer.html（免责声明页面）
│  │  home.html（首页）
│  │
│  ├─auth（认证页面）
│  ├─benben（犇犇页面）
│  ├─errors（错误页）
│  ├─notes（笔记页面）
│  ├─partials（公共片段）
│  └─share（分享页面）
│
├─image（图片资源）
│      logo.png
│
├─.github
│  │  issue-labeler.yml（Issue 标签配置）
│  │
│  ├─ISSUE_TEMPLATE（Issue 模板）
│  └─workflows（GitHub Actions）
│          auto-merge.yml（自动合并）
│          check.yml（检查）
│          codeql.yml（CodeQL 分析）
│          labeler.yml（自动打标签）
│          release.yml（发布）
│          trigger-fork-sync.yml（触发 Fork 同步）
│          upstream-sync.yml（上游同步）
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
- `global_cdn` 全局前端静态资源 CDN 基础地址。
   - 默认 `https://cdn.jsdmirror.cn`；

   前端资源统一从该地址拼接加载：FontAwesome 图标、marked 编辑器脚本、DOMPurify 清洗库与 KaTeX 公式（路径均为 `npm/` 形式，因此也兼容 `https://cdn.jsdelivr.net` 等 npm CDN）。可按网络环境在 config.json 中整体替换，无需改代码。
- `latex_render` LaTeX 公式渲染。
   - `enabled` ：是否开启，默认 `true`；
   - KaTeX 静态资源从 `global_cdn` 基础地址拼接（默认 jsdmirror，可换 jsdelivr 等）；

    开启后，Markdown 只读页面支持 `$...$` 行内公式与 `$$...$$` 块级公式（KaTeX 洛谷同款，客户端渲染，无需服务端依赖）。
- `code_highlight` 代码高亮（highlight.js，客户端渲染）。
   - `enabled` ：是否开启，默认 `true`；

    开启后，所有 Markdown 渲染处（笔记只读页、编辑页实时预览、犇犇动态、免责声明）的代码块自动语法高亮并显示行号，跟随站点浅色/暗色主题切换，无需服务端依赖。
- `note_refs` 笔记快捷引用（`#` 引用，见「产品特性」）。
   - `enabled` ：是否开启，默认 `true`；置 `false` 后编辑器不弹引用补全框、渲染时不把 `#ID` 转为链接；
   - `search_limit` ：补全接口单次最多返回条数，默认 `8`；
   - `scan_limit` ：补全搜索最多扫描的笔记数（按修改时间倒序），默认 `100`。upstash / postgres 等远程存储后端每篇笔记需一次网络读取，笔记较多时可适当调低。
- `avatar` 用户头像（通过第三方服务生成，显示在导航栏当前用户、犇犇动态发布者与用户笔记列表标题处）。
   - `enabled` ：是否开启，默认 `true`；置 `false` 后完全关闭头像显示；
   - `url_template` ：头像 URL 模板，默认 `https://cn.cravatar.com/avatar/{hash}?d=identicon&f=y`。支持两个占位符：`{hash}`（`md5(用户名)` 小写十六进制）、`{username}`（URL 编码后的用户名）。由于本站用户没有邮箱，默认用 `md5(用户名)` 作为哈希，`d=identicon` 会让 Gravatar 系服务为每个哈希生成确定性的几何头像；也可换成其他按用户名生成头像的服务（如 DiceBear：`https://api.dicebear.com/9.x/identicon/svg?seed={username}`）；
   - `size` ：模板中的默认尺寸（当前仅作为备用值，模板内按位置使用固定尺寸）。
- `attachments` 笔记附件（编辑器附件按钮上传，/attachment/<u>/<id> 公开下载）。
   - `enabled` ：是否开启，默认 `true`；置 `false` 后编辑器不显示附件按钮、附件管理页返回 404；
   - `max_size_kb` ：单个附件上限（KB），默认 `10240`（10MB）；
   - `max_total_kb` ：每用户附件总配额（KB），默认 `10240`（10MB）；
   - `blocked_extensions` ：禁止上传的文件扩展名列表（黑名单模式），默认包含 `.exe`、`.bat`、`.sh`、`.zip` 等可执行文件与压缩包。  
- `password_policy`：密码策略，定义访客密码的复杂度要求。  
   - `min_length`：密码最小长度，默认 `8`；  
   - `max_length`：密码最大长度，默认 `128`（硬上限 `128`，防止超长密码进入 PBKDF2 慢哈希消耗 CPU）；  
   - `require_uppercase`：是否必须包含大写字母，默认 `true`；  
   - `require_lowercase`：是否必须包含小写字母，默认 `true`；  
   - `require_digits`：是否必须包含数字，默认 `true`；  
   - `require_special`：是否必须包含特殊符号（不含 `/ \ ( ) " '`），默认 `true`； 
- `RUSIN_DATA_DIR`：可选环境变量，用于指定运行数据目录，默认当前项目目录（仅 `file` 后端使用）。

    笔记、用户、会话、分享和日志会写入该目录下的 `notes/`、`users.json`、`sessions.json`、`shares.json`、`benben.json`、`log/`。在 Zeabur 等自动部署平台上建议挂载持久化卷到 `/data`，并设置 `RUSIN_DATA_DIR=/data`，避免每次部署清空剪贴板数据。
- `RUSIN_STORAGE`：可选环境变量，显式指定存储后端：`file`（本地/VPS，默认）、`memory`（纯内存）、`upstash`（外部 KV）、`postgres`（Neon/PostgreSQL）。未指定时自动识别：设置了 `KV_REST_API_URL` / `KV_REST_API_TOKEN` 用 `upstash`，设置了 `DATABASE_URL` 用 `postgres`，检测到无服务器平台环境变量用 `memory`，否则 `file`。详见上方「存储后端说明」。
- **多语言**：界面支持简体中文与 English。导航栏右侧提供语言切换链接（`/lang/zh` / `/lang/en`），选择后通过 Cookie（`rusin-lang`）记住偏好；未设置时自动按浏览器 `Accept-Language` 判断，默认中文。切换后全站文本（导航、按钮、提示、错误信息、犇犇预览等）即时切换语言。 
- `benben` 犇犇动态（`/benben`，登录可发布、未登录只读）。
   - `max_length`：单条犇犇最大长度（单位：**字符**），默认 `1024`（约 1KB）；
   - `page_size`：每批加载条数，默认 `50`；
   - `cooldown_seconds`：单个用户两次发布犇犇的最小间隔（单位：**秒**），默认 `3`；
   - `max_height_px`：犇犇内容渲染后的最大显示高度（单位：**px**），默认 `1000`，超出部分在内容区内滚动；
   - `max_posts`：犇犇持久化条数上限，默认 `200`（外部存储单键体积控制，超出丢弃最旧）；

   内容支持 Markdown 与 LaTeX 公式（`$...$` / `$$...$$`，依赖 `latex_render` 开关），发布表单带实时预览（客户端 marked.js 渲染，预览同样过滤危险标签与链接）；渲染时经 bleach 安全清洗防止 XSS；每页显示 `page_size` 条，通过「加载更多」分批加载，加载与发布均受请求速率限制（GET/POST 限流），发布还受单用户冷却限制（`cooldown_seconds`）；每条犇犇头部展示发布者 IP（按 `trust_proxy_headers` 决定是否信任代理头，旧数据无 IP 字段时不显示）。
- `plugins` 插件系统（详见上方「插件系统」章节）。
   - `enabled`：是否启用，默认 `true`（无服务器环境自动禁用）；
   - `update_interval_hours`：后台更新检查线程的轮询周期（单位：**小时**），默认 $6$；
   - `update_stale_days`：距 `last_update` 超过该天数才请求 `upstream_repo`（单位：**天**），默认 $3$。
- `features` / `admin_users` 功能开关（#90）。
   - `features`：各功能的**默认开关**，包括 `world_notes`（公开笔记与短链）、`benben`（犇犇动态）、`share_links`（分享链接）、`open_register`（开放注册）、`note_tags`（笔记标签）、`note_folders`（笔记文件夹）、`note_pins`（笔记置顶）、`note_images`（笔记图床）、`note_attachments`（笔记附件）、`heading_anchors`（Markdown 标题锚点），均默认 `true`。历史功能（`note_refs`、`latex_render`、`code_highlight`、`avatar`）的默认值沿用各自原有配置段；
   - `admin_users`：功能开关管理员用户名列表；也可用环境变量 `RUSIN_ADMIN` 指定（多个用户名逗号分隔，两者取并集）。

   管理员登录后可在 `/admin/features` 用滑块开关切换各功能的启用状态，保存后立即生效（无需重启）：运行时状态持久化在存储后端（file 后端即数据目录下的 `feature_flags.json`），多实例部署经约 5 秒的缓存 TTL 自动收敛；停用的功能路由直接 404、导航与首页入口自动隐藏。全部功能开关状态会呈现在 `/count` 数据汇总页的「功能状态」区（未设管理员时该区对所有人可见，但无人能修改开关）。注意：无服务器 `memory` 后端不持久，实例冷启动后回退到 `config.json` 默认值。
