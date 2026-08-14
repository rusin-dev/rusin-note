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
    "trust_proxy_headers": False,           # 仅当部署在可信反向代理之后才置 True，否则一律用直连 IP
    "secure_cookies": False,                # HTTPS 部署时置 True，为会话 Cookie 添加 Secure 标志
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
        "enabled": True,
        "cdn": "https://cdn.jsdelivr.net/npm/katex@0.16.11/dist"
    },
    "password_policy": {
        "min_length": 8,
        "require_uppercase": True,
        "require_lowercase": True,
        "require_digits": True,
        "require_special": True
    },
    "benben": {
        "max_length": 1024,
        "page_size": 50,
        "cooldown_seconds": 3,
        "max_height_px": 1000
    }
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

# 可信代理配置（BUG-3：默认不信任 X-Forwarded-For / X-Real-IP，防止伪造头绕过限流）
TRUST_PROXY_HEADERS = bool(config.get("trust_proxy_headers", False))

# Cookie 安全配置（BUG-13）
SECURE_COOKIES = bool(config.get("secure_cookies", False))
# 会话 Cookie 的 Max-Age：与服务器端会话超时保持一致；未启用超时时默认 30 天
COOKIE_MAX_AGE_DEFAULT = 30 * 24 * 3600

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

# LaTeX 公式渲染配置（客户端 KaTeX 渲染，洛谷同款，仅影响 Markdown 只读页面）
# cdn 为 KaTeX 静态文件基础目录，自动拼接 katex.min.css / katex.min.js / contrib/auto-render.min.js
LATEX_RENDER_ENABLED = config.get("latex_render", {}).get("enabled", True)
LATEX_CDN = config.get("latex_render", {}).get(
    "cdn", "https://cdn.jsdelivr.net/npm/katex@0.16.11/dist")

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
PW_REQUIRE_UPPER = PW_POLICY.get("require_uppercase", True)
PW_REQUIRE_LOWER = PW_POLICY.get("require_lowercase", True)
PW_REQUIRE_DIGIT = PW_POLICY.get("require_digits", True)
PW_REQUIRE_SPECIAL = PW_POLICY.get("require_special", True)


def get_password_requirements_description(lang: str = "zh"):
    """密码要求描述（zh/en）。由各单项要求拼装，`、`/`, ` 分隔。"""
    if lang == "en":
        parts = [f"at least {PW_MIN_LENGTH} characters"]
        if PW_REQUIRE_UPPER:
            parts.append("uppercase letters")
        if PW_REQUIRE_LOWER:
            parts.append("lowercase letters")
        if PW_REQUIRE_DIGIT:
            parts.append("digits")
        if PW_REQUIRE_SPECIAL:
            parts.append("special characters (not / \\ ( ) \" ' )")
        return ", ".join(parts)
    parts = [f"至少 {PW_MIN_LENGTH} 位"]
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
try:
    BENBEN_MAX_HEIGHT_PX = int(BENBEN_MAX_HEIGHT_PX)
    if BENBEN_MAX_HEIGHT_PX <= 0:
        BENBEN_MAX_HEIGHT_PX = 1000
except (TypeError, ValueError):
    BENBEN_MAX_HEIGHT_PX = 1000
