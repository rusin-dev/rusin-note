# Rusin-Note 项目指南

## 项目简介
基于 Flask 的轻量级云端剪贴板，支持公开短链笔记、用户私有笔记、分享链接、动态（犇犇）、评论、首页工作台待办、组织/团队协作，以及第三方登录（OAuth）、双因素认证（2FA）与邮箱/手机号验证。可部署在 VPS（sqlite/file 后端）或 Vercel / AWS Lambda 等无服务器平台（upstash / postgres 后端接入外部存储）。

## 技术栈
- Python 3.10+, Flask 3, Flask-WTF, Flask-Limiter, Flask-Caching, waitress/gunicorn, mangum（Lambda 适配）
- Markdown 渲染：markdown + pymdown-extensions + bleach（防 XSS）+ Pygments（服务端代码着色）；客户端 highlight.js 兜底未识别语言并生成行号
- 数据校验/处理：psycopg（PostgreSQL）、redis（可选缓存/限流共享）；图片格式校验用自研魔数嗅探（`app/apps/images/service.py`，不依赖 Pillow）
- 前端：Jinja2 模板，支持中英双语（i18n），无独立 JS/CSS 文件

## 常用命令
- 开发运行：`python3 -m app`（监听 8080，默认 sqlite 后端）
- 生产部署（VPS）：`gunicorn 'app.wsgi:app' -b 0.0.0.0:${PORT:-8080} --workers 2 --threads 4`
- WAF 供给（nginx + ModSecurity + OWASP CRS）：`waf.enabled=true` 后 `python3 -m app` 启动时自动下载规则集并生成配置；其它部署方式手动执行 `python3 -m app.core.waf`（`--refresh` 强制重下），生成的配置在 `<RUSIN_DATA_DIR>/waf/`，用 `sudo nginx -t -c <RUSIN_DATA_DIR>/waf/nginx/nginx.conf` 校验后启用
- 无服务器部署（Vercel）：`vercel.json` + `api/index.py` 已内置，绑定 Neon（自动注入 `DATABASE_URL` → postgres 后端）或 Upstash（`KV_REST_API_URL` + `KV_REST_API_TOKEN`），并设置 `RUSIN_SECRET_KEY` 即可
- 无服务器部署（AWS Lambda）：入口 `lambda_handler.handler`（Mangum）
- 数据目录：由环境变量 `RUSIN_DATA_DIR` 指定（默认 `data`；内容数据仅本地 sqlite/file 后端使用（日志 `log/`、插件 `plugins/` 与 WAF `waf/` 目录始终在该目录下））
- 依赖安装：`pip install -r requirements.txt`
- 前端语法检查：`python tests/frontend_check.py`（校验 Jinja2 模板语法、模板内联 CSS、JSON；本机有 Node 时额外校验内联 JS，CI 的 `frontend` job 会安装 Node 并执行全部检查）
- 端到端测试：统一放在 `tests/` 目录，使用 **pytest + logging**（`pip install -r requirements-dev.txt` 后运行 `pytest tests/`，如 `pytest tests/test_user_settings.py`）；`conftest.py` 会自动隔离临时 `RUSIN_DATA_DIR` 并清空运行时缓存

## 数据存储（重点：可插拔后端）
存储层统一在 `app/core/storage.py`（**统一数据接口**，所有业务模块只通过 `storage` 单例访问数据），后端由 `RUSIN_STORAGE` 显式指定或自动识别：

| 后端 | 启用 | 说明 |
|---|---|---|
| sqlite | 默认（本地/VPS） | SQLite 索引（`<DATA_DIR>/index.db`）用于快速列表/排序/检索/统计，具体内容 JSON 落盘于 `RUSIN_DATA_DIR`（默认 `data/`）；笔记为 `notes/<用户>/<ID>.json`，集合为 `users.json` 等；实现见 `app/core/storage_sqlite.py`，旧版 file 布局首次启动自动迁移 |
| file | `RUSIN_STORAGE=file` | 纯 JSON 文件落盘（兼容旧部署），布局同上但不含 `index.db` |
| upstash | `KV_REST_API_URL` + `KV_REST_API_TOKEN` | Upstash Redis REST API（纯 urllib，无驱动依赖），键统一加 `rusin:` 前缀，多实例共享 |
| postgres | `DATABASE_URL`（Neon / 任意 PostgreSQL，Vercel 绑定 Neon 自动注入） | psycopg 驱动，表 `storage_kv`（通用 KV）+ `storage_notes`（笔记）+ `storage_images` / `storage_attachments`（二进制）；跨实例互斥用 PG advisory lock |
| memory | `RUSIN_STORAGE=memory`（无服务器且未配以上存储时自动） | 纯内存，重启清空 |

自动识别优先级：显式 `RUSIN_STORAGE` > KV 环境变量（upstash）> `DATABASE_URL`（postgres）> 无服务器平台（memory）> 本地（sqlite）。

- 集合类 KV 键在 `storage.py` 的 `KV_FILE_MAP` 登记落盘文件名（`users.json`、`sessions.json`、`shares.json`、`benben.json`、`comments.json`、`note_tags.json`、`note_folders.json`、`note_pins.json`、`note_titles.json`、`todos.json`、`feature_flags.json`、`orgs.json`、`org_members.json`、`org_invites.json`、`org_join_requests.json`、`oauth_accounts.json`、`two_factor.json`、`user_contacts.json`、`verification_codes.json`、`.secret_key`）；笔记键为 `note:<用户>:<ID>`，图床/附件键为 `img:` / `att:` 前缀（file/postgres 后端走原生二进制文件）。

- 统一接口在基类 `StorageBackend` 提供笔记元数据/检索能力：`note_title`、`list_notes_detailed`、`search_notes`、`notes_stats`（与后端无关的退化实现），SQLite 后端覆盖为单次索引查询（`notes.py` 的 `search_user_notes`/`get_stats` 与列表页据此避免逐篇读取内容）。

- 犇犇动态已改为持久化（最多 `benben.max_posts` 条，默认 200），不再纯内存。犇犇/评论内容限高滚动：`benben.max_height_px` / `comments.max_height_px` 默认 280（超出在内容区内滑动，防长帖霸屏；视图渲染时必须传 `max_height_px`，模板变量为空会让 `max-height` 静默失效）。
- **尾斜杠路由**：POST 型动作路由（笔记删除 `/user/<u>/<id>/delete`、组织笔记删除、待办删除）统一 `strict_slashes=False`，同时接受带/不带尾斜杠——否则尾斜杠触发重定向链，经代理层降级为 GET 后 404。回归测试：`pytest tests/test_regression_fixes.py`
- 写路径统一锁序：**threading.Lock（进程内）→ storage.lock（跨进程/跨实例）**，顺序颠倒会死锁（见 `store.flush_share_views` 注释）。
- 无服务器环境（`VERCEL`/`NETLIFY`/`AWS_LAMBDA_FUNCTION_NAME`）不启动后台线程，清理由 `middleware._opportunistic_cleanup()` 请求内机会式执行；日志回退 stderr。
- `RUSIN_SECRET_KEY` 必填于无服务器平台；可持久化后端会自动生成并存储（键 `secret_key`）。

## 关键安全约定
- **CSRF 防护**：全站启用，不要在任何表单中省略 `{{ csrf_token() }}`。
- **限流**：基于 IP，使用 Flask-Limiter；新增路由时务必添加 `@limiter.limit` 装饰器（另有 `ip_rate_limit` 全站每 IP 总上限，应用级作用域对所有路由生效）。限流存储可用 `REDIS_URL` 切换为共享 Redis。
- **单用户并发闸门（长连接防护，#191）**：IP 限流只约束「单位时间请求数」，拦不住「少量请求、超长时间占用」（如发起上千个队列、每个以 1KB/s 传输，或用 100 线程并行下载）。附件下载/上传因此额外经 `app/core/concurrency.py` 的进程内闸门限制**单用户同时在途数**（`attachments.max_concurrent_downloads` 默认 1 / `max_concurrent_uploads` 默认 1，即每账号 1 个下载队列 + 1 个上传队列；`0` = 不限）；`Slot.release()` 幂等，必须同时挂在生成器 `finally` 与 `Response.call_on_close` 上，异常/断开/正常结束三条路径都要归还名额。超限即拒绝（不排队，排队同样占 worker）：下载走全局 429 处理器（带 `Retry-After` + 文案），上传返回 429 JSON。计数在进程内，N 个 worker ≈ `N × 上限`。端到端测试：`pytest tests/test_attachments.py`
- **附件下载权限**：`/attachment/<u>/<id>` 默认**禁止匿名下载**（`attachments.allow_anonymous_download=false`，未登录 401 并提示登录），响应缓存为 `private`（避免共享缓存回放给匿名访客）；仅登录用户可下载，如需「仅本人可下载」须另加所有权校验（见 `app/apps/attachments/views.py` 注释与测试 B3）。
- **客户端 IP / 防 XFF 伪造**：`g.client_ip` 一律经 `app/core/ip_utils.py` 解析——仅当 TCP 直连对端命中 `trusted_proxies`（IP/CIDR 或预设 `loopback`/`private`/`cloudflare`，`"*"` 为不安全的兼容模式）时才采信 `X-Forwarded-For`/`X-Real-IP`/`CF-Connecting-IP`，且只接受合法 IP、XFF 从右往左解析。**不要**使用 `ProxyFix`，也不要直接读 `request.remote_addr` 或原始代理头做限流/冷却，否则可被伪造头绕过。`ip_blocklist` 直接 403，`ip_allowlist` 免限流（并支持 `RUSIN_TRUSTED_PROXIES`/`RUSIN_IP_ALLOWLIST`/`RUSIN_IP_BLOCKLIST` 环境变量）。端到端测试：`pytest tests/test_ip_limiter.py`
- **反向代理 WAF（可选，`app/core/waf.py`）**：`waf.enabled=true` 后由启动脚本自动下载 OWASP CRS 并生成 nginx + ModSecurity 配置，攻击流量在进 Flask 之前就被拦掉（与应用内 Flask-Limiter 构成纵深防御）。**供给脚本只做下载与写配置**：不装系统包、不执行下载到的任何二进制、默认不 reload nginx（`waf.auto_reload` 显式开启才做，需 root）。CRS 版本与 SHA256 双锁定在 config，换版本必须同步换校验和；`waf.verify_checksum=false` 会接受任意内容，仅限内网镜像调试。上线务必先跑 `waf.mode=detectiononly` 观察 `<DATA_DIR>/waf/log/audit.log`，确认无误报再改 `on`。
- **XSS 防护**：所有 Markdown 渲染必须通过 `utils.render_markdown_html`（内部使用 bleach 清洗）；GitHub 风格提示卡片（`> [!NOTE]` 等）在 utils 内以 treeprocessor 转为 `<details>`，输出前同样过 bleach——新增标签/属性时须同步 `allowed_tags`/`allowed_attrs` 白名单。
- **路径安全**：笔记 ID 和用户名必须符合正则 `^[a-zA-Z0-9_\-]+$`，避免路径穿越；后端键由 storage 层统一构造，解析用 `parse_note_key`。
- **Cookie**：生产环境应开启 `secure_cookies`（仓库 config.json 已默认开启，本地开发请关闭）。

## 架构要点
- 入口：`app/__main__.py`（waitress）或 `app/wsgi.py`（gunicorn）；无服务器：`api/index.py`（Vercel）、`lambda_handler.py`（Lambda）
- 代码分层：**共享内核 `app/core/`**（基础设施 + 跨功能领域服务）与**功能 App `app/apps/<feature>/`**（每个 App 自带 `views.py` 蓝图，必要时带 `service.py` 业务逻辑）；`app/apps/registry.py` 统一按序注册各 App 蓝图。
- 核心模块（`app/core/`）：`storage.py`（存储后端抽象）、`storage_sqlite.py`（默认 SQLite 索引后端）、`store.py`（数据存储业务）、`auth.py`（认证，含 `set_session_cookie`/`clear_session_cookie` 共享 Cookie 助手）、`totp.py`（纯标准库 RFC 6238 TOTP 与恢复码）、`cleanup.py`（清理任务注册表：依赖倒置，避免 core → app）、`notes.py`（笔记底层操作）、`tags.py`/`folders.py`/`pins.py`（笔记标签/文件夹/置顶）、`middleware.py`（请求上下文）、`ip_utils.py`（客户端 IP 安全解析 / 可信代理校验 / IP 名单）、`concurrency.py`（进程内并发闸门：单用户在途请求上限）、`prefs.py`（简洁模式偏好）、`plugins.py`（插件系统：zip 解压安装 / auth_token 校验 / 命名空间冲突检查 / 蓝图加载 / 上游更新线程）、`feature_flags.py`（功能开关：注册表 + 存储持久化 + `require_feature` 装饰器）
- 功能 App（`app/apps/`）：home / auth / notes / world / share / benben / comments / org / todos / images / attachments / user / admin / static / **oauth**（第三方登录）/ **twofa**（双因素认证）/ **email**（邮箱/手机号验证）；其中 `comments`、`todos`、`images`、`attachments`、`user`、`oauth`、`twofa`、`email` 自带 `service.py`（业务逻辑：评论存取、待办、图床/附件校验配额、密码与改名迁移、OAuth 流程与账号绑定、TOTP 状态、联系方式与验证码）。
- 路由蓝图（`app/apps/`，注册顺序见 `app/apps/registry.py`）：home, auth, benben, static, notes, images, attachments, user, share, world, admin（`/admin/features` 功能开关管理）, comments, org（组织/团队协作）, todos（工作台待办）, oauth / twofa / email（认证与验证）, **插件蓝图（在 registry.register_blueprints 内注册）**, world_short（注意最后注册 catch-all）
- 用户设置（`/user/<u>/settings`，`app/apps/user/service.py`）：简洁模式（原导航栏切换按钮已并入，账号级偏好存 users.json，`middleware` 注入 `g.simple_mode` 服务端渲染 `<html class="simple-mode">`，页面缓存键含该标志）、修改密码（注销其它会话；纯第三方注册账号无密码时允许直接设置初始密码）、修改用户名（先复制笔记/图床/附件再迁移各存储用户标识（含 2FA/联系方式/第三方绑定），最后删旧数据）、账号安全总览（链接到 `/user/<u>/twofa`、`/user/<u>/email`、`/user/<u>/oauth`）。端到端测试：`pytest tests/test_user_settings.py`
- 第三方登录（OAuth，`app/apps/oauth/`）：Provider 注册表覆盖 GitHub / Google / Microsoft / 微信 / QQ，网络请求全部用标准库 `urllib`（无 authlib/requests 依赖）；`oauth.providers` 填凭据、`oauth.auto_register` 控制自动注册、`oauth.enabled` 为总开关（默认 false，硬关闭全部 OAuth）；账号绑定存 KV 键 `oauth_accounts`（`provider:uid → username`，一 uid 仅绑一人）；路由 `/oauth/<provider>`（发起，`?link=1` 为绑定）、`/oauth/<provider>/callback`、`/user/<u>/oauth` 管理页；state/PKCE 存 Flask 签名会话；可用 = `oauth.enabled` 总开关 ∧ `oauth_<provider>` 功能开关 ∧ 凭据已配置，三者任一不满足即 404 / 不展示。端到端测试：`pytest tests/test_oauth.py`
- 双因素认证（2FA，`app/apps/twofa/`）：TOTP 算法在 `app/core/totp.py`（纯标准库），状态存 KV 键 `two_factor`（密钥 + 恢复码哈希 + 防重放 `last_step`）；`/login/2fa` 为密码校验后的第二因素页，`/user/<u>/twofa` 为绑定/确认/停用/重生成恢复码管理页；受 `two_factor_auth` 开关控制；密码校验成功后若 `twofa.service.is_required` 为真则转入第二因素页。端到端测试：`pytest tests/test_twofa.py`
- 邮箱/手机号验证（`app/apps/email/`）：联系方式存 KV 键 `user_contacts`（值 + `verified`），验证码存 `verification_codes`（仅哈希 + 有效期 + 尝试次数 + 冷却）；投递用 SMTP（`security.smtp`）与通用短信 Webhook（`security.sms`），未配置时记录日志且不落库；支持绑定验证（`purpose=bind`）与验证码免密登录（`purpose=login`，`/login/otp`）；管理页 `/user/<u>/email`；受 `email_verify`/`phone_verify` 开关控制。端到端测试：`pytest tests/test_email_verify.py`
- 首页公告横幅：`app/apps/home/views.py` 的 `index` 读取 `config.NOTICE_FILE`（仓库根目录 `NOTICE.txt`）第一个非空行（跳过前导空行）并传入 `home.html`，内容非空时渲染 `.home-notice` 横幅（文本经 HTML 转义）；读取逻辑见 `utils.read_notice_first_line`，端到端测试 `pytest tests/test_home_notice.py`
- 功能开关（`app/core/feature_flags.py`，#90）：管理员（`RUSIN_ADMIN` 环境变量或 config.json `admin_users`）在 `/admin/features` 用滑块切换；运行时状态存 KV 键 `feature_flags`（file 后端即 `feature_flags.json`），进程内 5s TTL 缓存；停用功能路由 404、导航/首页入口隐藏，状态呈现于 `/count`。注册表共 27 项（含 `notes_import_export`/`login_captcha`/`oauth_github`/`oauth_google`/`oauth_microsoft`/`oauth_wechat`/`oauth_qq`/`two_factor_auth`/`email_verify`/`phone_verify`，默认读 `features` 段且 OAuth/验证类默认 false），并按 `FEATURE_GROUPS` 五组（`notes`/`rendering`/`media`/`account`/`security`）分组呈现于管理页与 `/count`（各组为 `<details>` 折叠区块，默认收起，标题旁显示启用数/总数）。新增可开关功能：在 `FEATURES` 注册表登记（key/icon/group，组 id 须已注册）+ 视图加 `@require_feature(key)`（必须放 `@bp.route` 之后、`@cache.cached`/`@limiter.limit` 之前；Provider 级动态开关在视图中用 `feature_enabled("oauth_<key>")` 判定）。
- 插件系统（`app/core/plugins.py`；无服务器只读盘环境自动禁用）：`*.plugin.zip` 投放到 `RUSIN_DATA_DIR` 自动解压安装到 `plugins/<namespace>/` 并删除包；desc.json 缺 `auth_token` 须 `--skip-auth`（或 `RUSIN_PLUGIN_SKIP_AUTH=1`）放行；命名空间冲突非同源且未声明 OVERRIDE 拒绝；后台线程每 `plugins.update_interval_hours`（默认 6h）检查，`last_update` 超过 `update_stale_days`（默认 3 天）则请求 `upstream_repo`（3s 超时）后重跑安装。
- 反向代理 WAF（`app/core/waf.py`，`waf.enabled` 默认 false）：Flask 进程内没有可用的开源 WAF 引擎，本项目采用业界轻量方案 **nginx + ModSecurity + OWASP CoreRuleSet**，可自动化的部分由 `python -m app` 启动时供给（gunicorn / Lambda 用 `python -m app.core.waf [--refresh]` 手动供给，避免多 worker 重复下载）：① 下载 CRS minimal 规则集（`waf.crs_version` + `crs_sha256` 双锁定，仅放行 https，校验失败即丢弃并保留已装版本；换版本必须同步换校验和）到 `<DATA_DIR>/waf/crs/`；② 生成 `modsecurity.conf`（`SecRuleEngine On|DetectionOnly` 随 `waf.mode`）、`crs-setup.conf`（等级/阈值，**必须写 `tx.crs_setup_version`，否则 CRS 的 901001 直接 500 罢工**，该值从随包 `crs-setup.conf.example` 提取）、`exclusions.conf`、`nginx/nginx.conf`（standalone，可 `nginx -c` 直接跑）与 `nginx/rusin-note.conf`（conf.d 片段）；`custom.conf` 只生成一次不覆盖，Include 顺序固定为 setup → exclusions → `crs/rules/*.conf` → custom（排除规则必须先于 CRS 生效）。**安全约定**：只下载解压文本规则，绝不下载/执行二进制、不装系统包、默认不 reload nginx（`waf.auto_reload=true` 才执行，需 root）；tar 解压做穿越/软链/设备文件/体积与文件数上限防护且不复用权限位；写进 nginx 配置的 `listen`/`server_name`/`upstream` 经 `_nginx_token` 白名单校验，防配置注入；引擎缺失或下载失败都不抛异常（WAF 是可选纵深防御层，不能拖垮启动），`nginx -t` 或 reload 失败即 `ready=false`。**两个易踩的坑**：`waf.body_limit_kb=0` 时自动取笔记/导入/附件上限的较大值，配小了会让上传先被 nginx 回 413；反代后必须 `trust_proxy_headers=true` 且 `trusted_proxies` 覆盖回源地址，否则应用只看到反代 IP、全站每 IP 限流会集体 429（供给时会主动告警）。内容型端点（笔记正文/评论/待办/导入）默认按 tag 排除注入类规则——粘贴 SQL/JS/shell 代码是本站核心用法，正文渲染前都过 bleach；只关注入类，协议强制(920)/方法强制(911)/扫描器识别(913) 仍全程生效，`waf.default_exclusions=false` 可关。无服务器环境自动跳过（只读盘 + 平台自带 WAF）。端到端测试：`pytest tests/test_waf.py`（离线，网络与子进程均由 monkeypatch 替换）
- 组织/团队协作（`app/apps/org/views.py` + `app/core/store.py` 组织段）：组织笔记以 `_orgs/<org_name>` 作为存储用户名命名空间，与个人笔记完全隔离；Owner / Admin / Member 三级角色，加入方式支持邀请码 / 公开加入 / 审批制，受 `orgs` 功能开关控制。端到端测试：`pytest tests/test_org.py`
- 评论系统（`app/apps/comments/service.py` + `app/apps/comments/views.py`）：目标类型为 `note` / `share`，统一存 KV 键 `comments:all`（file 后端即 `comments.json`），受 `comments` 功能开关与 `comments` 配置段（长度 / 上限 / 冷却 / 分页）控制。
- 首页落地页（`app/apps/home/views.py` + `templates/home.html`）：登录态 `/` 为类 ChatGPT 官网风格互动落地页，自上而下为「居中 Hero（头像+问候语、渐变大标题、双 CTA）→ 数据亮点（笔记总数/近一年更新/活跃天数）→ 常用功能入口卡片（按功能开关过滤：导入导出、犇犇、组织等）→ 使用指南三步 → 记录轨迹（近一年笔记热力图 + 最近编辑）→ FAQ（`<details>` 折叠）→ 渐变 CTA 横幅」，样式在 home.html 内 `.lp-*` 且仅登录分支输出；匿名 `/` 保持站点入口页；TODO 待办 UI 已移出首页（`app/apps/todos/` 后端路由保留）；简洁模式下首页 302 直接跳到新建笔记。端到端测试：`pytest tests/test_home_landing.py`
- 笔记批量导入 / 导出（`app/apps/notes/service.py` + `/user/<u>/export|import`，受 `notes_import_export` 开关控制）：导出默认 ZIP（每篇 `notes/<id>.md` + `manifest.json` 记录文件夹/标签，导入可还原），`?format=md` 导出为单文件 Markdown（`<!-- rusin-note-id: X -->` 标记）；导入接受 .zip/.md/.txt，同名笔记**跳过不覆盖**，受 `note_transfer`（max_file_kb / max_notes）与单笔记大小上限约束，全程内存处理不落盘解压。端到端测试：`pytest tests/test_note_transfer.py`
- 登录/注册页与图形验证码（`app/core/captcha.py`，受 `login_captcha` 开关控制，默认开）：登录页与注册页为全幅左右分栏、无卡片外壳，共用结构（`.auth-split` 左通高插画 `/image/login-hero.webp` + 右居中表单）与样式 partial `templates/partials/_auth_split_css.html`（`base.html` 的 `{% block body_class %}` 钩子加 `auth-page` 类：隐藏顶栏并重置 `.container` 卡片；≤768px 隐藏插画回退单列+浮动语言切换；输入框/按钮统一 46px 高、10px 圆角，主按钮主题色）。验证码行与刷新 JS 也抽为 `partials/_captcha_row.html` / `_captcha_js.html`，登录与注册共用；POST 时验证码先行校验，失败 400 并重签发；两页 GET 均回 `Cache-Control: no-store`，`create_app` 开 `TEMPLATES_AUTO_RELOAD=True`（注意 auto-reload 不覆盖被 include 的 partial，改 partial 需重启）。验证码为纯标准库生成的 SVG（旋转字符 + 噪点干扰线，4 位去混淆字符集），答案存 KV 键 `login_captchas`（TTL 10 分钟、一次性、verify 即销毁、写入时清理过期项），token 经十六进制格式校验；`GET /login/captcha` 返回新 token/SVG 供刷新按钮使用。端到端测试：`pytest tests/test_login_captcha.py`
- 测试清单：`tests/` 覆盖 `test_org` / `test_user_settings` / `test_images` / `test_pins` / `test_folders` / `test_sqlite_storage` / `test_markdown_alerts` / `test_home_notice` / `test_home_landing` / `test_attachments` / `test_ip_limiter` / `test_frontend` / `test_oauth` / `test_twofa` / `test_email_verify` / `test_note_transfer` / `test_login_captcha` / `test_waf`，统一 `pytest tests/` 运行。
- 模板：Jinja2，支持 `{{ t('key') }}` 多语言
- 无服务器默认存储：Vercel 绑定 Neon 后 `DATABASE_URL` 自动注入 → 自动切到 postgres 后端
- 前端检查：前端资源全部内联在 Jinja2 模板中，无独立 JS/CSS 文件；`tests/frontend_check.py` 做静态语法检查（Jinja2 `Environment.parse` + Node `--check` 校验内联 JS + CSS 括号配平 + JSON 解析），由 `.github/workflows/check.yml` 的 `frontend` job 在前端文件变更时运行

## 文档导航
- 详细的模块职责、路由表、配置项说明，请参考 Skill：`.opencode/skills/rusin-note-codebase/SKILL.md`。
- 完整用户文档见 `docs/`：各部署方式（Vercel / Lambda / VPS / Zeabur）与存储后端说明在 `docs/deployment/`，配置项详解在 `docs/configuration.md`，插件系统在 `docs/plugins.md`；`README.md` 仅保留概览与跳转链接。