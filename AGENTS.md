# Rusin-Note 项目指南

## 项目简介
基于 Flask 的轻量级云端剪贴板，支持公开短链笔记、用户私有笔记、分享链接和动态（犇犇）。可部署在 VPS（file 后端）或 Vercel / AWS Lambda 等无服务器平台（upstash 后端接入外部 KV）。

## 技术栈
- Python 3.10+, Flask 3, Flask-WTF, Flask-Limiter, waitress/gunicorn, mangum（Lambda 适配）
- Markdown 渲染：markdown + bleach（防 XSS）+ Pygments（代码高亮、行号）
- 前端：Jinja2 模板，支持中英双语（i18n）

## 常用命令
- 开发运行：`python3 -m app`（监听 8080，file 后端）
- 生产部署（VPS）：`gunicorn 'app.wsgi:app' -b 0.0.0.0:$PORT --workers 2 --threads 4`
- 无服务器部署（Vercel）：`vercel.json` + `api/index.py` 已内置，绑定 Vercel KV 并设置 `RUSIN_SECRET_KEY` 即可
- 无服务器部署（AWS Lambda）：入口 `lambda_handler.handler`（Mangum）
- 数据目录：由环境变量 `RUSIN_DATA_DIR` 指定（默认 `.`，仅 file 后端）
- 依赖安装：`pip install -r requirements.txt`

## 数据存储（重点：可插拔后端）
存储层统一在 `app/storage.py`，后端由 `RUSIN_STORAGE` 显式指定或自动识别：

| 后端 | 启用 | 说明 |
|---|---|---|
| file | 默认（本地/VPS） | JSON 文件落盘于 `RUSIN_DATA_DIR`：`notes/`、`users.json`、`sessions.json`、`shares.json`、`benben.json`、`log/` |
| upstash | `KV_REST_API_URL` + `KV_REST_API_TOKEN` | Upstash Redis REST API（纯 urllib，无驱动依赖），键统一加 `rusin:` 前缀，多实例共享 |
| postgres | `DATABASE_URL`（Neon / 任意 PostgreSQL，Vercel 绑定 Neon 自动注入） | psycopg 驱动，表 `storage_kv`（通用 KV）+ `storage_notes`（笔记）；跨实例互斥用 PG advisory lock |
| memory | `RUSIN_STORAGE=memory`（无服务器且未配以上存储时自动） | 纯内存，重启清空 |

自动识别优先级：显式 `RUSIN_STORAGE` > KV 环境变量（upstash）> `DATABASE_URL`（postgres）> 无服务器平台（memory）> 本地（file）。

- 犇犇动态已改为持久化（最多 `benben.max_posts` 条，默认 200），不再纯内存。
- 写路径统一锁序：**threading.Lock（进程内）→ storage.lock（跨进程/跨实例）**，顺序颠倒会死锁（见 `store.flush_share_views` 注释）。
- 无服务器环境（`VERCEL`/`NETLIFY`/`AWS_LAMBDA_FUNCTION_NAME`）不启动后台线程，清理由 `middleware._opportunistic_cleanup()` 请求内机会式执行；日志回退 stderr。
- `RUSIN_SECRET_KEY` 必填于无服务器平台；可持久化后端会自动生成并存储（键 `secret_key`）。

## 关键安全约定
- **CSRF 防护**：全站启用，不要在任何表单中省略 `{{ csrf_token() }}`。
- **限流**：基于 IP，使用 Flask-Limiter；新增路由时务必添加 `@limiter.limit` 装饰器。限流存储可用 `REDIS_URL` 切换为共享 Redis。
- **XSS 防护**：所有 Markdown 渲染必须通过 `utils.render_markdown_html`（内部使用 bleach 清洗）。
- **路径安全**：笔记 ID 和用户名必须符合正则 `^[a-zA-Z0-9_\-]+$`，避免路径穿越；后端键由 storage 层统一构造，解析用 `parse_note_key`。
- **Cookie**：生产环境应开启 `secure_cookies`（仓库 config.json 已默认开启，本地开发请关闭）。

## 架构要点
- 入口：`app/__main__.py`（waitress）或 `app/wsgi.py`（gunicorn）；无服务器：`api/index.py`（Vercel）、`lambda_handler.py`（Lambda）
- 核心模块：`storage.py`（存储后端抽象）、`store.py`（数据存储业务）、`auth.py`（认证）、`notes.py`（笔记操作）、`middleware.py`（请求上下文）、`plugins.py`（插件系统：zip 解压安装 / auth_token 校验 / 命名空间冲突检查 / 蓝图加载 / 上游更新线程）、`feature_flags.py`（功能开关：注册表 + 存储持久化 + `require_feature` 装饰器）
- 路由蓝图：home, auth, benben, static_routes, world, user, share, admin（`/admin/features` 功能开关管理）, **插件蓝图（在 views.register_blueprints 内注册）**, world_short（注意最后注册 catch-all）
- 功能开关（`app/feature_flags.py`，#90）：管理员（`RUSIN_ADMIN` 环境变量或 config.json `admin_users`）在 `/admin/features` 用滑块切换；运行时状态存 KV 键 `feature_flags`（file 后端即 `feature_flags.json`），进程内 5s TTL 缓存；停用功能路由 404、导航/首页入口隐藏，状态呈现于 `/count`。新增可开关功能：在 `FEATURES` 注册表登记 + 视图加 `@require_feature(key)`（必须放 `@bp.route` 之后、`@cache.cached`/`@limiter.limit` 之前）。端到端测试：`python flags_test.py`
- 插件系统（`app/plugins.py`；无服务器只读盘环境自动禁用）：`*.plugin.zip` 投放到 `RUSIN_DATA_DIR` 自动解压安装到 `plugins/<namespace>/` 并删除包；desc.json 缺 `auth_token` 须 `--skip-auth`（或 `RUSIN_PLUGIN_SKIP_AUTH=1`）放行；命名空间冲突非同源且未声明 OVERRIDE 拒绝；后台线程每 `plugins.update_interval_hours`（默认 6h）检查，`last_update` 超过 `update_stale_days`（默认 3 天）则请求 `upstream_repo`（3s 超时）后重跑安装。端到端测试：`python plugin_test.py`
- 模板：Jinja2，支持 `{{ t('key') }}` 多语言
- 无服务器默认存储：Vercel 绑定 Neon 后 `DATABASE_URL` 自动注入 → 自动切到 postgres 后端

## 文档导航
- 详细的模块职责、路由表、配置项说明，请参考 Skill：`.opencode/skills/rusin-note-codebase/SKILL.md`。
- 完整用户文档见 `README.md`（含 Vercel / Lambda 部署步骤与存储后端说明）。