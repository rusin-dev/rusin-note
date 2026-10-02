# 配置项详解

本文列出 `config.json` 各配置项与环境变量的含义、默认值与安全说明。部署方式见 [部署总览](deployment/index.md)，存储后端选择见 [存储后端说明](deployment/storage-backends.md)，反向代理与真实 IP 见 [真实客户端 IP 与防 XFF 伪造](deployment/ip-and-proxy.md)。

> 说明：以下「默认值」以仓库 `config.json` 为准；配置缺失时部分项存在代码回退值，已在对应条目注明。

## 基础与站点

- `max_note_size_kb`：笔记最大大小（单位：**KB**）默认 $512$（即 $0.5$ MB，为仓库 `config.json` 的值；配置缺失时代码回退 $5120$）。
- `sitename`：网页名称。填你的站点名。
- `global_cdn` 全局前端静态资源 CDN 基础地址。
   - 默认 `https://cdn.jsdmirror.cn`；

   前端资源统一从该地址拼接加载：FontAwesome 图标、marked 编辑器脚本、DOMPurify 清洗库与 KaTeX 公式（路径均为 `npm/` 形式，因此也兼容 `https://cdn.jsdelivr.net` 等 npm CDN）。可按网络环境在 config.json 中整体替换，无需改代码。

## 速率限制

- `rate_limit` 速率限制。
   - `window_seconds` ： 时间 $t$，默认 $60$；
   - `max_requests` ：请求数 $s$，默认 $30$;

   $t$ 秒内最大请求 $s$ 次。
- `get_rate_limit` GET 请求独立限流。
   - `window_seconds` ：时间 $t$，默认 $60$；
   - `max_requests` ：请求数 $s$，默认 $45$;

   $t$ 秒内 GET 请求最大 $s$ 次（world / 笔记 / 用户列表等显式标注的路由；首页、`/count` 与静态资源未挂 GET 限流，只受下方 `ip_rate_limit` 约束）。
- `save_rate_limit` 保存类 POST 独立限流（笔记保存/分享写回）。
   - `window_seconds` ：时间 $t$，默认 $60$；
   - `max_requests` ：请求数 $s$，默认 $120$;

   $t$ 秒内保存笔记最多 $s$ 次；这是保存类路由专用的一档，与其它 POST 路由共用的 `rate_limit` 分开计数，避免频繁保存被误伤。
- `register_rate_limit` 注册速率限制（单IP注册账号限制）。
   - `window_seconds` ：时间 $t$，默认 $120$；
   - `max_requests` ：请求数 $s$，默认 $1$;

   $t$ 秒内单个IP最多注册 $s$ 个账号，防止恶意批量注册。
- `ip_rate_limit` 全站每 IP 总请求上限（**应用级**限流，对所有路由累计生效，叠加在各路由独立限流之上）。
   - `window_seconds` ：时间 $t$，默认 $60$；
   - `max_requests` ：请求数 $s$，默认 $300$（置 `0` 关闭全站兜底限流）；
   - `enabled` ：开关，默认 `true`，置 `false` 同样关闭兜底限流。

## IP 与 Cookie（反向代理相关）

- `trust_proxy_headers`：是否信任反向代理传递的客户端 IP 头，当前仓库配置为 `true`，适用于无服务器平台或可信反向代理。
  
  **安全说明**：应用内置默认值为关闭；仅当部署在可信反向代理（如 Nginx、Vercel）之后才置为 `true`，否则客户端可能伪造请求头绕过限流。
- `trusted_proxies`：**可信代理网段**（防伪造 `X-Forwarded-For` 的关键）。仅当 TCP 直连对端命中该列表时才会采信代理头；公网直连时所有代理头一律忽略，按直连 IP 限流。

  元素可为 IP/CIDR，也可用预设名 `loopback`（回环）、`private`（RFC1918 / CGNAT / 链路本地）、`cloudflare`（Cloudflare 官方回源段），或用 `"*"` 信任任意对端（**有伪造风险**，仅建议临时排障使用）。默认 `["loopback", "private"]`。
- `proxy_hops`：兼容模式（`trusted_proxies` 设为 `"*"` / `"any"` / `"all"`）下 `X-Forwarded-For` 从右往左的代理跳数，默认 `1`；列表为空**不**等于兼容模式，而是「不采信任何代理头」。
- `ip_allowlist`：免限流 IP/CIDR 白名单（如监控、内网探活），默认 `[]`。
- `ip_blocklist`：直接拒绝（HTTP 403）的 IP/CIDR 黑名单，默认 `[]`。

  以上 IP 相关配置也可用环境变量覆盖（无服务器平台配置文件只读时更方便）：`RUSIN_TRUSTED_PROXIES`、`RUSIN_PROXY_HOPS`、`RUSIN_IP_ALLOWLIST`、`RUSIN_IP_BLOCKLIST`（逗号分隔，名单类环境变量与配置文件取并集）。
- `secure_cookies`：会话 Cookie 是否附加 `Secure` 标志，当前仓库配置为 `true`。

  **安全说明**：仅当通过 HTTPS 访问时置为 `true`，否则浏览器会拒绝在 HTTP 下回传 Cookie。

## ID / Token 生成

- `id_generation` 随机 url 配置（下列为仓库 `config.json` 的值，配置缺失时代码回退为长度 $6$、大小写与数字全开）。
   - `length` ：长度，默认 $4$；
   - `use_uppercase` ：是否使用大写字母，默认 `false`；
   - `use_lowercase` ：是否使用小写字母，默认 `true`；
   - `use_digits` ：是否使用数字，默认 `false`；
- `share_token` 分享链接 token 配置。
   - `length` ：长度，默认 $64$；
   - `use_uppercase` ：是否使用大写字母，默认 `true`；
   - `use_lowercase` ：是否使用小写字母，默认 `true`；
   - `use_digits` ：是否使用数字，默认 `true`；

## 会话与过期

- `session_timeout` 单次会话时间。
   - `enabled` ：是否开启，默认 `false`；
   - `minutes` ：设定时长，（单位：**分钟**）当前仓库默认 $1440$；

    当时间超过设定时，将登出访客账号。
- `note_expiration` 笔记自动清除（剪贴板超过保存时间自动删除）。
   - `enabled` ：是否开启，默认 `false`；
   - `hours` ：保存时长（单位：**小时**）默认 $24$；

    开启后，超过设定小时数未被修改的剪贴板（公开+私有）将被后台线程自动删除，每 30 分钟扫描一次。

## 渲染

- `latex_render` LaTeX 公式渲染。
   - `enabled` ：是否开启，默认 `true`；
   - KaTeX 静态资源从 `global_cdn` 基础地址拼接（默认 jsdmirror，可换 jsdelivr 等）；

    开启后，Markdown 只读页面支持 `$...$` 行内公式与 `$$...$$` 块级公式（KaTeX 洛谷同款，客户端渲染，无需服务端依赖）。
- `code_highlight` 代码高亮（服务端 Pygments 着色 + 客户端 highlight.js 补充）。
   - `enabled` ：是否开启，默认 `true`；

    代码块在服务端始终由 Pygments 分词着色；该开关额外控制客户端 highlight.js：开启后，所有 Markdown 渲染处（笔记只读页、编辑页实时预览、犇犇动态、评论、免责声明）对 Pygments 未识别的语言兜底高亮、生成行号，并跟随站点浅色/暗色主题切换。关闭后行号与客户端高亮一并移除，服务端着色仍保留。

## 缓存

- `cache` 页面缓存。
   - `enabled`：是否启用缓存，默认 `true`；
   - `backend`：缓存后端，当前配置为 `redis`；
   - `default_timeout`：默认缓存时间（秒），当前为 `300`；
   - `redis_url`：Redis 地址，可由环境变量 `REDIS_URL` 覆盖。Redis 不可达时自动降级到进程内 SimpleCache。

     另外：限流计数存储也读取 `REDIS_URL`（设置后多实例共享限流计数，未设置用进程内 memory://）。

## 编辑器与首页

- `note_editor` 编辑页行为。
   - `live_preview_default`：实时预览的默认开关，默认 `false`；访客可手动开启，选择记在浏览器 localStorage；
   - `markdown_manual_url`：编辑页「Markdown 语法说明」链接地址，默认 `https://markdown.com.cn`。
- `home_page` 首页工作台。
   - `recent_notes_limit`：首页展示的最近编辑笔记条数，默认 `5`；
   - `recent_shares_limit`：预留的最近分享条数（当前首页未展示分享列表），默认 `5`。
- `todos` 首页工作台待办清单。
   - `max_items`：单个用户待办条数上限，默认 `100`；
   - `max_length`：单条待办文本长度上限（字符），默认 `200`。

## 笔记组织

- `note_refs` 笔记快捷引用（`#` 引用）。
   - `enabled` ：是否开启，默认 `true`；置 `false` 后编辑器不弹引用补全框、渲染时不把 `#ID` 转为链接；
   - `search_limit` ：补全接口单次最多返回条数，默认 `8`；
   - `scan_limit` ：补全搜索最多扫描的笔记数（按修改时间倒序），默认 `100`。upstash / postgres 等远程存储后端每篇笔记需一次网络读取，笔记较多时可适当调低。
- `max_note_tags`：每篇笔记最多标签数，默认 `10`；
- `max_tag_length`：单个标签最大长度（单位：**字符**），默认 `24`；
- `max_folder_name_length`：文件夹名最大长度（单位：**字符**），默认 `64`；
- `max_folder_depth`：文件夹嵌套层级上限（以 `/` 分隔计数），默认 `8`；
- `max_note_id_length`：笔记 ID 最大长度，默认 `250`（短链/长链接兼容性上限）；

## 头像

- `avatar` 用户头像（通过第三方服务生成，显示在导航栏当前用户、犇犇动态发布者与用户笔记列表标题处）。
   - `enabled` ：是否开启，默认 `true`；置 `false` 后完全关闭头像显示；
   - `url_template` ：头像 URL 模板，默认 `https://cn.cravatar.com/avatar/{hash}?d=identicon&f=y`。支持两个占位符：`{hash}`（`md5(用户名)` 小写十六进制）、`{username}`（URL 编码后的用户名）。由于本站用户没有邮箱，默认用 `md5(用户名)` 作为哈希，`d=identicon` 会让 Gravatar 系服务为每个哈希生成确定性的几何头像；也可换成其他按用户名生成头像的服务（如 DiceBear：`https://api.dicebear.com/9.x/identicon/svg?seed={username}`）；
   - `size` ：模板中的默认尺寸（当前仅作为备用值，模板内按位置使用固定尺寸）。

## 图床与附件

- `images` 笔记图床（编辑器粘贴/拖拽上传，`/image/<u>/<id>` 公开访问）。
   - `enabled`：是否启用，默认 `true`；
   - `max_size_kb`：单张图片上限，默认 `2048`（2MB）；
   - `max_total_kb`：每用户图片总配额，默认 `51200`（50MB）；
   - 支持 PNG、JPEG、GIF、WebP，并按文件魔数校验；SVG 不允许上传。
- `attachments` 笔记附件（编辑器附件按钮上传，`/attachment/<u>/<id>` 默认**需登录**下载）。
   - `enabled` ：是否开启，默认 `true`；置 `false` 后编辑器不显示附件按钮、附件管理页返回 404；
   - `max_size_kb` ：单个附件上限（KB），默认 `50`；
   - `max_per_note_kb` ：单个笔记引用附件总量上限（KB），默认 `500`；
   - `max_total_kb` ：每用户附件总配额（KB），默认 `10240`（10MB）；
   - `allow_anonymous_download` ：是否允许**匿名（未登录）**下载附件，默认 `false`：未登录访问 `/attachment/<u>/<id>` 返回 401（错误页提示先登录）；置 `true` 回到「知道链接即可下载」的旧行为；
   - `max_concurrent_downloads` ：**单用户同时下载**上限（同一账号在途的下载请求数），默认 `1`（[#191](https://github.com/rusin-dev/rusin-note/issues/191)「限制 1 队列」），`0` 表示不限；
   - `max_concurrent_uploads` ：**单用户同时上传**上限（同一账号在途的上传请求数），默认 `1`（同上），`0` 表示不限；
   - `download_rate_limit` ：附件下载路由的独立每 IP 限流，`window_seconds`（默认 `60`）与 `max_requests`（默认 `120`）；
   - 并发上限用于拦截「发起上千个慢速连接（每个 1KB/s）、或用上百线程同时下载上百个文件」这类**请求数不超限但长期占用 worker / 打满出站带宽**的行为：超出时下载返回 429（带 `Retry-After`），上传返回 429 JSON（编辑器可直接展示提示）；**超限直接拒绝、不排队**（排队同样占用 worker）。闸门计数在**进程内**（`app/core/concurrency.py`），gunicorn 起 N 个 worker 时实际上限约为 `N × 该值`；跨实例严格计数需要外部存储原子自增，本项目未采用；
   - 附件在笔记中默认以链接形式引用；若一篇笔记内联了多个附件图片（同一账号并发请求 > 上限），可适当调高 `max_concurrent_downloads` 或置 `0`；
   - `blocked_extensions` ：禁止上传的文件扩展名列表（黑名单模式），默认包含 `.exe`、`.bat`、`.sh`、`.zip` 等可执行文件与压缩包。**取值本身不带前导点**（`config.json` 里写 `exe`、`zip`，代码会自动补 `.`），自行添加时不要写成 `.exe`，否则永不命中。

## 评论与动态

- `comments` 评论系统（`/comments/<target_type>/<path:target_id>`，支持笔记和分享页面评论）。
   - `enabled` ：是否开启，默认 `true`；置 `false` 后评论页面返回 404；
   - `max_length` ：单条评论最大长度（字符），默认 `1024`（约 1KB）；
   - `max_comments` ：每个目标（笔记/分享）最多评论数，默认 `200`；
   - `cooldown_seconds` ：单个用户两次发布评论的最小间隔（秒），默认 `3`；
   - `page_size` ：每页显示评论数，默认 `50`；
   - `max_height_px` ：评论内容渲染后的最大显示高度（px），默认 `280`，超出部分在内容区内滚动。
- `benben` 犇犇动态（`/benben`，登录可发布、未登录只读）。
   - `max_length`：单条犇犇最大长度（单位：**字符**），默认 `1024`（约 1KB）；
   - `page_size`：每批加载条数，默认 `50`；
   - `cooldown_seconds`：单个用户两次发布犇犇的最小间隔（单位：**秒**），默认 `3`；
   - `max_height_px`：犇犇内容渲染后的最大显示高度（单位：**px**），默认 `280`，超出部分在内容区内滚动（防止长帖霸屏）；
   - `max_posts`：犇犇持久化条数上限，默认 `200`（外部存储单键体积控制，超出丢弃最旧）；

   内容支持 Markdown 与 LaTeX 公式（`$...$` / `$$...$$`，依赖 `latex_render` 开关），发布表单带实时预览（客户端 marked.js 渲染，预览同样过滤危险标签与链接）；渲染时经 bleach 安全清洗防止 XSS；每页显示 `page_size` 条，通过「加载更多」分批加载，加载与发布均受请求速率限制（GET/POST 限流），发布还受单用户冷却限制（`cooldown_seconds`）。登录用户可点击动态右上角的「回复」，以 `|| @用户名: 原内容` 覆盖填入发布框。

## 密码策略

- `password_policy`：密码策略，定义访客密码的复杂度要求。  
   - `min_length`：密码最小长度，默认 `8`；  
   - `max_length`：密码最大长度，默认 `128`（硬上限 `128`，防止超长密码进入 PBKDF2 慢哈希消耗 CPU）；  
   - `require_uppercase`：是否必须包含大写字母，默认 `true`；  
   - `require_lowercase`：是否必须包含小写字母，默认 `true`；  
   - `require_digits`：是否必须包含数字，默认 `true`；  
   - `require_special`：是否必须包含特殊符号（不含 `/ \ ( ) " '`），默认 `true`；

## 数据目录与存储后端（环境变量）

- `RUSIN_DATA_DIR`：可选环境变量，用于指定运行数据目录，默认 `data`（即项目下的 `data/`）。**内容数据**（笔记 / 图片 / 附件 / 各集合 JSON）仅本地 `sqlite` / `file` 后端写入该目录；日志 `log/` 与插件 `plugins/` 目录则始终建在该目录下、与后端无关（无服务器平台日志回退 stderr）。

    笔记、图片、附件及各业务 JSON 数据会写入该目录；完整布局见 [Zeabur 部署](deployment/zeabur.md) 中的数据目录示例。在自动部署平台上建议挂载持久化卷到 `/data`，并设置 `RUSIN_DATA_DIR=/data`，避免重新部署时清空数据。
- `RUSIN_STORAGE`：可选环境变量，显式指定存储后端：`sqlite`（本地/VPS，默认）、`file`（纯 JSON 文件）、`memory`（纯内存）、`upstash`（外部 KV）、`postgres`（Neon/PostgreSQL）。未指定时自动识别：设置了 `KV_REST_API_URL` / `KV_REST_API_TOKEN` 用 `upstash`，设置了 `DATABASE_URL` 用 `postgres`，检测到无服务器平台环境变量用 `memory`，否则 `sqlite`。详见 [存储后端说明](deployment/storage-backends.md)。

## 多语言

- **多语言**：界面支持简体中文与 English。导航栏右侧提供语言切换链接（`/lang/zh` / `/lang/en`），选择后通过 Cookie（`rusin-lang`）记住偏好；未设置时自动按浏览器 `Accept-Language` 判断，默认中文。切换后全站文本（导航、按钮、提示、错误信息、犇犇预览等）即时切换语言。

## 插件

- `plugins` 插件系统（详见 [插件系统](plugins.md)；`config.json` 中可省略该段，缺省时使用内置默认值）。
   - `enabled`：是否启用，默认 `true`（无服务器环境自动禁用）；
   - `update_interval_hours`：后台更新检查线程的轮询周期（单位：**小时**），默认 $6$；
   - `update_stale_days`：距 `last_update` 超过该天数才请求 `upstream_repo`（单位：**天**），默认 $3$。

## 第三方登录（OAuth）

- `oauth` 第三方登录（OAuth 2.0）。
   - `enabled`：总开关，**默认 `false`（关闭全部 OAuth）**。即使功能开关被打开、凭据已配置，此开关为 `false` 时所有第三方登录仍不可用；适合在配置层硬关闭，不受运行时功能开关影响；
   - `auto_register`：第三方账号未绑定时是否自动创建站内用户，默认 `true`（关闭后需先登录再在设置中绑定）；
   - `timeout_seconds`：向各 Provider 发起 HTTP 请求的超时（秒），默认 `10`；
   - `providers.<github|google|microsoft|wechat|qq>`：各平台凭据，分别填 `client_id`/`client_secret`（Microsoft 另可填 `tenant`，微信/QQ 为 `app_id`/`app_secret`）；留空即视为未配置，登录页不展示对应按钮。

## 2FA / 邮箱 / 手机验证

- `security` 2FA / 邮箱 / 手机验证。
   - `code_length`（验证码长度，默认 `6`）、`code_ttl_seconds`（有效期秒，默认 `600`）、`code_resend_cooldown_seconds`（重发冷却秒，默认 `60`）、`code_max_attempts`（最大尝试次数，默认 `5`）、`challenge_ttl_seconds`（登录二次验证挑战有效期秒，默认 `600`）、`timeout_seconds`（投递超时秒，默认 `10`）；
   - `email_login` / `phone_login`：是否允许邮箱 / 手机验证码免密登录，默认 `true`；
   - `smtp`：邮箱验证码投递（`host`/`port`/`username`/`password`/`from_addr`/`use_tls`/`use_ssl`），留空则仅记录日志、不发送；
   - `sms`：短信验证码投递（`webhook_url` + 可选 `token`），向该地址 POST JSON `{"phone","code","site","ttl"}`。

## 功能开关

- `features` / `admin_users` 功能开关（#90）。
   - `features`：各功能的**默认开关**。当前 `config.json` 显式配置了 `world_notes`（公开笔记与短链）、`benben`（犇犇动态）、`share_links`（分享链接）、`open_register`（开放注册）、`note_tags`（笔记标签）、`note_folders`（笔记文件夹）、`note_pins`（笔记置顶）、`heading_anchors`（Markdown 标题锚点）、`markdown_alerts`（Markdown 提示卡片）、`note_images`（笔记图床）、`note_attachments`（笔记附件）、`comments`（评论系统）以及 `oauth_github`/`oauth_google`/`oauth_microsoft`/`oauth_wechat`/`oauth_qq`/`two_factor_auth`/`email_verify`/`phone_verify` 共 20 项（后 8 项默认 `false`）。

     **优先级**：`note_refs`、`latex_render`、`code_highlight`、`avatar`、`note_images`、`note_attachments`、`comments` 这 7 个「历史功能」的默认值**始终取自各自配置段**（如 `images.enabled`、`attachments.enabled`、`comments.enabled`），本段中的同名项不生效；其余功能未在本段配置时默认启用（含 `orgs`）。第三方登录平台的展示还需 `oauth.enabled` 为 `true` 且在 `oauth.providers` 中填好凭据。
   - `admin_users`：功能开关管理员用户名列表；也可用环境变量 `RUSIN_ADMIN` 指定（多个用户名逗号分隔，两者取并集）。

   管理员登录后可在 `/admin/features` 用滑块开关切换各功能的启用状态，保存后立即生效（无需重启）：运行时状态持久化在存储后端（`sqlite`/`file` 后端即数据目录下的 `feature_flags.json`），多实例部署经约 5 秒的缓存 TTL 自动收敛；停用的功能路由直接 404、导航与首页入口自动隐藏。全部功能开关状态会呈现在 `/count` 数据汇总页的「功能状态」区（未设管理员时该区对所有人可见，但无人能修改开关）。注意：无服务器 `memory` 后端不持久，实例冷启动后回退到 `config.json` 默认值。

## 日志与调试

- `logger` 日志。
   - `max_size`：单个日志文件的字节上限（RotatingFileHandler `maxBytes`），默认 `4294967296`（4 GiB）；
   - `path_pattern`：日志文件路径模板，默认 `log/{timestamp}.log`，相对数据目录解析（即 `<RUSIN_DATA_DIR>/log/`）；

    日志文件不可创建时（如无服务器只读文件系统）自动回退到 stderr，进入平台日志流。
- `debug`：日志详细程度开关，默认 `false`。**不会**开启 Flask 调试模式；取值与日志级别的对应关系是——`false` 记录 `INFO` 及以上（详细），`true` 只记录 `ERROR`（精简）。生产环境请保持 `false`。
