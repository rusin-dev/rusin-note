---
name: rusin-note-codebase
description: Use when working in this project (Rusin-Note, a Flask 云端剪贴板/在线记事本). Covers the full directory structure, responsibilities of every module and view blueprint, data persistence model, routing rules, rate limiting, security mechanisms and config.json knobs, so you can navigate, modify and debug the code without re-reading files.
---

# Rusin-Note 项目结构与文件作用

Rusin-Note 是一个受 note.ms 启发的轻量级云端剪贴板 / 在线记事本，基于 Flask 3，支持 VPS 与无服务器（Vercel / AWS Lambda）部署。核心是"随机短链公开笔记 + 用户私有笔记 + 分享链接 + 犇犇动态"，数据存储通过可插拔、统一的存储接口（`app/storage.py` 的 `storage` 单例）访问：sqlite（本地默认，SQLite 索引 + JSON 内容）/ file（纯 JSON 落盘）/ upstash（外部 KV）/ postgres（Neon/PostgreSQL）/ memory（纯内存）。

## 运行方式

- 本地/生产：`python3 -m app`（入口 `app/__main__.py`，用 waitress 监听 `$PORT` 默认 8080）
- 生产建议（Linux）：`gunicorn 'app.wsgi:app' -b 0.0.0.0:$PORT --workers 2 --threads 4`
- 无服务器（Vercel）：`api/index.py`（WSGI app 由 @vercel/python 构建器识别）+ `vercel.json`（routes 全量转发 + includeFiles 打包模板/配置）；存储推荐绑定 **Neon**（自动注入 `DATABASE_URL` → postgres 后端）或 Upstash Redis（手动填 `KV_REST_API_URL`/`KV_REST_API_TOKEN`），并设置 `RUSIN_SECRET_KEY`（Vercel KV 已停服）
- 无服务器（AWS Lambda）：`lambda_handler.py` 的 `handler`（Mangum 适配 WSGI，API Gateway 代理集成）
- 数据目录：`RUSIN_DATA_DIR` 环境变量（默认 `data`，即项目下 `data/`，JSON 内容 + SQLite 索引均在此），本地 sqlite/file 后端使用；Zeabur 等平台挂卷到 `/data` 并设 `RUSIN_DATA_DIR=/data`
- 存储后端：`RUSIN_STORAGE`（sqlite/file/memory/upstash/postgres）显式指定，未指定时自动识别：KV 环境变量 → upstash；`DATABASE_URL` → postgres；检测到 `VERCEL`/`NETLIFY`/`AWS_LAMBDA_FUNCTION_NAME` → memory；否则本地默认 sqlite
- 依赖：见 `requirements.txt`（Flask、Flask-WTF、Flask-Limiter、Flask-Caching、waitress、markdown、pymdown-extensions、pygments、bleach、redis、mangum、psycopg、Pillow——Pillow 未被代码引用，图片校验用 `images.py` 的魔数嗅探）；测试依赖见 `requirements-dev.txt`（pytest，含 `-r requirements.txt`）
- 要求 Python >= 3.10

## 数据模型（统一存储接口 + 可插拔后端）

存储后端统一键布局（`app/storage.py` 内 `KV_FILE_MAP` / `_note_key`），内容均落盘到 `RUSIN_DATA_DIR`（默认 `data/`）；sqlite 后端另建 `index.db` 索引以加速查找：

| 键 | 内容 JSON / 二进制落盘 | 内容 | 关键结构 |
|---|---|---|---|
| `users.json` | `users.json` | 用户 | `{username: {salt, hash}}`，hash 为 PBKDF2 格式 |
| `sessions.json` | `sessions.json` | 会话 | `{sha256(token): {username, created_at}}` |
| `shares.json` | `shares.json` | 分享链接 | `{token: {owner, note_id, created_at, editable, views}}` |
| `benben:posts` | `benben.json` | 犇犇（已持久化） | `[{username, content, time, ip}]`，最多 `benben.max_posts` 条（默认 200） |
| `feature_flags` | `feature_flags.json` | 功能开关运行时状态（#90） | `{feature_key: bool}`，默认值来自 config.json（`features` 段 + 历史功能各自配置段） |
| `comments:all` | `comments.json` | 评论 | `{"<target_type>:<target_id>": [{username, content, time, ip, is_anonymous}]}`，target_type 为 `note` / `share` |
| `note_tags` | `note_tags.json` | 笔记标签 | `{username: {note_id: [tag, ...]}}` |
| `note_folders` | `note_folders.json` | 笔记文件夹 | `{username: {note_id: "a/b"}}`（单归属，`/` 分层） |
| `note_pins` | `note_pins.json` | 笔记置顶 | `{username: {note_id: bool}}` |
| `note_titles` | `note_titles.json` | 旧版遗留键（当前代码不读写） | 仅登记于 `KV_FILE_MAP` 与 `LEGACY_ROOT_ITEMS`，新部署不会生成 |
| `todos` | `todos.json` | 首页工作台待办 | `{username: [{id, text, done, created_at}]}`，受 `todos.max_items`/`max_length` 约束 |
| `orgs` / `org_members` / `org_invites` / `org_join_requests` | 同名 `.json` | 组织、成员角色、邀请码、加入申请 | 见 `store.py` 组织段（Owner/Admin/Member 角色） |
| `note:<u>:<id>` | `notes/<u>/<id>.json` | 笔记 | sqlite 存 `{"content", "created_at", "updated_at"}` 并索引标题/大小/mtime；file 后端存 `notes/<u>/<id>.txt` 纯文本；memory/upstash 存 `{"content", "mtime"}` |
| `img:<u>:<img_id>` / `att:<u>:<att_id>` | `images/<u>/<id>`、`attachments/<u>/<id>` + `<id>.meta.json` | 图床 / 附件（原生二进制） | file/sqlite 直接落盘；postgres 进 `storage_images`/`storage_attachments`；memory/upstash 走 base64 KV |
| `secret_key` | `.secret_key` | SECRET_KEY | 纯文本 |

sqlite 索引表（`<DATA_DIR>/index.db`）：`notes_index`（标题/大小/mtime/created_at）、`kv_index`（键→路径/大小/更新时间）、`images_index`、`attachments_index`。图床/附件在 sqlite 与 file 后端均为原生二进制文件（`images/<u>/<id>`、`attachments/<u>/<id>` + `<id>.meta.json`）。

upstash 后端所有键统一加 `rusin:` 前缀；memory 后端 get/set 带 deepcopy（防外部原地修改破坏内部数据）。

并发写路径统一锁序：**`threading.Lock`（进程内）→ `storage.lock`（跨进程/跨实例）**，顺序颠倒会死锁（见 `store.flush_share_views` 注释）。读多写少用内存缓存 + 周期重载（`reload_users`/`reload_sessions`/`_resync_benben_locked`），单值写（`write_note`）直接整值覆盖无需锁。注意：`threading.Lock` 不可重入——持锁块内绝不能调用会再次加锁的函数（见 `auth.get_session_user` 的 BUG-01 注释）。

无服务器环境（`config.SERVERLESS` 为真）不启动后台线程，清理由 `middleware._opportunistic_cleanup()` 在请求内按 `SESSION_CLEANUP_INTERVAL` 节流执行；日志回退 stderr。

## 根目录文件

| 文件 | 作用 |
|---|---|
| `config.json` | 运行配置（默认已开 `trust_proxy_headers`/`secure_cookies`，详见下方"配置项"） |
| `requirements.txt` / `requirements-dev.txt` | Python 依赖 / 测试依赖（pytest） |
| `pytest.ini` | pytest 配置（`testpaths=tests`、`log_cli=true`） |
| `NOTICE.txt` | 首页公告横幅内容（取第一行，见 `utils.read_notice_first_line`） |
| `zbpack.json` | Zeabur 打包配置 |
| `vercel.json` | Vercel 无服务器构建/路由配置（`@vercel/python` + includeFiles） |
| `api/index.py` | Vercel Python 入口（`from app import create_app; app = create_app()`） |
| `lambda_handler.py` | AWS Lambda 入口（Mangum 适配） |
| `.env.example` | 环境变量示例（RUSIN_STORAGE / RUSIN_DATA_DIR / RUSIN_SECRET_KEY / RUSIN_ADMIN） |
| `README.md` / `README_en.md` | 中英文文档（含 Vercel / Lambda / VPS 部署步骤、配置项与存储后端说明） |
| `Disclaimer.md` / `Disclaimer-en.md` | 中英文免责声明（`/disclaimer` 页面读取） |
| `contributing.md` | 协作指南 |
| `AGENTS.md` / `CLAUDE.md` | AI 协作指南（命令、存储、安全约定、架构要点） |
| `todo.md` | 路线图（已实现 / 会实现 / 待讨论，链接对应 GitHub Issue） |
| `feature_flags.json` | **仓库根目录的历史遗留文件**，运行时不读取（运行时状态写入 `data/feature_flags.json`） |
| `tests/` | 测试目录（pytest + logging：`test_*.py` 端到端测试 + `conftest.py` 环境隔离 + `support.py` 共享辅助，`frontend_check.py` 前端语法检查 CLI）；运行 `pytest tests/`，各测试使用独立临时 `RUSIN_DATA_DIR` |
| `favicon.ico` / `image/logo.png` / `image/screenshots1.png` | 站点图标与图片资源 |
| `.github/` | Issue 模板、issue-labeler、CI/CD workflows（check/codeql/release/auto-merge/upstream-sync 等）；`check.yml` 含 `changes`（paths-filter 判断 python/frontend 变更）、`test`（启动服务健康检查）、`frontend`（前端语法检查）三个 job |
| `.gitignore` | Git 忽略规则 |

## app/ 核心模块

| 模块 | 作用 |
|---|---|
| `__init__.py` | Flask app 工厂 `create_app()`：组装 SECRET_KEY（`RUSIN_SECRET_KEY` > 存储后端 `secret_key`（file 即 `.secret_key` 文件、upstash 存 KV 多实例共享）> 随机兜底）、CSRF、限流（`REDIS_URL` 可切共享存储）、请求钩子、i18n、蓝图、错误页；`SERVERLESS` 或 `TESTING` 时不启动后台线程 |
| `__main__.py` | 入口 `python -m app`，waitress 启动 |
| `wsgi.py` | WSGI 入口 `app.wsgi:app`（gunicorn 用） |
| `storage.py` | **统一存储接口**：所有业务模块只通过模块级 `storage` 单例访问数据。`StorageBackend` 基类 + `SqliteBackend`（本地默认，SQLite 索引 + JSON 内容，见 `storage_sqlite.py`）/`FileBackend`/`MemoryBackend`/`UpstashBackend`（纯 urllib REST）/`PostgresBackend`（psycopg，表 `storage_kv`+`storage_notes`+`storage_images`+`storage_attachments`），接口为 `get/set/delete/list_keys` + 笔记专用方法 + 统一元数据/检索方法（`note_title`/`list_notes_detailed`/`search_notes`/`notes_stats`，基类退化实现、SQLite 覆盖为索引查询）+ `lock(name)` 跨实例互斥（file/sqlite 用 fcntl 文件锁、upstash 用 SET NX EX 自动过期、postgres 用 `pg_try_advisory_xact_lock`、memory 用线程锁）；`select_backend()` 自动识别（KV 环境变量 > DATABASE_URL > SERVERLESS memory > 本地 sqlite）；`StorageError` 统一异常 |
| `storage_sqlite.py` | **SQLite + JSON 后端**：`SqliteBackend(FileBackend)` 在 `<DATA_DIR>/index.db`（WAL）维护 `kv_index`/`notes_index`/`images_index`/`attachments_index` 四张索引表，内容仍以 JSON/二进制落盘（`notes/<u>/<id>.json`、`<name>.json`、`images/`、`attachments/`）；首次启动自动导入旧版 `notes/*.txt`，默认数据目录切到 `data/` 时 `migrate_legacy_data_root()` 从旧根目录迁移 |
| `config.py` | 加载 `config.json` 并导出全部全局常量（`MAX_CONTENT_BYTES`、各类限流参数、`ID_CHARSET`、`SHARE_TOKEN_CHARSET`/`SHARE_TOKEN_PATTERN`、密码策略 `PW_*`、`BENBEN_*`（含 `BENBEN_MAX_POSTS`）、会话/笔记过期、LaTeX、代理信任、Cookie 安全、`SERVERLESS` 平台检测、`data_path()` 等）。标记为 ADDED/BUG-x 的注释说明某常量的引入原因 |
| `store.py` | 用户/会话/分享/犇犇/评论/组织的内存缓存 + 存储层持久化：`register_user`/`store_session`/`remove_session`/`delete_sessions_if`/`create_share`/`delete_share`/`add_benben_post`/`add_comment`/组织 CRUD 与邀请审批 均走「线程锁 + storage.lock + 重读合并 + 整值写入」；分享视图计数延迟批量持久化（`increment_share_views`/`flush_share_views`）；犇犇与评论发布冷却（内存态）、分页读取（带周期重载）；`rename_user_records` 改用户名时迁移各集合中的用户标识 |
| `auth.py` | PBKDF2-HMAC-SHA256 密码哈希（兼容旧单轮 SHA-256 可验证、登录后自然升级）、会话 token 生成/校验（存哈希）、过期会话清理、密码复杂度检查 |
| `notes.py` | 笔记读写走 `storage` 后端（无路径穿越代码——校验交给 `validate_username`/`validate_note_id` 正则）、ID/用户名校验（含保留名单）、`note_exists`、统计（30s TTL 缓存）、随机 ID 生成、过期笔记清理 |
| `middleware.py` | `before_request` 钩子：向 `flask.g` 写入 `client_ip`/`client_ip_source`/`lang`/`theme`/`current_user`/`rate_limit_exempt`；命中 `ip_blocklist` 直接 403；`SERVERLESS` 时调用 `_opportunistic_cleanup()`（节流执行过期会话/笔记清理 + 视图刷盘）；`get_client_ip()` 委托 `ip_utils.analyze_client_ip`（仅可信代理才采信代理头） |
| `ip_utils.py` | **客户端 IP 安全解析（防 XFF 伪造）**：`parse_ip`（严格 IP 规范化，支持 `ip:port`/`[ipv6]:port`/IPv4-mapped）、`analyze_client_ip`（只有 TCP 直连对端命中 `trusted_proxies` 才采信代理头；XFF 从右往左、跳过可信代理取真实客户端；`"*"` 为按 `proxy_hops` 取值的兼容模式）、`ip_in_any`（CIDR + 预设 `loopback`/`private`/`cloudflare`，带解析缓存）、`note_ignored_proxy_headers`（伪造告警节流）、`clear_caches` |
| `concurrency.py` | **进程内并发闸门**（防慢速长连接占满 worker，#191）：`ConcurrencyLimiter.try_acquire(key, limit)` 返回 `Slot`（超限返回 `None`，`limit<=0` 返回不计数的一次性 Slot），`Slot.release()` **幂等**（可同时挂在生成器 `finally` 与 `Response.call_on_close`）；`active/total_active/peak/rejected/reset` + `reset_all()`（测试隔离用）。实例在 `attachments.py`：`download_guard`/`upload_guard`，key 为 `user:<名>`（未登录按 `ip:<ip>`），上限默认各 1 个在途队列 |
| `extensions.py` | CSRF（Flask-WTF）与 Limiter（Flask-Limiter）单例；限流 key 用安全解析后的 `g.client_ip`（`ip_allowlist` 命中时返回一次性键=免限流）；`default_limits` 为 `ip_rate_limit` 全局兜底；`on_breach` 记录审计日志；`REDIS_URL` 环境变量切换限流共享存储 |
| `i18n.py` | 中英双语：`STRINGS` 字典（zh/en 成对），`t(lang, key)` 取翻译（缺 key 返回 key 本身）；语言检测 Cookie `rusin-lang` > Accept-Language > zh；`register_i18n` 注入模板全局 `t`/`lang`/`theme`/`current_user`/`site_name` 等 |
| `theme.py` | 暗色主题 CSS 变量（`THEME_VARS`）与切换脚本（Cookie + localStorage + 系统偏好）、favicon 内存缓存 |
| `logger.py` | `create_logger(name)` 返回写入 `log/{timestamp}.log` 的 RotatingFileHandler 日志器；文件不可写（无服务器只读 FS）时回退 stderr |
| `utils.py` | `format_size`/`format_note_time` 格式化、`get_avatar_url` 头像 URL、`expand_note_refs`（`#ID` 快捷引用展开）、`render_markdown_html`（markdown + pymdownx.tilde + Pygments 服务端着色 + bleach 清洗防 XSS；`markdown_alerts` 启用时把 `> [!NOTE]` 等引用块经 treeprocessor 转为可折叠 `<details>` 卡片）、`render_pygments_head`（亮/暗两套 Pygments CSS，注入 `pygments_head`）、`render_code_highlight_head`（客户端 highlight.js + 行号 + 主题切换）、`render_heading_anchors_head`、`render_markdown_alerts_head`（`window.MarkdownAlerts.apply`，供实时预览）、`render_latex_head`（KaTeX CDN 引入）、`read_notice_first_line`、`read_disclaimer` |
| `feature_flags.py` | **功能开关（#90）**：`FEATURES` 注册表共 17 项（world_notes / benben / share_links / open_register / note_refs / note_tags / note_folders / note_pins / heading_anchors / markdown_alerts / note_images / note_attachments / comments / latex_render / code_highlight / avatar / orgs）+ 运行时状态（KV 键 `feature_flags`，进程内 5s TTL 缓存）；`feature_enabled(key)` 查询、`set_flags` 整体写入、`require_feature(key)` 视图装饰器（停用→404，须放 `@bp.route` 后、缓存/限流装饰器前）、`is_admin`（`RUSIN_ADMIN` env + config `admin_users` 并集）；默认值：`_HERITAGE_DEFAULTS` 中的 7 个历史功能（note_refs/latex_render/code_highlight/avatar/note_images/note_attachments/comments）沿用各自配置段，其余读 `features` 段（缺省 True） |
| `plugins.py` | 插件系统：`*.plugin.zip` 投放到 `RUSIN_DATA_DIR` 启动时解压安装到 `plugins/<namespace>/`（zip 路径穿越/体积防护、根目录白名单、auth_token 校验、命名空间冲突检查）并注册蓝图；`start_update_thread` 后台每 `update_interval_hours` 检查上游、`last_update` 超 `update_stale_days` 拉取 `upstream_repo` 重装；无服务器只读盘环境自动禁用 |
| `background.py` | 后台守护线程：会话清理、分享视图定期刷盘、过期笔记清理（`start_background_threads()` 一次性启动；`SERVERLESS` 时为无操作） |
| `user_settings.py` | 用户设置业务：简洁模式（账号级偏好，存 users.json，`middleware` 注入 `g.simple_mode` 供服务端渲染）、修改密码（校验原密码/复杂度，注销其它会话）、修改用户名（先复制笔记/图床/附件到新命名空间，再迁移标签/文件夹/置顶/分享/犇犇/评论/组织等用户标识，最后删除旧数据） |

## app/views/ 蓝图与路由

注册顺序在 `views/__init__.py`：home → auth → benben → static_routes → world → user → share → admin → comments → org → todos → **插件蓝图** → **world_short（必须最后，因含 catch-all 短链）**。

| 蓝图 | 模块 | 路由与作用 |
|---|---|---|
| home | `home.py` | `/` 首页（匿名态为功能开关过滤的卡片；登录态为工作台：最近笔记 + 待办清单，`cache.cached` 对登录态/简洁模式跳过缓存；简洁模式 302 直接到新建笔记）、`/count` 统计（含「功能状态」呈现区）、`/disclaimer` 免责声明 |
| auth | `auth.py` | `/register` GET/POST（注册限流，密码复杂度校验；受 `open_register` 开关控制）、`/login` GET/POST、`/logout`、`/lang/<lang>` 语言切换（回跳 Referer） |
| world | `world.py` | `/world`（生成随机 ID 重定向）、`/world/<id>` GET/POST（公开笔记，POST 走 SAVE 限流）、`/world/<id>/md` 与 `/world/<id>.md` Markdown 只读渲染；全部受 `world_notes` 开关控制 |
| world_short | `world_short.py` | `/<id>`（短链重定向到 `/world/<id>`）、`/<id>.md`（短链 Markdown），catch-all 必须最后注册；受 `world_notes` 开关控制 |
| user | `user.py` | `/user/<u>/` 笔记列表（支持 `?tag=` / `?folder=` 筛选）、`/user/<u>/new` 新建、`/user/<u>/settings` GET/POST 用户设置（简洁模式 / 修改密码 / 修改用户名，见 `user_settings.py`）、`/user/<u>/<id>` GET/POST、`/user/<u>/<id>/delete`、`/user/<u>/<id>/pin`（`note_pins`）、`/user/<u>/<id>/md`、`/user/<u>/refs` 引用搜索（`note_refs`）、`/user/<u>/images` GET/POST/delete（图床管理，`note_images`）、`/user/<u>/attachments` GET/POST/delete（附件管理，`note_attachments`）、`/user/<u>/shares` 分享管理（创建/删除，`share_links`）。全部 `_require_auth`（当前会话用户须等于 URL 用户名，否则 401） |
| share | `share.py` | `/share/<token>`（可编辑则进编辑页、只读则进 Markdown 页；每次访问 `increment_share_views`）、POST 写回分享者原笔记（可编辑才允许，否则 403）、`/share/<token>/md` 与 `/share/<token>.md`；全部受 `share_links` 开关控制 |
| benben | `benben.py` | `/benben` GET 分页查看（新→旧，`page` 参数）、POST 发布（需登录 + 内容长度 + 单用户冷却 + 限流）；受 `benben` 开关控制 |
| admin | `admin.py` | `/admin/features` GET/POST 功能开关滑块管理页（仅管理员，非管理员 404；POST 保存后 `cache.clear()`） |
| static_routes | `static_routes.py` | `/favicon.ico`（内存缓存）、`/image/<name>`（仓库 `image/` 内置静态资源）、`/image/<u>/<id>`（用户图床，公开 + `public, max-age=86400`）、`/attachment/<u>/<id>`（用户附件：**默认禁止匿名下载**（未登录 401，`attachments.allow_anonymous_download` 可放开）、单用户同时下载上限（超限 429 + `Retry-After`）、按块流式产出并在结束/断开时释放并发槽位、缓存 `private`、路由带 `download_rate_limit` 每 IP 限流） |
| — | `_helpers.py` | 共享：`check_note_id()`（非法 ID 分情况 400/404）、`build_note_context()`（构造 note_edit/note_md 模板上下文） |

## 模板（templates/，Jinja2）

- `base.html` 基础布局（含功能开关滑块 `.ff-switch` 与状态卡 `.ff-card` 样式、简洁模式 `.simple-mode` 隐藏规则）；`partials/_navbar.html` 导航栏（benben/注册/分享/组织入口按 `feature_enabled` 与 `simple_mode` 条件渲染）
- `home.html` 首页/工作台（最近笔记 + 待办清单 + 公告横幅）、`count.html` 统计（含「功能状态」呈现区）、`disclaimer.html` 免责声明、`admin/features.html` 功能开关滑块管理页
- `auth/` 注册/登录；`notes/` 笔记（`note_edit.html` 编辑页、`note_md.html` Markdown 只读页、`user_list.html` 笔记列表/文件夹树/标签筛选、`user_settings.html` 用户设置页）；`share/share_list.html` 分享管理；`benben/benben.html` 犇犇；`comments/comments.html` 评论组件；`images/image_list.html`、`attachments/attachment_list.html` 图床/附件管理页
- `org/` 组织（`org.html` 首页、`org_notes.html`、`org_note_view.html` / `org_note_edit.html`、`org_members.html`、`org_settings.html`、`org_invites.html`、`org_requests.html`、`org_create.html`、`org_mine.html`）
- `errors/` 错误页 400/401/404/429/500（403/413 复用 400 模板）

模板可直接用 i18n 注入的全局：`{{ t('key') }}`、`{{ lang }}`、`{{ theme }}`、`{{ theme_script }}`、`{{ theme_vars }}`、`{{ pygments_head }}`、`{{ current_user }}`、`{{ site_name }}`、`{{ lang_switch_url }}`。

前端**无独立 JS/CSS 文件**（无 `static/`），脚本/样式全部内联在模板的 `<script>`/`<style>` 中；`partials/_card_theme_css.html`、`_navbar_css.html`、`_page_transition_css.html` 是纯 CSS 片段，被 `<style>{% include %}</style>` 引入。改动模板后请运行 `python tests/frontend_check.py`（Jinja2 语法 + 内联 JS 经 Node `--check` + 内联 CSS 配平 + JSON）。

## 安全与限流机制（改动时必须保持）

- **CSRF**：Flask-WTF 全站开启（`WTF_CSRF_TIME_LIMIT=None`）
- **限流**：Flask-Limiter，key 为安全解析后的客户端 IP。分层：全局 POST `rate_limit`（30/60s）、GET `get_rate_limit`（45/60s）、保存类 POST `save_rate_limit`（120/60s）、注册 `register_rate_limit`（1/120s）、**全站每 IP 总上限 `ip_rate_limit`（应用级作用域，300/60s，对所有路由累计生效）**。视图函数上用 `@limiter.limit(lambda: f"...")` 显式标注
- **客户端 IP / 防 XFF 伪造**：`config.TRUST_PROXY_HEADERS` 默认 false（一律用 TCP 直连 IP）；置 true 后仍需 TCP 直连对端命中 `trusted_proxies`（默认 `["loopback","private"]`，可加 `"cloudflare"`；`"*"` 为不安全兼容模式）才采信代理头。头部值必须为合法 IP（超长/非法一律丢弃，XFF 最多 16 项），XFF 从右往左解析并逐层跳过可信代理。**不要使用 `ProxyFix`**（会被伪造 XFF 改写 `remote_addr`）。`ip_blocklist` 命中直接 403，`ip_allowlist` 命中免限流；环境变量 `RUSIN_TRUSTED_PROXIES`/`RUSIN_PROXY_HOPS`/`RUSIN_IP_ALLOWLIST`/`RUSIN_IP_BLOCKLIST` 可覆盖/追加。测试：`pytest tests/test_ip_limiter.py`
- **单用户并发闸门（长连接防护，#191）**：IP 限流只算「单位时间请求数」，拦不住「少量请求、超长时间占用」（如发起上千个队列、每个 1KB/s，或用 100 线程下载 100 个文件打满出站带宽）。附件下载/上传因此在限流之外再经 `app/concurrency.py` 限制**单用户同时在途数**（`attachments.max_concurrent_downloads` 默认 1、`max_concurrent_uploads` 默认 1，即每账号 1 个下载队列 + 1 个上传队列，`0` = 不限）：超限即拒绝、不排队；下载 `abort(429, description=...)`（全局 429 处理器补 `Retry-After`），上传直接返回 429 JSON（`/user/*/attachments` 的 POST 在全局处理器里也走 JSON 分支）。槽位必须在正常结束（生成器 `finally`）、客户端断开（`Response.call_on_close`）两条路径归还，`Slot` 幂等可双重挂载；视图内任何异常/404 也要先释放。计数在进程内，N 个 worker ≈ `N × 上限`。测试：`pytest tests/test_attachments.py`
- **附件下载权限**：`/attachment/<u>/<id>` 默认仅登录可下载（未登录 401 + 登录提示文案），响应缓存为 `private`（`public` 会让共享缓存把附件回放给匿名访客）；当前策略为「登录用户凭链接即可下载」，如需「仅本人可下载」须在视图中补所有权校验（测试 B3 记录了当前语义）
- **XSS**：Markdown 渲染后经 bleach 白名单清洗（`utils.render_markdown_html`）；提示卡片输出 `<details>/<summary>` 前同样过 bleach，新增标签/属性须同步 `allowed_tags`/`allowed_attrs`
- **密码**：PBKDF2 10 万次迭代慢哈希 + 常量时间比较；`PW_MAX_LENGTH` 硬上限 128 防超长输入 CPU DoS
- **路径穿越**：笔记 ID 正则 `^[a-zA-Z0-9_\-]+$` + realpath/commonpath 双重校验；用户名/ID 有保留名单（`RESERVED_USERNAMES`、`FORBIDDEN_NOTE_IDS`）
- **Cookie**：session HttpOnly + SameSite=Lax，`secure_cookies` 开关控制 Secure 标志

## 配置项（config.json 关键项）

- `max_note_size_kb`（默认 512KB）、`sitename`
- 限流五项：`rate_limit` / `get_rate_limit` / `save_rate_limit` / `register_rate_limit` / `ip_rate_limit`（全站每 IP 总上限，应用级作用域，`max_requests` 置 0 关闭）
- `trust_proxy_headers`、`trusted_proxies`（IP/CIDR 或预设 `loopback`/`private`/`cloudflare`/`"*"`）、`proxy_hops`、`ip_allowlist`（免限流）、`ip_blocklist`（403）、`secure_cookies`
- `id_generation`（短链 ID 字符集/长度）、`share_token`（分享 token 长度 64/字符集）
- `session_timeout`（会话超时，默认关）、`note_expiration`（笔记过期清理，默认关，每 30 分钟扫描）
- `global_cdn`（前端 CDN 基地址，默认 `https://cdn.jsdmirror.cn`，KaTeX / FontAwesome / marked / DOMPurify / highlight.js 均从此拼 `npm/` 路径）
- `latex_render`（KaTeX，默认开，资源从 `global_cdn` 拼）、`code_highlight`（客户端 highlight.js + 行号，默认开；服务端 Pygments 着色不受该开关影响）
- `cache`（页面缓存：`enabled` / `backend` 默认 `redis` / `default_timeout` 300 / `redis_url`，`REDIS_URL` 可覆盖；Redis 不可达自动降级 SimpleCache）
- `password_policy`（密码复杂度，`PW_*` 常量，硬上限 128）
- `benben`（犇犇最大长度 1024 / 每页 50 / 冷却 3s / 最大高度 1000px / 持久化上限 `max_posts` 200）
- `comments`（评论：`max_length` 1024 / `max_comments` 200 / `cooldown_seconds` 3 / `page_size` 50 / `max_height_px` 1000）
- `images`（图床：`enabled` / `max_size_kb` 2048 / `max_total_kb` 51200）、`attachments`（附件：`max_size_kb` 50 / `max_per_note_kb` 500 / `max_total_kb` 10240 / `blocked_extensions` 黑名单）
- `note_editor`（`live_preview_default` 编辑页实时渲染默认值，默认 false，访客可手动开、以 localStorage 记住）、`markdown_manual_url`
- `note_refs`（`#` 引用：`enabled` / `search_limit` 8 / `scan_limit` 100）
- `avatar`（用户头像：`enabled` 默认 true；`url_template` 默认 cn.cravatar.com，占位符 `{hash}`=md5(用户名)、`{username}`=URL 编码用户名；`size` 备用值）
- `max_note_id_length`（250）、`logger`（日志大小/路径）、`debug`
- `images`（图床：`enabled`/`max_size_kb` 2048/`max_total_kb` 51200，公开读取）、`attachments`（附件：`enabled`/`max_size_kb` 50/`max_per_note_kb` 500/`max_total_kb` 10240/`blocked_extensions` + `allow_anonymous_download`（默认 false，禁匿名下载）/`max_concurrent_downloads`（1，#191）/`max_concurrent_uploads`（1，#191）/`download_rate_limit`（60s/120 次））
- `features`（功能开关默认值：world_notes/benben/share_links/open_register，#90）、`admin_users`（功能开关管理员，与环境变量 `RUSIN_ADMIN` 取并集）

## 常见改动点

- **新增页面/路由**：在 `app/views/` 加蓝图模块并更新 `views/__init__.py` 注册；若新增根级 catch-all 路由注意注册顺序
- **新增翻译文案**：`i18n.py` 的 zh/en 字典必须成对添加；模板用 `{{ t('key') }}`
- **新增头像显示位**：模板直接用 `{{ get_avatar(username) }}`（已由 i18n 注入全局），空串时用 `{% if av %}` 隐藏 `<img>`；生成逻辑见 `utils.get_avatar_url`，配置在 `config.json` 的 `avatar`
- **改限流**：`config.json` 对应键 + 视图函数 `@limiter.limit` 字符串
- **改数据格式**：留意 `store.py`/`auth.py` 中的旧数据兼容注释（BUG-7 损坏数据跳过等）；加字段时给 `get_*` 用 `.get()` 兜底
- **新增可开关功能（#90）**：`feature_flags.py` 的 `FEATURES` 注册表登记（key/icon）+ i18n 加 `feature_<key>` zh/en 文案 + 视图加 `@require_feature(key)`（放 `@bp.route` 之后、`@cache.cached`/`@limiter.limit` 之前）+ config.json `features` 段加默认值；模板用 `feature_enabled(key)` 条件渲染
- **新增存储键/后端**：键布局在 `storage.py`（`KV_FILE_MAP`/`_note_key`），sqlite/file 后端新键需在 `KV_FILE_MAP` 登记路径（否则 sqlite 落到 `kv/<hash>.json`）；新增后端需实现 `StorageBackend` 全部方法并在 `select_backend()` 注册（sqlite 在 `storage_sqlite.py`，postgres 后端新表需在 `_ensure_schema` 增加 DDL）
- **写路径并发**：读改写必须「线程锁 → `storage.lock(键)`」再重读合并，顺序不可颠倒；纯整值覆盖（`write_note`）无需跨实例锁
- **新增端到端测试**：`tests/test_*.py`，复用 `conftest.py` 的 `app`/`client`/`anon`/`ctx`/`data_dir` fixture 与 `support.py` 的 `expect()`/CSRF/注册登录辅助；跨方法共享状态挂 class 级 `ctx`，不要挂 `self`
- **改前端模板**：改完跑 `python tests/frontend_check.py`（需要 Node 才校验内联 JS）；CI 在 `dev` 分支 push/PR 按 paths-filter 触发 `frontend`（前端变更）与 `test`（Python 变更，pytest + 启动健康检查）