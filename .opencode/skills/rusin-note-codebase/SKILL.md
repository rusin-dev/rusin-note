---
name: rusin-note-codebase
description: Use when working in this project (Rusin-Note, a Flask 云端剪贴板/在线记事本). Covers the full directory structure, responsibilities of every module and view blueprint, data persistence model, routing rules, rate limiting, security mechanisms and config.json knobs, so you can navigate, modify and debug the code without re-reading files.
---

# Rusin-Note 项目结构与文件作用

Rusin-Note 是一个受 note.ms 启发的轻量级云端剪贴板 / 在线记事本，基于 Flask 3，支持 VPS 与无服务器（Vercel / AWS Lambda）部署。核心是"随机短链公开笔记 + 用户私有笔记 + 分享链接 + 犇犇动态"，数据存储通过可插拔存储层（`app/storage.py`）统一：file（JSON 落盘）/ upstash（外部 KV）/ postgres（Neon/PostgreSQL）/ memory（纯内存）。

## 运行方式

- 本地/生产：`python3 -m app`（入口 `app/__main__.py`，用 waitress 监听 `$PORT` 默认 8080）
- 生产建议（Linux）：`gunicorn 'app.wsgi:app' -b 0.0.0.0:$PORT --workers 2 --threads 4`
- 无服务器（Vercel）：`api/index.py`（WSGI app 由 @vercel/python 构建器识别）+ `vercel.json`（routes 全量转发 + includeFiles 打包模板/配置）；存储推荐绑定 **Neon**（自动注入 `DATABASE_URL` → postgres 后端）或 Upstash Redis（手动填 `KV_REST_API_URL`/`KV_REST_API_TOKEN`），并设置 `RUSIN_SECRET_KEY`（Vercel KV 已停服）
- 无服务器（AWS Lambda）：`lambda_handler.py` 的 `handler`（Mangum 适配 WSGI，API Gateway 代理集成）
- 数据目录：`RUSIN_DATA_DIR` 环境变量（默认 `.`），仅 file 后端使用；Zeabur 等平台挂卷到 `/data` 并设 `RUSIN_DATA_DIR=/data`
- 存储后端：`RUSIN_STORAGE`（file/memory/upstash/postgres）显式指定，未指定时自动识别：KV 环境变量 → upstash；`DATABASE_URL` → postgres；检测到 `VERCEL`/`NETLIFY`/`AWS_LAMBDA_FUNCTION_NAME` → memory；否则 file
- 依赖：见 `requirements.txt`（Flask、Flask-WTF、Flask-Limiter、waitress、markdown、bleach、redis、mangum、psycopg）
- 要求 Python >= 3.10

## 数据模型（存储层可插拔）

存储后端统一键布局（`app/storage.py` 内 `KV_FILE_MAP` / `_note_key`）：

| 键 | file 后端落盘 | 内容 | 关键结构 |
|---|---|---|---|
| `users.json` | `users.json` | 用户 | `{username: {salt, hash}}`，hash 为 PBKDF2 格式 |
| `sessions.json` | `sessions.json` | 会话 | `{sha256(token): {username, created_at}}` |
| `shares.json` | `shares.json` | 分享链接 | `{token: {owner, note_id, created_at, editable, views}}` |
| `benben:posts` | `benben.json` | 犇犇（已持久化） | `[{username, content, time, ip}]`，最多 `benben.max_posts` 条（默认 200） |
| `feature_flags` | `feature_flags.json` | 功能开关运行时状态（#90） | `{feature_key: bool}`，默认值来自 config.json（`features` 段 + 历史功能各自配置段） |
| `note:<u>:<id>` | `notes/<u>/<id>.txt` | 笔记 | file 后端存纯文本（mtime 取文件 stat）；memory/upstash 存 `{"content", "mtime"}` |
| `secret_key` | `.secret_key` | SECRET_KEY | 纯文本 |

upstash 后端所有键统一加 `rusin:` 前缀；memory 后端 get/set 带 deepcopy（防外部原地修改破坏内部数据）。

并发写路径统一锁序：**`threading.Lock`（进程内）→ `storage.lock`（跨进程/跨实例）**，顺序颠倒会死锁（见 `store.flush_share_views` 注释）。读多写少用内存缓存 + 周期重载（`reload_users`/`reload_sessions`/`_resync_benben_locked`），单值写（`write_note`）直接整值覆盖无需锁。注意：`threading.Lock` 不可重入——持锁块内绝不能调用会再次加锁的函数（见 `auth.get_session_user` 的 BUG-01 注释）。

无服务器环境（`config.SERVERLESS` 为真）不启动后台线程，清理由 `middleware._opportunistic_cleanup()` 在请求内按 `SESSION_CLEANUP_INTERVAL` 节流执行；日志回退 stderr。

## 根目录文件

| 文件 | 作用 |
|---|---|
| `config.json` | 运行配置（默认已开 `trust_proxy_headers`/`secure_cookies`，详见下方"配置项"） |
| `requirements.txt` | Python 依赖 |
| `zbpack.json` | Zeabur 打包配置 |
| `vercel.json` | Vercel 无服务器构建/路由配置（`@vercel/python` + includeFiles） |
| `api/index.py` | Vercel Python 入口（`from app import create_app; app = create_app()`） |
| `lambda_handler.py` | AWS Lambda 入口（Mangum 适配） |
| `.env.example` | 环境变量示例（KV_REST_API_URL / KV_REST_API_TOKEN / RUSIN_SECRET_KEY / REDIS_URL / RUSIN_STORAGE / RUSIN_DATA_DIR） |
| `README.md` / `README_en.md` | 中英文文档（含 Vercel / Lambda / VPS 部署步骤与存储后端说明） |
| `Disclaimer.md` / `Disclaimer-en.md` | 中英文免责声明（`/disclaimer` 页面读取） |
| `contributing.md` | 协作指南 |
| `favicon.ico` / `image/logo.png` | 站点图标与 logo |
| `.github/` | Issue 模板、issue-labeler、CI/CD workflows（check/codeql/release/auto-merge/upstream-sync 等） |
| `.gitignore` | Git 忽略规则 |

## app/ 核心模块

| 模块 | 作用 |
|---|---|
| `__init__.py` | Flask app 工厂 `create_app()`：组装 SECRET_KEY（`RUSIN_SECRET_KEY` > 存储后端 `secret_key`（file 即 `.secret_key` 文件、upstash 存 KV 多实例共享）> 随机兜底）、CSRF、限流（`REDIS_URL` 可切共享存储）、请求钩子、i18n、蓝图、错误页；`SERVERLESS` 或 `TESTING` 时不启动后台线程 |
| `__main__.py` | 入口 `python -m app`，waitress 启动 |
| `wsgi.py` | WSGI 入口 `app.wsgi:app`（gunicorn 用） |
| `storage.py` | **存储层抽象**：`StorageBackend` 基类 + `FileBackend`/`MemoryBackend`/`UpstashBackend`（纯 urllib REST）/`PostgresBackend`（psycopg，表 `storage_kv`+`storage_notes`），接口为 `get/set/delete/list_keys` + 笔记专用方法 + `lock(name)` 跨实例互斥（file 用 fcntl 文件锁、upstash 用 SET NX EX 自动过期、postgres 用 `pg_try_advisory_xact_lock`、memory 用线程锁）；`select_backend()` 自动识别（KV 环境变量 > DATABASE_URL > SERVERLESS memory > file）；`StorageError` 统一异常 |
| `config.py` | 加载 `config.json` 并导出全部全局常量（`MAX_CONTENT_BYTES`、各类限流参数、`ID_CHARSET`、`SHARE_TOKEN_CHARSET`/`SHARE_TOKEN_PATTERN`、密码策略 `PW_*`、`BENBEN_*`（含 `BENBEN_MAX_POSTS`）、会话/笔记过期、LaTeX、代理信任、Cookie 安全、`SERVERLESS` 平台检测、`data_path()` 等）。标记为 ADDED/BUG-x 的注释说明某常量的引入原因 |
| `store.py` | 用户/会话/分享/犇犇的内存缓存 + 存储层持久化：`register_user`/`store_session`/`remove_session`/`delete_sessions_if`/`create_share`/`delete_share`/`add_benben_post` 均走「线程锁 + storage.lock + 重读合并 + 整值写入」；分享视图计数延迟批量持久化（`increment_share_views`/`flush_share_views`）；犇犇发布冷却（内存态）、分页读取（带周期重载） |
| `auth.py` | PBKDF2-HMAC-SHA256 密码哈希（兼容旧单轮 SHA-256 可验证、登录后自然升级）、会话 token 生成/校验（存哈希）、过期会话清理、密码复杂度检查 |
| `notes.py` | 笔记读写走 `storage` 后端（无路径穿越代码——校验交给 `validate_username`/`validate_note_id` 正则）、ID/用户名校验（含保留名单）、`note_exists`、统计（30s TTL 缓存）、随机 ID 生成、过期笔记清理 |
| `middleware.py` | `before_request` 钩子：向 `flask.g` 写入 `client_ip`/`lang`/`theme`/`current_user`；`SERVERLESS` 时调用 `_opportunistic_cleanup()`（节流执行过期会话/笔记清理 + 视图刷盘）；`get_client_ip()` 按可信度取 `CF-Connecting-IP` > `X-Real-IP` > XFF 最右非空 > remote_addr（仅 `trust_proxy_headers` 开启时） |
| `extensions.py` | CSRF（Flask-WTF）与 Limiter（Flask-Limiter）单例；限流 key 优先用 `g.client_ip`；`REDIS_URL` 环境变量切换限流共享存储 |
| `i18n.py` | 中英双语：`STRINGS` 字典（zh/en 成对），`t(lang, key)` 取翻译（缺 key 返回 key 本身）；语言检测 Cookie `rusin-lang` > Accept-Language > zh；`register_i18n` 注入模板全局 `t`/`lang`/`theme`/`current_user`/`site_name` 等 |
| `theme.py` | 暗色主题 CSS 变量（`THEME_VARS`）与切换脚本（Cookie + localStorage + 系统偏好）、favicon 内存缓存 |
| `logger.py` | `create_logger(name)` 返回写入 `log/{timestamp}.log` 的 RotatingFileHandler 日志器；文件不可写（无服务器只读 FS）时回退 stderr |
| `utils.py` | `format_size`/`format_note_time` 格式化、`render_markdown_html`（markdown + codehilite/Pygments 高亮+行号 + bleach 清洗防 XSS）、`render_pygments_head`（亮/暗两套高亮 CSS，注入 base）、`render_latex_head`（KaTeX CDN 引入）、`read_disclaimer` |
| `feature_flags.py` | **功能开关（#90）**：`FEATURES` 注册表（world_notes/benben/share_links/open_register/note_refs/latex_render/code_highlight/avatar）+ 运行时状态（KV 键 `feature_flags`，进程内 5s TTL 缓存）；`feature_enabled(key)` 查询、`set_flags` 整体写入、`require_feature(key)` 视图装饰器（停用→404，须放 `@bp.route` 后、缓存/限流装饰器前）、`is_admin`（`RUSIN_ADMIN` env + config `admin_users` 并集）；默认值：新功能读 `features` 段，历史功能沿用 latex_render/note_refs 等原配置段 |
| `background.py` | 后台守护线程：会话清理、分享视图定期刷盘、过期笔记清理（`start_background_threads()` 一次性启动；`SERVERLESS` 时为无操作） |

## app/views/ 蓝图与路由

注册顺序在 `views/__init__.py`：home → auth → benben → static_routes → world → user → share → admin → **插件蓝图** → **world_short（必须最后，因含 catch-all 短链）**。

| 蓝图 | 模块 | 路由与作用 |
|---|---|---|
| home | `home.py` | `/` 首页（登录态/匿名态卡片不同，卡片按功能开关过滤）、`/count` 统计（含「功能状态」呈现区）、`/disclaimer` 免责声明 |
| auth | `auth.py` | `/register` GET/POST（注册限流，密码复杂度校验；受 `open_register` 开关控制）、`/login` GET/POST、`/logout`、`/lang/<lang>` 语言切换（回跳 Referer） |
| world | `world.py` | `/world`（生成随机 ID 重定向）、`/world/<id>` GET/POST（公开笔记，POST 走 SAVE 限流）、`/world/<id>/md` 与 `/world/<id>.md` Markdown 只读渲染；全部受 `world_notes` 开关控制 |
| world_short | `world_short.py` | `/<id>`（短链重定向到 `/world/<id>`）、`/<id>.md`（短链 Markdown），catch-all 必须最后注册；受 `world_notes` 开关控制 |
| user | `user.py` | `/user/<u>/` 笔记列表、`/user/<u>/new` 新建、`/user/<u>/<id>` GET/POST、`/user/<u>/<id>/md`、`/user/<u>/refs` 引用搜索（`note_refs` 开关）、`/user/<u>/shares` 分享管理（创建/删除，`share_links` 开关）。全部 `_require_auth`（当前会话用户须等于 URL 用户名，否则 401） |
| share | `share.py` | `/share/<token>`（可编辑则进编辑页、只读则进 Markdown 页；每次访问 `increment_share_views`）、POST 写回分享者原笔记（可编辑才允许，否则 403）、`/share/<token>/md` 与 `/share/<token>.md`；全部受 `share_links` 开关控制 |
| benben | `benben.py` | `/benben` GET 分页查看（新→旧，`page` 参数）、POST 发布（需登录 + 内容长度 + 单用户冷却 + 限流）；受 `benben` 开关控制 |
| admin | `admin.py` | `/admin/features` GET/POST 功能开关滑块管理页（仅管理员，非管理员 404；POST 保存后 `cache.clear()`） |
| static_routes | `static_routes.py` | `/favicon.ico`（内存缓存） |
| — | `_helpers.py` | 共享：`check_note_id()`（非法 ID 分情况 400/404）、`build_note_context()`（构造 note_edit/note_md 模板上下文） |

## 模板（templates/，Jinja2）

- `base.html` 基础布局（含功能开关滑块 `.ff-switch` 与状态卡 `.ff-card` 样式）；`partials/_navbar.html` 导航栏（benben/注册/分享入口按 `feature_enabled` 条件渲染）
- `home.html` 首页、`count.html` 统计（含「功能状态」呈现区）、`disclaimer.html` 免责声明、`admin/features.html` 功能开关滑块管理页
- `auth/` 注册/登录；`notes/` 笔记（`note_edit.html` 编辑页、`note_md.html` Markdown 只读页、`user_list.html` 笔记列表）；`share/share_list.html` 分享管理；`benben/benben.html` 犇犇
- `errors/` 错误页 400/401/404/429/500（403/413 复用 400 模板）

模板可直接用 i18n 注入的全局：`{{ t('key') }}`、`{{ lang }}`、`{{ theme }}`、`{{ theme_script }}`、`{{ theme_vars }}`、`{{ pygments_head }}`、`{{ current_user }}`、`{{ site_name }}`、`{{ lang_switch_url }}`。

## 安全与限流机制（改动时必须保持）

- **CSRF**：Flask-WTF 全站开启（`WTF_CSRF_TIME_LIMIT=None`）
- **限流**：Flask-Limiter，key 为 `g.client_ip`。分层：全局 POST `rate_limit`（30/60s）、GET `get_rate_limit`（45/60s）、保存类 POST `save_rate_limit`（120/60s）、注册 `register_rate_limit`（1/120s）。视图函数上用 `@limiter.limit(lambda: f"...")` 显式标注
- **代理头**：`trust_proxy_headers` 默认 false，限流一律用 TCP 直连 IP，防伪造头绕过；置 true 后 `CF-Connecting-IP` > `X-Real-IP` > XFF 最右项
- **XSS**：Markdown 渲染后经 bleach 白名单清洗（`utils.render_markdown_html`）
- **密码**：PBKDF2 10 万次迭代慢哈希 + 常量时间比较；`PW_MAX_LENGTH` 硬上限 128 防超长输入 CPU DoS
- **路径穿越**：笔记 ID 正则 `^[a-zA-Z0-9_\-]+$` + realpath/commonpath 双重校验；用户名/ID 有保留名单（`RESERVED_USERNAMES`、`FORBIDDEN_NOTE_IDS`）
- **Cookie**：session HttpOnly + SameSite=Lax，`secure_cookies` 开关控制 Secure 标志

## 配置项（config.json 关键项）

- `max_note_size_kb`（默认 512KB）、`sitename`
- 限流四项：`rate_limit` / `get_rate_limit` / `save_rate_limit` / `register_rate_limit`
- `trust_proxy_headers`、`secure_cookies`
- `id_generation`（短链 ID 字符集/长度）、`share_token`（分享 token 长度 64/字符集）
- `session_timeout`（会话超时，默认关）、`note_expiration`（笔记过期清理，默认关，每 30 分钟扫描）
- `latex_render`（KaTeX CDN，默认 jsdelivr，可换 BootCDN）
- `password_policy`（密码复杂度）
- `benben`（犇犇最大长度 1024 / 每页 50 / 冷却 3s / 最大高度 1000px / 持久化上限 `max_posts` 200）
- `note_editor`（`live_preview_default` 编辑页实时渲染默认值，默认 false，访客可手动开、以 localStorage 记住）
- `avatar`（用户头像：`enabled` 默认 true；`url_template` 默认 cn.cravatar.com，占位符 `{hash}`=md5(用户名)、`{username}`=URL 编码用户名；`size` 备用值）
- `max_note_id_length`（250）、`logger`（日志大小/路径）、`debug`
- `features`（功能开关默认值：world_notes/benben/share_links/open_register，#90）、`admin_users`（功能开关管理员，与环境变量 `RUSIN_ADMIN` 取并集）

## 常见改动点

- **新增页面/路由**：在 `app/views/` 加蓝图模块并更新 `views/__init__.py` 注册；若新增根级 catch-all 路由注意注册顺序
- **新增翻译文案**：`i18n.py` 的 zh/en 字典必须成对添加；模板用 `{{ t('key') }}`
- **新增头像显示位**：模板直接用 `{{ get_avatar(username) }}`（已由 i18n 注入全局），空串时用 `{% if av %}` 隐藏 `<img>`；生成逻辑见 `utils.get_avatar_url`，配置在 `config.json` 的 `avatar`
- **改限流**：`config.json` 对应键 + 视图函数 `@limiter.limit` 字符串
- **改数据格式**：留意 `store.py`/`auth.py` 中的旧数据兼容注释（BUG-7 损坏数据跳过等）；加字段时给 `get_*` 用 `.get()` 兜底
- **新增可开关功能（#90）**：`feature_flags.py` 的 `FEATURES` 注册表登记（key/icon）+ i18n 加 `feature_<key>` zh/en 文案 + 视图加 `@require_feature(key)`（放 `@bp.route` 之后、`@cache.cached`/`@limiter.limit` 之前）+ config.json `features` 段加默认值；模板用 `feature_enabled(key)` 条件渲染
- **新增存储键/后端**：键布局在 `storage.py`（`KV_FILE_MAP`/`_note_key`），file 后端新键需在 `KV_FILE_MAP` 登记路径；新增后端需实现 `StorageBackend` 全部方法并在 `select_backend()` 注册（postgres 后端新表需在 `_ensure_schema` 增加 DDL）
- **写路径并发**：读改写必须「线程锁 → `storage.lock(键)`」再重读合并，顺序不可颠倒；纯整值覆盖（`write_note`）无需跨实例锁