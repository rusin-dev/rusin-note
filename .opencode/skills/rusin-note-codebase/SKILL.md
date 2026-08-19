---
name: rusin-note-codebase
description: Use when working in this project (Rusin-Note, a Flask 云端剪贴板/在线记事本). Covers the full directory structure, responsibilities of every module and view blueprint, data persistence model, routing rules, rate limiting, security mechanisms and config.json knobs, so you can navigate, modify and debug the code without re-reading files.
---

# Rusin-Note 项目结构与文件作用

Rusin-Note 是一个受 note.ms 启发的轻量级云端剪贴板 / 在线记事本，基于 Flask 3，专为 VPS 部署设计。核心是"随机短链公开笔记 + 用户私有笔记 + 分享链接 + 犇犇动态"，所有数据存内存并以 JSON 文件落盘，无数据库。

## 运行方式

- 本地/生产：`python3 -m app`（入口 `app/__main__.py`，用 waitress 监听 `$PORT` 默认 8080）
- 生产建议（Linux）：`gunicorn 'app.wsgi:app' -b 0.0.0.0:$PORT --workers 2 --threads 4`
- 数据目录：`RUSIN_DATA_DIR` 环境变量（默认 `.`），Zeabur 等平台挂卷到 `/data` 并设 `RUSIN_DATA_DIR=/data`
- 依赖：见 `requirements.txt`（Flask、Flask-WTF、Flask-Limiter、waitress、markdown、bleach）
- 要求 Python >= 3.10

## 数据模型（全部内存态 + JSON 落盘）

运行数据落在 `RUSIN_DATA_DIR` 下：

| 文件/目录 | 内容 | 关键结构 |
|---|---|---|
| `notes/` | 笔记文件（.txt） | `notes/<username>/<id>.txt`；`notes/public/` 是公开笔记命名空间 |
| `users.json` | 用户 | `{username: {salt, hash}}`，hash 为 PBKDF2 格式 |
| `sessions.json` | 会话 | `{sha256(token): {username, created_at}}` |
| `shares.json` | 分享链接 | `{token: {owner, note_id, created_at, editable, views}}` |
| `log/` | 日志 | `log/{timestamp}.log`，RotatingFileHandler |

犇犇动态为**纯内存存储**（`store.benben_posts`，重启清空，不再落盘，也没有 `benben.json`）。

所有 JSON 写入走 `store._atomic_json_dump`（临时文件 + flush + fsync + `os.replace`）。并发用 `threading.Lock`（`users_lock`/`sessions_lock`/`shares_lock`/`benben_lock`）。注意：`threading.Lock` 不可重入——持锁块内绝不能调用 `save_sessions()` 等会再次加锁的函数（见 `auth.get_session_user` 的 BUG-01 注释）。

## 根目录文件

| 文件 | 作用 |
|---|---|
| `config.json` | 运行配置（详见下方"配置项"） |
| `requirements.txt` | Python 依赖 |
| `zbpack.json` | Zeabur 打包配置 |
| `README.md` / `README_en.md` | 中英文文档（含完整配置解析与部署说明） |
| `Disclaimer.md` / `Disclaimer-en.md` | 中英文免责声明（`/disclaimer` 页面读取） |
| `contributing.md` | 协作指南 |
| `favicon.ico` / `image/logo.png` | 站点图标与 logo |
| `.github/` | Issue 模板、issue-labeler、CI/CD workflows（check/codeql/release/auto-merge/upstream-sync 等） |
| `.gitignore` | Git 忽略规则 |

## app/ 核心模块

| 模块 | 作用 |
|---|---|
| `__init__.py` | Flask app 工厂 `create_app()`：组装 SECRET_KEY（读 `RUSIN_SECRET_KEY`，缺省随机）、CSRF、限流、请求钩子、i18n、蓝图、错误页；测试模式（`TESTING`）不启动后台线程 |
| `__main__.py` | 入口 `python -m app`，waitress 启动 |
| `wsgi.py` | WSGI 入口 `app.wsgi:app`（gunicorn 用） |
| `config.py` | 加载 `config.json` 并导出全部全局常量（`MAX_CONTENT_BYTES`、各类限流参数、`ID_CHARSET`、`SHARE_TOKEN_CHARSET`/`SHARE_TOKEN_PATTERN`、密码策略 `PW_*`、`BENBEN_*`、会话/笔记过期、LaTeX、代理信任、Cookie 安全、`data_path()` 等）。标记为 ADDED/BUG-x 的注释说明某常量的引入原因 |
| `store.py` | 用户/会话/分享/犇犇的字典存储、原子持久化、分享业务（`create_share`/`get_share`/`delete_share`/`increment_share_views` 延迟批量写盘）、犇犇发布冷却（内存态）、分页读取 |
| `auth.py` | PBKDF2-HMAC-SHA256 密码哈希（兼容旧单轮 SHA-256 可验证、登录后自然升级）、会话 token 生成/校验（存哈希）、过期会话清理、密码复杂度检查 |
| `notes.py` | 笔记文件读写（`.txt`）、ID/用户名校验（含保留名单）、路径穿越防护（realpath + commonpath 校验）、统计（30s TTL 缓存）、随机 ID 生成、过期笔记清理 |
| `middleware.py` | `before_request` 钩子：向 `flask.g` 写入 `client_ip`/`lang`/`theme`/`current_user`；`get_client_ip()` 按可信度取 `CF-Connecting-IP` > `X-Real-IP` > XFF 最右非空 > remote_addr（仅 `trust_proxy_headers` 开启时） |
| `extensions.py` | CSRF（Flask-WTF）与 Limiter（Flask-Limiter）单例；限流 key 优先用 `g.client_ip` |
| `i18n.py` | 中英双语：`STRINGS` 字典（zh/en 成对），`t(lang, key)` 取翻译（缺 key 返回 key 本身）；语言检测 Cookie `rusin-lang` > Accept-Language > zh；`register_i18n` 注入模板全局 `t`/`lang`/`theme`/`current_user`/`site_name` 等 |
| `theme.py` | 暗色主题 CSS 变量（`THEME_VARS`）与切换脚本（Cookie + localStorage + 系统偏好）、favicon 内存缓存 |
| `logger.py` | `create_logger(name)` 返回写入 `log/{timestamp}.log` 的 RotatingFileHandler 日志器 |
| `utils.py` | `format_size`/`format_note_time` 格式化、`render_markdown_html`（markdown + codehilite/Pygments 高亮+行号 + bleach 清洗防 XSS）、`render_pygments_head`（亮/暗两套高亮 CSS，注入 base）、`render_latex_head`（KaTeX CDN 引入）、`read_disclaimer` |
| `background.py` | 后台守护线程：会话清理、分享视图定期刷盘、过期笔记清理（`start_background_threads()` 一次性启动） |

## app/views/ 蓝图与路由

注册顺序在 `views/__init__.py`：home → auth → benben → static_routes → world → user → share → **world_short（必须最后，因含 catch-all 短链）**。

| 蓝图 | 模块 | 路由与作用 |
|---|---|---|
| home | `home.py` | `/` 首页（登录态/匿名态卡片不同）、`/count` 统计、`/disclaimer` 免责声明 |
| auth | `auth.py` | `/register` GET/POST（注册限流，密码复杂度校验）、`/login` GET/POST、`/logout`、`/lang/<lang>` 语言切换（回跳 Referer） |
| world | `world.py` | `/world`（生成随机 ID 重定向）、`/world/<id>` GET/POST（公开笔记，POST 走 SAVE 限流）、`/world/<id>/md` 与 `/world/<id>.md` Markdown 只读渲染 |
| world_short | `world_short.py` | `/<id>`（短链重定向到 `/world/<id>`）、`/<id>.md`（短链 Markdown），catch-all 必须最后注册 |
| user | `user.py` | `/user/<u>/` 笔记列表、`/user/<u>/new` 新建、`/user/<u>/<id>` GET/POST、`/user/<u>/<id>/md`、`/user/<u>/shares` 分享管理（创建/删除）。全部 `_require_auth`（当前会话用户须等于 URL 用户名，否则 401） |
| share | `share.py` | `/share/<token>`（可编辑则进编辑页、只读则进 Markdown 页；每次访问 `increment_share_views`）、POST 写回分享者原笔记（可编辑才允许，否则 403）、`/share/<token>/md` 与 `/share/<token>.md` |
| benben | `benben.py` | `/benben` GET 分页查看（新→旧，`page` 参数）、POST 发布（需登录 + 内容长度 + 单用户冷却 + 限流） |
| static_routes | `static_routes.py` | `/favicon.ico`（内存缓存） |
| — | `_helpers.py` | 共享：`check_note_id()`（非法 ID 分情况 400/404）、`build_note_context()`（构造 note_edit/note_md 模板上下文） |

## 模板（templates/，Jinja2）

- `base.html` 基础布局；`partials/_navbar.html` 导航栏
- `home.html` 首页、`count.html` 统计、`disclaimer.html` 免责声明
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
- `benben`（犇犇最大长度 1024 / 每页 50 / 冷却 3s / 最大高度 1000px）
- `note_editor`（`live_preview_default` 编辑页实时渲染默认值，默认 false，访客可手动开、以 localStorage 记住）
- `max_note_id_length`（250）、`logger`（日志大小/路径）、`debug`

## 常见改动点

- **新增页面/路由**：在 `app/views/` 加蓝图模块并更新 `views/__init__.py` 注册；若新增根级 catch-all 路由注意注册顺序
- **新增翻译文案**：`i18n.py` 的 zh/en 字典必须成对添加；模板用 `{{ t('key') }}`
- **改限流**：`config.json` 对应键 + 视图函数 `@limiter.limit` 字符串
- **改数据格式**：留意 `store.py`/`auth.py` 中的旧数据兼容注释（BUG-7 损坏数据跳过等）；加字段时给 `get_*` 用 `.get()` 兜底