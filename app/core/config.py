"""配置加载与全局常量"""
import os
import json
import string

# ---------- 尝试导入 Markdown 和 Bleach（用于安全渲染） ----------
try:
    import markdown
    MARKDOWN_AVAILABLE = True
except ImportError:
    markdown = None
    MARKDOWN_AVAILABLE = False

try:
    import bleach
    BLEACH_AVAILABLE = True
except ImportError:
    bleach = None
    BLEACH_AVAILABLE = False

try:
    import pygments
    PYGMENTS_AVAILABLE = True
except ImportError:
    pygments = None
    PYGMENTS_AVAILABLE = False

# ---------- 加载配置 ----------
CONFIG_FILE = "config.json"
DEFAULT_CONFIG = {
    "max_note_size_kb": 5120,
    "sitename": "如形の笔记",
    "rate_limit": {
        "window_seconds": 60,
        "max_requests": 30
    },
    "get_rate_limit": {                     # ADDED: GET请求独立限流
        "window_seconds": 60,
        "max_requests": 45
    },
    "save_rate_limit": {                    # 保存类 POST 独立限流（避免与全局 POST 限流冲突）
        "window_seconds": 60,
        "max_requests": 120
    },
    "register_rate_limit": {                # 注册速率限制：单IP在window_seconds内最多注册max_requests个账号
        "window_seconds": 120,
        "max_requests": 1
    },
    "ip_rate_limit": {                      # 全站每 IP 总请求上限（应用级限流，对所有路由累计生效；max_requests=0 关闭）
        "window_seconds": 60,
        "max_requests": 300
    },
    "trust_proxy_headers": False,           # 仅当部署在可信反向代理之后才置 True，否则一律用直连 IP
    # 可信反向代理网段：仅「TCP 直连对端」命中该列表时才采信代理头（防伪造 XFF）。
    # 元素可为 IP/CIDR，或预设名 loopback / private / cloudflare；"*" 表示信任任意对端（有伪造风险）
    "trusted_proxies": ["loopback", "private"],
    "proxy_hops": 1,                        # 兼容模式（trusted_proxies 为 "*"/留空）下 XFF 从右往左的代理跳数
    "ip_allowlist": [],                     # 免限流 IP/CIDR 白名单（如监控、内网探活）
    "ip_blocklist": [],                     # 直接拒绝（403）的 IP/CIDR 黑名单
    "secure_cookies": False,                # HTTPS 部署时置 True，为会话 Cookie 添加 Secure 标志
    "global_cdn": "https://cdn.jsdmirror.cn",  # 全局 CDN 基础地址，KaTeX / FontAwesome / marked 等前端资源均从该地址拼接
    "id_generation": {
        "length": 6,
        "use_uppercase": True,
        "use_lowercase": True,
        "use_digits": True
    },
    "share_token": {
        "length": 64,
        "use_uppercase": True,
        "use_lowercase": True,
        "use_digits": True
    },
    "session_timeout": {
        "enabled": False,
        "minutes": 60
    },
    "note_expiration": {
        "enabled": False,
        "hours": 24
    },
    "latex_render": {
        "enabled": True
    },
    "code_highlight": {
        "enabled": True
    },
    "cache": {
        "enabled": True,
        "backend": "redis",
        "default_timeout": 300,
        "redis_url": "redis://localhost:6379/0"
    },
    "password_policy": {
        "min_length": 8,
        "max_length": 128,
        "require_uppercase": True,
        "require_lowercase": True,
        "require_digits": True,
        "require_special": True
    },
    "benben": {
        "max_length": 1024,
        "page_size": 50,
        "cooldown_seconds": 3,
        "max_height_px": 280,
        "max_posts": 200
    },
    "todos": {
        "max_items": 100,
        "max_length": 200
    },
    "note_editor": {
        "live_preview_default": False,
        "markdown_manual_url": "https://markdown.com.cn"
    },
    "note_refs": {
        "enabled": True,
        "search_limit": 8,
        "scan_limit": 100
    },
    "note_transfer": {                           # 笔记批量导入 / 导出（/user/<u>/export|import）
        "max_file_kb": 4096,                     # 导入文件大小上限（KB，另受全局请求体上限约束）
        "max_notes": 300                         # 单次导入笔记数上限
    },
    "avatar": {
        "enabled": True,
        "url_template": "https://cn.cravatar.com/avatar/{hash}?d=identicon&f=y",
        "size": 24
    },
    "images": {                                # 笔记图床：编辑器粘贴/拖拽上传，/image/<u>/<id> 公开访问
        "enabled": True,
        "max_size_kb": 2048,                   # 单张图片上限（KB）
        "max_total_kb": 51200                  # 每用户配额（KB）
    },
    "attachments": {                          # 笔记附件：编辑器上传，/attachment/<u>/<id> 需登录后下载
        "enabled": True,
        "max_size_kb": 50,                     # 单个附件上限（KB）
        "max_per_note_kb": 500,                # 单个笔记引用附件总量上限（KB）
        "max_total_kb": 10240,                 # 每用户配额（KB）
        "allow_anonymous_download": False,     # 是否允许匿名（未登录）下载附件，默认禁止
        "max_concurrent_downloads": 1,         # 单用户同时下载附件上限（#191：限制 1 个队列；0 = 不限）
        "max_concurrent_uploads": 1,           # 单用户同时上传附件上限（#191：限制 1 个队列；0 = 不限）
        "download_rate_limit": {               # 附件下载路由的每 IP 限流
            "window_seconds": 60,
            "max_requests": 120
        },
        "blocked_extensions": [                # 黑名单扩展名（不含点），可执行文件
            "exe", "bat", "cmd", "com", "msi", "scr", "pif",
            "vbs", "vbe", "js", "jse", "ws", "wsf", "wsc", "wsh",
            "ps1", "psm1", "psd1", "psc1", "psc2",
            "reg", "inf", "hta", "cpl", "lnk", "url",
            "sh", "bash", "csh", "ksh", "zsh", "fish",
            "command", "app", "workflow", "scpt", "applescript",
            "dylib", "so", "dll", "class", "jar",
            "py", "pyc", "pyo", "pyd", "rb", "pl", "pm", "tcl", "tk",
            "zip", "zipx", "rar", "7z", "cab", "lzh", "ace", "arc", "arj",
            "tar", "tar.gz", "tgz", "tpz", "gz", "bz2", "xz", "z",
            "deb", "rpm", "dmg", "iso", "img", "bin",
        ]
    },
    "comments": {                            # 评论系统：笔记/分享页面的评论功能
        "enabled": True,
        "max_length": 1024,                  # 单条评论最大长度（字符）
        "max_comments": 200,                 # 每个目标（笔记/分享）最多评论数
        "cooldown_seconds": 3,               # 单用户发布评论冷却时间（秒）
        "page_size": 50,                     # 每页显示评论数
        "max_height_px": 280,                # 评论内容渲染后最大显示高度（px），超出滚动
    },
    "oauth": {                                # 第三方登录（GitHub/Google/Microsoft/微信/QQ）
        "enabled": False,                      # 总开关：默认关闭所有 OAuth（即使功能开关被打开也需此开关为 true）
        "auto_register": True,                 # 未绑定账号时是否自动创建新用户（关闭后需先登录再绑定）
        "timeout_seconds": 10,                 # 向各 Provider 发起 HTTP 请求的超时（秒）
        "providers": {                         # 各 Provider 凭据；留空即视为未配置，登录页不展示
            "github": {"client_id": "", "client_secret": ""},
            "google": {"client_id": "", "client_secret": ""},
            "microsoft": {"client_id": "", "client_secret": "", "tenant": "common"},
            "wechat": {"app_id": "", "app_secret": ""},
            "qq": {"app_id": "", "app_secret": ""},
        },
    },
    "security": {                             # 2FA / 邮箱 / 手机号验证
        "code_length": 6,                      # 邮箱/手机验证码长度
        "code_ttl_seconds": 600,               # 验证码有效期（秒）
        "code_resend_cooldown_seconds": 60,    # 同一目标重发验证码的最小间隔（秒）
        "code_max_attempts": 5,                # 单个验证码最大尝试次数（防爆破）
        "challenge_ttl_seconds": 600,          # 登录二次验证挑战有效期（秒）
        "timeout_seconds": 10,                 # 验证码投递（SMTP / 短信 Webhook）超时（秒）
        "email_login": True,                   # 是否允许邮箱验证码直接登录
        "phone_login": True,                   # 是否允许手机验证码直接登录
        "smtp": {                              # 邮箱验证码投递（留空则仅记录日志、不发送）
            "host": "", "port": 587, "username": "", "password": "",
            "from_addr": "", "use_tls": True, "use_ssl": False,
        },
        "sms": {                               # 短信验证码投递：通用 HTTP Webhook（POST JSON）
            "webhook_url": "", "token": "",
        },
    },
    "features": {                             # 功能开关默认值（#90）：运行时可由管理员在 /admin/features 切换
        "world_notes": True,
        "benben": True,
        "share_links": True,
        "open_register": True,
        "note_tags": True,
        "note_folders": True,
        "note_pins": True,
        "notes_import_export": True,
        "heading_anchors": True,
        "note_images": True,
        "note_attachments": True,
        "comments": True,
        # 第三方登录：需要先在 oauth.providers 填好凭据，默认关闭
        "oauth_github": False,
        "oauth_google": False,
        "oauth_microsoft": False,
        "oauth_wechat": False,
        "oauth_qq": False,
        # 双因素 / 联系方式验证：默认关闭
        "login_captcha": True,
        "two_factor_auth": False,
        "email_verify": False,
        "phone_verify": False,
    },
    "admin_users": [],                        # 功能开关管理员用户名（也可用环境变量 RUSIN_ADMIN 指定，逗号分隔）
    "max_note_id_length": 250,
    "max_note_tags": 10,                      # 笔记标签：每篇笔记最多标签数
    "max_tag_length": 24,                     # 笔记标签：单个标签最大长度（字符）
    "max_folder_name_length": 64,             # 笔记文件夹：文件夹路径最大长度（字符）
    "max_folder_depth": 8,                    # 笔记文件夹：最大层级数（/ 分隔）
    "logger": {
        "max_size": 4294967296,
        "path": "log/"
    },
    "plugins": {
        "enabled": True,
        "update_interval_hours": 6,
        "update_stale_days": 3
    },
    "waf": {                                 # 反向代理 WAF（nginx + ModSecurity + OWASP CRS）自动供给
        "enabled": False,                    # 总开关：默认关闭（仅 VPS 反代部署有意义，无服务器平台自带 WAF）
        "auto_download": True,               # 启用后自动下载 CRS 规则集（纯文本规则，SHA256 锁定校验）
        "crs_version": "4.29.0",             # 锁定的 OWASP CoreRuleSet 版本
        "crs_url": "https://github.com/coreruleset/coreruleset/releases/download/v4.29.0/coreruleset-4.29.0-minimal.tar.gz",
        # 上述官方 release 的 SHA256；换版本必须同步换校验和，否则下载会被拒绝
        "crs_sha256": "1aa1c5c8fc29e532d35293bcea36bf72de61db8f6ed4716a0f91ab14552b7fed",
        "verify_checksum": True,             # 置 false 会接受任意内容（仅内网镜像调试用，不要在生产关闭）
        "mode": "on",                        # on = 命中即拦截(403)；detectiononly = 只写审计日志不拦截
        "response_inspection": False,        # 出站响应体检测：渲染 Markdown/代码的站点误报多且耗 CPU，默认关
        "listen": "80",                      # nginx 监听地址/端口（如 "80" 或 "127.0.0.1:8081"）
        "server_name": "_",
        "upstream": "127.0.0.1",             # 回源地址（应用监听处）
        "upstream_port": 0,                  # 0 = 跟随 PORT 环境变量（默认 8080）
        "paranoia_level": 1,                 # CRS 检测等级 1-4（越高越严，误报越多）
        "inbound_anomaly_threshold": 5,      # 入站异常分阈值（CRS 默认 5）
        "outbound_anomaly_threshold": 4,     # 出站异常分阈值（CRS 默认 4）
        "body_limit_kb": 0,                  # 请求体上限；0 = 自动取笔记/附件/导入上限的较大值
        "default_exclusions": True,          # 生成笔记正文类端点的 CRS 误报排除（代码片段会命中 SQLi/XSS 规则）
        "update_stale_days": 7,              # 距上次下载超过该天数才重新拉取（避免每次启动都下载）
        "validate_config": True,             # 生成后跑 nginx -t 校验（只读，不改系统状态）
        "auto_reload": False,                # 校验通过后是否 nginx -s reload（需 root 权限，默认关闭）
    },
    "debug": False,
}


def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"[警告] 读取配置文件失败，使用默认配置: {e}")
    return DEFAULT_CONFIG


config = load_config()
# 运行数据目录：默认落到项目下的 data/（JSON 内容 + SQLite 索引都在这里）。
# 通过 RUSIN_DATA_DIR 覆盖，如 Zeabur 挂载持久卷时设为 /data。
DATA_DIR = os.environ.get("RUSIN_DATA_DIR", "data")
try:
    os.makedirs(DATA_DIR, exist_ok=True)
except (OSError, IOError):
    pass

# ---------- 无服务器平台检测 ----------
# 无服务器环境没有可写的持久磁盘：数据必须走外部存储（upstash 后端），
# 且不能启动后台守护线程（冷实例闲置时不会执行，日志需回退到 stderr）。
SERVERLESS = bool(
    os.environ.get("VERCEL")
    or os.environ.get("NETLIFY")
    or os.environ.get("AWS_LAMBDA_FUNCTION_NAME")
)


def data_path(*parts: str) -> str:
    return os.path.join(DATA_DIR, *parts)


SITE_NAME = config.get("sitename", "")
MAX_CONTENT_BYTES = config.get("max_note_size_kb", 5120) * 1024

RATE_WINDOW = config.get("rate_limit", {}).get("window_seconds", 60)
RATE_MAX = config.get("rate_limit", {}).get("max_requests", 30)

# GET限流配置
GET_RATE_CFG = config.get("get_rate_limit", DEFAULT_CONFIG["get_rate_limit"])
GET_RATE_WINDOW = GET_RATE_CFG.get("window_seconds", 60)
GET_RATE_MAX = GET_RATE_CFG.get("max_requests", 45)

# 保存类 POST 独立限流配置（BUG-14：与全局 POST 限流解耦）
SAVE_RATE_CFG = config.get("save_rate_limit", DEFAULT_CONFIG["save_rate_limit"])
SAVE_RATE_WINDOW = SAVE_RATE_CFG.get("window_seconds", 60)
SAVE_RATE_MAX = SAVE_RATE_CFG.get("max_requests", 120)

# 注册速率限制配置：单IP在window_seconds内最多注册max_requests个账号
REGISTER_RATE_CFG = config.get("register_rate_limit", DEFAULT_CONFIG["register_rate_limit"])
REGISTER_RATE_WINDOW = REGISTER_RATE_CFG.get("window_seconds", 120)
REGISTER_RATE_MAX = REGISTER_RATE_CFG.get("max_requests", 1)


def _env_list(name: str) -> list:
    """读取逗号/分号/空白分隔的列表型环境变量（无服务器平台只读盘时用）。"""
    raw = os.environ.get(name, "")
    for sep in (";", ",", " ", "\n", "\t"):
        raw = raw.replace(sep, ",")
    return [item.strip() for item in raw.split(",") if item.strip()]


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "") or default)
    except (TypeError, ValueError):
        return default


# 全站每 IP 总请求上限（应用级作用域，叠加在各路由独立限流之上，max_requests=0 表示关闭）
IP_RATE_CFG = config.get("ip_rate_limit", DEFAULT_CONFIG["ip_rate_limit"])
IP_RATE_WINDOW = int(IP_RATE_CFG.get("window_seconds", 60) or 60)
IP_RATE_MAX = int(IP_RATE_CFG.get("max_requests", 300) or 0)
IP_RATE_ENABLED = bool(IP_RATE_CFG.get("enabled", True)) and IP_RATE_MAX > 0

# 可信代理配置（BUG-3：默认不信任 X-Forwarded-For / X-Real-IP，防止伪造头绕过限流）
TRUST_PROXY_HEADERS = bool(config.get("trust_proxy_headers", False))
# 可信代理网段：仅当 TCP 直连对端命中该列表时才采信代理头；"*" 表示信任任意对端
TRUSTED_PROXIES = _env_list("RUSIN_TRUSTED_PROXIES") or config.get(
    "trusted_proxies", DEFAULT_CONFIG["trusted_proxies"])
# 兼容模式下的 XFF 跳数（仅当 trusted_proxies 为 "*"/留空时生效）
PROXY_HOPS = max(1, _env_int("RUSIN_PROXY_HOPS", int(config.get("proxy_hops", 1) or 1)))
# IP 白名单（免限流）与黑名单（403），环境变量追加在配置文件之后
IP_ALLOWLIST = list(config.get("ip_allowlist", []) or []) + _env_list("RUSIN_IP_ALLOWLIST")
IP_BLOCKLIST = list(config.get("ip_blocklist", []) or []) + _env_list("RUSIN_IP_BLOCKLIST")

# Cookie 安全配置（BUG-13）
SECURE_COOKIES = bool(config.get("secure_cookies", False))
# 会话 Cookie 的 Max-Age：与服务器端会话超时保持一致；未启用超时时默认 30 天
COOKIE_MAX_AGE_DEFAULT = 30 * 24 * 3600
# 登录会话 Cookie 名称：不能与 Flask 的 session cookie（默认名 "session"，
# 存放 Flask-WTF CSRF token）冲突，否则打开带 CSRF 表单的页面会把登录态覆盖掉
SESSION_COOKIE = "rusin_session"

# 会话超时配置
SESSION_TIMEOUT_ENABLED = config.get("session_timeout", {}).get("enabled", False)
SESSION_TIMEOUT_MINUTES = config.get("session_timeout", {}).get("minutes", 60)
SESSION_TIMEOUT_SECONDS = SESSION_TIMEOUT_MINUTES * 60

# 笔记过期清除配置（超出保存时间的剪贴板自动删除，单位：小时，默认不启用）
NOTE_EXPIRATION_ENABLED = config.get("note_expiration", {}).get("enabled", False)
NOTE_EXPIRATION_HOURS = config.get("note_expiration", {}).get("hours", 24)
NOTE_EXPIRATION_SECONDS = NOTE_EXPIRATION_HOURS * 3600
# 后台过期笔记清理线程的扫描间隔（秒）
NOTE_CLEANUP_INTERVAL = 1800

# 剪贴板名称（笔记 ID）最大长度：超过该长度的 URL 视为不合法
MAX_NOTE_ID_LENGTH = config.get("max_note_id_length", 250)

# 笔记标签限制：每篇笔记最多标签数 / 单个标签最大长度（字符）
MAX_NOTE_TAGS = config.get("max_note_tags", 10)
MAX_TAG_LENGTH = config.get("max_tag_length", 24)

# 笔记文件夹限制：文件夹路径最大长度（字符）与最大层级数（用 / 分隔的多级），
# 每篇笔记至多归属一个文件夹
MAX_FOLDER_NAME_LENGTH = config.get("max_folder_name_length", 64)
MAX_FOLDER_DEPTH = config.get("max_folder_depth", 8)

# LaTeX 公式渲染配置（客户端 KaTeX 渲染，洛谷同款，仅影响 Markdown 只读页面）
# 全局 CDN：KaTeX / FontAwesome / marked 等前端静态资源统一从该地址拼接加载，
# 默认使用国内可达的 jsdmirror 镜像，可在 config.json 的 global_cdn 字段替换
LATEX_RENDER_ENABLED = config.get("latex_render", {}).get("enabled", True)
GLOBAL_CDN = config.get("global_cdn", "https://cdn.jsdmirror.cn").rstrip("/")
KATEX_VERSION = "0.18.4"
LATEX_CDN = f"{GLOBAL_CDN}/npm/katex@{KATEX_VERSION}/dist"

# 代码高亮配置（客户端 highlight.js 渲染，仿 latex_render 开关）
# cdn 为 highlight.js 静态文件基础目录，自动拼接 styles/github.min.css、
# styles/github-dark.min.css 与 highlight.min.js（浏览器 UMD 构建）
CODE_HIGHLIGHT_ENABLED = config.get("code_highlight", {}).get("enabled", True)
CODE_HIGHLIGHT_CDN = f"{GLOBAL_CDN}/npm/@highlightjs/cdn-assets@11.9.0"

# socket 超时（秒）：防止慢速连接长期占用线程（BUG-008）
SOCKET_TIMEOUT = 60
# 后台会话清理线程的间隔（秒）（BUG-013）
SESSION_CLEANUP_INTERVAL = 300

# 分享视图计数批量持久化（BUG-06）：内存累计达到阈值或距上次写盘超过间隔时，
# 才全量写一次 shares.json，避免每次访问分享链接都写盘
SHARE_VIEWS_FLUSH_THRESHOLD = 30
SHARE_VIEWS_FLUSH_INTERVAL = 60.0

# ---------- ID生成配置 ----------
ID_CFG = config.get("id_generation", DEFAULT_CONFIG["id_generation"])
ID_LENGTH = ID_CFG.get("length", 6)
USE_UPPER = ID_CFG.get("use_uppercase", True)
USE_LOWER = ID_CFG.get("use_lowercase", True)
USE_DIGIT = ID_CFG.get("use_digits", True)

_charset_parts = []
if USE_UPPER:
    _charset_parts.append(string.ascii_uppercase)
if USE_LOWER:
    _charset_parts.append(string.ascii_lowercase)
if USE_DIGIT:
    _charset_parts.append(string.digits)
if not _charset_parts:
    _charset_parts = [string.ascii_lowercase, string.digits]
ID_CHARSET = ''.join(_charset_parts)

# ---------- 分享 token 配置 ----------
SHARE_CFG = config.get("share_token", DEFAULT_CONFIG["share_token"])
SHARE_TOKEN_LENGTH = SHARE_CFG.get("length", 64)
SHARE_USE_UPPER = SHARE_CFG.get("use_uppercase", True)
SHARE_USE_LOWER = SHARE_CFG.get("use_lowercase", True)
SHARE_USE_DIGIT = SHARE_CFG.get("use_digits", True)

_share_charset_parts = []
if SHARE_USE_UPPER:
    _share_charset_parts.append(string.ascii_uppercase)
if SHARE_USE_LOWER:
    _share_charset_parts.append(string.ascii_lowercase)
if SHARE_USE_DIGIT:
    _share_charset_parts.append(string.digits)
if not _share_charset_parts:
    _share_charset_parts = [string.ascii_lowercase, string.digits]
SHARE_TOKEN_CHARSET = ''.join(_share_charset_parts)
# 路由校验用（宽松字符集，仅校验长度，查找仍走精确字典匹配）
SHARE_TOKEN_PATTERN = f"[A-Za-z0-9]{{{SHARE_TOKEN_LENGTH}}}"

# ---------- 密码策略配置 ----------
PW_POLICY = config.get("password_policy", DEFAULT_CONFIG["password_policy"])
PW_MIN_LENGTH = PW_POLICY.get("min_length", 8)
# BUG-108: 密码最大长度（默认 128），硬上限 128，防止超长密码进入 PBKDF2 慢哈希造成 CPU DoS。
# 配置值可调但不会超过硬上限，超限请求在进入哈希前即被拒绝。
try:
    PW_MAX_LENGTH = min(int(PW_POLICY.get("max_length", 128)), 128)
except (TypeError, ValueError):
    PW_MAX_LENGTH = 128
PW_REQUIRE_UPPER = PW_POLICY.get("require_uppercase", True)
PW_REQUIRE_LOWER = PW_POLICY.get("require_lowercase", True)
PW_REQUIRE_DIGIT = PW_POLICY.get("require_digits", True)
PW_REQUIRE_SPECIAL = PW_POLICY.get("require_special", True)


def get_password_requirements_description(lang: str = "zh"):
    """密码要求描述（zh/en）。由各单项要求拼装，`、`/`, ` 分隔。"""
    if lang == "en":
        parts = [f"at least {PW_MIN_LENGTH} and at most {PW_MAX_LENGTH} characters"]
        if PW_REQUIRE_UPPER:
            parts.append("uppercase letters")
        if PW_REQUIRE_LOWER:
            parts.append("lowercase letters")
        if PW_REQUIRE_DIGIT:
            parts.append("digits")
        if PW_REQUIRE_SPECIAL:
            parts.append("special characters (not / \\ ( ) \" ' )")
        return ", ".join(parts)
    parts = [f"至少 {PW_MIN_LENGTH} 位、至多 {PW_MAX_LENGTH} 位"]
    if PW_REQUIRE_UPPER:
        parts.append("大写字母")
    if PW_REQUIRE_LOWER:
        parts.append("小写字母")
    if PW_REQUIRE_DIGIT:
        parts.append("数字")
    if PW_REQUIRE_SPECIAL:
        parts.append("特殊符号 (不含 / \\ ( ) \" ' )")
    return "、".join(parts)


# ---------- 犇犇（用户动态）配置 ----------
BENBEN_CFG = config.get("benben", DEFAULT_CONFIG["benben"])
BENBEN_MAX_LENGTH = BENBEN_CFG.get("max_length", 1024)
BENBEN_PAGE_SIZE = BENBEN_CFG.get("page_size", 50)
# 犇犇发布冷却时间（秒）：单个用户两次发布犇犇的最小间隔，默认 3 秒
BENBEN_COOLDOWN_SECONDS = BENBEN_CFG.get("cooldown_seconds", 3)
# 犇犇内容渲染后的最大显示高度（px）：超出部分在内容区内滚动，默认 280px（防止长帖霸屏）
BENBEN_MAX_HEIGHT_PX = BENBEN_CFG.get("max_height_px", 280)
# 犇犇持久化条数上限（外部存储单键体积控制，超出丢弃最旧）
BENBEN_MAX_POSTS = BENBEN_CFG.get("max_posts", 200)
try:
    BENBEN_MAX_HEIGHT_PX = int(BENBEN_MAX_HEIGHT_PX)
    if BENBEN_MAX_HEIGHT_PX <= 0:
        BENBEN_MAX_HEIGHT_PX = 280
except (TypeError, ValueError):
    BENBEN_MAX_HEIGHT_PX = 280

# ---------- 笔记编辑器配置 ----------
# 实时渲染开关的默认值（访客可在编辑页手动切换，选择以 localStorage 记住）。
# 默认 False：关闭实时渲染，访客需点击开关开启。
NOTE_EDITOR_CFG = config.get("note_editor", DEFAULT_CONFIG["note_editor"])
LIVE_PREVIEW_DEFAULT = bool(NOTE_EDITOR_CFG.get("live_preview_default", False))
# Markdown 使用手册链接（预览栏头部显示，可在 config.json 中改为其他文档地址）
MARKDOWN_MANUAL_URL = NOTE_EDITOR_CFG.get(
    "markdown_manual_url", "https://markdown.com.cn")

# ---------- 笔记快捷引用配置（#87：GitHub Issues 风格的 # 引用） ----------
# enabled=False 时：编辑器不弹引用补全框，Markdown 渲染不把 #id 转为链接
NOTE_REFS_CFG = config.get("note_refs", DEFAULT_CONFIG["note_refs"])
NOTE_REFS_ENABLED = bool(NOTE_REFS_CFG.get("enabled", True))
# 引用搜索接口单次返回的最多条数
NOTE_REF_SEARCH_LIMIT = NOTE_REFS_CFG.get("search_limit", 8)
# 引用搜索最多扫描的笔记数（按修改时间倒序，防止大量笔记时读取过慢；
# upstash/postgres 等远程后端可调低）
NOTE_REF_SCAN_LIMIT = NOTE_REFS_CFG.get("scan_limit", 100)
try:
    NOTE_REF_SEARCH_LIMIT = max(1, int(NOTE_REF_SEARCH_LIMIT))
except (TypeError, ValueError):
    NOTE_REF_SEARCH_LIMIT = 8
try:
    NOTE_REF_SCAN_LIMIT = max(1, int(NOTE_REF_SCAN_LIMIT))
except (TypeError, ValueError):
    NOTE_REF_SCAN_LIMIT = 100

# ---------- 笔记批量导入 / 导出配置 ----------
NOTE_TRANSFER_CFG = config.get("note_transfer", DEFAULT_CONFIG["note_transfer"])
try:
    NOTE_TRANSFER_MAX_FILE_BYTES = max(1, int(NOTE_TRANSFER_CFG.get("max_file_kb", 4096))) * 1024
except (TypeError, ValueError):
    NOTE_TRANSFER_MAX_FILE_BYTES = 4096 * 1024
try:
    NOTE_TRANSFER_MAX_NOTES = max(1, int(NOTE_TRANSFER_CFG.get("max_notes", 300)))
except (TypeError, ValueError):
    NOTE_TRANSFER_MAX_NOTES = 300

# ---------- 首页显示配置 ----------
HOME_PAGE_CFG = config.get("home_page", {})
RECENT_NOTES_LIMIT = HOME_PAGE_CFG.get("recent_notes_limit", 5)
RECENT_SHARES_LIMIT = HOME_PAGE_CFG.get("recent_shares_limit", 5)
try:
    RECENT_NOTES_LIMIT = max(0, int(RECENT_NOTES_LIMIT))
except (TypeError, ValueError):
    RECENT_NOTES_LIMIT = 5
try:
    RECENT_SHARES_LIMIT = max(0, int(RECENT_SHARES_LIMIT))
except (TypeError, ValueError):
    RECENT_SHARES_LIMIT = 5

# 项目根目录（仓库根），用于定位仓库内的固定资源
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# 首页横幅：仓库根目录 NOTICE.txt 的第一行（文件缺失/内容为空时首页不展示）
NOTICE_FILE = os.path.join(BASE_DIR, "NOTICE.txt")
# 文档目录（免责声明、协作指南、路线图等）
DOCS_DIR = os.path.join(BASE_DIR, "docs")

# ---------- 工作台待办（TODO LIST）----------
TODOS_CFG = config.get("todos", DEFAULT_CONFIG["todos"])
TODO_MAX_ITEMS = TODOS_CFG.get("max_items", 100)
TODO_MAX_LENGTH = TODOS_CFG.get("max_length", 200)
try:
    TODO_MAX_ITEMS = max(1, int(TODO_MAX_ITEMS))
except (TypeError, ValueError):
    TODO_MAX_ITEMS = 100
try:
    TODO_MAX_LENGTH = max(1, int(TODO_MAX_LENGTH))
except (TypeError, ValueError):
    TODO_MAX_LENGTH = 200

# ---------- 用户头像配置 ----------
# 头像通过第三方服务生成。由于本站用户没有邮箱，默认用 md5(用户名) 作为哈希（
# Gravatar 系 API 的默认参数 d=identicon 会为每个哈希生成确定性的几何头像）。
# url_template 支持占位符：{hash}（md5(用户名)）、{username}（URL 编码的用户名）。
AVATAR_CFG = config.get("avatar", DEFAULT_CONFIG["avatar"])
AVATAR_ENABLED = bool(AVATAR_CFG.get("enabled", True))
AVATAR_URL_TEMPLATE = AVATAR_CFG.get(
    "url_template", "https://cn.cravatar.com/avatar/{hash}?d=identicon&f=y")
AVATAR_SIZE = int(AVATAR_CFG.get("size", 24))

# ---------- 笔记图床配置 ----------
IMAGES_CFG = config.get("images", DEFAULT_CONFIG["images"])
IMAGES_ENABLED = bool(IMAGES_CFG.get("enabled", True))
MAX_IMAGE_SIZE_KB = IMAGES_CFG.get("max_size_kb", 2048)
MAX_IMAGE_TOTAL_KB = IMAGES_CFG.get("max_total_kb", 51200)
MAX_IMAGE_SIZE_BYTES = MAX_IMAGE_SIZE_KB * 1024
MAX_IMAGE_TOTAL_BYTES = MAX_IMAGE_TOTAL_KB * 1024

# ---------- 笔记附件配置 ----------
ATTACHMENTS_CFG = config.get("attachments", DEFAULT_CONFIG["attachments"])
ATTACHMENTS_ENABLED = bool(ATTACHMENTS_CFG.get("enabled", True))
MAX_ATTACHMENT_SIZE_KB = ATTACHMENTS_CFG.get("max_size_kb", 50)
MAX_ATTACHMENT_PER_NOTE_KB = ATTACHMENTS_CFG.get("max_per_note_kb", 500)
MAX_ATTACHMENT_TOTAL_KB = ATTACHMENTS_CFG.get("max_total_kb", 10240)
MAX_ATTACHMENT_SIZE_BYTES = MAX_ATTACHMENT_SIZE_KB * 1024
MAX_ATTACHMENT_PER_NOTE_BYTES = MAX_ATTACHMENT_PER_NOTE_KB * 1024
MAX_ATTACHMENT_TOTAL_BYTES = MAX_ATTACHMENT_TOTAL_KB * 1024
ATTACHMENT_BLOCKED_EXTENSIONS = ATTACHMENTS_CFG.get("blocked_extensions", DEFAULT_CONFIG["attachments"]["blocked_extensions"])

# 附件下载权限：默认「不允许匿名用户下载」（未登录访问 /attachment/<u>/<id> 返回 401）；
# 置 true 则放开为「知道链接即可下载」的旧行为。
ATTACHMENTS_ALLOW_ANONYMOUS_DOWNLOAD = bool(ATTACHMENTS_CFG.get(
    "allow_anonymous_download", DEFAULT_CONFIG["attachments"]["allow_anonymous_download"]))


def _positive_int(value, default: int = 0) -> int:
    """解析「并发上限」类整数配置：非法值回退默认，负数归一为 0（= 不限）。"""
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return default


# 单用户并发上限（同时在途的请求数）：慢速连接（如 1KB/s）会长期占用 worker，
# 单纯限制「单位时间请求数」拦不住，因此对在途数量单独设闸（见 app/concurrency.py）。
# 默认各 1 个（#191「单用户上传/下载队列限制 1 队列」）：同一账号同时只允许
# 1 个下载 + 1 个上传在途，超出直接 429（不做排队等待——排队同样占用 worker）。
MAX_CONCURRENT_ATTACHMENT_DOWNLOADS = _positive_int(ATTACHMENTS_CFG.get(
    "max_concurrent_downloads", DEFAULT_CONFIG["attachments"]["max_concurrent_downloads"]), 1)
MAX_CONCURRENT_ATTACHMENT_UPLOADS = _positive_int(ATTACHMENTS_CFG.get(
    "max_concurrent_uploads", DEFAULT_CONFIG["attachments"]["max_concurrent_uploads"]), 1)

# 附件下载路由的独立限流（与 GET 限流解耦：下载多为长连接，阈值可单独调）
ATTACHMENT_DOWNLOAD_RATE_CFG = ATTACHMENTS_CFG.get(
    "download_rate_limit", DEFAULT_CONFIG["attachments"]["download_rate_limit"])
ATTACHMENT_DOWNLOAD_RATE_WINDOW = _positive_int(
    ATTACHMENT_DOWNLOAD_RATE_CFG.get("window_seconds", 60), 60) or 60
ATTACHMENT_DOWNLOAD_RATE_MAX = _positive_int(
    ATTACHMENT_DOWNLOAD_RATE_CFG.get("max_requests", 120), 120) or 120

# ---------- 评论系统配置 ----------
COMMENTS_CFG = config.get("comments", DEFAULT_CONFIG["comments"])
COMMENTS_ENABLED = bool(COMMENTS_CFG.get("enabled", True))
COMMENTS_MAX_LENGTH = COMMENTS_CFG.get("max_length", 1024)
COMMENTS_MAX_POSTS = COMMENTS_CFG.get("max_comments", 200)
COMMENTS_COOLDOWN_SECONDS = COMMENTS_CFG.get("cooldown_seconds", 3)
COMMENTS_PAGE_SIZE = COMMENTS_CFG.get("page_size", 50)
COMMENTS_MAX_HEIGHT_PX = COMMENTS_CFG.get("max_height_px", 280)
try:
    COMMENTS_MAX_HEIGHT_PX = int(COMMENTS_MAX_HEIGHT_PX)
    if COMMENTS_MAX_HEIGHT_PX <= 0:
        COMMENTS_MAX_HEIGHT_PX = 280
except (TypeError, ValueError):
    COMMENTS_MAX_HEIGHT_PX = 280

# ---------- 第三方登录（OAuth）配置 ----------
# 各 Provider 的授权/令牌/用户信息端点硬编码在 app/core/oauth.py，这里只放
# 凭据与开关。凭据留空即视为「未配置」，登录页不展示对应按钮。
OAUTH_CFG = config.get("oauth", DEFAULT_CONFIG["oauth"])
# 总开关：默认关闭所有第三方登录。仅当其为 true 且对应功能开关开启、凭据已配置时
# 才展示 / 允许使用某 Provider（线下可硬关闭，不受运行时功能开关影响）。
OAUTH_ENABLED = bool(OAUTH_CFG.get("enabled", False))
OAUTH_AUTO_REGISTER = bool(OAUTH_CFG.get("auto_register", True))
try:
    OAUTH_TIMEOUT_SECONDS = max(1, int(OAUTH_CFG.get("timeout_seconds", 10)))
except (TypeError, ValueError):
    OAUTH_TIMEOUT_SECONDS = 10
_OAUTH_PROVIDERS_CFG = OAUTH_CFG.get("providers", {}) or {}
if not isinstance(_OAUTH_PROVIDERS_CFG, dict):
    _OAUTH_PROVIDERS_CFG = {}

# ---------- 2FA / 邮箱 / 手机号验证配置 ----------
SECURITY_CFG = config.get("security", DEFAULT_CONFIG["security"])

def _security_int(key: str, default: int, minimum: int = 1) -> int:
    try:
        return max(minimum, int(SECURITY_CFG.get(key, default)))
    except (TypeError, ValueError):
        return default

SECURITY_CODE_LENGTH = _security_int("code_length", 6, 4)
# 验证码字符集固定为数字，长度可配（4-8 位），过长会导致比对/输入困难
if SECURITY_CODE_LENGTH > 8:
    SECURITY_CODE_LENGTH = 8
SECURITY_CODE_TTL = _security_int("code_ttl_seconds", 600)
SECURITY_CODE_RESEND_COOLDOWN = _security_int("code_resend_cooldown_seconds", 60, 0)
SECURITY_CODE_MAX_ATTEMPTS = _security_int("code_max_attempts", 5)
SECURITY_CHALLENGE_TTL = _security_int("challenge_ttl_seconds", 600)
SECURITY_EMAIL_LOGIN = bool(SECURITY_CFG.get("email_login", True))
SECURITY_PHONE_LOGIN = bool(SECURITY_CFG.get("phone_login", True))
try:
    SECURITY_TIMEOUT_SECONDS = max(1, int(SECURITY_CFG.get("timeout_seconds", 10)))
except (TypeError, ValueError):
    SECURITY_TIMEOUT_SECONDS = 10
SMTP_CFG = SECURITY_CFG.get("smtp", DEFAULT_CONFIG["security"]["smtp"]) or {}
SMS_CFG = SECURITY_CFG.get("sms", DEFAULT_CONFIG["security"]["sms"]) or {}

# ---------- 功能开关管理员（#90：/admin/features 的访问者） ----------
# config.json 的 admin_users 与环境变量 RUSIN_ADMIN（逗号分隔用户名）取并集
_admin_cfg = config.get("admin_users", [])
if not isinstance(_admin_cfg, list):
    _admin_cfg = []
_admin_env = [u.strip() for u in os.environ.get("RUSIN_ADMIN", "").split(",") if u.strip()]
ADMIN_USERS = frozenset(_admin_cfg + _admin_env)

# ---------- 日志功能 ----------
LOGGER_CFG = config.get("logger", DEFAULT_CONFIG["logger"])
LOGGER_MAX_SIZE = LOGGER_CFG.get("max_size", 4294967296)
LOGGER_PATH = data_path(LOGGER_CFG.get("path_pattern", "log/{timestamp}.log"))

# ---------- 插件系统配置 ----------
# 插件包（*.plugin.zip）投放到运行时目录（RUSIN_DATA_DIR）即可自动安装，
# 详见 app/plugins.py。无服务器环境（只读盘）自动禁用。
PLUGINS_CFG = config.get("plugins", DEFAULT_CONFIG["plugins"])
PLUGINS_ENABLED = bool(PLUGINS_CFG.get("enabled", True))
# Phase 2 更新检查：距 last_update 超过该天数才请求 upstream_repo
try:
    PLUGIN_UPDATE_STALE_SECONDS = int(PLUGINS_CFG.get("update_stale_days", 3)) * 86400
except (TypeError, ValueError):
    PLUGIN_UPDATE_STALE_SECONDS = 3 * 86400
# 后台更新检查线程的轮询周期（小时）
try:
    PLUGIN_UPDATE_CHECK_INTERVAL = int(PLUGINS_CFG.get("update_interval_hours", 6)) * 3600
except (TypeError, ValueError):
    PLUGIN_UPDATE_CHECK_INTERVAL = 6 * 3600

# ---------- 反向代理 WAF（nginx + ModSecurity + OWASP CRS）配置 ----------
# 详见 app/core/waf.py：python -m app 启动时下载 CRS 规则集并生成反代配置。
# 引擎本体（nginx + libmodsecurity 模块）属系统包，只探测与提示，绝不自动安装。
WAF_CFG = config.get("waf", DEFAULT_CONFIG["waf"])
# 环境变量 RUSIN_WAF=1 可临时开启（无服务器平台仍会被 SERVERLESS 判定禁用）
_waf_env = os.environ.get("RUSIN_WAF", "").strip().lower()
WAF_ENABLED = bool(WAF_CFG.get("enabled", False)) or _waf_env in ("1", "true", "yes")
WAF_AUTO_DOWNLOAD = bool(WAF_CFG.get("auto_download", True))
WAF_CRS_VERSION = str(WAF_CFG.get("crs_version", "") or "").strip()
WAF_CRS_URL = str(WAF_CFG.get("crs_url", "") or "").strip()
WAF_CRS_SHA256 = str(WAF_CFG.get("crs_sha256", "") or "").strip().lower()
WAF_VERIFY_CHECKSUM = bool(WAF_CFG.get("verify_checksum", True))
WAF_MODE = str(WAF_CFG.get("mode", "on") or "on").strip().lower()
if WAF_MODE not in ("on", "detectiononly"):
    WAF_MODE = "on"
WAF_RESPONSE_INSPECTION = bool(WAF_CFG.get("response_inspection", False))
WAF_LISTEN = str(WAF_CFG.get("listen", "80") or "80").strip()
WAF_SERVER_NAME = str(WAF_CFG.get("server_name", "_") or "_").strip()
WAF_UPSTREAM = str(WAF_CFG.get("upstream", "127.0.0.1") or "127.0.0.1").strip()
WAF_UPSTREAM_PORT = int(WAF_CFG.get("upstream_port", 0) or 0) or _env_int("PORT", 8080)
WAF_PARANOIA_LEVEL = min(4, max(1, _positive_int(WAF_CFG.get("paranoia_level", 1), 1)))
WAF_INBOUND_THRESHOLD = max(1, _positive_int(WAF_CFG.get("inbound_anomaly_threshold", 5), 5))
WAF_OUTBOUND_THRESHOLD = max(1, _positive_int(WAF_CFG.get("outbound_anomaly_threshold", 4), 4))
# 请求体上限：必须 ≥ 应用自身接受的最大上传体积，否则 ModSecurity/nginx 会先于应用回 413
WAF_BODY_LIMIT_BYTES = int(WAF_CFG.get("body_limit_kb", 0) or 0) * 1024
if WAF_BODY_LIMIT_BYTES <= 0:
    WAF_BODY_LIMIT_BYTES = max(MAX_CONTENT_BYTES, NOTE_TRANSFER_MAX_FILE_BYTES,
                               MAX_ATTACHMENT_SIZE_BYTES, 1024 * 1024)
WAF_DEFAULT_EXCLUSIONS = bool(WAF_CFG.get("default_exclusions", True))
try:
    WAF_UPDATE_STALE_SECONDS = int(WAF_CFG.get("update_stale_days", 7)) * 86400
except (TypeError, ValueError):
    WAF_UPDATE_STALE_SECONDS = 7 * 86400
WAF_VALIDATE_CONFIG = bool(WAF_CFG.get("validate_config", True))
WAF_AUTO_RELOAD = bool(WAF_CFG.get("auto_reload", False))

DEBUG = config.get("debug", False)

# ---------- 页面缓存配置 ----------
CACHE_CFG = config.get("cache", DEFAULT_CONFIG["cache"])
CACHE_ENABLED = bool(CACHE_CFG.get("enabled", True))
CACHE_BACKEND = CACHE_CFG.get("backend", "redis")
CACHE_DEFAULT_TIMEOUT = int(CACHE_CFG.get("default_timeout", 300))
CACHE_REDIS_URL = os.environ.get("REDIS_URL") or CACHE_CFG.get("redis_url", "redis://localhost:6379/0")
# 页面缓存 TTL（秒）
CACHE_TIMEOUT_INDEX = 1800    # 首页 30min
CACHE_TIMEOUT_NOTES = 300     # 笔记页面 5min
CACHE_TIMEOUT_BENBEN = 60     # 犇犇 1min
