"""多语言支持：语言检测（Cookie > Accept-Language）与翻译查找

- 语言偏好通过 Cookie `rusin-lang` 保存（值: zh / en）
- 未设置时根据 Accept-Language 判断，默认中文（zh）
- 所有翻译 key 必须在 STRINGS["zh"] 与 STRINGS["en"] 中成对存在
"""
import html

from flask import Flask, g, request

LANG_COOKIE = "rusin-lang"
LANGS = ("zh", "en")
DEFAULT_LANG = "zh"

# ---------- 翻译字典 ----------
STRINGS = {
    "zh": {
        # 导航栏
        "nav_user_prefix": "用户: ",
        "nav_anonymous": "匿名",
        "nav_my_notes": "我的笔记",
        "nav_new_note": "新建笔记",
        "nav_share_mgmt": "分享管理",
        "nav_benben": "犇犇",
        "nav_logout": "登出",
        "nav_register": "注册",
        "nav_login": "登录",
        "nav_stats": "统计",
        "nav_disclaimer": "免责声明",
        "lang_switch": "English",
        "theme_dark": "",
        "theme_light": "",
        # 首页
        "page_home": "首页",
        "home_tagline": "轻量级在线记事本：随手记录、即时分享、畅所欲言",
        "home_public_notes": "创建笔记",
        "home_public_notes_desc": "匿名创建公开笔记",
        "home_login": "登录",
        "home_login_desc": "登录以管理你的笔记",
        "home_register": "注册",
        "home_register_desc": "创建你的专属账号",
        "home_stats": "统计",
        "home_stats_desc": "查看全站数据统计",
        "home_benben": "犇犇",
        "home_benben_desc": "看看大家都在聊什么",
        "home_my_notes_desc": "管理你的全部私有笔记",
        "home_new_note_desc": "创建一篇新的笔记",
        "home_share_mgmt_desc": "管理你发布的分享链接",
        "home_github": "开源仓库",
        "home_github_desc": "本项目完全开源，欢迎 Star 与贡献",
        # 注册
        "register_title": "注册",
        "reg_username_label": "用户名",
        "reg_password_label": "密码",
        "reg_confirm_label": "确认密码",
        "reg_submit": "注册",
        "reg_have_account": "已有账号？登录",
        "err_username_reserved": "禁止使用该用户名，请更换其他用户名",
        "err_username_invalid": "用户名只能包含字母、数字、下划线、连字符",
        "err_password_mismatch": "两次密码不一致",
        "err_password_weak": "密码不符合要求：{req}",
        "err_username_taken": "用户名不可用",
        # 登录
        "login_title": "登录",
        "login_username": "用户名",
        "login_password": "密码",
        "login_submit": "登录",
        "login_no_account": "没有账号？注册",
        "err_login_failed": "用户名或密码错误",
        # 认证
        "auth_required_title": "需要登录",
        "auth_required_body": "请先 <a href=\"/login\">登录</a> 或 <a href=\"/register\">注册</a> 以访问您的私有笔记。",
        "auth_required_body_shares": "请先 <a href=\"/login\">登录</a> 或 <a href=\"/register\">注册</a> 以访问您的分享管理。",
        # 笔记列表
        "user_notes_title": "{username} 的笔记",
        "user_new_note": "+ 新建笔记",
        "user_no_notes": "还没有笔记，创建一个吧",
        # 统计
        "stats_title": "笔记统计",
        "stats_public": "公开笔记",
        "stats_total_size": "总大小: {size}",
        "stats_private": "私有笔记",
        "stats_users": "注册用户",
        "stats_users_detail": "已注册账号",
        "stats_benben": "犇犇动态",
        "stats_benben_detail": "已发布犇犇数",
        "back_home": "返回首页",
        # 免责声明
        "disclaimer_title": "免责声明",
        "disclaimer_none": "暂无，请联系站长添加",
        "disclaimer_not_found": "免责声明文件 (Disclaimer.md) 未找到。",
        "disclaimer_read_error": "读取免责声明文件失败: {e}",
        # 笔记编辑页
        "note_public_prefix": "公开笔记",
        "note_private_prefix": "私有笔记",
        "note_share_prefix": "分享笔记",
        "note_save_btn": " 保存",
        "note_save_hint": " 按 <kbd>Ctrl</kbd> + <kbd>S</kbd> 快速保存",
        "note_last_edited": "最后编辑：",
        "note_never_edited": "尚未编辑",
        "save_status_saving": " 保存中...",
        "save_status_saved": "已保存",
        "save_status_failed": " 保存失败 ({status})",
        "save_status_net_error": " 网络错误",
        "save_hint_saved": " 已保存！按 <kbd>Ctrl</kbd> + <kbd>S</kbd> 再次保存",
        "save_hint_retry": " 保存失败，请重试",
        "save_failed_msg": " 保存失败：",
        # Markdown 只读页
        "md_readonly": "只读",
        "md_back_edit": "返回编辑",
        "md_back_share": "返回分享",
        "md_refresh": "刷新",
        "md_home": "首页",
        # 大纲预览（Markdown 只读页目录导航）
        "outline_label": "大纲",
        "outline_show": "显示大纲",
        "outline_hide": "收起大纲",
        # 分享管理
        "shares_title": "分享管理",
        "shares_create": "创建分享",
        "shares_select_note": "选择要分享的笔记",
        "shares_no_notes": "（暂无笔记，请先创建笔记）",
        "shares_editable_label": "允许编辑（访客保存将修改我的原笔记）",
        "shares_create_btn": "创建分享",
        "shares_my": "我的分享（{count}）",
        "shares_col_note": "笔记",
        "shares_col_link": "分享链接",
        "shares_col_perm": "权限",
        "shares_col_views": "查看次数",
        "shares_col_action": "操作",
        "shares_editable": "可编辑",
        "shares_readonly": "只读",
        "shares_delete": "删除",
        "shares_empty": "还没有分享链接，创建第一个吧",
        "shares_back": "返回我的笔记",
        "err_share_invalid_note": "请选择有效的笔记",
        "err_share_note_missing": "笔记不存在，请选择已有的笔记",
        "err_share_delete": "删除失败：分享不存在或无权删除",
        "err_url_invalid": "URL 不合法",
        "share_edit_hint": " 可编辑分享：保存后将写入分享者原笔记",
        # 犇犇
        "benben_title": "犇犇",
        "benben_page_info": "第 {page} 页 · 每页 {size} 条",
        "benben_label": "发布犇犇（支持 Markdown 与 LaTeX 公式，输入即预览，最多 {max} 字符）",
        "benben_submit": "发布",
        "benben_readonly": "登录后可发布犇犇，当前为只读模式",
        "benben_empty": "还没有犇犇，快来发布第一条吧",
        "benben_more": "加载更多（更早）",
        "benben_no_more": "没有更多了",
        "err_benben_empty": "内容不能为空",
        "err_benben_too_long": "内容超出长度限制（最多 {max} 字符）",
        "err_benben_cooldown": "发布过于频繁，请 {sec} 秒后再试",
        "preview_load_failed": "预览库加载失败",
        "preview_render_failed": "预览渲染失败",
        "note_live_preview": "实时渲染",
        "note_live_preview_hint": "实时渲染已关闭，点击此处开启",
        "md_manual": "Markdown 使用手册",
        "note_editor_label": "编辑器",
        "note_preview_label": "预览",
        "preview_show": "预览",
        "preview_edit": "编辑",
        "note_refs_label": "引用笔记",
        "note_refs_recent": "最近编辑",
        "note_refs_no_match": "没有匹配的笔记",
        # 笔记标签
        "note_tags_label": "标签",
        "note_tags_placeholder": "添加标签，逗号分隔",
        "note_tags_all": "全部",
        "note_tags_no_match": "该标签下没有笔记",
        # 笔记文件夹
        "note_folders_label": "文件夹",
        "note_folders_placeholder": "文件夹名，留空不归类",
        "note_folders_no_match": "该文件夹下没有笔记",
        # 笔记置顶
        "note_pins_toggle": "置顶 / 取消置顶",
        # 功能开关（#90）
        "feature_world_notes": "公开笔记",
        "feature_benben": "犇犇动态",
        "feature_share_links": "分享链接",
        "feature_open_register": "开放注册",
        "feature_note_refs": "笔记快捷引用",
        "feature_note_tags": "笔记标签",
        "feature_note_folders": "笔记文件夹",
        "feature_note_pins": "笔记置顶",
        "feature_latex_render": "LaTeX 公式渲染",
        "feature_code_highlight": "代码高亮",
        "feature_avatar": "用户头像",
        "features_status_title": "功能状态",
        "features_status_desc": "站点当前启用 / 停用的功能（由管理员配置）",
        "feature_on": "已启用",
        "feature_off": "已停用",
        "admin_features_title": "功能开关管理",
        "admin_features_desc": "通过滑块开关启用或停用站点功能，保存后立即生效，启用中的功能会在统计页呈现",
        "admin_features_submit": "保存设置",
        "admin_features_saved": "设置已保存",
        "admin_features_link": "管理功能开关",
    },
    "en": {
        # Navbar
        "nav_user_prefix": "User: ",
        "nav_anonymous": "Anonymous",
        "nav_my_notes": "My Notes",
        "nav_new_note": "New Note",
        "nav_share_mgmt": "Shares",
        "nav_benben": "Benben",
        "nav_logout": "Logout",
        "nav_register": "Register",
        "nav_login": "Log In",
        "nav_stats": "Stats",
        "nav_disclaimer": "Disclaimer",
        "lang_switch": "简体中文",
        "theme_dark": "",
        "theme_light": "",
        # Home
        "page_home": "Home",
        "home_tagline": "A lightweight online notepad: jot it down, share instantly, speak freely",
        "home_public_notes": "Public Note (Anonymous)",
        "home_public_notes_desc": "Browse public notes anonymously",
        "home_register": "Sign Up",
        "home_register_desc": "Create your own account",
        "home_login": "Log In",
        "home_login_desc": "Log in to manage your notes",
        "home_stats": "Stats",
        "home_stats_desc": "View site-wide statistics",
        "home_disclaimer": "Disclaimer",
        "home_disclaimer_desc": "Read the terms and disclaimer",
        "home_benben": "Benben",
        "home_benben_desc": "See what everyone is talking about",
        "home_my_notes_desc": "Manage all your private notes",
        "home_new_note_desc": "Create a new note",
        "home_share_mgmt_desc": "Manage the share links you publish",
        "home_github": "Open Source",
        "home_github_desc": "Fully open source. Star it and contribute!",
        # Register
        "register_title": "Register",
        "reg_username_label": "Username",
        "reg_password_label": "Password",
        "reg_confirm_label": "Confirm Password",
        "reg_submit": "Register",
        "reg_have_account": "Already have an account? Log in",
        "err_username_reserved": "This username is reserved, please choose another",
        "err_username_invalid": "Username may only contain letters, digits, underscores and hyphens",
        "err_password_mismatch": "Passwords do not match",
        "err_password_weak": "Password does not meet requirements: {req}",
        "err_username_taken": "Username unavailable",
        # Login
        "login_title": "Log In",
        "login_username": "Username",
        "login_password": "Password",
        "login_submit": "Log In",
        "login_no_account": "No account? Register",
        "err_login_failed": "Invalid username or password",
        # Auth
        "auth_required_title": "Login Required",
        "auth_required_body": "Please <a href=\"/login\">log in</a> or <a href=\"/register\">register</a> to access your private notes.",
        "auth_required_body_shares": "Please <a href=\"/login\">log in</a> or <a href=\"/register\">register</a> to access your share management.",
        # Note list
        "user_notes_title": "{username}'s Notes",
        "user_new_note": "+ New Note",
        "user_no_notes": "No notes yet, create one",
        # Stats
        "stats_title": "Note Statistics",
        "stats_public": "Public Notes",
        "stats_total_size": "Total size: {size}",
        "stats_private": "Private Notes",
        "stats_users": "Registered Users",
        "stats_users_detail": "Registered accounts",
        "stats_benben": "Benben Posts",
        "stats_benben_detail": "Total posts published",
        "back_home": "Back to Home",
        # Disclaimer
        "disclaimer_title": "Disclaimer",
        "disclaimer_none": "None yet, contact the admin",
        "disclaimer_not_found": "Disclaimer file (Disclaimer.md) not found.",
        "disclaimer_read_error": "Failed to read disclaimer file: {e}",
        # Note editor
        "note_public_prefix": "Public Note",
        "note_private_prefix": "Private Note",
        "note_share_prefix": "Shared Note",
        "note_save_btn": " Save",
        "note_save_hint": " Press <kbd>Ctrl</kbd> + <kbd>S</kbd> to save",
        "note_last_edited": "Last edited: ",
        "note_never_edited": "Not edited yet",
        "save_status_saving": " Saving...",
        "save_status_saved": "Saved",
        "save_status_failed": " Save failed ({status})",
        "save_status_net_error": " Network error",
        "save_hint_saved": " Saved! Press <kbd>Ctrl</kbd> + <kbd>S</kbd> to save again",
        "save_hint_retry": " Save failed, please retry",
        "save_failed_msg": " Save failed: ",
        # Markdown read-only
        "md_readonly": "Read-only",
        "md_back_edit": "Back to edit",
        "md_back_share": "Back to share",
        "md_refresh": "Refresh",
        "md_home": "Home",
        # Outline preview (TOC navigation on the Markdown read-only page)
        "outline_label": "Outline",
        "outline_show": "Show outline",
        "outline_hide": "Hide outline",
        # Share management
        "shares_title": "Share Management",
        "shares_create": "Create Share",
        "shares_select_note": "Select a note to share",
        "shares_no_notes": "(No notes yet, create one first)",
        "shares_editable_label": "Allow editing (visitor saves will modify my original note)",
        "shares_create_btn": "Create Share",
        "shares_my": "My Shares ({count})",
        "shares_col_note": "Note",
        "shares_col_link": "Share Link",
        "shares_col_perm": "Permission",
        "shares_col_views": "Views",
        "shares_col_action": "Action",
        "shares_editable": "Editable",
        "shares_readonly": "Read-only",
        "shares_delete": "Delete",
        "shares_empty": "No shares yet, create one",
        "shares_back": "Back to My Notes",
        "err_share_invalid_note": "Please select a valid note",
        "err_share_note_missing": "Note does not exist, please select an existing one",
        "err_share_delete": "Delete failed: share not found or not yours",
        "err_url_invalid": "Invalid URL",
        "share_edit_hint": " Editable share: saves will be written back to the owner's note",
        # Benben
        "benben_title": "Benben",
        "benben_page_info": "Page {page} · {size} per page",
        "benben_label": "Post to Benben (Markdown & LaTeX supported, live preview, max {max} chars)",
        "benben_submit": "Post",
        "benben_readonly": "Log in to post; currently read-only",
        "benben_empty": "No posts yet, be the first!",
        "benben_more": "Load more (earlier)",
        "benben_no_more": "No more",
        "err_benben_empty": "Content cannot be empty",
        "err_benben_too_long": "Content exceeds the length limit (max {max} chars)",
        "err_benben_cooldown": "Posting too frequently, try again in {sec} seconds",
        "preview_load_failed": "Preview library failed to load",
        "preview_render_failed": "Preview rendering failed",
        "note_live_preview": "Live Render",
        "note_live_preview_hint": "Live preview is off · click to enable",
        "md_manual": "Markdown Guide",
        "note_editor_label": "Editor",
        "note_preview_label": "Preview",
        "preview_show": "Preview",
        "preview_edit": "Edit",
        "note_refs_label": "Reference a note",
        "note_refs_recent": "Recently edited",
        "note_refs_no_match": "No matching notes",
        # Note tags
        "note_tags_label": "Tags",
        "note_tags_placeholder": "Add tags, separated by commas",
        "note_tags_all": "All",
        "note_tags_no_match": "No notes with this tag",
        # Note folders
        "note_folders_label": "Folder",
        "note_folders_placeholder": "Folder name, empty for none",
        "note_folders_no_match": "No notes in this folder",
        # Note pinning
        "note_pins_toggle": "Pin / unpin",
        # Feature flags (#90)
        "feature_world_notes": "Public Notes",
        "feature_benben": "Benben Feed",
        "feature_share_links": "Share Links",
        "feature_open_register": "Open Registration",
        "feature_note_refs": "Note Quick References",
        "feature_note_tags": "Note Tags",
        "feature_note_folders": "Note Folders",
        "feature_note_pins": "Note Pinning",
        "feature_latex_render": "LaTeX Rendering",
        "feature_code_highlight": "Code Highlighting",
        "feature_avatar": "User Avatars",
        "features_status_title": "Feature Status",
        "features_status_desc": "Features currently enabled on this site (configured by the admin)",
        "feature_on": "Enabled",
        "feature_off": "Disabled",
        "admin_features_title": "Feature Flags",
        "admin_features_desc": "Toggle site features on or off with the switches. Changes take effect immediately; enabled features are shown on the stats page",
        "admin_features_submit": "Save",
        "admin_features_saved": "Settings saved",
        "admin_features_link": "Manage feature flags",
    },
}


def detect_lang(handler) -> str:
    """兼容旧 BaseHTTPRequestHandler 接口（保留供其他模块调用）"""
    cookie = handler.headers.get("Cookie", "")
    for pair in cookie.split(";"):
        pair = pair.strip()
        if pair.startswith("rusin-lang="):
            value = pair[len("rusin-lang="):].strip()
            if value in LANGS:
                return value
    accept = handler.headers.get("Accept-Language", "")
    first = accept.split(",")[0].strip().lower()
    if first.startswith("zh"):
        return "zh"
    if first.startswith("en"):
        return "en"
    return DEFAULT_LANG


def detect_lang_from_request() -> str:
    """Flask 请求上下文下的语言检测（Cookie > Accept-Language > 默认中文）"""
    cookie = request.headers.get("Cookie", "")
    for pair in cookie.split(";"):
        pair = pair.strip()
        if pair.startswith(f"{LANG_COOKIE}="):
            value = pair[len(LANG_COOKIE) + 1:].strip()
            if value in LANGS:
                return value
    accept = request.headers.get("Accept-Language", "")
    first = accept.split(",")[0].strip().lower()
    if first.startswith("zh"):
        return "zh"
    if first.startswith("en"):
        return "en"
    return DEFAULT_LANG


def register_i18n(app: Flask) -> None:
    """注册 Jinja2 全局上下文，使模板可直接用 {{ t('key') }} / {{ lang }} / {{ theme }} / {{ theme_script }} / {{ theme_vars }} / {{ current_user }} / {{ site_name }}"""
    from . import config as _cfg
    from .feature_flags import feature_enabled
    from .theme import THEME_VARS, get_theme_script
    from .utils import get_avatar_url, render_code_highlight_head, render_pygments_head

    @app.context_processor
    def inject_globals():
        lang = getattr(g, "lang", DEFAULT_LANG)
        return {
            "t": lambda key, **kw: t(lang, key, **kw),
            "lang": lang,
            "lang_switch_url": "/lang/" + ("en" if lang == "zh" else "zh"),
            "theme": getattr(g, "theme", None),
            "theme_script": get_theme_script(lang),
            "theme_vars": THEME_VARS,
            "pygments_head": render_pygments_head(),
            "current_user": getattr(g, "current_user", None),
            "site_name": _cfg.SITE_NAME,
            "code_highlight_head": render_code_highlight_head(),
            "get_avatar": get_avatar_url,
            "feature_enabled": feature_enabled,
        }


def t(lang: str, key: str, **fmt) -> str:
    """按语言取翻译；key 缺失时返回 key 本身（便于发现遗漏）"""
    text = STRINGS.get(lang, {}).get(key)
    if text is None:
        text = STRINGS.get(DEFAULT_LANG, {}).get(key, key)
    if fmt:
        try:
            return text.format(**fmt)
        except (KeyError, IndexError):
            return text
    return text


def get_lang_switch(lang: str) -> str:
    """导航栏语言切换链接（切换到另一种语言）"""
    target = "en" if lang == "zh" else "zh"
    return f'<a href="/lang/{target}"><i class="fa-solid fa-language" aria-hidden="true"></i>{html.escape(t(lang, "lang_switch"))}</a>'


def get_theme_labels_js(lang: str) -> str:
    """主题按钮文字映射（注入 THEME_SCRIPT 用）"""
    import json
    return json.dumps({
        "dark": t(lang, "theme_dark"),
        "light": t(lang, "theme_light"),
    }, ensure_ascii=False)
