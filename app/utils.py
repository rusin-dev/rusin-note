"""Markdown 安全渲染（Pygments 高亮 + 行号）+ 文件大小/时间格式化（替代原 templates.py 的工具函数）"""
import html
import time


def format_size(size) -> str:
    """将字节数格式化为人类可读大小（B/KB/MB/GB，保留两位小数）"""
    if not isinstance(size, (int, float)) or size < 0:
        return ""
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.2f} KB"
    if size < 1024 * 1024 * 1024:
        return f"{size / (1024 * 1024):.2f} MB"
    return f"{size / (1024 * 1024 * 1024):.2f} GB"


def format_note_time(mtime) -> str:
    """将 epoch 秒格式化为本地时间字符串 YYYY-MM-DD HH:MM:SS"""
    if not mtime:
        return ""
    try:
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(mtime))
    except (ValueError, OverflowError, OSError):
        return ""


def render_markdown_html(content: str) -> str:
    """将 Markdown 安全渲染为 HTML（依赖 bleach 清洗防 XSS）。
    代码块使用 Pygments 高亮（codehilite），并默认显示行号。"""
    from . import config
    if config.MARKDOWN_AVAILABLE and config.BLEACH_AVAILABLE:
        try:
            raw_html = config.markdown.markdown(
                content, extensions=['extra', 'codehilite'],
                extension_configs={'codehilite': {
                    'linenums': True,
                    'guess_lang': False,
                    'css_class': 'codehilite',
                }},
            )
            allowed_tags = [
                'p', 'br', 'strong', 'em', 'u', 'strike', 'a',
                'ul', 'ol', 'li', 'blockquote', 'pre', 'code',
                'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'hr',
                'table', 'thead', 'tbody', 'tr', 'th', 'td',
                'div', 'span',
            ]
            allowed_attrs = {
                '*': ['class'],
                'a': ['href', 'title', 'target'],
            }
            return config.bleach.clean(
                raw_html, tags=allowed_tags, attributes=allowed_attrs, strip=True
            )
        except Exception:
            pass
    return f"<pre>{html.escape(content)}</pre>"


# Pygments 高亮样式缓存（亮/暗两套 CSS，生成后不再计算）
_LIGHT_RULES = None
_DARK_RULES = None


def _pygments_rules(style: str) -> str:
    """按 pygments 样式生成 .codehilite 作用域下的 token 配色规则。
    丢弃前 5 行未作用域化的 pre/linenos 全局规则（由 render_pygments_head 自管）。"""
    from pygments.formatters import HtmlFormatter
    lines = HtmlFormatter(style=style, cssclass="codehilite").get_style_defs().splitlines()
    return "\n".join(lines[5:]) if len(lines) >= 5 else "\n".join(lines)


def render_pygments_head() -> str:
    """返回启用 Pygments 代码高亮所需的 <head> 内容（含亮/暗两套配色与行号容器样式）。
    Pygments 不可用时返回空字符串。"""
    global _LIGHT_RULES, _DARK_RULES
    from . import config
    if not config.PYGMENTS_AVAILABLE:
        return ""
    if _LIGHT_RULES is None:
        _LIGHT_RULES = _pygments_rules("default")
        _DARK_RULES = _pygments_rules("monokai")
    return f"""<style>
:root {{
{_LIGHT_RULES}
}}
[data-theme="dark"] {{
{_DARK_RULES}
}}
.codehilite {{
    background: var(--code-bg);
    border: 1px solid var(--border);
    border-radius: 6px;
    overflow-x: auto;
    margin: 12px 0;
}}
.codehilite table {{
    border-collapse: collapse;
    width: 100%;
    margin: 0;
}}
.codehilite td {{
    border: none;
    padding: 0;
    vertical-align: top;
}}
.codehilite td.linenos {{
    text-align: right;
    padding: 12px 10px;
    background: var(--code-bg);
    border-right: 1px solid var(--border);
    color: var(--muted);
    user-select: none;
    -webkit-user-select: none;
}}
.codehilite td.code pre,
.codehilite .linenodiv pre {{
    margin: 0;
    padding: 12px 14px;
    background: transparent;
    border: none;
    font-size: 13px;
    line-height: 1.6;
}}
.codehilite .linenodiv pre {{
    padding: 12px 0 12px 14px;
}}
.codehilite td.code pre code {{
    background: transparent;
    padding: 0;
    border: none;
    color: inherit;
}}
</style>
"""


def render_latex_head() -> str:
    """返回启用 LaTeX 渲染所需的 <head> 内容（KaTeX）"""
    from . import config
    if not config.LATEX_RENDER_ENABLED:
        return ""
    return (
        f'<link rel="stylesheet" href="{config.LATEX_CDN}/katex.min.css">\n'
        f'<script defer src="{config.LATEX_CDN}/katex.min.js"></script>\n'
        f'<script defer src="{config.LATEX_CDN}/contrib/auto-render.min.js"></script>\n'
        "<script>\n"
        "document.addEventListener('DOMContentLoaded', function() {\n"
        "    renderMathInElement(document.body, {\n"
        "        delimiters: [\n"
        "            {left: '$$', right: '$$', display: true},\n"
        "            {left: '$', right: '$', display: false},\n"
        "            {left: '\\\\(', right: '\\\\)', display: false},\n"
        "            {left: '\\\\[', right: '\\\\]', display: true}\n"
        "        ],\n"
        "        throwOnError: false\n"
        "    });\n"
        "});\n"
        "</script>\n"
    )


def read_disclaimer(lang: str) -> str:
    """读取免责声明文件并渲染为 HTML"""
    import os
    from . import config
    from .i18n import t
    file_name = "Disclaimer-en.md" if lang == "en" else "Disclaimer.md"
    if os.path.exists(file_name):
        try:
            with open(file_name, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception as e:
            content = t(lang, "disclaimer_read_error", e=e)
    else:
        content = t(lang, "disclaimer_not_found")
    if config.MARKDOWN_AVAILABLE and config.BLEACH_AVAILABLE:
        return render_markdown_html(content)
    return content