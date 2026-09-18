"""首页、统计、免责声明"""
from flask import Blueprint, g, redirect, render_template, request, url_for

from .. import config
from ..extensions import cache
from ..feature_flags import feature_enabled, get_all_features, is_admin
from ..i18n import t
from ..notes import generate_random_id, get_stats, search_user_notes
from ..todos import get_user_todos
from ..utils import format_size, format_note_time, read_disclaimer
from ._helpers import page_cache_key

bp = Blueprint("home", __name__)


@bp.route("/")
@cache.cached(timeout=config.CACHE_TIMEOUT_INDEX, make_cache_key=page_cache_key,
              # 简洁模式跳过首页；登录用户的工作台含实时统计/最近笔记，不缓存以保证数据新鲜
              unless=lambda: bool(getattr(g, "simple_mode", False))
              or bool(getattr(g, "current_user", None)))
def index():
    # 简洁模式（账号级偏好）：跳过首页直接进入编辑/公开笔记，减少干扰
    if getattr(g, "simple_mode", False):
        current_user = getattr(g, "current_user", None)
        if current_user:
            note_id = generate_random_id()
            return redirect(f"/user/{current_user}/{note_id}", code=302)
        return redirect("/world/", code=302)
    lang = getattr(g, "lang", "zh")
    current_user = getattr(g, "current_user", None)
    # 首页卡片按功能开关过滤（#90）：停用的功能不再展示入口
    if current_user:
        # 工作台（VSCode 欢迎页风格）：最近编辑 + TODO LIST
        cards = []
        quick_actions = []
        all_notes = search_user_notes(current_user, "")
        recent_notes = all_notes[:config.RECENT_NOTES_LIMIT]
        recent_shares = []
        note_count = len(all_notes)
        share_count = 0
        share_views = 0
        todos = get_user_todos(current_user)
    else:
        cards = []
        quick_actions = []
        note_count = 0
        share_count = 0
        share_views = 0
        todos = []
        if feature_enabled("world_notes"):
            cards.append(("/world/", "fa-globe", t(lang, "home_public_notes"), t(lang, "home_public_notes_desc")))
        cards.append(("/login", "fa-right-to-bracket", t(lang, "home_login"), t(lang, "home_login_desc")))
        if feature_enabled("open_register"):
            cards.append(("/register", "fa-user-plus", t(lang, "home_register"), t(lang, "home_register_desc")))
        cards.append(("/count", "fa-chart-simple", t(lang, "home_stats"), t(lang, "home_stats_desc")))
        recent_notes = []
        recent_shares = []
    todo_err_key = (request.args.get("todo_err") or "").strip()
    todo_err = t(lang, f"wb_todo_err_{todo_err_key}") if todo_err_key in (
        "empty", "too_long", "too_many", "storage") else ""
    return render_template("home.html", site_name=config.SITE_NAME or "如形の笔记", cards=cards,
                           recent_notes=recent_notes, recent_shares=recent_shares,
                           current_user=current_user, show_benben=feature_enabled("benben"),
                           quick_actions=quick_actions, note_count=note_count,
                           share_count=share_count, share_views=share_views,
                           todos=todos, todo_max_length=config.TODO_MAX_LENGTH,
                           todo_err=todo_err)


@bp.route("/count")
def count():
    pub_cnt, pub_size, priv_cnt, priv_size, user_cnt, benben_cnt = get_stats()
    # 功能状态区（#90）：启用的功能在数据汇总页呈现；对应统计卡片随开关隐藏
    user = getattr(g, "current_user", None)
    return render_template(
        "count.html",
        pub_cnt=pub_cnt, pub_size=format_size(pub_size),
        priv_cnt=priv_cnt, priv_size=format_size(priv_size),
        user_cnt=user_cnt, benben_cnt=benben_cnt,
        features=get_all_features(),
        show_public=feature_enabled("world_notes"),
        show_benben=feature_enabled("benben"),
        is_admin_page=bool(user and is_admin(user)),
    )


@bp.route("/disclaimer")
def disclaimer():
    lang = getattr(g, "lang", "zh")
    content = read_disclaimer(lang)
    return render_template("disclaimer.html", content=content)