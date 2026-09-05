"""首页、统计、免责声明"""
from flask import Blueprint, g, redirect, render_template, request

from .. import config
from ..extensions import cache
from ..feature_flags import feature_enabled, get_all_features, is_admin
from ..i18n import t
from ..notes import get_stats
from ..utils import format_size, read_disclaimer
from ._helpers import page_cache_key

bp = Blueprint("home", __name__)


@bp.route("/")
@cache.cached(timeout=config.CACHE_TIMEOUT_INDEX, make_cache_key=page_cache_key,
              unless=lambda: request.cookies.get("rusin-simple") == "1")
def index():
    if request.cookies.get("rusin-simple") == "1":
        return redirect("/world/", code=302)
    lang = getattr(g, "lang", "zh")
    current_user = getattr(g, "current_user", None)
    # 首页卡片按功能开关过滤（#90）：停用的功能不再展示入口
    if current_user:
        cards = [
            (f"/user/{current_user}/", "fa-file-lines", t(lang, "nav_my_notes"), t(lang, "home_my_notes_desc")),
            (f"/user/{current_user}/new", "fa-square-plus", t(lang, "nav_new_note"), t(lang, "home_new_note_desc")),
        ]
        if feature_enabled("share_links"):
            cards.append((f"/user/{current_user}/shares/", "fa-share-nodes", t(lang, "nav_share_mgmt"), t(lang, "home_share_mgmt_desc")))
        if feature_enabled("benben"):
            cards.append(("/benben", "fa-sticky-note", t(lang, "home_benben"), t(lang, "home_benben_desc")))
        cards.append(("/count", "fa-chart-simple", t(lang, "home_stats"), t(lang, "home_stats_desc")))
    else:
        cards = []
        if feature_enabled("world_notes"):
            cards.append(("/world/", "fa-globe", t(lang, "home_public_notes"), t(lang, "home_public_notes_desc")))
        cards.append(("/login", "fa-right-to-bracket", t(lang, "home_login"), t(lang, "home_login_desc")))
        if feature_enabled("open_register"):
            cards.append(("/register", "fa-user-plus", t(lang, "home_register"), t(lang, "home_register_desc")))
        if feature_enabled("benben"):
            cards.append(("/benben", "fa-sticky-note", t(lang, "home_benben"), t(lang, "home_benben_desc")))
        cards.append(("/count", "fa-chart-simple", t(lang, "home_stats"), t(lang, "home_stats_desc")))
    return render_template("home.html", site_name=config.SITE_NAME or "如形の笔记", cards=cards)


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