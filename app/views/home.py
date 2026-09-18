"""首页、统计、免责声明"""
from flask import Blueprint, g, redirect, render_template, url_for

from .. import config
from ..extensions import cache
from ..feature_flags import feature_enabled, get_all_features, is_admin
from ..i18n import t
from ..notes import generate_random_id, get_stats, search_user_notes
from ..store import list_user_shares
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
        # 工作台：快捷入口 + 数据概览 + 最近笔记/分享
        cards = []
        quick_actions = [
            (f"/user/{current_user}/", "fa-file-lines", t(lang, "nav_my_notes")),
            (f"/user/{current_user}/new", "fa-square-plus", t(lang, "nav_new_note")),
        ]
        if feature_enabled("share_links"):
            quick_actions.append((f"/user/{current_user}/shares/", "fa-share-nodes", t(lang, "nav_share_mgmt")))
        if feature_enabled("benben"):
            quick_actions.append(("/benben", "fa-sticky-note", t(lang, "nav_benben")))
        quick_actions.append(("/count", "fa-chart-simple", t(lang, "nav_stats")))
        quick_actions.append((f"/user/{current_user}/settings", "fa-gear", t(lang, "nav_settings")))
        # 最近编辑的笔记（同时用于统计总数）
        all_notes = search_user_notes(current_user, "")
        recent_notes = all_notes[:config.RECENT_NOTES_LIMIT]
        # 最近分享的笔记
        my_shares = list_user_shares(current_user)
        my_shares.sort(key=lambda x: x[1].get("created_at", 0), reverse=True)
        recent_shares = []
        for token, share in my_shares[:config.RECENT_SHARES_LIMIT]:
            note_id = share.get("note_id", "")
            recent_shares.append({
                "token": token,
                "note_id": note_id,
                "views": share.get("views", 0),
                "editable": share.get("editable", False),
            })
        note_count = len(all_notes)
        share_count = len(my_shares)
        share_views = sum(int(s.get("views", 0) or 0) for _, s in my_shares)
    else:
        cards = []
        quick_actions = []
        note_count = 0
        share_count = 0
        share_views = 0
        if feature_enabled("world_notes"):
            cards.append(("/world/", "fa-globe", t(lang, "home_public_notes"), t(lang, "home_public_notes_desc")))
        cards.append(("/login", "fa-right-to-bracket", t(lang, "home_login"), t(lang, "home_login_desc")))
        if feature_enabled("open_register"):
            cards.append(("/register", "fa-user-plus", t(lang, "home_register"), t(lang, "home_register_desc")))
        cards.append(("/count", "fa-chart-simple", t(lang, "home_stats"), t(lang, "home_stats_desc")))
        recent_notes = []
        recent_shares = []
    return render_template("home.html", site_name=config.SITE_NAME or "如形の笔记", cards=cards,
                           recent_notes=recent_notes, recent_shares=recent_shares,
                           current_user=current_user, show_benben=feature_enabled("benben"),
                           quick_actions=quick_actions, note_count=note_count,
                           share_count=share_count, share_views=share_views)


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