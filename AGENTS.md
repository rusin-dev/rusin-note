# Rusin-Note 项目指南

## 项目简介
基于 Flask 的轻量级云端剪贴板，支持公开短链笔记、用户私有笔记、分享链接、动态（犇犇）、评论、首页工作台待办与组织/团队协作。可部署在 VPS（sqlite/file 后端）或 Vercel / AWS Lambda 等无服务器平台（upstash / postgres 后端接入外部存储）。

## 技术栈
- Python 3.10+, Flask 3, Flask-WTF, Flask-Limiter, Flask-Caching, waitress/gunicorn, mangum（Lambda 适配）
- Markdown 渲染：markdown + pymdown-extensions + bleach（防 XSS）+ Pygments（服务端代码着色）；客户端 highlight.js 兜底未识别语言并生成行号
- 数据校验/处理：psycopg（PostgreSQL）、redis（可选缓存/限流共享）；图片格式校验用自研魔数嗅探（`app/images.py`，不依赖 Pillow）
- 前端：Jinja2 模板，支持中英双语（i18n），无独立 JS/CSS 文件

## 常用命令
- 开发运行：`python3 -m app`（监听 8080，默认 sqlite 后端）
- 生产部署（VPS）：`gunicorn 'app.wsgi:app' -b 0.0.0.0:$PORT --workers 2 --threads 4`
- 无服务器部署（Vercel）：`vercel.json` + `api/index.py` 已内置，绑定 Neon（自动注入 `DATABASE_URL` → postgres 后端）或 Upstash（`KV_REST_API_URL` + `KV_REST_API_TOKEN`），并设置 `RUSIN_SECRET_KEY` 即可
- 无服务器部署（AWS Lambda）：入口 `lambda_handler.handler`（Mangum）
- 数据目录：由环境变量 `RUSIN_DATA_DIR` 指定（默认 `data`；仅本地 sqlite/file 后端使用）
- 依赖安装：`pip install -r requirements.txt`
- 前端语法检查：`python tests/frontend_check.py`（校验 Jinja2 模板语法、模板内联 JS/CSS、JSON；CI 中由 `check.yml` 的 `frontend` job 自动执行）
- 端到端测试：统一放在 `tests/` 目录，使用 **pytest + logging**（`pip install -r requirements-dev.txt` 后运行 `pytest tests/`，如 `pytest tests/test_user_settings.py`）；`conftest.py` 会自动隔离临时 `RUSIN_DATA_DIR` 并清空运行时缓存

## 数据存储（重点：可插拔后端）
存储层统一在 `app/storage.py`（**统一数据接口**，所有业务模块只通过 `storage` 单例访问数据），后端由 `RUSIN_STORAGE` 显式指定或自动识别：

| 后端 | 启用 | 说明 |
|---|---|---|
| sqlite | 默认（本地/VPS） | SQLite 索引（`<DATA_DIR>/index.db`）用于快速列表/排序/检索/统计，具体内容 JSON 落盘于 `RUSIN_DATA_DIR`（默认 `data/`）；笔记为 `notes/<用户>/<ID>.json`，集合为 `users.json` 等；实现见 `app/storage_sqlite.py`，旧版 file 布局首次启动自动迁移 |
| file | `RUSIN_STORAGE=file` | 纯 JSON 文件落盘（兼容旧部署），布局同上但不含 `index.db` |
| upstash | `KV_REST_API_URL` + `KV_REST_API_TOKEN` | Upstash Redis REST API（纯 urllib，无驱动依赖），键统一加 `rusin:` 前缀，多实例共享 |
| postgres | `DATABASE_URL`（Neon / 任意 PostgreSQL，Vercel 绑定 Neon 自动注入） | psycopg 驱动，表 `storage_kv`（通用 KV）+ `storage_notes`（笔记）+ `storage_images` / `storage_attachments`（二进制）；跨实例互斥用 PG advisory lock |
| memory | `RUSIN_STORAGE=memory`（无服务器且未配以上存储时自动） | 纯内存，重启清空 |

自动识别优先级：显式 `RUSIN_STORAGE` > KV 环境变量（upstash）> `DATABASE_URL`（postgres）> 无服务器平台（memory）> 本地（sqlite）。

- 集合类 KV 键在 `storage.py` 的 `KV_FILE_MAP` 登记落盘文件名（`users.json`、`sessions.json`、`shares.json`、`benben.json`、`comments.json`、`note_tags.json`、`note_folders.json`、`note_pins.json`、`note_titles.json`、`todos.json`、`feature_flags.json`、`orgs.json`、`org_members.json`、`org_invites.json`、`org_join_requests.json`、`.secret_key`）；笔记键为 `note:<用户>:<ID>`，图床/附件键为 `img:` / `att:` 前缀（file/postgres 后端走原生二进制文件）。

- 统一接口在基类 `StorageBackend` 提供笔记元数据/检索能力：`note_title`、`list_notes_detailed`、`search_notes`、`notes_stats`（与后端无关的退化实现），SQLite 后端覆盖为单次索引查询（`notes.py` 的 `search_user_notes`/`get_stats` 与列表页据此避免逐篇读取内容）。

- 犇犇动态已改为持久化（最多 `benben.max_posts` 条，默认 200），不再纯内存。
- 写路径统一锁序：**threading.Lock（进程内）→ storage.lock（跨进程/跨实例）**，顺序颠倒会死锁（见 `store.flush_share_views` 注释）。
- 无服务器环境（`VERCEL`/`NETLIFY`/`AWS_LAMBDA_FUNCTION_NAME`）不启动后台线程，清理由 `middleware._opportunistic_cleanup()` 请求内机会式执行；日志回退 stderr。
- `RUSIN_SECRET_KEY` 必填于无服务器平台；可持久化后端会自动生成并存储（键 `secret_key`）。

## 关键安全约定
- **CSRF 防护**：全站启用，不要在任何表单中省略 `{{ csrf_token() }}`。
- **限流**：基于 IP，使用 Flask-Limiter；新增路由时务必添加 `@limiter.limit` 装饰器（另有 `ip_rate_limit` 全站每 IP 总上限，应用级作用域对所有路由生效）。限流存储可用 `REDIS_URL` 切换为共享 Redis。
- **单用户并发闸门（长连接防护，#191）**：IP 限流只约束「单位时间请求数」，拦不住「少量请求、超长时间占用」（如发起上千个队列、每个以 1KB/s 传输，或用 100 线程并行下载）。附件下载/上传因此额外经 `app/concurrency.py` 的进程内闸门限制**单用户同时在途数**（`attachments.max_concurrent_downloads` 默认 1 / `max_concurrent_uploads` 默认 1，即每账号 1 个下载队列 + 1 个上传队列；`0` = 不限）；`Slot.release()` 幂等，必须同时挂在生成器 `finally` 与 `Response.call_on_close` 上，异常/断开/正常结束三条路径都要归还名额。超限即拒绝（不排队，排队同样占 worker）：下载走全局 429 处理器（带 `Retry-After` + 文案），上传返回 429 JSON。计数在进程内，N 个 worker ≈ `N × 上限`。端到端测试：`pytest tests/test_attachments.py`
- **附件下载权限**：`/attachment/<u>/<id>` 默认**禁止匿名下载**（`attachments.allow_anonymous_download=false`，未登录 401 并提示登录），响应缓存为 `private`（避免共享缓存回放给匿名访客）；仅登录用户可下载，如需「仅本人可下载」须另加所有权校验（见 `app/views/static_routes.py` 注释与测试 B3）。
- **客户端 IP / 防 XFF 伪造**：`g.client_ip` 一律经 `app/ip_utils.py` 解析——仅当 TCP 直连对端命中 `trusted_proxies`（IP/CIDR 或预设 `loopback`/`private`/`cloudflare`，`"*"` 为不安全的兼容模式）时才采信 `X-Forwarded-For`/`X-Real-IP`/`CF-Connecting-IP`，且只接受合法 IP、XFF 从右往左解析。**不要**使用 `ProxyFix`，也不要直接读 `request.remote_addr` 或原始代理头做限流/冷却，否则可被伪造头绕过。`ip_blocklist` 直接 403，`ip_allowlist` 免限流（并支持 `RUSIN_TRUSTED_PROXIES`/`RUSIN_IP_ALLOWLIST`/`RUSIN_IP_BLOCKLIST` 环境变量）。端到端测试：`pytest tests/test_ip_limiter.py`
- **XSS 防护**：所有 Markdown 渲染必须通过 `utils.render_markdown_html`（内部使用 bleach 清洗）；GitHub 风格提示卡片（`> [!NOTE]` 等）在 utils 内以 treeprocessor 转为 `<details>`，输出前同样过 bleach——新增标签/属性时须同步 `allowed_tags`/`allowed_attrs` 白名单。
- **路径安全**：笔记 ID 和用户名必须符合正则 `^[a-zA-Z0-9_\-]+$`，避免路径穿越；后端键由 storage 层统一构造，解析用 `parse_note_key`。
- **Cookie**：生产环境应开启 `secure_cookies`（仓库 config.json 已默认开启，本地开发请关闭）。

## 架构要点
- 入口：`app/__main__.py`（waitress）或 `app/wsgi.py`（gunicorn）；无服务器：`api/index.py`（Vercel）、`lambda_handler.py`（Lambda）
- 核心模块：`storage.py`（存储后端抽象）、`store.py`（数据存储业务）、`auth.py`（认证）、`notes.py`（笔记操作）、`middleware.py`（请求上下文）、`ip_utils.py`（客户端 IP 安全解析 / 可信代理校验 / IP 名单）、`concurrency.py`（进程内并发闸门：单用户在途请求上限，供附件下载/上传使用）、`user_settings.py`（用户设置：简洁模式 / 修改密码 / 修改用户名，含数据迁移）、`plugins.py`（插件系统：zip 解压安装 / auth_token 校验 / 命名空间冲突检查 / 蓝图加载 / 上游更新线程）、`feature_flags.py`（功能开关：注册表 + 存储持久化 + `require_feature` 装饰器）
- 路由蓝图：home, auth, benben, static_routes, world, user, share, admin（`/admin/features` 功能开关管理）, **插件蓝图（在 views.register_blueprints 内注册）**, world_short（注意最后注册 catch-all）
- 用户设置（`/user/<u>/settings`，`app/user_settings.py`）：简洁模式（原导航栏切换按钮已并入，账号级偏好存 users.json，`middleware` 注入 `g.simple_mode` 服务端渲染 `<html class="simple-mode">`，页面缓存键含该标志）、修改密码（注销其它会话）、修改用户名（先复制笔记/图床/附件再迁移各存储用户标识，最后删旧数据）。端到端测试：`pytest tests/test_user_settings.py`
- 首页公告横幅：`app/views/home.py` 的 `index` 读取 `config.NOTICE_FILE`（仓库根目录 `NOTICE.txt`）首行并传入 `home.html`，内容非空时渲染 `.home-notice` 横幅（文本经 HTML 转义）；读取逻辑见 `utils.read_notice_first_line`，端到端测试 `pytest tests/test_home_notice.py`
- 功能开关（`app/feature_flags.py`，#90）：管理员（`RUSIN_ADMIN` 环境变量或 config.json `admin_users`）在 `/admin/features` 用滑块切换；运行时状态存 KV 键 `feature_flags`（file 后端即 `feature_flags.json`），进程内 5s TTL 缓存；停用功能路由 404、导航/首页入口隐藏，状态呈现于 `/count`。新增可开关功能：在 `FEATURES` 注册表登记 + 视图加 `@require_feature(key)`（必须放 `@bp.route` 之后、`@cache.cached`/`@limiter.limit` 之前）。
- 插件系统（`app/plugins.py`；无服务器只读盘环境自动禁用）：`*.plugin.zip` 投放到 `RUSIN_DATA_DIR` 自动解压安装到 `plugins/<namespace>/` 并删除包；desc.json 缺 `auth_token` 须 `--skip-auth`（或 `RUSIN_PLUGIN_SKIP_AUTH=1`）放行；命名空间冲突非同源且未声明 OVERRIDE 拒绝；后台线程每 `plugins.update_interval_hours`（默认 6h）检查，`last_update` 超过 `update_stale_days`（默认 3 天）则请求 `upstream_repo`（3s 超时）后重跑安装。
- 组织/团队协作（`app/views/org.py` + `store.py` 组织段）：组织笔记以 `_orgs/<org_name>` 作为存储用户名命名空间，与个人笔记完全隔离；Owner / Admin / Member 三级角色，加入方式支持邀请码 / 公开加入 / 审批制，受 `orgs` 功能开关控制。端到端测试：`pytest tests/test_org.py`
- 评论系统（`app/comments.py` + `views/comments.py`）：目标类型为 `note` / `share`，统一存 KV 键 `comments:all`（file 后端即 `comments.json`），受 `comments` 功能开关与 `comments` 配置段（长度 / 上限 / 冷却 / 分页）控制。
- 首页工作台（`app/views/home.py` + `app/todos.py`）：登录态首页展示最近编辑笔记（`home_page.recent_notes_limit`）与待办清单（KV 键 `todos`，受 `todos.max_items` / `todos.max_length` 约束）；简洁模式下首页 302 直接跳到新建笔记。
- 测试清单：`tests/` 覆盖 `test_org` / `test_user_settings` / `test_images` / `test_pins` / `test_folders` / `test_sqlite_storage` / `test_markdown_alerts` / `test_home_notice` / `test_frontend`，统一 `pytest tests/` 运行。
- 模板：Jinja2，支持 `{{ t('key') }}` 多语言
- 无服务器默认存储：Vercel 绑定 Neon 后 `DATABASE_URL` 自动注入 → 自动切到 postgres 后端
- 前端检查：前端资源全部内联在 Jinja2 模板中，无独立 JS/CSS 文件；`tests/frontend_check.py` 做静态语法检查（Jinja2 `Environment.parse` + Node `--check` 校验内联 JS + CSS 括号配平 + JSON 解析），由 `.github/workflows/check.yml` 的 `frontend` job 在前端文件变更时运行

## 文档导航
- 详细的模块职责、路由表、配置项说明，请参考 Skill：`.opencode/skills/rusin-note-codebase/SKILL.md`。
- 完整用户文档见 `README.md`（含 Vercel / Lambda 部署步骤与存储后端说明）。