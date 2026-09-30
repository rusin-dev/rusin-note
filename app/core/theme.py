"""暗色模式主题样式/脚本与 favicon 缓存"""
import os

# ---------- 暗色模式（CSS 变量 + 切换脚本，所有页面共用；类 ChatGPT 风格） ----------
THEME_VARS = """:root {
    color-scheme: light dark;
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
[data-theme="dark"] {
    color-scheme: dark;
    --bg: #212121;
    --text: #ececec;
    --heading-border: #2f2f2f;
    --navbar-bg: #171717;
    --navbar-border: #2f2f2f;
    --link: #1aba8a;
    --hover: #c5c5d2;
    --border: #4d4d4f;
    --input-bg: #2f2f2f;
    --btn-bg: #2f2f2f;
    --btn-hover: #424242;
    --error: #f93a37;
    --muted: #b4b4b4;
    --list-border: #2f2f2f;
    --card-bg: #2f2f2f;
    --card-border: #424242;
    --card-head: #ececec;
    --card-detail: #b4b4b4;
    --disclaimer-bg: #2f2f2f;
    --disclaimer-border: #424242;
    --code-bg: #2f2f2f;
    --quote-border: #4d4d4f;
    --quote-text: #b4b4b4;
    --status-bg: rgba(33, 33, 33, 0.95);
    --card-shadow: 0 4px 16px rgba(0, 0, 0, 0.4);
    --card-icon-bg: #353535;
    --hero-grad-a: #ececec;
    --hero-grad-b: #2dd4a7;
    --glow-ring: rgba(255, 255, 255, 0.14);
    --glow-soft: rgba(255, 255, 255, 0.06);
    --glow-shadow: 0 2px 8px rgba(0, 0, 0, 0.35);
}
"""
# 主题切换脚本：放在 <head> 最前避免闪烁；优先服务器渲染的主题（Cookie），其次 localStorage，最后跟随系统偏好。
# 切换时同时写入 Cookie（服务端据此直接渲染 data-theme，慢网速下切页不再闪白屏）与 localStorage。
def get_theme_script(lang: str) -> str:
    return f"""
<script>
(function() {{
    function setCookie(t) {{
        document.cookie = 'rusin-theme=' + t + '; Path=/; Max-Age=31536000; SameSite=Lax';
    }}
    function apply(t) {{
        document.documentElement.setAttribute('data-theme', t);
        var b = document.getElementById('themeBtn');
        if (b) {{
            var icon = t === 'dark' ? 'fa-sun' : 'fa-moon';
            b.innerHTML = '<i class="fa-solid ' + icon + '" aria-hidden="true"></i>';
        }}
        try {{ localStorage.setItem('rusin-theme', t); }} catch (e) {{}}
        setCookie(t);
    }}
    window.toggleTheme = function() {{
        apply(document.documentElement.getAttribute('data-theme') === 'dark' ? 'light' : 'dark');
    }};
    var saved = null;
    try {{ saved = localStorage.getItem('rusin-theme'); }} catch (e) {{}}
    var serverTheme = document.documentElement.getAttribute('data-theme');
    if (serverTheme) saved = serverTheme;
    apply(saved || (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'));
    document.addEventListener('DOMContentLoaded', function() {{
        apply(document.documentElement.getAttribute('data-theme') === 'dark' ? 'dark' : 'light');
    }});
}})();
</script>
"""


def get_theme_toggle_btn(lang: str, theme: str = None) -> str:
    icon = "fa-sun" if theme == "dark" else "fa-moon"
    return (f'<button type="button" id="themeBtn" class="theme-toggle" '
            f'onclick="toggleTheme()"><i class="fa-solid {icon}" aria-hidden="true"></i></button>')


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
