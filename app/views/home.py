"""首页、统计、免责声明"""
from flask import Blueprint, g, render_template

from .. import config
from ..i18n import t
from ..notes import get_stats
from ..utils import format_size, read_disclaimer

bp = Blueprint("home", __name__)


@bp.route("/")
def index():
    lang = getattr(g, "lang", "zh")
    current_user = getattr(g, "current_user", None)
    if current_user:
        cards = [
            (f"/user/{current_user}/", "fa-file-lines", t(lang, "nav_my_notes"), t(lang, "home_my_notes_desc")),
            (f"/user/{current_user}/new", "fa-square-plus", t(lang, "nav_new_note"), t(lang, "home_new_note_desc")),
            (f"/user/{current_user}/shares/", "fa-share-nodes", t(lang, "nav_share_mgmt"), t(lang, "home_share_mgmt_desc")),
            ("/benben", "fa-sticky-note", t(lang, "home_benben"), t(lang, "home_benben_desc")),
            ("/count", "fa-chart-simple", t(lang, "home_stats"), t(lang, "home_stats_desc")),
        ]
    else:
        cards = [
            ("/world/", "fa-globe", t(lang, "home_public_notes"), t(lang, "home_public_notes_desc")),
            ("/login", "fa-right-to-bracket", t(lang, "home_login"), t(lang, "home_login_desc")),
            ("/register", "fa-user-plus", t(lang, "home_register"), t(lang, "home_register_desc")),
            ("/benben", "fa-sticky-note", t(lang, "home_benben"), t(lang, "home_benben_desc")),
            ("/count", "fa-chart-simple", t(lang, "home_stats"), t(lang, "home_stats_desc")),
        ]
    return render_template("home.html", site_name=config.SITE_NAME or "如形の笔记", cards=cards)


@bp.route("/count")
def count():
    pub_cnt, pub_size, priv_cnt, priv_size, user_cnt, benben_cnt = get_stats()
    return render_template(
        "count.html",
        pub_cnt=pub_cnt, pub_size=format_size(pub_size),
        priv_cnt=priv_cnt, priv_size=format_size(priv_size),
        user_cnt=user_cnt, benben_cnt=benben_cnt,
    )


@bp.route("/disclaimer")
def disclaimer():
    lang = getattr(g, "lang", "zh")
    content = read_disclaimer(lang)
    return render_template("disclaimer.html", content=content)