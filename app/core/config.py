"""配置加载与全局常量"""
import os
import json
import string

# ---------- Markdown / Bleach / Pygments 可选依赖 ----------
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
    "get_rate_limit": {                     # GET 独立限流
        "window_seconds": 60,
        "max_requests": 45
    },
    "save_rate_limit": {                    # 保存类 POST 独立限流
        "window_seconds": 60,
        "max_requests": 120
    },
    "register_rate_limit": {                # 注册限流：单 IP 每窗口最多注册数
        "window_seconds": 120,
        "max_requests": 1
    },
    "ip_rate_limit": {                      # 全站每 IP 总请求上限（0 关闭）
        "window_seconds": 60,
        "max_requests": 300
    },
    "trust_proxy_headers": False,           # 仅在可信反代后置 True
    # 可信代理网段（IP/CIDR 或 loopback/private/cloudflare）；仅直连对端命中才采信代理头
    "trusted_proxies": ["loopback", "private"],
    "proxy_hops": 1,                        # 兼容模式（"*"）下 XFF 从右往左的跳数
    "ip_allowlist": [],                     # 免限流白名单
    "ip_blocklist": [],                     # 直接 403 黑名单
    "secure_cookies": False,                # HTTPS 部署置 True
    "global_cdn": "https://cdn.jsdmirror.cn",  # 前端静态资源 CDN 基础地址
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
    "note_transfer": {                           # 笔记批量导入 / 导出
        "max_file_kb": 4096,                     # 导入文件大小上限（KB）
        "max_notes": 300                         # 单次导入笔记数上限
    },
    "avatar": {
        "enabled": True,
        "url_template": "https://cn.cravatar.com/avatar/{hash}?d=identicon&f=y",
        "size": 24
    },
    "images": {                                # 笔记图床
        "enabled": True,
        "max_size_kb": 2048,                   # 单图上限（KB）
        "max_total_kb": 51200                  # 每用户配额（KB）
    },
    "attachments": {                          # 笔记附件（登录后可下载）
        "enabled": True,
        "max_size_kb": 50,                     # 单附件上限（KB）
        "max_per_note_kb": 500,                # 单笔记引用总量上限（KB）
        "max_total_kb": 10240,                 # 每用户配额（KB）
        "allow_anonymous_download": False,     # 匿名下载，默认禁止
        "max_concurrent_downloads": 1,         # 单用户同时在途下载数（0 不限）
        "max_concurrent_uploads": 1,           # 单用户同时在途上传数（0 不限）
        "download_rate_limit": {               # 下载路由每 IP 限流
            "window_seconds": 60,
            "max_requests": 120
        },
        "blocked_extensions": [                # 黑名单扩展名（可执行/压缩包等）
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
    "comments": {                            # 评论系统
        "enabled": True,
        "max_length": 1024,                  # 单条长度（字符）
        "max_comments": 200,                 # 每目标评论数上限
        "cooldown_seconds": 3,               # 发布冷却（秒）
        "page_size": 50,                     # 分页大小
        "max_height_px": 280,                # 内容最大高度（px），超出滚动
    },
    "oauth": {                                # 第三方登录
        "enabled": False,                      # 总开关，默认全关
        "auto_register": True,                 # 未绑定时自动注册新用户
        "timeout_seconds": 10,                 # Provider HTTP 超时（秒）
        "providers": {                         # 凭据留空即未配置
            "github": {"client_id": "", "client_secret": ""},
            "google": {"client_id": "", "client_secret": ""},
            "microsoft": {"client_id": "", "client_secret": "", "tenant": "common"},
            "wechat": {"app_id": "", "app_secret": ""},
            "qq": {"app_id": "", "app_secret": ""},
        },
    },
    "security": {                             # 2FA / 邮箱 / 手机号验证
        "code_length": 6,                      # 验证码长度
        "code_ttl_seconds": 600,               # 验证码有效期（秒）
        "code_resend_cooldown_seconds": 60,    # 重发冷却（秒）
        "code_max_attempts": 5,                # 单码最大尝试次数
        "challenge_ttl_seconds": 600,          # 二次验证挑战有效期（秒）
        "timeout_seconds": 10,                 # 投递超时（秒）
        "email_login": True,                   # 允许邮箱验证码登录
        "phone_login": True,                   # 允许手机验证码登录
        "smtp": {                              # SMTP（留空只记日志不发送）
            "host": "", "port": 587, "username": "", "password": "",
            "from_addr": "", "use_tls": True, "use_ssl": False,
        },
        "sms": {                               # 短信 Webhook（POST JSON）
            "webhook_url": "", "token": "",
        },
    },
    "features": {                             # 功能开关默认值（运行时可在 /admin/features 切换）
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
        # 第三方登录：需先在 oauth.providers 填凭据
        "oauth_github": False,
        "oauth_google": False,
        "oauth_microsoft": False,
        "oauth_wechat": False,
        "oauth_qq": False,
        "login_captcha": True,
        "two_factor_auth": False,
        "email_verify": False,
        "phone_verify": False,
    },
    "admin_users": [],                        # 功能开关管理员（或环境变量 RUSIN_ADMIN）
    "max_note_id_length": 250,
    "max_note_tags": 10,                      # 每篇笔记标签数上限
    "max_tag_length": 24,                     # 单标签长度上限
    "max_folder_name_length": 64,             # 文件夹路径长度上限
    "max_folder_depth": 8,                    # 文件夹最大层级（/ 分隔）
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
        "enabled": False,                    # 默认关（仅 VPS 反代有意义）
        "auto_download": True,               # 自动下载 CRS 规则集（SHA256 校验）
        "crs_version": "4.29.0",             # 锁定的 CRS 版本
        "crs_url": "https://github.com/coreruleset/coreruleset/releases/download/v4.29.0/coreruleset-4.29.0-minimal.tar.gz",
        # 换版本必须同步换校验和，否则下载会被拒绝
        "crs_sha256": "1aa1c5c8fc29e532d35293bcea36bf72de61db8f6ed4716a0f91ab14552b7fed",
        "verify_checksum": True,             # 关闭仅内网镜像调试用
        "mode": "on",                        # on=拦截，detectiononly=只写审计日志
        "response_inspection": False,        # 出站检测误报多，默认关
        "listen": "80",                      # nginx 监听地址/端口
        "server_name": "_",
        "upstream": "127.0.0.1",             # 回源地址
        "upstream_port": 0,                  # 0 = 跟随 PORT（默认 8080）
        "paranoia_level": 1,                 # CRS 检测等级 1-4
        "inbound_anomaly_threshold": 5,      # 入站异常分阈值
        "outbound_anomaly_threshold": 4,     # 出站异常分阈值
        "body_limit_kb": 0,                  # 0 = 自动取应用上传上限最大值
        "default_exclusions": True,          # 正文类端点误报排除
        "update_stale_days": 7,              # 距上次下载超过该天数才重拉
        "validate_config": True,             # 生成后跑 nginx -t
        "auto_reload": False,                # 校验通过后 reload（需 root）
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
# 运行数据目录（JSON 内容 + SQLite 索引），RUSIN_DATA_DIR 可覆盖
DATA_DIR = os.environ.get("RUSIN_DATA_DIR", "data")
try:
    os.makedirs(DATA_DIR, exist_ok=True)
except (OSError, IOError):
    pass

# ---------- 无服务器平台检测 ----------
# 只读盘：数据须走外部存储，不启动后台线程，日志回退 stderr
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

# GET 限流
GET_RATE_CFG = config.get("get_rate_limit", DEFAULT_CONFIG["get_rate_limit"])
GET_RATE_WINDOW = GET_RATE_CFG.get("window_seconds", 60)
GET_RATE_MAX = GET_RATE_CFG.get("max_requests", 45)

# 保存类 POST 限流
SAVE_RATE_CFG = config.get("save_rate_limit", DEFAULT_CONFIG["save_rate_limit"])
SAVE_RATE_WINDOW = SAVE_RATE_CFG.get("window_seconds", 60)
SAVE_RATE_MAX = SAVE_RATE_CFG.get("max_requests", 120)

# 注册限流
REGISTER_RATE_CFG = config.get("register_rate_limit", DEFAULT_CONFIG["register_rate_limit"])
REGISTER_RATE_WINDOW = REGISTER_RATE_CFG.get("window_seconds", 120)
REGISTER_RATE_MAX = REGISTER_RATE_CFG.get("max_requests", 1)


def _env_list(name: str) -> list:
    """读取逗号/分号/空白分隔的列表型环境变量。"""
    raw = os.environ.get(name, "")
    for sep in (";", ",", " ", "\n", "\t"):
        raw = raw.replace(sep, ",")
    return [item.strip() for item in raw.split(",") if item.strip()]


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "") or default)
    except (TypeError, ValueError):
        return default


# 全站每 IP 总请求上限（叠加在路由限流之上，0 关闭）
IP_RATE_CFG = config.get("ip_rate_limit", DEFAULT_CONFIG["ip_rate_limit"])
IP_RATE_WINDOW = int(IP_RATE_CFG.get("window_seconds", 60) or 60)
IP_RATE_MAX = int(IP_RATE_CFG.get("max_requests", 300) or 0)
IP_RATE_ENABLED = bool(IP_RATE_CFG.get("enabled", True)) and IP_RATE_MAX > 0

# 可信代理：默认不信任 XFF/X-Real-IP，防伪造头绕过限流
TRUST_PROXY_HEADERS = bool(config.get("trust_proxy_headers", False))
# 仅直连对端命中该列表才采信代理头；"*" 信任任意对端
TRUSTED_PROXIES = _env_list("RUSIN_TRUSTED_PROXIES") or config.get(
    "trusted_proxies", DEFAULT_CONFIG["trusted_proxies"])
# 兼容模式 XFF 跳数（trusted_proxies 为 "*"/留空时生效）
PROXY_HOPS = max(1, _env_int("RUSIN_PROXY_HOPS", int(config.get("proxy_hops", 1) or 1)))
# IP 白名单（免限流）/ 黑名单（403）
IP_ALLOWLIST = list(config.get("ip_allowlist", []) or []) + _env_list("RUSIN_IP_ALLOWLIST")
IP_BLOCKLIST = list(config.get("ip_blocklist", []) or []) + _env_list("RUSIN_IP_BLOCKLIST")

# 会话 Cookie 的 Secure 标志
SECURE_COOKIES = bool(config.get("secure_cookies", False))
# 会话 Cookie Max-Age 默认 30 天
COOKIE_MAX_AGE_DEFAULT = 30 * 24 * 3600
# 登录态 Cookie 名须与 Flask session cookie（CSRF token）区分，否则互相覆盖
SESSION_COOKIE = "rusin_session"

# 会话超时
SESSION_TIMEOUT_ENABLED = config.get("session_timeout", {}).get("enabled", False)
SESSION_TIMEOUT_MINUTES = config.get("session_timeout", {}).get("minutes", 60)
SESSION_TIMEOUT_SECONDS = SESSION_TIMEOUT_MINUTES * 60

# 笔记过期清除（默认不启用）
NOTE_EXPIRATION_ENABLED = config.get("note_expiration", {}).get("enabled", False)
NOTE_EXPIRATION_HOURS = config.get("note_expiration", {}).get("hours", 24)
NOTE_EXPIRATION_SECONDS = NOTE_EXPIRATION_HOURS * 3600
# 后台清理线程扫描间隔（秒）
NOTE_CLEANUP_INTERVAL = 1800

# 笔记 ID 最大长度
MAX_NOTE_ID_LENGTH = config.get("max_note_id_length", 250)

# 笔记标签限制
MAX_NOTE_TAGS = config.get("max_note_tags", 10)
MAX_TAG_LENGTH = config.get("max_tag_length", 24)

# 笔记文件夹限制（每篇笔记至多归属一个文件夹）
MAX_FOLDER_NAME_LENGTH = config.get("max_folder_name_length", 64)
MAX_FOLDER_DEPTH = config.get("max_folder_depth", 8)

# LaTeX 渲染（客户端 KaTeX）
LATEX_RENDER_ENABLED = config.get("latex_render", {}).get("enabled", True)
GLOBAL_CDN = config.get("global_cdn", "https://cdn.jsdmirror.cn").rstrip("/")
KATEX_VERSION = "0.18.4"
LATEX_CDN = f"{GLOBAL_CDN}/npm/katex@{KATEX_VERSION}/dist"

# 代码高亮（客户端 highlight.js）
CODE_HIGHLIGHT_ENABLED = config.get("code_highlight", {}).get("enabled", True)
CODE_HIGHLIGHT_CDN = f"{GLOBAL_CDN}/npm/@highlightjs/cdn-assets@11.9.0"

# 后台会话清理线程间隔（秒）
SESSION_CLEANUP_INTERVAL = 300

# 分享浏览量批量写盘阈值/间隔，避免每次访问都写盘
SHARE_VIEWS_FLUSH_THRESHOLD = 30
SHARE_VIEWS_FLUSH_INTERVAL = 60.0

# ---------- ID 生成 ----------
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

# ---------- 分享 token ----------
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
# 路由校验宽松字符集，查找仍走字典精确匹配
SHARE_TOKEN_PATTERN = f"[A-Za-z0-9]{{{SHARE_TOKEN_LENGTH}}}"

# ---------- 密码策略 ----------
PW_POLICY = config.get("password_policy", DEFAULT_CONFIG["password_policy"])
PW_MIN_LENGTH = PW_POLICY.get("min_length", 8)
# 硬上限 128：防超长密码进 PBKDF2 造成 CPU DoS
try:
    PW_MAX_LENGTH = min(int(PW_POLICY.get("max_length", 128)), 128)
except (TypeError, ValueError):
    PW_MAX_LENGTH = 128
PW_REQUIRE_UPPER = PW_POLICY.get("require_uppercase", True)
PW_REQUIRE_LOWER = PW_POLICY.get("require_lowercase", True)
PW_REQUIRE_DIGIT = PW_POLICY.get("require_digits", True)
PW_REQUIRE_SPECIAL = PW_POLICY.get("require_special", True)


def get_password_requirements_description(lang: str = "zh"):
    """密码要求描述（zh/en），由各单项要求拼装。"""
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


# ---------- 犇犇 ----------
BENBEN_CFG = config.get("benben", DEFAULT_CONFIG["benben"])
BENBEN_MAX_LENGTH = BENBEN_CFG.get("max_length", 1024)
BENBEN_PAGE_SIZE = BENBEN_CFG.get("page_size", 50)
# 发布冷却（秒）
BENBEN_COOLDOWN_SECONDS = BENBEN_CFG.get("cooldown_seconds", 3)
# 内容最大显示高度（px），超出滚动
BENBEN_MAX_HEIGHT_PX = BENBEN_CFG.get("max_height_px", 280)
# 持久化条数上限，超出丢弃最旧
BENBEN_MAX_POSTS = BENBEN_CFG.get("max_posts", 200)
try:
    BENBEN_MAX_HEIGHT_PX = int(BENBEN_MAX_HEIGHT_PX)
    if BENBEN_MAX_HEIGHT_PX <= 0:
        BENBEN_MAX_HEIGHT_PX = 280
except (TypeError, ValueError):
    BENBEN_MAX_HEIGHT_PX = 280

# ---------- 笔记编辑器 ----------
# 实时渲染默认关闭（选择存 localStorage）
NOTE_EDITOR_CFG = config.get("note_editor", DEFAULT_CONFIG["note_editor"])
LIVE_PREVIEW_DEFAULT = bool(NOTE_EDITOR_CFG.get("live_preview_default", False))
# Markdown 手册链接
MARKDOWN_MANUAL_URL = NOTE_EDITOR_CFG.get(
    "markdown_manual_url", "https://markdown.com.cn")

# ---------- 笔记快捷引用（#id） ----------
NOTE_REFS_CFG = config.get("note_refs", DEFAULT_CONFIG["note_refs"])
NOTE_REFS_ENABLED = bool(NOTE_REFS_CFG.get("enabled", True))
# 引用搜索单次返回上限
NOTE_REF_SEARCH_LIMIT = NOTE_REFS_CFG.get("search_limit", 8)
# 引用搜索最多扫描的笔记数（防远程后端过慢）
NOTE_REF_SCAN_LIMIT = NOTE_REFS_CFG.get("scan_limit", 100)
try:
    NOTE_REF_SEARCH_LIMIT = max(1, int(NOTE_REF_SEARCH_LIMIT))
except (TypeError, ValueError):
    NOTE_REF_SEARCH_LIMIT = 8
try:
    NOTE_REF_SCAN_LIMIT = max(1, int(NOTE_REF_SCAN_LIMIT))
except (TypeError, ValueError):
    NOTE_REF_SCAN_LIMIT = 100

# ---------- 笔记导入 / 导出 ----------
NOTE_TRANSFER_CFG = config.get("note_transfer", DEFAULT_CONFIG["note_transfer"])
try:
    NOTE_TRANSFER_MAX_FILE_BYTES = max(1, int(NOTE_TRANSFER_CFG.get("max_file_kb", 4096))) * 1024
except (TypeError, ValueError):
    NOTE_TRANSFER_MAX_FILE_BYTES = 4096 * 1024
try:
    NOTE_TRANSFER_MAX_NOTES = max(1, int(NOTE_TRANSFER_CFG.get("max_notes", 300)))
except (TypeError, ValueError):
    NOTE_TRANSFER_MAX_NOTES = 300

# ---------- 首页显示 ----------
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

# 项目根目录
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# 首页横幅：NOTICE.txt 第一行（空则不展示）
NOTICE_FILE = os.path.join(BASE_DIR, "NOTICE.txt")
DOCS_DIR = os.path.join(BASE_DIR, "docs")

# ---------- 工作台待办 ----------
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

# ---------- 头像 ----------
# 第三方服务生成，md5(用户名) 为哈希；占位符 {hash} / {username}
AVATAR_CFG = config.get("avatar", DEFAULT_CONFIG["avatar"])
AVATAR_ENABLED = bool(AVATAR_CFG.get("enabled", True))
AVATAR_URL_TEMPLATE = AVATAR_CFG.get(
    "url_template", "https://cn.cravatar.com/avatar/{hash}?d=identicon&f=y")

# ---------- 笔记图床 ----------
IMAGES_CFG = config.get("images", DEFAULT_CONFIG["images"])
IMAGES_ENABLED = bool(IMAGES_CFG.get("enabled", True))
MAX_IMAGE_SIZE_KB = IMAGES_CFG.get("max_size_kb", 2048)
MAX_IMAGE_TOTAL_KB = IMAGES_CFG.get("max_total_kb", 51200)
MAX_IMAGE_SIZE_BYTES = MAX_IMAGE_SIZE_KB * 1024
MAX_IMAGE_TOTAL_BYTES = MAX_IMAGE_TOTAL_KB * 1024

# ---------- 笔记附件 ----------
ATTACHMENTS_CFG = config.get("attachments", DEFAULT_CONFIG["attachments"])
ATTACHMENTS_ENABLED = bool(ATTACHMENTS_CFG.get("enabled", True))
MAX_ATTACHMENT_SIZE_KB = ATTACHMENTS_CFG.get("max_size_kb", 50)
MAX_ATTACHMENT_PER_NOTE_KB = ATTACHMENTS_CFG.get("max_per_note_kb", 500)
MAX_ATTACHMENT_TOTAL_KB = ATTACHMENTS_CFG.get("max_total_kb", 10240)
MAX_ATTACHMENT_SIZE_BYTES = MAX_ATTACHMENT_SIZE_KB * 1024
MAX_ATTACHMENT_PER_NOTE_BYTES = MAX_ATTACHMENT_PER_NOTE_KB * 1024
MAX_ATTACHMENT_TOTAL_BYTES = MAX_ATTACHMENT_TOTAL_KB * 1024
ATTACHMENT_BLOCKED_EXTENSIONS = ATTACHMENTS_CFG.get("blocked_extensions", DEFAULT_CONFIG["attachments"]["blocked_extensions"])

# 默认禁止匿名下载（未登录 401）
ATTACHMENTS_ALLOW_ANONYMOUS_DOWNLOAD = bool(ATTACHMENTS_CFG.get(
    "allow_anonymous_download", DEFAULT_CONFIG["attachments"]["allow_anonymous_download"]))


def _positive_int(value, default: int = 0) -> int:
    """并发上限类整数配置：非法回退默认，负数归 0（= 不限）。"""
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return default


# 单用户在途请求闸门：慢速长连接占用 worker，请求数限流拦不住（见 core/concurrency.py）
MAX_CONCURRENT_ATTACHMENT_DOWNLOADS = _positive_int(ATTACHMENTS_CFG.get(
    "max_concurrent_downloads", DEFAULT_CONFIG["attachments"]["max_concurrent_downloads"]), 1)
MAX_CONCURRENT_ATTACHMENT_UPLOADS = _positive_int(ATTACHMENTS_CFG.get(
    "max_concurrent_uploads", DEFAULT_CONFIG["attachments"]["max_concurrent_uploads"]), 1)

# 附件下载路由独立限流
ATTACHMENT_DOWNLOAD_RATE_CFG = ATTACHMENTS_CFG.get(
    "download_rate_limit", DEFAULT_CONFIG["attachments"]["download_rate_limit"])
ATTACHMENT_DOWNLOAD_RATE_WINDOW = _positive_int(
    ATTACHMENT_DOWNLOAD_RATE_CFG.get("window_seconds", 60), 60) or 60
ATTACHMENT_DOWNLOAD_RATE_MAX = _positive_int(
    ATTACHMENT_DOWNLOAD_RATE_CFG.get("max_requests", 120), 120) or 120

# ---------- 评论 ----------
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

# ---------- 第三方登录（OAuth） ----------
# 端点硬编码在 oauth/service.py，这里只放凭据与开关；凭据留空即未配置
OAUTH_CFG = config.get("oauth", DEFAULT_CONFIG["oauth"])
# 总开关：须与功能开关、凭据三者同时满足才可用
OAUTH_ENABLED = bool(OAUTH_CFG.get("enabled", False))
OAUTH_AUTO_REGISTER = bool(OAUTH_CFG.get("auto_register", True))
try:
    OAUTH_TIMEOUT_SECONDS = max(1, int(OAUTH_CFG.get("timeout_seconds", 10)))
except (TypeError, ValueError):
    OAUTH_TIMEOUT_SECONDS = 10
_OAUTH_PROVIDERS_CFG = OAUTH_CFG.get("providers", {}) or {}
if not isinstance(_OAUTH_PROVIDERS_CFG, dict):
    _OAUTH_PROVIDERS_CFG = {}

# ---------- 2FA / 验证码 ----------
SECURITY_CFG = config.get("security", DEFAULT_CONFIG["security"])

def _security_int(key: str, default: int, minimum: int = 1) -> int:
    try:
        return max(minimum, int(SECURITY_CFG.get(key, default)))
    except (TypeError, ValueError):
        return default

SECURITY_CODE_LENGTH = _security_int("code_length", 6, 4)
# 验证码为纯数字，长度限 4-8 位
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

# ---------- 功能开关管理员 ----------
# config.json 的 admin_users 与环境变量 RUSIN_ADMIN 取并集
_admin_cfg = config.get("admin_users", [])
if not isinstance(_admin_cfg, list):
    _admin_cfg = []
_admin_env = [u.strip() for u in os.environ.get("RUSIN_ADMIN", "").split(",") if u.strip()]
ADMIN_USERS = frozenset(_admin_cfg + _admin_env)

# ---------- 日志 ----------
LOGGER_CFG = config.get("logger", DEFAULT_CONFIG["logger"])
LOGGER_MAX_SIZE = LOGGER_CFG.get("max_size", 4294967296)
LOGGER_PATH = data_path(LOGGER_CFG.get("path_pattern", "log/{timestamp}.log"))

# ---------- 插件 ----------
# *.plugin.zip 投放到 RUSIN_DATA_DIR 自动安装；无服务器环境自动禁用
PLUGINS_CFG = config.get("plugins", DEFAULT_CONFIG["plugins"])
PLUGINS_ENABLED = bool(PLUGINS_CFG.get("enabled", True))
# 距 last_update 超过该天数才请求 upstream_repo
try:
    PLUGIN_UPDATE_STALE_SECONDS = int(PLUGINS_CFG.get("update_stale_days", 3)) * 86400
except (TypeError, ValueError):
    PLUGIN_UPDATE_STALE_SECONDS = 3 * 86400
# 后台更新检查轮询周期（小时）
try:
    PLUGIN_UPDATE_CHECK_INTERVAL = int(PLUGINS_CFG.get("update_interval_hours", 6)) * 3600
except (TypeError, ValueError):
    PLUGIN_UPDATE_CHECK_INTERVAL = 6 * 3600

# ---------- WAF ----------
# 见 core/waf.py；系统包（nginx + libmodsecurity）只探测不安装
WAF_CFG = config.get("waf", DEFAULT_CONFIG["waf"])
# RUSIN_WAF=1 可临时开启（无服务器仍禁用）
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
# 请求体上限须 ≥ 应用最大上传体积，否则 nginx 先回 413
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

# ---------- 页面缓存 ----------
CACHE_CFG = config.get("cache", DEFAULT_CONFIG["cache"])
CACHE_ENABLED = bool(CACHE_CFG.get("enabled", True))
CACHE_BACKEND = CACHE_CFG.get("backend", "redis")
CACHE_DEFAULT_TIMEOUT = int(CACHE_CFG.get("default_timeout", 300))
CACHE_REDIS_URL = os.environ.get("REDIS_URL") or CACHE_CFG.get("redis_url", "redis://localhost:6379/0")
# 页面缓存 TTL（秒）
CACHE_TIMEOUT_INDEX = 1800    # 首页
CACHE_TIMEOUT_NOTES = 300     # 笔记
CACHE_TIMEOUT_BENBEN = 60     # 犇犇
