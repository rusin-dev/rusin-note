"""Markdown 安全渲染（Pygments 高亮 + 行号）+ 文件大小/时间格式化（替代原 templates.py 的工具函数）"""
import hashlib
import html
import re
import time
import urllib.parse


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


def get_avatar_url(username: str) -> str:
    """按配置生成用户头像 URL；头像未启用或用户名为空时返回空串。

    url_template 支持 {hash}（md5(用户名)）与 {username}（URL 编码）占位符。
    """
    from . import config
    if not config.AVATAR_ENABLED or not username:
        return ""
    h = hashlib.md5(username.encode("utf-8")).hexdigest()
    name = urllib.parse.quote(username, safe="")
    return config.AVATAR_URL_TEMPLATE.format(hash=h, username=name)


# ---------- 笔记快捷引用（#87：GitHub Issues 风格的 # 引用） ----------
# 匹配 #<笔记ID> 形式的快捷引用。# 前面出现以下字符时不算引用：
#   ASCII 字母数字下划线 —— abc#def 中间的井号（普通文本 / hashtag 的一部分）；
#   注意用显式 [0-9A-Za-z_] 而非 \w：Python 的 \w 含中文，会把「参见#笔记」
#   误判为排除（JS 端 \w 本就只匹配 ASCII，改后两端行为一致）
#   #  —— ##Heading、##id（多级标题或转义后的井号）
#   "' —— HTML 属性 href="#x"、'#x' 中的锚点
#   ([ —— Markdown 链接 [text](#a) / 引用式链接 [text][#b] 的目标
#   /  —— URL 路径片段 /path#frag
#   \  —— 被反斜杠转义的 \#foo
_NOTE_REF_RE = re.compile(r'(?<![0-9A-Za-z_#"\'\(\[/\\])#([A-Za-z0-9][A-Za-z0-9_\-]*)')
# Markdown 链接定义行（[label]: url），井号是 URL 一部分，整行跳过
_NOTE_REF_LINK_DEF_RE = re.compile(r'^\s{0,3}\[[^\]]*\]:')
# 围栏代码块的开头（``` 或 ~~~，允许最多 3 个前导空格）
_FENCE_RE = re.compile(r'^\s{0,3}(`{3,}|~{3,})')
# 行内代码 span（`code` / ``code``），替换时跳过
_BACKTICK_SPAN_RE = re.compile(r'`+[^`]+?`+')


def expand_note_refs(content: str, namespace: str, url_prefix: str,
                     resolver) -> str:
    """把 Markdown 原文中代码区域之外的 ``#<笔记ID>`` 展开为 Markdown 链接。

    在 markdown 解析前对原文逐行扫描：跳过围栏代码块（``` / ~~~）、缩进
    代码块（空行后 4 空格缩进）、链接定义行，行内再跳过反引号代码 span，
    其余位置的 ``#id`` 若 resolver(id) 返回非 None（笔记存在）则替换为
    ``[#id](<url_prefix>/<id> "标题")``。这样行首的 ``#id`` 也不会被
    Python-Markdown 误判为 ATX 标题，且与编辑器实时预览行为一致。
    """
    if "#" not in content:
        return content

    def repl(m: re.Match) -> str:
        note_id = m.group(1)
        from . import config
        if len(note_id) > config.MAX_NOTE_ID_LENGTH:
            return m.group(0)
        title = resolver(note_id)
        if title is None:
            return m.group(0)
        # 标题进入 Markdown 链接的 title 部分，去掉会破坏语法的字符
        title = title.replace('"', "'").replace("(", "（").replace(")", "）").strip()
        suffix = f' "{title}"' if title else ""
        return f"[{m.group(0)}]({url_prefix}/{note_id}{suffix})"

    fence = ""          # 当前所处围栏代码块的围栏串（空 = 不在代码块内）
    prev_blank = True   # 上一行是否为空行（判断缩进代码块起始）
    out_lines: list[str] = []
    for line in content.split("\n"):
        m = _FENCE_RE.match(line)
        if fence:
            out_lines.append(line)
            # 同字符且长度不少于开栏围栏的行视为闭栏
            if m and m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence):
                fence = ""
            continue
        if m:
            fence = m.group(1)
            out_lines.append(line)
            continue
        if not line.strip():
            prev_blank = True
            out_lines.append(line)
            continue
        is_indented_code = prev_blank and (line.startswith("    ") or line.startswith("\t"))
        prev_blank = False
        if is_indented_code or _NOTE_REF_LINK_DEF_RE.match(line):
            out_lines.append(line)
            continue
        if "#" in line:
            parts: list[str] = []
            last = 0
            for span in _BACKTICK_SPAN_RE.finditer(line):
                parts.append(_NOTE_REF_RE.sub(repl, line[last:span.start()]))
                parts.append(span.group(0))  # 行内代码保持原样
                last = span.end()
            parts.append(_NOTE_REF_RE.sub(repl, line[last:]))
            line = "".join(parts)
        out_lines.append(line)
    return "\n".join(out_lines)


def _note_ref_resolver(namespace: str):
    """构造引用解析函数：返回目标笔记的标题（存在）或 None（不存在），
    同一次渲染内对相同 ID 只读一次存储。"""
    from .notes import read_note, title_from_content
    cache: dict[str, str | None] = {}

    def resolve(note_id: str) -> str | None:
        if note_id in cache:
            return cache[note_id]
        content = read_note(namespace, note_id)  # 空内容等价于不存在
        title = title_from_content(content) if content else None
        cache[note_id] = title
        return title

    return resolve


def render_markdown_html(content: str, ref_namespace: str | None = None,
                         ref_url_prefix: str | None = None) -> str:
    """将 Markdown 安全渲染为 HTML（依赖 bleach 清洗防 XSS）

    使用 extra 扩展（含 fenced_code）：代码块经 Pygments 分词后输出带
    ``<span class="nc">`` / ``<span class="nf">`` / ``<span class="nv">`` 等
    token 类的 HTML，使标识符着色规则（类名、函数名、变量名、装饰器、常量）生效。
    无法识别语言时回退到客户端 highlight.js。

    传入 ref_namespace（笔记所属命名空间：用户名或 "public"）与
    ref_url_prefix（引用链接前缀，如 "/user/alice" 或 "/world"）时，
    原文中的 ``#<笔记ID>`` 快捷引用会被展开为指向该笔记的链接（#87）。
    """
    from . import config
    if config.MARKDOWN_AVAILABLE and config.BLEACH_AVAILABLE:
        try:
            if ref_namespace and ref_url_prefix and config.NOTE_REFS_ENABLED:
                content = expand_note_refs(
                    content, ref_namespace, ref_url_prefix,
                    _note_ref_resolver(ref_namespace),
                )
            raw_html = config.markdown.markdown(
                content, extensions=['extra']
            )
            raw_html = _highlight_code_blocks(raw_html)
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


# ---------- Pygments 代码块高亮 ----------
# 匹配 markdown-extra 输出的 <pre><code class="language-xxx">...code...</code></pre>
_code_block_re = re.compile(
    r'<pre><code\s+class="language-([^"]+)"[^>]*>(.*?)</code></pre>',
    re.DOTALL,
)


def _highlight_code_blocks(html: str) -> str:
    """将 HTML 中的 fenced code block 用 Pygments 重新着色。

    无法识别语言时保留原样（交由客户端 highlight.js 处理）。
    """
    from pygments.lexers import get_lexer_by_name
    from pygments.formatters import HtmlFormatter

    def _replace(match: re.Match) -> str:
        lang = match.group(1).lower()
        code = match.group(2)
        # 转义 HTML 实体（markdown 输出中 &lt; 等已由 markdown 处理，此处取原始字符）
        try:
            lexer = get_lexer_by_name(lang)
        except Exception:
            return match.group(0)  # 无法识别语言，原样保留
        formatter = HtmlFormatter(style='default', nowrap=True)
        try:
            import io
            buf = io.StringIO()
            formatter.format(lexer.get_tokens(code), buf)
            highlighted = buf.getvalue()
        except Exception:
            return match.group(0)
        return f'<pre><code class="language-{lang}">{highlighted}</code></pre>'

    return _code_block_re.sub(_replace, html)


# Pygments 高亮样式缓存（亮/暗两套 CSS，生成后不再计算）
_LIGHT_RULES = None
_DARK_RULES = None

# Pygments Name 子类型（类、函数、变量、装饰器、常量等）的标识符着色规则。
# 亮/暗主题各有专属配色，通过 CSS 变量实现与站点主题联动。
# 规则覆盖在 Pygments 默认样式之上（优先级更高）。
_IDENT_RULES_LIGHT = """
/* 标识符着色（亮色主题）：类、函数、变量、装饰器、常量各有专属色 */
.codehilite .nc,
.codehilite .nn,
.codehilite .nd { color: #8250df; font-weight: 600; }   /* Name.Class / Namespace / Decorator */
.codehilite .nf,
.codehilite .fm { color: #0550ae; font-weight: 600; }   /* Name.Function / Magic */
.codehilite .nv,
.codehilite .vc,
.codehilite .vg,
.codehilite .vi,
.codehilite .vm { color: #0a3069; }                      /* Name.Variable (all variants) */
.codehilite .nb,
.codehilite .bp { color: #6e39e0; }                      /* Name.Builtin / Builtin.Pseudo */
.codehilite .no { color: #7c3aed; }                      /* Name.Constant */
.codehilite .na  { color: #0f6251; }                     /* Name.Attribute */
.codehilite .ne  { color: #c53033; font-weight: 600; }  /* Name.Exception */
"""

_IDENT_RULES_DARK = """
/* 标识符着色（暗色主题） */
.codehilite .nc,
.codehilite .nn,
.codehilite .nd { color: #d4b7ff; font-weight: 600; }
.codehilite .nf,
.codehilite .fm { color: #91bbfd; font-weight: 600; }
.codehilite .nv,
.codehilite .vc,
.codehilite .vg,
.codehilite .vi,
.codehilite .vm { color: #e2e8f0; }
.codehilite .nb,
.codehilite .bp { color: #c4b5fd; }
.codehilite .no { color: #a78bfa; }
.codehilite .na  { color: #38bdf8; }
.codehilite .ne  { color: #f87171; font-weight: 600; }
"""


def _pygments_rules(style: str) -> str:
    """按 pygments 样式生成 .codehilite 作用域下的 token 配色规则。
    丢弃前 5 行未作用域化的 pre/linenos 全局规则（由 render_pygments_head 自管）。"""
    from pygments.formatters import HtmlFormatter
    lines = HtmlFormatter(style=style, cssclass="codehilite").get_style_defs().splitlines()
    return "\n".join(lines[5:]) if len(lines) >= 5 else "\n".join(lines)


def render_pygments_head() -> str:
    """返回启用 Pygments 代码高亮所需的 <head> 内容（含亮/暗两套配色、行号容器样式，以及标识符着色规则）。
    标识符着色规则覆盖在 Pygments 默认样式之上，使类名、函数名、变量名等各有专属颜色。
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
{_IDENT_RULES_LIGHT}
}}
[data-theme="dark"] {{
{_DARK_RULES}
{_IDENT_RULES_DARK}
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
        "            function normalizeNewlines(html) {\n"
        "                var out = '';\n"
        "                var stack = [];\n"
        "                var i = 0;\n"
        "                while (i < html.length) {\n"
        "                    if (html.slice(i, i + 7) === '</span>') {\n"
        "                        if (stack.length) stack.pop();\n"
        "                        out += '</span>';\n"
        "                        i += 7;\n"
        "                    } else if (html.slice(i, i + 5) === '<span') {\n"
        "                        var end = html.indexOf('>', i);\n"
        "                        if (end === -1) { out += html.charAt(i); i++; continue; }\n"
        "                        var tag = html.slice(i, end + 1);\n"
        "                        stack.push(tag);\n"
        "                        out += tag;\n"
        "                        i = end + 1;\n"
        "                    } else if (html.charAt(i) === '\\n') {\n"
        "                        for (var k = 0; k < stack.length; k++) out += '</span>';\n"
        "                        out += '\\n';\n"
        "                        for (var k = 0; k < stack.length; k++) out += stack[k];\n"
        "                        i++;\n"
        "                    } else {\n"
        "                        out += html.charAt(i);\n"
        "                        i++;\n"
        "                    }\n"
        "                }\n"
        "                return out;\n"
        "            }\n"
        "            var lines = normalizeNewlines(block.innerHTML).split('\\n');\n"
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