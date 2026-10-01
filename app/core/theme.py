"""主题 CSS 变量与 favicon 缓存"""
import os

# ---------- 主题 CSS 变量（仅浅色，所有页面共用；类 ChatGPT 风格） ----------
THEME_VARS = """:root {
    color-scheme: light;
    background-color: var(--bg);
    --bg: #ffffff;
    --text: #0d0d0d;
    --heading-border: #ececec;
    --navbar-bg: #ffffff;
    --navbar-border: #ececec;
    --link: #0e8a6d;
    --hover: #353740;
    --border: #d9d9d9;
    --input-bg: #ffffff;
    --btn-bg: #ececec;
    --btn-hover: #e3e3e3;
    --error: #f93a37;
    --muted: #6e6e80;
    --list-border: #ececec;
    --card-bg: #f7f7f8;
    --card-border: #ececec;
    --card-head: #202123;
    --card-detail: #6e6e80;
    --disclaimer-bg: #f7f7f8;
    --disclaimer-border: #ececec;
    --code-bg: #f1f1f3;
    --quote-border: #d9d9d9;
    --quote-text: #6e6e80;
    --status-bg: rgba(255, 255, 255, 0.95);
    --card-shadow: 0 4px 16px rgba(0, 0, 0, 0.06);
    --card-icon-bg: #ececec;
    --hero-grad-a: #0d0d0d;
    --hero-grad-b: #10a37f;
    --glow-ring: rgba(0, 0, 0, 0.12);
    --glow-soft: rgba(0, 0, 0, 0.05);
    --glow-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
}
"""


# ---------- favicon 缓存（BUG-16：避免每次请求读磁盘） ----------
_FAVICON_CACHE = None


def get_favicon() -> bytes | None:
    global _FAVICON_CACHE
    if _FAVICON_CACHE is None:
        try:
            favicon_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "static", "favicon.ico",
            )
            with open(favicon_path, "rb") as f:
                _FAVICON_CACHE = f.read()
        except (IOError, OSError):
            _FAVICON_CACHE = b""
    return _FAVICON_CACHE or None
