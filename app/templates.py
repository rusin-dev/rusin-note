"""所有页面的 HTML 渲染（导航栏、通用模板、各页面、Markdown/LaTeX 渲染）"""
import html
import json
import os
import time

from . import config
from .i18n import detect_lang, get_lang_switch, t
from .notes import get_note_mtime, get_note_size, get_stats, list_user_notes
from .store import list_user_shares
from .theme import get_theme_script, get_theme_toggle_btn, THEME_VARS
from .logger import create_logger

logger = create_logger("templates")

# ---------- 导航栏 ----------
def get_navbar(handler, current_user=None) -> str:
    if current_user is None:
        current_user = handler.get_current_user()
    lang = detect_lang(handler)
    if current_user:
        return f"""
            <div class="navbar">
                <span class="user-info">{html.escape(t(lang, "nav_user_prefix") + current_user)}</span>
                <span class="nav-links">
                    <a href="/user/{html.escape(current_user)}/"><i class="fa-solid fa-file-lines" aria-hidden="true"></i>{t(lang, "nav_my_notes")}</a>
                    <a href="/user/{html.escape(current_user)}/new"><i class="fa-solid fa-square-plus" aria-hidden="true"></i>{t(lang, "nav_new_note")}</a>
                    <a href="/user/{html.escape(current_user)}/shares/"><i class="fa-solid fa-share-nodes" aria-hidden="true"></i>{t(lang, "nav_share_mgmt")}</a>
                    <a href="/benben"><i class="fa-solid fa-sticky-note" aria-hidden="true"></i>{t(lang, "nav_benben")}</a>
                    <a href="/logout"><i class="fa-solid fa-right-from-bracket" aria-hidden="true"></i>{t(lang, "nav_logout")}</a>
                    {get_lang_switch(lang)}
                    {get_theme_toggle_btn(lang, handler.get_theme())}
                </span>
            </div>
        """
    else:
        return f"""
            <div class="navbar">
                <span class="user-info">{t(lang, "nav_anonymous")}</span>
                <span class="nav-links">
                    <a href="/register"><i class="fa-solid fa-user-plus" aria-hidden="true"></i>{t(lang, "nav_register")}</a>
                    <a href="/login"><i class="fa-solid fa-right-to-bracket" aria-hidden="true"></i>{t(lang, "nav_login")}</a>
                    <a href="/benben"><i class="fa-solid fa-sticky-note" aria-hidden="true"></i>{t(lang, "nav_benben")}</a>
                    <a href="/count"><i class="fa-solid fa-chart-simple" aria-hidden="true"></i>{t(lang, "nav_stats")}</a>
                    <a href="/disclaimer"><i class="fa-solid fa-circle-info" aria-hidden="true"></i>{t(lang, "nav_disclaimer")}</a>
                    {get_lang_switch(lang)}
                    {get_theme_toggle_btn(lang, handler.get_theme())}
                </span>
            </div>
        """


# ---------- 通用 HTML 渲染 ----------
def render_base(handler, body: str, title="rusin-note", navbar=None, extra_head="", theme=None):
    if theme is None:
        theme = handler.get_theme()
    theme_attr = f' data-theme="{theme}"' if theme else ""
    if config.SITE_NAME:
        full_title = f"{title} | {config.SITE_NAME}"
    else:
        full_title = title
    if navbar is None:
        navbar = get_navbar(handler)
    return f"""<!DOCTYPE html>
<html{theme_attr}>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{html.escape(full_title)}</title>
    <link rel="icon" href="/favicon.ico" type="image/x-icon">
    <link rel="preload" href="https://cdn.jsdmirror.cn/npm/@fortawesome/fontawesome-free@6.5.2/webfonts/fa-solid-900.woff2" as="font" type="font/woff2" crossorigin>
    <link rel="preload" href="https://cdn.jsdmirror.cn/npm/@fortawesome/fontawesome-free@6.5.2/webfonts/fa-brands-400.woff2" as="font" type="font/woff2" crossorigin>
    <link rel="stylesheet" href="https://cdn.jsdmirror.cn/npm/@fortawesome/fontawesome-free@6.5.2/css/all.min.css" media="print" onload="this.media='all'">
    <noscript><link rel="stylesheet" href="https://cdn.jsdmirror.cn/npm/@fortawesome/fontawesome-free@6.5.2/css/all.min.css"></noscript>
    {get_theme_script(detect_lang(handler))}
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
        .navbar .nav-links i {{
            margin-right: 5px;
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
        .note-list .note-time {{ color: var(--muted); font-size: 13px; margin-left: 12px; }}
        .note-list .note-size {{ color: var(--muted); font-size: 13px; margin-left: 12px; }}
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
        .home-hero {{
            text-align: center;
            padding: 28px 8px 8px;
        }}
        .home-hero h1 {{
            border: none;
            font-size: 34px;
            font-weight: 600;
            background: linear-gradient(135deg, var(--hero-grad-a), var(--hero-grad-b));
            -webkit-background-clip: text;
            background-clip: text;
            -webkit-text-fill-color: transparent;
            color: transparent;
            padding-bottom: 0;
        }}
        .home-hero p {{
            color: var(--muted);
            margin-top: 10px;
            font-size: 15px;
        }}
        .home-grid {{
            list-style: none;
            padding: 0;
            margin-top: 28px;
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(250px, 1fr));
            gap: 16px;
        }}
        .home-card {{
            display: flex;
            align-items: center;
            gap: 14px;
            padding: 18px 20px;
            background: var(--card-bg);
            border: 1px solid var(--card-border);
            border-radius: 12px;
            text-decoration: none;
            color: var(--text);
            transition: transform 0.18s ease, box-shadow 0.18s ease, border-color 0.18s ease;
        }}
        .home-card:hover {{
            transform: translateY(-3px);
            border-color: var(--hover);
            box-shadow: var(--card-shadow);
        }}
        .home-card:active {{
            transform: translateY(-1px) scale(0.99);
        }}
        .home-card:focus-visible {{
            outline: 2px solid var(--link);
            outline-offset: 2px;
        }}
        .home-card-icon {{
            flex-shrink: 0;
            width: 46px;
            height: 46px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 20px;
            color: #546271;
            background: var(--card-icon-bg);
            border-radius: 10px;
            transition: transform 0.18s ease, background 0.18s ease;
        }}
        .home-card:hover .home-card-icon {{
            transform: scale(1.1);
        }}
        .home-card-body {{
            flex: 1;
            min-width: 0;
        }}
        .home-card-title {{
            display: block;
            font-size: 16px;
            font-weight: 600;
        }}
        .home-card-desc {{
            display: block;
            color: var(--muted);
            font-size: 13px;
            margin-top: 4px;
            line-height: 1.4;
        }}
        .home-card-arrow {{
            flex-shrink: 0;
            color: var(--muted);
            font-size: 14px;
            transition: transform 0.18s ease, color 0.18s ease;
        }}
        .home-card:hover .home-card-arrow {{
            transform: translateX(4px);
            color: var(--hover);
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
def format_size(size) -> str:
    """将字节数格式化为人类可读大小（B/KB/MB/GB，保留两位小数）"""
    if not isinstance(size, (int, float)) or size < 0:
        return ""
    if size < 1024:
        return f"{size} B"
    elif size < 1024 * 1024:
        return f"{size / 1024:.2f} KB"
    elif size < 1024 * 1024 * 1024:
        return f"{size / (1024 * 1024):.2f} MB"
    else:
        return f"{size / (1024 * 1024 * 1024):.2f} GB"


def render_home(handler):
    lang = detect_lang(handler)
    current_user = handler.get_current_user()

    if current_user:
        # 已登录用户：直接进入个人功能，登录/注册入口不再展示
        links = [
            ("/user/" + html.escape(current_user) + "/", "fa-file-lines", t(lang, "nav_my_notes"), t(lang, "home_my_notes_desc")),
            ("/user/" + html.escape(current_user) + "/new", "fa-square-plus", t(lang, "nav_new_note"), t(lang, "home_new_note_desc")),
            ("/user/" + html.escape(current_user) + "/shares/", "fa-share-nodes", t(lang, "nav_share_mgmt"), t(lang, "home_share_mgmt_desc")),
            ("/benben", "fa-sticky-note", t(lang, "home_benben"), t(lang, "home_benben_desc")),
            ("/count", "fa-chart-simple", t(lang, "home_stats"), t(lang, "home_stats_desc")),
        ]
    else:
        links = [
            ("/world/", "fa-globe", t(lang, "home_public_notes"), t(lang, "home_public_notes_desc")),
            ("/login", "fa-right-to-bracket", t(lang, "home_login"), t(lang, "home_login_desc")),
            ("/register", "fa-user-plus", t(lang, "home_register"), t(lang, "home_register_desc")),
            ("/benben", "fa-sticky-note", t(lang, "home_benben"), t(lang, "home_benben_desc")),
            ("/count", "fa-chart-simple", t(lang, "home_stats"), t(lang, "home_stats_desc")),
        ]

    cards = "".join(
        f"""
        <a class="home-card" href="{href}">
            <span class="home-card-icon"><i class="fa-solid {icon}" aria-hidden="true"></i></span>
            <span class="home-card-body">
                <span class="home-card-title">{title}</span>
                <span class="home-card-desc">{desc}</span>
            </span>
            <span class="home-card-arrow"><i class="fa-solid fa-arrow-right" aria-hidden="true"></i></span>
        </a>"""
        for href, icon, title, desc in links
    )

    cards += f"""
        <a class="home-card" href="https://github.com/rusin-dev/rusin-note" target="_blank" rel="noopener noreferrer">
            <span class="home-card-icon"><i class="fa-brands fa-github" aria-hidden="true"></i></span>
            <span class="home-card-body">
                <span class="home-card-title">{t(lang, "home_github")}</span>
                <span class="home-card-desc">{t(lang, "home_github_desc")}</span>
            </span>
            <span class="home-card-arrow"><i class="fa-solid fa-arrow-right" aria-hidden="true"></i></span>
        </a>"""

    body = f"""
        <div class="home-hero">
            <h1>{html.escape(config.SITE_NAME or "如形の笔记")}</h1>
            <p>{t(lang, "home_tagline")}</p>
        </div>
        <div class="home-grid">
            {cards}
        </div>
    """
    return render_base(handler, body, t(lang, "page_home"))


def render_register_form(handler, error=""):
    lang = detect_lang(handler)
    req_desc = config.get_password_requirements_description(lang)
    body = f"""
        <h1>{t(lang, "register_title")}</h1>
        {f'<p class="error">{html.escape(error)}</p>' if error else ''}
        <form method="POST" action="/register">
            <div class="form-group">
                <label>{t(lang, "reg_username_label")}</label>
                <input type="text" name="username" required pattern="[a-zA-Z0-9_\\-]+">
            </div>
            <div class="form-group">
                <label>{t(lang, "reg_password_label", req=req_desc)}</label>
                <input type="password" name="password" required>
            </div>
            <div class="form-group">
                <label>{t(lang, "reg_confirm_label")}</label>
                <input type="password" name="confirm" required>
            </div>
            <button type="submit">{t(lang, "reg_submit")}</button>
        </form>
        <p style="margin-top:12px;"><a href="/login">{t(lang, "reg_have_account")}</a></p>
    """
    return render_base(handler, body, t(lang, "register_title"))


def render_login_form(handler, error=""):
    lang = detect_lang(handler)
    body = f"""
        <h1>{t(lang, "login_title")}</h1>
        {f'<p class="error">{html.escape(error)}</p>' if error else ''}
        <form method="POST" action="/login">
            <div class="form-group">
                <label>{t(lang, "login_username")}</label>
                <input type="text" name="username" required>
            </div>
            <div class="form-group">
                <label>{t(lang, "login_password")}</label>
                <input type="password" name="password" required>
            </div>
            <button type="submit">{t(lang, "login_submit")}</button>
        </form>
        <p style="margin-top:12px;"><a href="/register">{t(lang, "login_no_account")}</a></p>
    """
    return render_base(handler, body, t(lang, "login_title"))


def render_user_list(handler, username: str, notes: list[str]):
    lang = detect_lang(handler)
    note_items = ""
    if notes:
        for nid in notes:
            mtime = get_note_mtime(username, nid)
            time_str = format_note_time(mtime) if mtime else ""
            time_html = f'<span class="note-time">{html.escape(time_str)}</span>' if time_str else ""
            size = get_note_size(username, nid)
            size_html = f'<span class="note-size">{html.escape(format_size(size))}</span>' if size is not None else ""
            note_items += (f'<li><a href="/user/{html.escape(username)}/{html.escape(nid)}">'
                           f'{html.escape(nid)}</a>{time_html}{size_html}</li>')
    else:
        note_items = f'<li class="empty">{t(lang, "user_no_notes")}</li>'
    body = f"""
        <h1>{t(lang, "user_notes_title", username=username)}</h1>
        <div style="margin-bottom: 16px;">
            <a href="/user/{html.escape(username)}/new">{t(lang, "user_new_note")}</a>
        </div>
        <ul class="note-list">
            {note_items}
        </ul>
    """
    navbar = get_navbar(handler, username)
    return render_base(handler, body, t(lang, "user_notes_title", username=username), navbar)


def render_count_page(handler):
    lang = detect_lang(handler)
    pub_cnt, pub_size, priv_cnt, priv_size, user_cnt, benben_cnt = get_stats()
    body = f"""
        <h1>{t(lang, "stats_title")}</h1>
        <div class="stat-grid">
            <div class="stat-card">
                <h3>{t(lang, "stats_public")}</h3>
                <div class="number">{pub_cnt}</div>
                <div class="detail">{t(lang, "stats_total_size", size=format_size(pub_size))}</div>
            </div>
            <div class="stat-card">
                <h3>{t(lang, "stats_private")}</h3>
                <div class="number">{priv_cnt}</div>
                <div class="detail">{t(lang, "stats_total_size", size=format_size(priv_size))}</div>
            </div>
            <div class="stat-card">
                <h3>{t(lang, "stats_users")}</h3>
                <div class="number">{user_cnt}</div>
                <div class="detail">{t(lang, "stats_users_detail")}</div>
            </div>
            <div class="stat-card">
                <h3>{t(lang, "stats_benben")}</h3>
                <div class="number">{benben_cnt}</div>
                <div class="detail">{t(lang, "stats_benben_detail")}</div>
            </div>
        </div>
        <p style="margin-top: 24px;"><a href="/">{t(lang, "back_home")}</a></p>
    """
    return render_base(handler, body, t(lang, "stats_title"))


def render_disclaimer(handler):
    """读取 Disclaimer.md 并渲染为 HTML（支持 Markdown）"""
    lang = detect_lang(handler)
    disclaimer_file = "Disclaimer-en.md" if lang == "en" else "Disclaimer.md"
    if os.path.exists(disclaimer_file):
        try:
            with open(disclaimer_file, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception as e:
            content = t(lang, "disclaimer_read_error", e=e)
    else:
        content = t(lang, "disclaimer_not_found")

    # 尝试使用 markdown 库渲染（同样需要安全清洗，但此处内容由管理员控制，风险较低，不过仍建议统一使用安全渲染）
    if config.MARKDOWN_AVAILABLE and config.BLEACH_AVAILABLE:
        html_content = render_markdown_html(content)
        body = f"""
            <div class="disclaimer markdown-body">{html_content}</div>
            <p style="margin-top: 20px;"><a href="/">{t(lang, "back_home")}</a></p>
        """
        return render_base(handler, body, t(lang, "disclaimer_title"), extra_head=get_latex_head())

    # 降级：纯文本（安全）
    body = f"""
        <h1>{t(lang, "disclaimer_title")}</h1>
        <p>{t(lang, "disclaimer_none")}</p>
        <div class="disclaimer">{html.escape(content)}</div>
        <p style="margin-top: 20px;"><a href="/">{t(lang, "back_home")}</a></p>
    """
    return render_base(handler, body, t(lang, "disclaimer_title"))


def format_note_time(mtime) -> str:
    """将 epoch 秒格式化为本地时间字符串 YYYY-MM-DD HH:MM:SS"""
    if not mtime:
        return ""
    try:
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(mtime))
    except (ValueError, OverflowError, OSError):
        return ""


def render_note_page(handler, note_id: str, content: str, username: str = None, is_world: bool = False,
                     action_url: str = None, navbar: str = None, title_prefix: str = None,
                     hint_text: str = None, theme=None, mtime=None):
    lang = detect_lang(handler)
    escaped_id = html.escape(note_id)
    escaped_content = html.escape(content)

    # ---- 生成标题 ----
    if title_prefix is None:
        title_prefix = t(lang, "note_public_prefix") if is_world else t(lang, "note_private_prefix")
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
        hint_text = t(lang, "note_save_hint")
    if theme is None:
        theme = handler.get_theme()
    theme_attr = f' data-theme="{theme}"' if theme else ""
    save_btn_label = t(lang, "note_save_btn")
    if mtime:
        last_edited = f'{t(lang, "note_last_edited")}{format_note_time(mtime)}'
    else:
        last_edited = t(lang, "note_never_edited")
    l10n = json.dumps({
        "saving": t(lang, "save_status_saving"),
        "saved": t(lang, "save_status_saved"),
        "failedStatus": t(lang, "save_status_failed"),
        "netError": t(lang, "save_status_net_error"),
        "savedHint": t(lang, "save_hint_saved"),
        "retryHint": t(lang, "save_hint_retry"),
        "failedMsg": t(lang, "save_failed_msg"),
    }, ensure_ascii=False)

    page = f"""<!DOCTYPE html>
<html{theme_attr}>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{html.escape(full_title)}</title>
    <link rel="preload" href="https://cdn.jsdmirror.cn/npm/@fortawesome/fontawesome-free@6.5.2/webfonts/fa-solid-900.woff2" as="font" type="font/woff2" crossorigin>
    <link rel="preload" href="https://cdn.jsdmirror.cn/npm/@fortawesome/fontawesome-free@6.5.2/webfonts/fa-brands-400.woff2" as="font" type="font/woff2" crossorigin>
    <link rel="stylesheet" href="https://cdn.jsdmirror.cn/npm/@fortawesome/fontawesome-free@6.5.2/css/all.min.css" media="print" onload="this.media='all'">
    <noscript><link rel="stylesheet" href="https://cdn.jsdmirror.cn/npm/@fortawesome/fontawesome-free@6.5.2/css/all.min.css"></noscript>
    {get_theme_script(lang)}
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
        .navbar .nav-links i {{
            margin-right: 5px;
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
        .note-mtime {{
            position: fixed;
            bottom: 24px;
            left: 24px;
            font-size: 12px;
            color: var(--muted);
            z-index: 10;
            user-select: none;
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
            .note-mtime {{
                bottom: 16px;
                left: 16px;
                font-size: 11px;
            }}
        }}
    </style>
</head>
<body>
    {navbar}
    <form method="POST" action="{action_url}" id="noteForm">
        <textarea name="content" id="noteContent" autofocus spellcheck="true">{escaped_content}</textarea>
        <button type="button" class="save-btn" id="saveBtn">{save_btn_label}</button>
    </form>
    <div class="save-hint" id="saveHint">
        {hint_text}
    </div>
    <div class="save-status" id="saveStatus"></div>
    <div class="note-mtime" id="noteMtime">{html.escape(last_edited)}</div>

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
            const L10N = {l10n};

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
                showStatus(L10N.saving, 'saving');
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
                        showStatus(L10N.saved, '');
                        showHint(L10N.savedHint);
                    }} else {{
                        showStatus(L10N.failedStatus.replace('{{status}}', response.status), 'error');
                        showHint(L10N.retryHint);
                    }}
                }})
                .catch(error => {{
                    isSaving = false;
                    showStatus(L10N.netError, 'error');
                    showHint(L10N.failedMsg + error.message);
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


# ---------- 只读 Markdown 渲染（安全清洗，犇犇/笔记通用） ----------
def render_markdown_html(content: str) -> str:
    """
    将 Markdown 安全渲染为 HTML。
    使用 bleach 清洗 HTML，防止 XSS；依赖缺失或渲染失败时降级为纯文本。
    """
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
            return config.bleach.clean(raw_html, tags=ALLOWED_TAGS, attributes=ALLOWED_ATTRS, strip=True)
        except Exception:
            pass  # 渲染失败，降级为纯文本
    return f"<pre>{html.escape(content)}</pre>"


# ---------- 只读 Markdown 渲染页面 ----------
def render_markdown_page(handler, note_id: str, content: str, title_label: str = None,
                         back_url: str = None, back_label: str = None, navbar: str = None):
    """
    渲染笔记为 Markdown 只读页面（公开/私有/分享通用）。
    使用 bleach 清洗 HTML，防止 XSS。
    """
    lang = detect_lang(handler)
    html_content = render_markdown_html(content)

    if title_label is None:
        title_label = t(lang, "note_public_prefix")
    if back_label is None:
        back_label = t(lang, "md_back_edit")
    if back_url is None:
        back_url = f"/world/{note_id}"
    if navbar is None:
        navbar = get_navbar(handler)  # 匿名导航
    body = f"""
        <h1>{html.escape(title_label)} · {html.escape(note_id)} <span style="font-size:0.6em; font-weight:400; color:#888;">{t(lang, "md_readonly")}</span></h1>
        <div class="markdown-body" style="margin-top:20px; padding-bottom:40px;">
            {html_content}
        </div>
        <p style="margin-top: 20px;"><a href="{html.escape(back_url)}">{html.escape(back_label)}</a> · <a href="/">{t(lang, "md_home")}</a></p>
    """
    return render_base(handler, body, f"Markdown - {note_id}", navbar, extra_head=get_latex_head())


# ---------- 分享管理页面 ----------
def render_shares_page(handler, username: str, error=""):
    lang = detect_lang(handler)
    my_shares = list_user_shares(username)
    notes = list_user_notes(username)

    note_options = ""
    if notes:
        for nid in notes:
            note_options += f'<option value="{html.escape(nid)}">{html.escape(nid)}</option>'
    else:
        note_options = f'<option value="">{t(lang, "shares_no_notes")}</option>'

    rows = ""
    if my_shares:
        for tok, s in sorted(my_shares, key=lambda kv: kv[1].get("created_at", 0), reverse=True):
            nid = s.get("note_id", "")
            editable = t(lang, "shares_editable") if s.get("editable") else t(lang, "shares_readonly")
            rows += f"""
                <tr>
                    <td>{html.escape(nid)}</td>
                    <td><a class="share-link" href="/share/{tok}" target="_blank">/share/{tok}</a></td>
                    <td>{editable}</td>
                    <td>{s.get("views", 0)}</td>
                    <td>
                        <form method="POST" action="/user/{html.escape(username)}/shares/delete" style="display:inline;">
                            <input type="hidden" name="token" value="{tok}">
                            <button type="submit" class="btn-sm">{t(lang, "shares_delete")}</button>
                        </form>
                    </td>
                </tr>"""
    else:
        rows = f'<tr><td colspan="5" class="empty">{t(lang, "shares_empty")}</td></tr>'

    body = f"""
        <h1>{t(lang, "shares_title")}</h1>
        {f'<p class="error">{html.escape(error)}</p>' if error else ''}
        <div style="margin: 20px 0;">
            <h2 style="border:none; margin-bottom: 12px;">{t(lang, "shares_create")}</h2>
            <form method="POST" action="/user/{html.escape(username)}/shares/" style="max-width: 420px;">
                <div class="form-group">
                    <label>{t(lang, "shares_select_note")}</label>
                    <select name="note_id">{note_options}</select>
                </div>
                <div class="form-group" style="display:flex; align-items:center; gap:8px;">
                    <input type="checkbox" name="editable" value="1" id="editable_cb" style="width:auto;">
                    <label for="editable_cb" style="margin:0;">{t(lang, "shares_editable_label")}</label>
                </div>
                <button type="submit">{t(lang, "shares_create_btn")}</button>
            </form>
        </div>
        <h2 style="border:none; margin-bottom: 12px;">{t(lang, "shares_my", count=len(my_shares))}</h2>
        <table class="share-table">
            <thead>
                <tr><th>{t(lang, "shares_col_note")}</th><th>{t(lang, "shares_col_link")}</th><th>{t(lang, "shares_col_perm")}</th><th>{t(lang, "shares_col_views")}</th><th>{t(lang, "shares_col_action")}</th></tr>
            </thead>
            <tbody>{rows}</tbody>
        </table>
        <p style="margin-top: 24px;"><a href="/user/{html.escape(username)}/">{t(lang, "shares_back")}</a></p>
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
    return render_base(handler, body, t(lang, "shares_title"), navbar, extra_head=share_css)


# ---------- 可编辑分享页面 ----------
def render_share_edit_page(handler, token: str, note_id: str, content: str, owner: str):
    lang = detect_lang(handler)
    return render_note_page(
        handler, note_id, content,
        action_url=f"/share/{token}",
        navbar=get_navbar(handler),
        title_prefix=t(lang, "note_share_prefix"),
        hint_text=t(lang, "share_edit_hint"),
    )


# ---------- 犇犇（用户动态）页面 ----------
def render_benben_page(handler, posts, page, has_more, error="", prefill=""):
    """犇犇页面：登录可发布，未登录只读。posts 为（新→旧）的犇犇条目，每页 BENBEN_PAGE_SIZE 条。"""
    lang = detect_lang(handler)
    current_user = handler.get_current_user()

    items = ""
    for post in posts:
        if not isinstance(post, dict):
            continue
        username = post.get("username", "")
        content = render_markdown_html(post.get("content", ""))
        ts = post.get("time", 0)
        if isinstance(ts, (int, float)) and ts > 0:
            time_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))
        else:
            time_str = ""
        ip_html = ""
        items += f"""
            <div class="benben-post">
                <div class="benben-head">{html.escape(username)}<span class="benben-time">{time_str}</span>{ip_html}</div>
                <div class="benben-body markdown-body">{content}</div>
            </div>
        """
    if not items:
        items = f'<p class="empty">{t(lang, "benben_empty")}</p>'

    error_html = f'<p class="error">{html.escape(error)}</p>' if error else ""
    if current_user:
        form_area = f"""
            {error_html}
            <form method="POST" action="/benben" class="benben-form">
                <div class="form-group">
                    <label>{t(lang, "benben_label", max=config.BENBEN_MAX_LENGTH)}</label>
                    <textarea name="content" id="benbenInput" rows="4" maxlength="{config.BENBEN_MAX_LENGTH}">{html.escape(prefill)}</textarea>
                </div>
                <div id="benbenPreview" class="benben-preview markdown-body"></div>
                <button type="submit" style="width:auto;">{t(lang, "benben_submit")}</button>
            </form>
        """
    else:
        form_area = f"""
            <p style="color: var(--muted);">{t(lang, "benben_readonly")}</p>
            {error_html}
        """

    if has_more:
        more_link = f'<p class="benben-more"><a href="/benben?page={page + 1}">{t(lang, "benben_more")}</a></p>'
    else:
        more_link = f'<p class="benben-more empty">{t(lang, "benben_no_more")}</p>'

    body = f"""
        <h1>{t(lang, "benben_title")}</h1>
        <p style="color: var(--muted); margin: 12px 0 16px;">{t(lang, "benben_page_info", page=page, size=config.BENBEN_PAGE_SIZE)}</p>
        {form_area}
        <div class="benben-list">
            {items}
        </div>
        {more_link}
    """
    benben_css = _BENBEN_CSS_TEMPLATE.replace(
        "__BENBEN_MAX_HEIGHT_PX__", str(config.BENBEN_MAX_HEIGHT_PX)
    )
    # 犇犇发布预览：客户端 Markdown（marked.js）+ LaTeX 公式（KaTeX，依赖 latex_render 开关）实时渲染。
    # 渲染前对 marked 输出做轻量消毒（移除脚本类元素与事件属性），预览仅供本人查看，发布仍由服务端 bleach 清洗。
    preview_l10n = json.dumps({
        "loadFailed": t(lang, "preview_load_failed"),
        "renderFailed": t(lang, "preview_render_failed"),
    }, ensure_ascii=False)
    benben_preview_script = _BENBEN_PREVIEW_SCRIPT.replace(
        "var L10N = null; // __PREVIEW_L10N__",
        f"var L10N = {preview_l10n};",
    )
    navbar = get_navbar(handler, current_user)
    return render_base(handler, body, t(lang, "benben_title"), navbar,
                       extra_head=benben_css + get_latex_head() + benben_preview_script)


# 犇犇页面样式模板（静态字符串，max-height 通过占位符注入，避免 f-string 转义 CSS 花括号）
_BENBEN_CSS_TEMPLATE = """
        <style>
            .benben-post { border: 1px solid var(--card-border); border-radius: 8px; padding: 12px 16px; margin-bottom: 12px; background: var(--card-bg); }
            .benben-head { font-weight: 500; margin-bottom: 6px; }
            .benben-time { color: var(--muted); font-size: 13px; font-weight: 400; margin-left: 8px; }
            .benben-body { font-size: 15px; word-break: break-word; max-height: __BENBEN_MAX_HEIGHT_PX__px; overflow-y: auto; }
            .benben-form { max-width: 720px; margin: 16px 0 24px; }
            .benben-more { text-align: center; margin-top: 16px; }
            .benben-preview { border: 1px dashed var(--border); border-radius: 8px; padding: 12px 16px; margin-bottom: 16px; background: var(--card-bg); font-size: 15px; word-break: break-word; display: none; }
        </style>
    """


# 犇犇预览脚本模板（静态字符串，L10N 通过占位符注入，避免 f-string 转义 JS 花括号）
_BENBEN_PREVIEW_SCRIPT = """
<script defer src="https://cdn.jsdelivr.net/npm/marked@12.0.2/marked.min.js"></script>
<script>
document.addEventListener('DOMContentLoaded', function() {
    var L10N = null; // __PREVIEW_L10N__
    var ta = document.getElementById('benbenInput');
    var pre = document.getElementById('benbenPreview');
    if (!ta || !pre) return;
    var timer = null;
    function renderPreview() {
        var text = ta.value.trim();
        if (!text) { pre.style.display = 'none'; return; }
        if (!window.marked) { pre.textContent = L10N.loadFailed; pre.style.display = 'block'; return; }
        var html = '';
        try { html = window.marked.parse(text); } catch (e) { html = '<p class="error">' + L10N.renderFailed + '</p>'; }
        var tmp = document.createElement('div');
        tmp.innerHTML = html;
        tmp.querySelectorAll('script, iframe, object, embed, link, meta, style').forEach(function(el) { el.remove(); });
        tmp.querySelectorAll('*').forEach(function(el) {
            ['onerror','onclick','onload','onmouseover','onmouseout','onfocus','onblur','onchange','onsubmit'].forEach(function(a) { el.removeAttribute(a); });
        });
        tmp.querySelectorAll('a').forEach(function(a) {
            a.setAttribute('rel', 'noopener noreferrer');
            var href = a.getAttribute('href') || '';
            if (!/^(https?:|mailto:|#)/i.test(href)) a.removeAttribute('href');
        });
        pre.innerHTML = tmp.innerHTML;
        pre.style.display = 'block';
        if (window.renderMathInElement) {
            try {
                window.renderMathInElement(pre, {
                    delimiters: [
                        {left: '$$', right: '$$', display: true},
                        {left: '$', right: '$', display: false},
                        {left: '\\\\(', right: '\\\\)', display: false},
                        {left: '\\\\[', right: '\\\\]', display: true}
                    ],
                    throwOnError: false
                });
            } catch (e) {}
        }
    }
    ta.addEventListener('input', function() { clearTimeout(timer); timer = setTimeout(renderPreview, 300); });
    renderPreview();
});
</script>
"""
