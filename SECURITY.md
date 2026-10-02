# 安全策略

Rusin-Note 是一款自托管（self-hosted）的云端剪贴板 / 笔记应用。我们欢迎并重视安全研究者对漏洞的报告，请将漏洞信息**私密**提交，不要在公开渠道讨论细节。

## 受支持的版本

| 版本 | 是否受支持 | 说明 |
|---|---|---|
| v3.x | ✅ | 当前主版本线，接受安全修复 |
| < v3.0（v1.x / v2.x） | ❌ | 已停止维护，请升级到 v3.x 后复现 |

发布版本号遵循语义化版本（`vMAJOR.MINOR.PATCH`），带 `-` 后缀的标签（如 `v2.1.0-alpha.1`）为预发布版本，只用于功能验证，**不作为安全问题的复现基准**。

只有能在**最新版**（见 [Releases](https://github.com/rusin-dev/rusin-note/releases)）上复现的问题才会进入修复流程。请在报告前先升级到最新版验证；若问题在最新版已消失，仍欢迎报告，我们会视情况回溯确认。

## 如何报告漏洞

**请使用 GitHub 的私密漏洞报告（Private Vulnerability Reporting）：**

1. 打开 <https://github.com/rusin-dev/rusin-note/security/advisories/new>；
2. 填写标题、受影响版本、复现步骤与影响说明；
3. 提交后该报告仅你与维护者可见，不会出现在公开的 Issue 列表中。

请勿通过以下渠道报告未修复的漏洞：

- 公开 Issue（包括 `bug` 类型模板）
- Pull Request 描述或代码评审评论
- Discussions、社群、微博 / 推特等公开渠道

若私密漏洞报告入口不可用（该功能需要仓库管理员在 **Settings → Code and automation → Security → Private vulnerability reporting** 中开启），请通过 Issue 联系维护者获取私密沟通方式，**不要在 Issue 中写明漏洞细节**。

### 报告中请尽量包含

- 受影响版本（`git rev-parse HEAD` 或 Release 标签）
- 部署形态：VPS（waitress / gunicorn）或无服务器（Vercel / AWS Lambda），是否位于反向代理之后
- 存储后端：`sqlite` / `file` / `upstash` / `postgres` / `memory`
- 相关配置段与功能开关状态（**请抹去密钥、Token、密码等敏感值**）
- 最小化复现步骤（请求方法、URL、请求体、所需权限）
- 影响面评估：可影响的账号范围、是否需要登录、是否可跨用户
- 若你已有修复思路，欢迎附上（可选）

## 处理流程与时间线

1. **确认接收**——项目为非商业的志愿维护，我们无法承诺固定的响应时限，但会尽力在收到报告后尽快回复确认，并告知初步评估结论。若长时间未获回复，请以 Issue 等方式礼貌追问一次（勿写明细节）。
2. **评估与修复**——确认存在漏洞后在私有分支修复，并补充端到端回归测试（`tests/`）。
3. **披露**——修复发布后，通过 GitHub Security Advisory 发布通告，可分配 CVE 编号；经你同意会在通告中署名致谢。
4. **协调披露**——在修复发布前请保持保密，保密期的长短由双方协商，我们不设单方面的时限上限。若你计划公开披露，请提前告知，我们会同步当前的修复进展与可用的临时缓解措施。

关于安全研究：请按本策略提交的善意研究视为在本仓库范围内获授权的行为，我们不会因此对报告者采取法律行动。需要说明的是，这一表述只代表本仓库维护者的立场：项目多为自托管部署，各处运行实例属于对应部署者，对其环境的测试请另行取得该部署者的授权；涉及第三方服务与上游框架的部分请遵循各自的政策。

## 范围界定

由于本项目是自托管软件，**部署者负责运行环境**，以下情形通常属于配置问题而非应用漏洞：

- 未设置 `RUSIN_SECRET_KEY`（可持久化后端会自动生成）、生产环境未开启 `secure_cookies`
- 位于反向代理之后却未开启 `trust_proxy_headers`，或 `trusted_proxies` 未覆盖回源地址（表现为全站限流异常）
- 使用 `trusted_proxies: "*"`（不安全的兼容模式）导致 `X-Forwarded-For` 可被伪造
- 关闭 WAF 或未先以 `waf.mode=detectiononly` 观察即上线；或部署方自行删改了 `waf.verify_checksum` 校验
- 无服务器平台使用 `memory` 后端（重启即清空数据）
- 保留默认管理员名 / 开放注册 / 弱 `password_policy` 等部署侧策略

以下情形**属于**我们接受的安全问题：

- 跨用户读取或篡改私有笔记、分享链接、附件、组织数据（越权 / IDOR）
- Markdown / 富文本 / 图片 / 附件渲染路径中的存储型或反射型 XSS（绕过 bleach 白名单）
- 路径穿越、笔记 ID / 用户名解析导致的越界文件访问
- 认证与会话缺陷：会话固定或注销后会话仍有效、密码或验证码策略可绕过、2FA 可跳过或重放、OAuth state / PKCE 校验缺陷
- CSRF 防护缺失、可伪造客户端 IP 绕过限流或 IP 名单
- 可造成拒绝服务的资源消耗（无上限的解析、解压、请求排队等）
- 密钥 / 验证码 / TOTP 秘密在存储或日志中明文泄漏
- 插件系统与 WAF 供给流程中的代码执行或供应链风险（例如下载内容未校验即执行、配置项未校验即写入 nginx 配置）

第三方服务（GitHub / Google / Microsoft / 微信 / QQ OAuth、Upstash、Neon、Gravatar 类头像服务、公共 CDN）与底层框架自身（Flask、werkzeug、psycopg、nginx、ModSecurity、OWASP CRS）的漏洞，请向对应上游报告；若影响本项目的默认使用路径，我们也会跟进依赖升级。

## 已内置的安全机制（供研究参考）

了解现有防御层有助于判断漏洞的成因与影响面：

- **输入约束**——用户名与笔记 ID 强制匹配 `^[a-zA-Z0-9_\-]+$`；上传内容按魔数嗅探图片格式；大小与数量受各功能配额限制。
- **输出清洗**——所有 Markdown 渲染统一经 bleach 白名单（`utils.render_markdown_html`），GitHub 风格提示卡片在清洗前转换，模板输出默认转义；服务端代码着色 + 客户端 highlight.js 兜底。
- **认证与会话**——签名会话 Cookie、会话超时、改密注销其它会话、图形验证码（一次性、TTL、答案不落盘明文）、TOTP 两步验证与恢复码、邮箱 / 手机验证码（仅存哈希、含尝试次数与冷却）。
- **访问控制与配额**——CSRF 全站防护、基于 IP 的限流（Flask-Limiter，可用 Redis 共享）、单用户并发闸门（`app/core/concurrency.py`，限制在途下载 / 上传数）、附件默认禁止匿名下载且响应缓存为 `private`。
- **纵深防御**——可选 nginx + ModSecurity + OWASP CRS 反向代理 WAF（CRS 版本与 SHA256 双锁定，规则集只做文本下载，不执行任何二进制）。
- **运行时隔离**——功能开关（`/admin/features`）可整体停用未需要的入口；插件安装校验 `auth_token` 与命名空间冲突；写入 nginx 配置的字段经白名单校验，防配置注入。

## 加固建议（部署侧）

生产部署请至少确认：

1. 显式设置 `RUSIN_SECRET_KEY`，并开启 `secure_cookies`；
2. 反代场景正确配置 `trust_proxy_headers` 与 `trusted_proxies`（使用具体 IP / CIDR 或 `loopback` / `private` / `cloudflare` 预设，避免 `*`）；
3. 关闭 `open_register`（除非确实需要公开注册），设置 `admin_users` 并启用 `two_factor_auth`；
4. 按最小可用原则在 `/admin/features` 停用未使用的功能，减少攻击面；
5. WAF 先 `detectiononly` 观察 `<DATA_DIR>/waf/log/audit.log`，确认无误报再切 `on`；
6. 保持依赖与 CRS 规则集更新（升级 CRS 时同步更换 `crs_sha256`，不要关闭校验）。

## 版本策略

- 安全修复通常随下一个 Release 发布；紧急情况下会单独发布 patch 版本并标记。
- 关注 [Releases](https://github.com/rusin-dev/rusin-note/releases) 与 Security Advisories 获取安全通告。
- fork 或二次分发时，请在文档中说明实际使用的上游版本，以便复现与验证。
