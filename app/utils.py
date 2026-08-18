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
    """将 Markdown 安全渲染为 HTML（依赖 bleach 清洗防 XSS）

    使用 extra 扩展（含 fenced_code）：无 Pygments 时输出标准的
    <pre><code class="language-xxx"> 结构，供客户端 highlight.js 代码高亮识别。
    """
    from . import config
    if config.MARKDOWN_AVAILABLE and config.BLEACH_AVAILABLE:
        try:
            raw_html = config.markdown.markdown(
                content, extensions=['extra']
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


def render_code_highlight_head() -> str:
    """返回启用代码高亮所需的 <head> 内容（highlight.js + 代码行号，客户端渲染）。

    提供浅色（github）/ 暗色（github-dark）两套主题，跟随站点主题自动切换；
    暴露 window.CodeHighlight.apply(root) 供动态渲染的预览调用。
    """
    from . import config
    if not config.CODE_HIGHLIGHT_ENABLED:
        return ""
    cdn = config.CODE_HIGHLIGHT_CDN.rstrip("/")
    return (
        f'<link rel="stylesheet" href="{cdn}/styles/github.min.css" id="hljs-theme-light">\n'
        f'<link rel="stylesheet" href="{cdn}/styles/github-dark.min.css" id="hljs-theme-dark" disabled>\n'
        f'<script defer src="{cdn}/highlight.min.js"></script>\n'
        "<style>\n"
        ".markdown-body pre { position: relative; }\n"
        ".markdown-body pre code { display: block; background: transparent; padding: 0; font-size: 14px; line-height: 1.6; font-family: Consolas, Monaco, \"Courier New\", monospace; }\n"
        ".code-line { display: flex; }\n"
        ".code-line-num {\n"
        "    flex: 0 0 auto; min-width: 2.4em; text-align: right; padding-right: 10px; margin-right: 10px;\n"
        "    border-right: 1px solid var(--border); color: var(--muted);\n"
        "    user-select: none; -webkit-user-select: none;\n"
        "    position: sticky; left: 0; background: var(--code-bg);\n"
        "}\n"
        ".code-line-content { white-space: pre; }\n"
        "</style>\n"
        "<script>\n"
        "window.CodeHighlight = (function() {\n"
        "    function applyTheme() {\n"
        "        var t = document.documentElement.getAttribute('data-theme');\n"
        "        var dark = document.getElementById('hljs-theme-dark');\n"
        "        var light = document.getElementById('hljs-theme-light');\n"
        "        if (dark) dark.disabled = (t !== 'dark');\n"
        "        if (light) light.disabled = (t === 'dark');\n"
        "    }\n"
        "    function apply(root) {\n"
        "        if (!window.hljs) return;\n"
        "        var blocks = (root || document).querySelectorAll('pre code');\n"
        "        for (var i = 0; i < blocks.length; i++) {\n"
        "            var block = blocks[i];\n"
        "            if (block.getAttribute('data-ch-highlighted')) continue;\n"
        "            block.setAttribute('data-ch-highlighted', '1');\n"
        "            if (/(?:^|\\s)language-[\\w-]+/.test(block.className)) {\n"
        "                try { hljs.highlightElement(block); } catch (e) {}\n"
        "            }\n"
        "            var lines = block.innerHTML.split('\\n');\n"
        "            if (lines.length < 2) continue;\n"
        "            if (lines[lines.length - 1].trim() === '') lines.pop();\n"
        "            var out = '';\n"
        "            for (var j = 0; j < lines.length; j++) {\n"
        "                out += '<span class=\"code-line\"><span class=\"code-line-num\">' + (j + 1)\n"
        "                    + '</span><span class=\"code-line-content\">' + (lines[j] || '') + '</span></span>';\n"
        "            }\n"
        "            block.innerHTML = out;\n"
        "        }\n"
        "    }\n"
        "    applyTheme();\n"
        "    if (document.readyState === 'loading') {\n"
        "        document.addEventListener('DOMContentLoaded', function() { applyTheme(); apply(document); });\n"
        "    } else {\n"
        "        applyTheme(); apply(document);\n"
        "    }\n"
        "    if (window.MutationObserver) {\n"
        "        new MutationObserver(applyTheme).observe(document.documentElement, {\n"
        "            attributes: true, attributeFilter: ['data-theme']\n"
        "        });\n"
        "    }\n"
        "    return { apply: apply };\n"
        "})();\n"
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