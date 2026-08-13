"""暗色模式主题样式/脚本与 favicon 缓存"""
# ---------- 暗色模式（CSS 变量 + 切换脚本，所有页面共用） ----------
THEME_VARS = """:root {
    --bg: #ffffff;
    --text: #111111;
    --heading-border: #eeeeee;
    --navbar-bg: #f8f9fa;
    --navbar-border: #dddddd;
    --link: #0366d6;
    --border: #cccccc;
    --input-bg: #ffffff;
    --btn-bg: #f0f0f0;
    --btn-hover: #e0e0e0;
    --error: #c00;
    --muted: #888888;
    --list-border: #eeeeee;
    --card-bg: #fafafa;
    --card-border: #dddddd;
    --card-head: #333333;
    --card-detail: #666666;
    --disclaimer-bg: #f9f9f9;
    --disclaimer-border: #eeeeee;
    --code-bg: #f4f4f4;
    --quote-border: #dddddd;
    --quote-text: #666666;
    --status-bg: rgba(255, 255, 255, 0.95);
}
[data-theme="dark"] {
    --bg: #1a1a1a;
    --text: #e6e6e6;
    --heading-border: #333333;
    --navbar-bg: #222222;
    --navbar-border: #3a3a3a;
    --link: #79b8ff;
    --border: #444444;
    --input-bg: #252525;
    --btn-bg: #333333;
    --btn-hover: #3d3d3d;
    --error: #f85149;
    --muted: #8b949e;
    --list-border: #2d2d2d;
    --card-bg: #21262d;
    --card-border: #30363d;
    --card-head: #c9d1d9;
    --card-detail: #8b949e;
    --disclaimer-bg: #1d2127;
    --disclaimer-border: #30363d;
    --code-bg: #2d2d2d;
    --quote-border: #444444;
    --quote-text: #8b949e;
    --status-bg: rgba(30, 30, 30, 0.95);
}
"""

# 主题切换脚本：放在 <head> 最前避免闪烁；优先 localStorage，其次跟随系统偏好
THEME_SCRIPT = """
<script>
(function() {
    function apply(t) {
        document.documentElement.setAttribute('data-theme', t);
        var b = document.getElementById('themeBtn');
        if (b) b.textContent = t === 'dark' ? '亮色' : '暗色';
        try { localStorage.setItem('rusin-theme', t); } catch (e) {}
    }
    window.toggleTheme = function() {
        apply(document.documentElement.getAttribute('data-theme') === 'dark' ? 'light' : 'dark');
    };
    var saved = null;
    try { saved = localStorage.getItem('rusin-theme'); } catch (e) {}
    apply(saved || (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'));
})();
</script>
"""

THEME_TOGGLE_BTN = '<button type="button" id="themeBtn" class="theme-toggle" onclick="toggleTheme()">暗色</button>'

# ---------- favicon 缓存（BUG-16：避免每次请求读磁盘） ----------
_FAVICON_CACHE = None


def get_favicon() -> bytes | None:
    global _FAVICON_CACHE
    if _FAVICON_CACHE is None:
        try:
            with open("favicon.ico", "rb") as f:
                _FAVICON_CACHE = f.read()
        except (IOError, OSError):
            _FAVICON_CACHE = b""
    return _FAVICON_CACHE or None
