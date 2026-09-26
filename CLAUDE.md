# Rusin-Note 项目指南

## 项目简介
基于 Flask 的轻量级云端剪贴板，支持公开短链笔记、用户私有笔记、分享链接、动态（犇犇）、评论、首页工作台待办与组织/团队协作。可部署在 VPS（sqlite/file 后端）或 Vercel / AWS Lambda 等无服务器平台（upstash / postgres 后端接入外部存储）。

## 技术栈
- Python 3.10+, Flask 3, Flask-WTF, Flask-Limiter, Flask-Caching, waitress/gunicorn, mangum（Lambda 适配）
- Markdown 渲染：markdown + pymdown-extensions + bleach（防 XSS）+ Pygments（服务端代码着色）；客户端 highlight.js 兜底未识别语言并生成行号
- 前端：Jinja2 模板，支持中英双语（i18n），无独立 JS/CSS 文件（脚本样式全部内联在模板中）

## 常用命令
- 开发运行：`python3 -m app`（监听 8080，默认 sqlite 后端，端口可用 `PORT` 覆盖）
- 生产部署：`gunicorn 'app.wsgi:app' -b 0.0.0.0:$PORT --workers 2 --threads 4`
- 数据目录：由环境变量 `RUSIN_DATA_DIR` 指定（默认 `data`；仅本地 sqlite/file 后端使用）
- 依赖安装：`pip install -r requirements.txt`；测试依赖 `pip install -r requirements-dev.txt`
- 测试：`pytest tests/`（pytest + logging，`conftest.py` 自动隔离临时数据目录并清空内存缓存）
- 前端检查：`python tests/frontend_check.py`（Jinja2 语法 + 内联 JS/CSS + JSON）

## 数据存储
存储层统一在 `app/storage.py`（`storage` 单例），后端由 `RUSIN_STORAGE` 显式指定或自动识别：
- `sqlite`（默认）：`<DATA_DIR>/index.db` 存索引，内容 JSON 落盘
- `file`：纯 JSON/二进制文件落盘（兼容旧部署）
- `upstash` / `postgres`：外部 KV / PostgreSQL，多实例共享、冷启动不丢
- `memory`：纯内存，重启清空（无服务器未配外部存储时的兜底）

`RUSIN_DATA_DIR`（默认 `data/`）下的主要文件：`index.db`、`notes/<用户>/<ID>.json`、`images/`、`attachments/`、`users.json`、`sessions.json`、`shares.json`、`benben.json`、`comments.json`、`note_tags.json`、`note_folders.json`、`note_pins.json`、`todos.json`、`feature_flags.json`、`orgs.json`、`org_members.json`、`org_invites.json`、`org_join_requests.json`、`plugins/`、`log/`。

持久化采用原子写入（临时文件 + `os.replace`）；写路径统一锁序 **threading.Lock → storage.lock**，顺序颠倒会死锁。

## 关键安全约定
- **CSRF**：全站启用，不要在任何表单中省略 `{{ csrf_token() }}`。
- **限流**：基于 IP，使用 Flask-Limiter；新增路由时务必添加 `@limiter.limit` 装饰器。限流存储可用 `REDIS_URL` 切换为共享 Redis。
- **XSS 防护**：所有 Markdown 渲染必须通过 `utils.render_markdown_html`（内部使用 bleach 清洗）；新增标签/属性须同步 `allowed_tags`/`allowed_attrs` 白名单。
- **路径安全**：笔记 ID 和用户名必须符合正则 `^[a-zA-Z0-9_\-]+$`，避免路径穿越。
- **Cookie**：生产环境应开启 `secure_cookies`（仓库 config.json 已默认开启，本地开发请关闭）。

## 架构要点
- 入口：`app/__main__.py`（waitress）、`app/wsgi.py`（gunicorn）、`api/index.py`（Vercel）、`lambda_handler.py`（Lambda）
- 核心模块：`storage.py` / `storage_sqlite.py`（存储）、`store.py`（用户/会话/分享/犇犇/评论/组织）、`auth.py`（认证）、`notes.py`（笔记）、`tags.py`/`folders.py`/`pins.py`/`todos.py`（笔记组织与待办）、`images.py`/`attachments.py`（图床/附件）、`comments.py`、`user_settings.py`、`feature_flags.py`、`plugins.py`、`middleware.py`
- 路由蓝图（注册顺序见 `app/views/__init__.py`）：home, auth, benben, static_routes, world, user, share, admin, comments, org, todos, 插件蓝图, world_short（catch-all 短链必须最后注册）
- 功能开关：管理员在 `/admin/features` 切换，状态存 `feature_flags` KV 键，停用功能路由 404
- 模板：Jinja2，支持 `{{ t('key') }}` 多语言

## 文档导航
- 详细的模块职责、路由表、配置项说明，请参考 Skill：`.opencode/skills/rusin-note-codebase/SKILL.md`。
- 完整用户文档见 `README.md`（含 Vercel / Lambda / VPS 部署步骤与存储后端说明）。
