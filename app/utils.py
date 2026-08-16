"""Markdown 安全渲染 + 文件大小/时间格式化（替代原 templates.py 的工具函数）"""
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
    """将 Markdown 安全渲染为 HTML（依赖 bleach 清洗防 XSS）"""
    from . import config
    if config.MARKDOWN_AVAILABLE and config.BLEACH_AVAILABLE:
        try:
            raw_html = config.markdown.markdown(
                content, extensions=['extra', 'codehilite']
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