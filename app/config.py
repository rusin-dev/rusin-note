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
    "trust_proxy_headers": False,           # 仅当部署在可信反向代理之后才置 True，否则一律用直连 IP
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
        "max_height_px": 1000,
        "max_posts": 200
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
    "attachments": {                          # 笔记附件：编辑器上传，/attachment/<u>/<id> 公开访问
        "enabled": True,
        "max_size_kb": 10240,                  # 单个附件上限（KB），默认 10 MB
        "max_total_kb": 10240,                 # 每用户配额（KB），默认 10 MB
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
        "max_height_px": 1000,               # 评论内容渲染后最大显示高度（px）
    },
    "features": {                             # 功能开关默认值（#90）：运行时可由管理员在 /admin/features 切换
        "world_notes": True,
        "benben": True,
        "share_links": True,
        "open_register": True,
        "note_tags": True,
        "note_folders": True,
        "note_pins": True,
        "heading_anchors": True,
        "note_images": True,
        "note_attachments": True,
        "comments": True,
    },
    "admin_users": [],                        # 功能开关管理员用户名（也可用环境变量 RUSIN_ADMIN 指定，逗号分隔）
    "max_note_id_length": 250,
    "max_note_tags": 10,                      # 笔记标签：每篇笔记最多标签数
    "max_tag_length": 24,                     # 笔记标签：单个标签最大长度（字符）
    "max_folder_name_length": 32,             # 笔记文件夹：文件夹名最大长度（字符）
    "logger": {
        "max_size": 4294967296,
        "path": "log/"
    },
    "plugins": {
        "enabled": True,
        "update_interval_hours": 6,
        "update_stale_days": 3
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
DATA_DIR = os.environ.get("RUSIN_DATA_DIR", ".")
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

# 可信代理配置（BUG-3：默认不信任 X-Forwarded-For / X-Real-IP，防止伪造头绕过限流）
TRUST_PROXY_HEADERS = bool(config.get("trust_proxy_headers", False))

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

# 笔记文件夹限制：文件夹名最大长度（字符），每篇笔记至多归属一个文件夹
MAX_FOLDER_NAME_LENGTH = config.get("max_folder_name_length", 32)

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
CODE_HIGHLIGHT_CDN = f"{GLOBAL_CDN}/npm/@highlightjs/cdn-assets@11.9.0/highlight.min.js"

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
# 犇犇内容渲染后的最大显示高度（px）：超出部分在内容区内滚动，默认 1000px
BENBEN_MAX_HEIGHT_PX = BENBEN_CFG.get("max_height_px", 1000)
# 犇犇持久化条数上限（外部存储单键体积控制，超出丢弃最旧）
BENBEN_MAX_POSTS = BENBEN_CFG.get("max_posts", 200)
try:
    BENBEN_MAX_HEIGHT_PX = int(BENBEN_MAX_HEIGHT_PX)
    if BENBEN_MAX_HEIGHT_PX <= 0:
        BENBEN_MAX_HEIGHT_PX = 1000
except (TypeError, ValueError):
    BENBEN_MAX_HEIGHT_PX = 1000

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
MAX_ATTACHMENT_SIZE_KB = ATTACHMENTS_CFG.get("max_size_kb", 10240)
MAX_ATTACHMENT_TOTAL_KB = ATTACHMENTS_CFG.get("max_total_kb", 10240)
MAX_ATTACHMENT_SIZE_BYTES = MAX_ATTACHMENT_SIZE_KB * 1024
MAX_ATTACHMENT_TOTAL_BYTES = MAX_ATTACHMENT_TOTAL_KB * 1024
ATTACHMENT_BLOCKED_EXTENSIONS = ATTACHMENTS_CFG.get("blocked_extensions", DEFAULT_CONFIG["attachments"]["blocked_extensions"])

# ---------- 评论系统配置 ----------
COMMENTS_CFG = config.get("comments", DEFAULT_CONFIG["comments"])
COMMENTS_ENABLED = bool(COMMENTS_CFG.get("enabled", True))
COMMENTS_MAX_LENGTH = COMMENTS_CFG.get("max_length", 1024)
COMMENTS_MAX_POSTS = COMMENTS_CFG.get("max_comments", 200)
COMMENTS_COOLDOWN_SECONDS = COMMENTS_CFG.get("cooldown_seconds", 3)
COMMENTS_PAGE_SIZE = COMMENTS_CFG.get("page_size", 50)
COMMENTS_MAX_HEIGHT_PX = COMMENTS_CFG.get("max_height_px", 1000)
try:
    COMMENTS_MAX_HEIGHT_PX = int(COMMENTS_MAX_HEIGHT_PX)
    if COMMENTS_MAX_HEIGHT_PX <= 0:
        COMMENTS_MAX_HEIGHT_PX = 1000
except (TypeError, ValueError):
    COMMENTS_MAX_HEIGHT_PX = 1000

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
