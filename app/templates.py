"""所有页面的 HTML 渲染（导航栏、通用模板、各页面、Markdown/LaTeX 渲染）"""
import html
import json
import os

from . import config
from .notes import get_stats, list_user_notes
from .store import list_user_shares
from .theme import THEME_VARS, THEME_SCRIPT, THEME_TOGGLE_BTN


# ---------- 导航栏 ----------
def get_navbar(handler, current_user=None) -> str:
    if current_user is None:
        current_user = handler.get_current_user()
    if current_user:
        return f"""
            <div class="navbar">
                <span class="user-info">用户: {html.escape(current_user)}</span>
                <span class="nav-links">
                    <a href="/user/{html.escape(current_user)}/">我的笔记</a>
                    <a href="/user/{html.escape(current_user)}/new">新建笔记</a>
                    <a href="/user/{html.escape(current_user)}/shares/">分享管理</a>
                    <a href="/logout">登出</a>
                    {THEME_TOGGLE_BTN}
                </span>
            </div>
        """
    else:
        return f"""
            <div class="navbar">
                <span class="user-info">匿名</span>
                <span class="nav-links">
                    <a href="/register">注册</a>
                    <a href="/login">登录</a>
                    <a href="/count">统计</a>
                    <a href="/disclaimer">免责声明</a>
                    {THEME_TOGGLE_BTN}
                </span>
            </div>
        """


# ---------- 通用 HTML 渲染 ----------
def render_base(handler, body: str, title="rusin-note", navbar=None, extra_head=""):
    if config.SITE_NAME:
        full_title = f"{title} | {config.SITE_NAME}"
    else:
        full_title = title
    if navbar is None:
        navbar = get_navbar(handler)
    return f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{html.escape(full_title)}</title>
    <link rel="icon" href="/favicon.ico" type="image/x-icon">
    {THEME_SCRIPT}
<style>
        {THEME_VARS}
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: var(--bg); color: var(--text); }}
        .navbar {{
            background: var(--navbar-bg);
            padding: 10px 24px;
            border-bottom: 1px solid var(--navbar-border);
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            font-size: 14px;
        }}
        .navbar .user-info {{
            font-weight: 500;
        }}
        .navbar .nav-links a {{
            margin-left: 16px;
            color: var(--link);
            text-decoration: none;
        }}
        .navbar .nav-links a:hover {{
            text-decoration: underline;
        }}
        .theme-toggle {{
            width: auto;
            margin-left: 16px;
            padding: 4px 14px;
            font-size: 13px;
            border-radius: 14px;
        }}
        .container {{
            max-width: 900px;
            margin: 20px auto;
            padding: 0 20px;
        }}
        h1 {{ font-weight: 400; border-bottom: 1px solid var(--heading-border); padding-bottom: 10px; }}
        .form-group {{ margin-bottom: 16px; }}
        label {{ display: block; margin-bottom: 4px; font-weight: 500; }}
        input, button, textarea {{
            width: 100%;
            padding: 10px;
            font-size: 16px;
            box-sizing: border-box;
            border: 1px solid var(--border);
            border-radius: 4px;
            background: var(--input-bg);
            color: var(--text);
        }}
        button {{
            background: var(--btn-bg);
            cursor: pointer;
        }}
        button:hover {{ background: var(--btn-hover); }}
        .error {{ color: var(--error); }}
        .note-list {{ list-style: none; padding: 0; }}
        .note-list li {{ padding: 8px 0; border-bottom: 1px solid var(--list-border); }}
        .note-list a {{ color: var(--link); text-decoration: none; }}
        .note-list a:hover {{ text-decoration: underline; }}
        .empty {{ color: var(--muted); }}
        .stat-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
            margin-top: 20px;
        }}
        .stat-card {{
            border: 1px solid var(--card-border);
            border-radius: 8px;
            padding: 16px 20px;
            background: var(--card-bg);
        }}
        .stat-card h3 {{
            margin-bottom: 8px;
            font-weight: 400;
            color: var(--card-head);
        }}
        .stat-card .number {{
            font-size: 28px;
            font-weight: 500;
        }}
        .stat-card .detail {{
            color: var(--card-detail);
            font-size: 14px;
            margin-top: 4px;
        }}
        .disclaimer {{
            background: var(--disclaimer-bg);
            padding: 20px;
            border-radius: 8px;
            border: 1px solid var(--disclaimer-border);
        }}
        .markdown-body {{
            font-size: 16px;
            line-height: 1.6;
        }}
        .markdown-body h1, .markdown-body h2, .markdown-body h3 {{
            border-bottom: 1px solid var(--heading-border);
            padding-bottom: 6px;
        }}
        .markdown-body ul, .markdown-body ol {{
            padding-left: 2em;
        }}
        .markdown-body code {{
            background: var(--code-bg);
            padding: 2px 6px;
            border-radius: 4px;
        }}
        .markdown-body pre {{
            background: var(--code-bg);
            padding: 12px;
            border-radius: 4px;
            overflow-x: auto;
        }}
        .markdown-body blockquote {{
            border-left: 4px solid var(--quote-border);
            padding-left: 16px;
            color: var(--quote-text);
        }}
        .markdown-body a {{
            color: var(--link);
        }}
        .home-links {{
            list-style: none;
            padding: 0;
            margin-top: 24px;
        }}
        .home-links li {{
            margin: 12px 0;
        }}
        .home-links a {{
            font-size: 18px;
            color: var(--link);
            text-decoration: none;
        }}
        .home-links a:hover {{
            text-decoration: underline;
        }}
    </style>
    {extra_head}
</head>
<body>
    {navbar}
    <div class="container">
        {body}
    </div>
</body>
</html>"""


# ---------- 页面渲染 ----------
def render_home(handler):
    body = """
        <h1>rusin-note</h1>
        <ul class="home-links">
            <li><a href="/world/">公开笔记（匿名）</a></li>
            <li><a href="/register">注册账号</a></li>
            <li><a href="/login">登录</a></li>
            <li><a href="/count">统计</a></li>
            <li><a href="/disclaimer">免责声明</a></li>
        </ul>
    """
    return render_base(handler, body, "首页")


def render_register_form(handler, error=""):
    req_desc = config.get_password_requirements_description()
    body = f"""
        <h1>注册</h1>
        {f'<p class="error">{html.escape(error)}</p>' if error else ''}
        <form method="POST" action="/register">
            <div class="form-group">
                <label>用户名 (字母数字下划线连字符，不可使用 login/logout 等系统关键词)</label>
                <input type="text" name="username" required pattern="[a-zA-Z0-9_\\-]+">
            </div>
            <div class="form-group">
                <label>密码 (要求: {req_desc})</label>
                <input type="password" name="password" required>
            </div>
            <div class="form-group">
                <label>确认密码</label>
                <input type="password" name="confirm" required>
            </div>
            <button type="submit">注册</button>
        </form>
        <p style="margin-top:12px;"><a href="/login">已有账号？登录</a></p>
    """
    return render_base(handler, body, "注册")


def render_login_form(handler, error=""):
    body = f"""
        <h1>登录</h1>
        {f'<p class="error">{html.escape(error)}</p>' if error else ''}
        <form method="POST" action="/login">
            <div class="form-group">
                <label>用户名</label>
                <input type="text" name="username" required>
            </div>
            <div class="form-group">
                <label>密码</label>
                <input type="password" name="password" required>
            </div>
            <button type="submit">登录</button>
        </form>
        <p style="margin-top:12px;"><a href="/register">没有账号？注册</a></p>
    """
    return render_base(handler, body, "登录")


def render_user_list(handler, username: str, notes: list[str]):
    note_items = ""
    if notes:
        for nid in notes:
            note_items += f'<li><a href="/user/{html.escape(username)}/{html.escape(nid)}">{html.escape(nid)}</a></li>'
    else:
        note_items = '<li class="empty">还没有笔记，创建一个吧</li>'
    body = f"""
        <h1>{html.escape(username)} 的笔记</h1>
        <div style="margin-bottom: 16px;">
            <a href="/user/{html.escape(username)}/new">+ 新建笔记</a>
        </div>
        <ul class="note-list">
            {note_items}
        </ul>
    """
    navbar = get_navbar(handler, username)
    return render_base(handler, body, f"{username} 的笔记", navbar)


def render_count_page(handler):
    pub_cnt, pub_size, priv_cnt, priv_size, user_cnt = get_stats()

    def fmt_size(sz):
        if sz < 1024:
            return f"{sz} B"
        elif sz < 1024*1024:
            return f"{sz/1024:.2f} KB"
        elif sz < 1024*1024*1024:
            return f"{sz/(1024*1024):.2f} MB"
        else:
            return f"{sz/(1024*1024*1024):.2f} GB"

    body = f"""
        <h1>笔记统计</h1>
        <div class="stat-grid">
            <div class="stat-card">
                <h3>公开笔记</h3>
                <div class="number">{pub_cnt}</div>
                <div class="detail">总大小: {fmt_size(pub_size)}</div>
            </div>
            <div class="stat-card">
                <h3>私有笔记</h3>
                <div class="number">{priv_cnt}</div>
                <div class="detail">总大小: {fmt_size(priv_size)}</div>
            </div>
            <div class="stat-card">
                <h3>注册用户</h3>
                <div class="number">{user_cnt}</div>
                <div class="detail">已注册账号</div>
            </div>
        </div>
        <p style="margin-top: 24px;"><a href="/">返回首页</a></p>
    """
    return render_base(handler, body, "统计信息")


def render_disclaimer(handler):
    """读取 Disclaimer.md 并渲染为 HTML（支持 Markdown）"""
    disclaimer_file = "Disclaimer.md"
    if os.path.exists(disclaimer_file):
        try:
            with open(disclaimer_file, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception as e:
            content = f"读取免责声明文件失败: {e}"
    else:
        content = "免责声明文件 (Disclaimer.md) 未找到。"

    # 尝试使用 markdown 库渲染（同样需要安全清洗，但此处内容由管理员控制，风险较低，不过仍建议统一使用安全渲染）
    if config.MARKDOWN_AVAILABLE and config.BLEACH_AVAILABLE:
        try:
            raw_html = config.markdown.markdown(content, extensions=['extra', 'codehilite'])
            ALLOWED_TAGS = ['p', 'br', 'strong', 'em', 'u', 'strike', 'a', 'ul', 'ol', 'li', 'blockquote', 'pre', 'code', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'hr', 'table', 'thead', 'tbody', 'tr', 'th', 'td', 'div', 'span']
            ALLOWED_ATTRS = {'*': ['class'], 'a': ['href', 'title', 'target']}
            html_content = config.bleach.clean(raw_html, tags=ALLOWED_TAGS, attributes=ALLOWED_ATTRS, strip=True)
            body = f"""
                <div class="disclaimer markdown-body">{html_content}</div>
                <p style="margin-top: 20px;"><a href="/">返回首页</a></p>
            """
            return render_base(handler, body, "免责声明", extra_head=get_latex_head())
        except Exception:
            pass  # 降级到纯文本

    # 降级：纯文本（安全）
    body = f"""
        <h1>免责声明</h1>
        <p>暂无，请联系站长添加</p>
        <div class="disclaimer">{html.escape(content)}</div>
        <p style="margin-top: 20px;"><a href="/">返回首页</a></p>
    """
    return render_base(handler, body, "免责声明")


def render_note_page(handler, note_id: str, content: str, username: str = None, is_world: bool = False,
                     action_url: str = None, navbar: str = None, title_prefix: str = None,
                     hint_text: str = None):
    escaped_id = html.escape(note_id)
    escaped_content = html.escape(content)

    # ---- 生成标题 ----
    if title_prefix is None:
        title_prefix = "公开笔记" if is_world else "私有笔记"
    if config.SITE_NAME:
        full_title = f"{title_prefix} {escaped_id} | {config.SITE_NAME}"
    else:
        full_title = f"{title_prefix} {escaped_id}"
    # -----------------

    if action_url is None:
        action_url = f"/world/{escaped_id}" if is_world else f"/user/{html.escape(username)}/{escaped_id}"
    if navbar is None:
        navbar = get_navbar(handler) if is_world else get_navbar(handler, username)
    if hint_text is None:
        hint_text = ' 按 <kbd>Ctrl</kbd> + <kbd>S</kbd> 快速保存'

    page = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{html.escape(full_title)}</title>
    {THEME_SCRIPT}
    <style>
        {THEME_VARS}
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            background: var(--bg);
            color: var(--text);
            height: 100vh;
            overflow: hidden;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", sans-serif;
        }}
        .navbar {{
            background: var(--navbar-bg);
            padding: 8px 24px;
            border-bottom: 1px solid var(--navbar-border);
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            font-size: 14px;
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            z-index: 30;
        }}
        .navbar .user-info {{
            font-weight: 500;
        }}
        .navbar .nav-links a {{
            margin-left: 16px;
            color: var(--link);
            text-decoration: none;
        }}
        .navbar .nav-links a:hover {{
            text-decoration: underline;
        }}
        .theme-toggle {{
            width: auto;
            margin-left: 16px;
            padding: 4px 14px;
            font-size: 13px;
            border-radius: 14px;
            background: var(--btn-bg);
            border: 1px solid var(--navbar-border);
            color: var(--text);
            cursor: pointer;
        }}
        form {{
            height: 100vh;
            display: flex;
            flex-direction: column;
            padding-top: 50px;
        }}
        textarea {{
            flex: 1;
            width: 100%;
            border: none;
            padding: 20px 24px;
            font-size: 16px;
            line-height: 1.7;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", sans-serif;
            resize: none;
            outline: none;
            background: var(--bg);
            color: var(--text);
        }}
        .save-btn {{
            position: fixed;
            bottom: 24px;
            right: 24px;
            background: var(--btn-bg);
            border: 1px solid var(--navbar-border);
            padding: 8px 20px;
            border-radius: 20px;
            font-size: 14px;
            color: var(--text);
            cursor: pointer;
            backdrop-filter: blur(4px);
            transition: all 0.2s;
            z-index: 10;
            font-weight: 500;
        }}
        .save-btn:hover {{
            background: var(--btn-hover);
            transform: scale(1.02);
        }}
        .save-btn:active {{
            background: var(--border);
            transform: scale(0.98);
        }}
        .save-hint {{
            position: fixed;
            bottom: 80px;
            left: 50%;
            transform: translateX(-50%);
            background: rgba(0, 0, 0, 0.75);
            color: #fff;
            padding: 10px 24px;
            border-radius: 24px;
            font-size: 14px;
            letter-spacing: 0.5px;
            backdrop-filter: blur(8px);
            opacity: 0;
            transition: opacity 0.4s ease, transform 0.4s ease;
            pointer-events: none;
            z-index: 20;
            font-weight: 400;
            box-shadow: 0 4px 20px rgba(0,0,0,0.2);
        }}
        .save-hint.show {{
            opacity: 1;
            transform: translateX(-50%) translateY(0);
        }}
        .save-hint kbd {{
            background: rgba(255, 255, 255, 0.2);
            padding: 2px 12px;
            border-radius: 6px;
            margin: 0 4px;
            font-size: 13px;
            border: 1px solid rgba(255, 255, 255, 0.15);
            font-family: inherit;
        }}
        .save-status {{
            position: fixed;
            bottom: 80px;
            right: 24px;
            font-size: 14px;
            color: #4CAF50;
            opacity: 0;
            transition: opacity 0.3s ease, transform 0.3s ease;
            pointer-events: none;
            z-index: 15;
            background: var(--status-bg);
            padding: 6px 18px;
            border-radius: 16px;
            border: 1px solid #4CAF50;
            box-shadow: 0 2px 12px rgba(0,0,0,0.08);
            transform: translateY(10px);
        }}
        .save-status.show {{
            opacity: 1;
            transform: translateY(0);
        }}
        .save-status.saving {{
            color: #ff9800;
            border-color: #ff9800;
        }}
        .save-status.error {{
            color: #f44336;
            border-color: #f44336;
        }}
        @media (max-width: 640px) {{
            textarea {{
                padding: 16px 18px;
                font-size: 15px;
            }}
            .save-btn {{
                bottom: 16px;
                right: 16px;
                padding: 6px 16px;
                font-size: 13px;
            }}
            .save-hint {{
                bottom: 70px;
                padding: 8px 16px;
                font-size: 12px;
                white-space: nowrap;
            }}
            .save-status {{
                bottom: 70px;
                right: 16px;
                font-size: 12px;
                padding: 4px 14px;
            }}
        }}
    </style>
</head>
<body>
    {navbar}
    <form method="POST" action="{action_url}" id="noteForm">
        <textarea name="content" id="noteContent" autofocus spellcheck="true">{escaped_content}</textarea>
        <button type="button" class="save-btn" id="saveBtn"> 保存</button>
    </form>
    <div class="save-hint" id="saveHint">
         按 <kbd>Ctrl</kbd> + <kbd>S</kbd> 快速保存
    </div>
    <div class="save-status" id="saveStatus"></div>

    <script>
        (function() {{
            const form = document.getElementById('noteForm');
            const textarea = document.getElementById('noteContent');
            const saveBtn = document.getElementById('saveBtn');
            const saveHint = document.getElementById('saveHint');
            const saveStatus = document.getElementById('saveStatus');
            let saveTimeout = null;
            let statusTimeout = null;
            let hintTimeout = null;
            let isSaving = false;
            // BUG-12: 使用 json.dumps 生成合法的 JS 字符串字面量，防止 hint 含引号/反斜杠时破坏脚本或注入
            const DEFAULT_HINT = {json.dumps(hint_text, ensure_ascii=False)};

            // ADDED: Tab键插入4个空格
            textarea.addEventListener('keydown', function(e) {{
                if (e.key === 'Tab') {{
                    e.preventDefault();
                    const start = this.selectionStart;
                    const end = this.selectionEnd;
                    this.value = this.value.substring(0, start) + '    ' + this.value.substring(end);
                    this.selectionStart = this.selectionEnd = start + 4;
                }}
            }});

            function showHint(message) {{
                if (message) {{
                    saveHint.innerHTML = message;
                }}
                saveHint.classList.add('show');
                clearTimeout(hintTimeout);
                hintTimeout = setTimeout(function() {{
                    saveHint.classList.remove('show');
                }}, 4000);
            }}

            function showStatus(message, type = '') {{
                saveStatus.textContent = message;
                saveStatus.className = 'save-status show';
                if (type) {{
                    saveStatus.classList.add(type);
                }}
                clearTimeout(statusTimeout);
                statusTimeout = setTimeout(function() {{
                    saveStatus.classList.remove('show');
                }}, 2500);
            }}

            setTimeout(function() {{
                showHint(DEFAULT_HINT);
            }}, 600);

            let inputTimer = null;
            textarea.addEventListener('input', function() {{
                clearTimeout(inputTimer);
                inputTimer = setTimeout(function() {{
                    showHint(DEFAULT_HINT);
                }}, 3000);
            }});

            textarea.addEventListener('focus', function() {{
                showHint(DEFAULT_HINT);
            }});

            document.addEventListener('keydown', function(e) {{
                if ((e.ctrlKey || e.metaKey) && e.key === 's') {{
                    e.preventDefault();
                    saveNote();
                }}
                if (e.key === 'Escape') {{
                    saveHint.classList.remove('show');
                    saveStatus.classList.remove('show');
                }}
            }});

            saveBtn.addEventListener('click', function(e) {{
                e.preventDefault();
                saveNote();
            }});

            function saveNote() {{
                if (isSaving) return;
                isSaving = true;
                showStatus(' 保存中...', 'saving');
                const content = textarea.value;
                fetch(window.location.href, {{
                    method: 'POST',
                    headers: {{
                        'Content-Type': 'application/x-www-form-urlencoded',
                    }},
                    body: 'content=' + encodeURIComponent(content)
                }})
                .then(response => {{
                    isSaving = false;
                    if (response.ok) {{
                        showStatus('已保存', '');
                        showHint(' 已保存！按 <kbd>Ctrl</kbd> + <kbd>S</kbd> 再次保存');
                    }} else {{
                        showStatus(' 保存失败 (' + response.status + ')', 'error');
                        showHint(' 保存失败，请重试');
                    }}
                }})
                .catch(error => {{
                    isSaving = false;
                    showStatus(' 网络错误', 'error');
                    showHint(' 保存失败：' + error.message);
                }});
            }}

            function autoResize() {{
                textarea.style.height = 'auto';
                textarea.style.height = textarea.scrollHeight + 'px';
            }}
            setTimeout(autoResize, 100);
            textarea.addEventListener('input', autoResize);
        }})();
    </script>
</body>
</html>"""
    return page


# ---------- LaTeX 渲染（KaTeX 客户端渲染，洛谷同款） ----------
def get_latex_head() -> str:
    """返回启用 LaTeX 渲染所需的 <head> 内容（KaTeX：$...$ 行内 与 $$...$$ 块级公式）"""
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


# ---------- 只读 Markdown 渲染页面（安全清洗） ----------
def render_markdown_page(handler, note_id: str, content: str, title_label: str = "公开笔记",
                         back_url: str = None, back_label: str = "返回编辑", navbar: str = None):
    """
    渲染笔记为 Markdown 只读页面（公开/私有/分享通用）。
    使用 bleach 清洗 HTML，防止 XSS。
    """
    # 如果 markdown 和 bleach 都可用，则安全渲染
    if config.MARKDOWN_AVAILABLE and config.BLEACH_AVAILABLE:
        try:
            raw_html = config.markdown.markdown(content, extensions=['extra', 'codehilite'])
            # 定义白名单标签和属性
            ALLOWED_TAGS = [
                'p', 'br', 'strong', 'em', 'u', 'strike', 'a',
                'ul', 'ol', 'li', 'blockquote', 'pre', 'code',
                'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'hr',
                'table', 'thead', 'tbody', 'tr', 'th', 'td',
                'div', 'span'  # 允许容器标签
            ]
            ALLOWED_ATTRS = {
                '*': ['class'],          # 允许 class（用于代码高亮等）
                'a': ['href', 'title', 'target']
            }
            html_content = config.bleach.clean(raw_html, tags=ALLOWED_TAGS, attributes=ALLOWED_ATTRS, strip=True)
        except Exception:
            # 渲染失败，降级为纯文本
            html_content = f"<pre>{html.escape(content)}</pre>"
    else:
        # 缺少依赖，降级为纯文本（安全）
        html_content = f"<pre>{html.escape(content)}</pre>"

    if back_url is None:
        back_url = f"/world/{note_id}"
    if navbar is None:
        navbar = get_navbar(handler)  # 匿名导航
    body = f"""
        <h1>{html.escape(title_label)} · {html.escape(note_id)} <span style="font-size:0.6em; font-weight:400; color:#888;">只读</span></h1>
        <div class="markdown-body" style="margin-top:20px; padding-bottom:40px;">
            {html_content}
        </div>
        <p style="margin-top: 20px;"><a href="{html.escape(back_url)}">{html.escape(back_label)}</a> · <a href="/">首页</a></p>
    """
    return render_base(handler, body, f"Markdown - {note_id}", navbar, extra_head=get_latex_head())


# ---------- 分享管理页面 ----------
def render_shares_page(handler, username: str, error=""):
    my_shares = list_user_shares(username)
    notes = list_user_notes(username)

    note_options = ""
    if notes:
        for nid in notes:
            note_options += f'<option value="{html.escape(nid)}">{html.escape(nid)}</option>'
    else:
        note_options = '<option value="">（暂无笔记，请先创建笔记）</option>'

    rows = ""
    if my_shares:
        for tok, s in sorted(my_shares, key=lambda kv: kv[1].get("created_at", 0), reverse=True):
            nid = s.get("note_id", "")
            editable = "可编辑" if s.get("editable") else "只读"
            rows += f"""
                <tr>
                    <td>{html.escape(nid)}</td>
                    <td><a class="share-link" href="/share/{tok}" target="_blank">/share/{tok}</a></td>
                    <td>{editable}</td>
                    <td>{s.get("views", 0)}</td>
                    <td>
                        <form method="POST" action="/user/{html.escape(username)}/shares/delete" style="display:inline;">
                            <input type="hidden" name="token" value="{tok}">
                            <button type="submit" class="btn-sm">删除</button>
                        </form>
                    </td>
                </tr>"""
    else:
        rows = '<tr><td colspan="5" class="empty">还没有分享链接，创建第一个吧</td></tr>'

    body = f"""
        <h1>分享管理</h1>
        {f'<p class="error">{html.escape(error)}</p>' if error else ''}
        <div style="margin: 20px 0;">
            <h2 style="border:none; margin-bottom: 12px;">创建分享</h2>
            <form method="POST" action="/user/{html.escape(username)}/shares/" style="max-width: 420px;">
                <div class="form-group">
                    <label>选择要分享的笔记</label>
                    <select name="note_id">{note_options}</select>
                </div>
                <div class="form-group" style="display:flex; align-items:center; gap:8px;">
                    <input type="checkbox" name="editable" value="1" id="editable_cb" style="width:auto;">
                    <label for="editable_cb" style="margin:0;">允许编辑（访客保存将修改我的原笔记）</label>
                </div>
                <button type="submit">创建分享</button>
            </form>
        </div>
        <h2 style="border:none; margin-bottom: 12px;">我的分享（{len(my_shares)}）</h2>
        <table class="share-table">
            <thead>
                <tr><th>笔记</th><th>分享链接</th><th>权限</th><th>查看次数</th><th>操作</th></tr>
            </thead>
            <tbody>{rows}</tbody>
        </table>
        <p style="margin-top: 24px;"><a href="/user/{html.escape(username)}/">返回我的笔记</a></p>
    """
    # 分享页专用样式
    share_css = """
        <style>
            .share-table { width: 100%; border-collapse: collapse; margin-top: 8px; }
            .share-table th, .share-table td { border: 1px solid var(--navbar-border); padding: 8px 10px; text-align: left; font-size: 14px; word-break: break-all; }
            .share-table th { background: var(--navbar-bg); font-weight: 500; }
            .share-link { font-family: Consolas, monospace; font-size: 12px; color: var(--link); }
            .btn-sm { width: auto; padding: 4px 14px; font-size: 13px; }
            select { width: 100%; padding: 10px; font-size: 16px; border: 1px solid var(--border); border-radius: 4px; background: var(--input-bg); color: var(--text); }
        </style>
    """
    navbar = get_navbar(handler, username)
    return render_base(handler, body, "分享管理", navbar, extra_head=share_css)


# ---------- 可编辑分享页面 ----------
def render_share_edit_page(handler, token: str, note_id: str, content: str, owner: str):
    return render_note_page(
        handler, note_id, content,
        action_url=f"/share/{token}",
        navbar=get_navbar(handler),
        title_prefix="分享笔记",
        hint_text=' 可编辑分享：保存后将写入分享者原笔记',
    )
