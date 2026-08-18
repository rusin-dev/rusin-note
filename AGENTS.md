# Rusin-Note 项目指南

## 项目简介
基于 Flask 的轻量级云端剪贴板，支持公开短链笔记、用户私有笔记、分享链接和动态（犇犇）。数据全部内存存储，通过 JSON 文件持久化，无需外部数据库。

## 技术栈
- Python 3.10+, Flask 3, Flask-WTF, Flask-Limiter, waitress/gunicorn
- Markdown 渲染：markdown + bleach（防 XSS）+ Pygments（代码高亮、行号）
- 前端：Jinja2 模板，支持中英双语（i18n）

## 常用命令
- 开发运行：`python3 -m app`（监听 8080）
- 生产部署：`gunicorn 'app.wsgi:app' -b 0.0.0.0:$PORT --workers 2 --threads 4`
- 数据目录：由环境变量 `RUSIN_DATA_DIR` 指定（默认 `.`）
- 依赖安装：`pip install -r requirements.txt`

## 数据存储
所有数据位于 `RUSIN_DATA_DIR`：
- `notes/`：笔记文件（公开/用户）
- `users.json`、`sessions.json`：用户与会话
- `shares.json`：分享链接
- `benben.json`：动态消息（已改为内存态，重启清空，不再落盘）
- `log/`：日志文件

持久化采用原子写入（临时文件+`os.replace`），并发操作使用 `threading.Lock`。

## 关键安全约定
- **CSRF 防护**：全站启用，不要在任何表单中省略 `{{ csrf_token() }}`。
- **限流**：基于 IP，使用 Flask-Limiter；新增路由时务必添加 `@limiter.limit` 装饰器。
- **XSS 防护**：所有 Markdown 渲染必须通过 `utils.render_markdown_html`（内部使用 bleach 清洗）。
- **路径安全**：笔记 ID 和用户名必须符合正则 `^[a-zA-Z0-9_\-]+$`，避免路径穿越。
- **Cookie**：生产环境应开启 `secure_cookies`。

## 架构要点
- 入口：`app/__main__.py`（waitress）或 `app/wsgi.py`（gunicorn）
- 核心模块：`store.py`（数据存储）、`auth.py`（认证）、`notes.py`（笔记操作）、`middleware.py`（请求上下文）
- 路由蓝图：home, auth, benben, static_routes, world, user, share, world_short（注意最后注册 catch-all）
- 模板：Jinja2，支持 `{{ t('key') }}` 多语言

## 文档导航
- 详细的模块职责、路由表、配置项说明，请参考 Skill：`.opencode/skills/rusin-note-codebase/SKILL.md`。
- 完整用户文档见 `README.md`。