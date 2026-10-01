"""首页、统计、免责声明"""
import time
from datetime import date, timedelta

from flask import Blueprint, g, redirect, render_template

from app.core import config
from app.core.extensions import cache
from app.core.feature_flags import feature_enabled, get_grouped_features, is_admin
from app.core.i18n import t
from app.core.notes import generate_random_id, get_stats, search_user_notes
from app.core.storage import StorageError, storage
from app.core.utils import format_size, format_note_time, read_disclaimer, read_notice_first_line
from app.apps.common.helpers import page_cache_key

bp = Blueprint("home", __name__)

_EN_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
              "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _greeting_key(hour: int) -> str:
    if 5 <= hour < 11:
        return "greeting_morning"
    if 11 <= hour < 13:
        return "greeting_noon"
    if 13 <= hour < 18:
        return "greeting_afternoon"
    return "greeting_evening"


def _build_heatmap(username: str, lang: str) -> dict:
    """近一年笔记修改热力图（GitHub 风格按周分列，周日为一列之首）。"""
    try:
        notes = storage.list_notes_detailed(username)
    except StorageError:
        notes = []
    counts: dict[date, int] = {}
    for note in notes:
        mtime = note.get("mtime") or 0
        if not mtime:
            continue
        try:
            d = date.fromtimestamp(mtime)
        except (ValueError, OverflowError, OSError):
            continue
        counts[d] = counts.get(d, 0) + 1

    today = date.today()
    start = today - timedelta(days=364)
    start -= timedelta(days=(start.weekday() + 1) % 7)  # 回退到所在周的周日
    peak = max(counts.values()) if counts else 0

    weeks = []
    total = 0
    d = start
    prev_month = None
    while d <= today:
        month_label = ""
        if prev_month is not None and d.month != prev_month:
            month_label = f"{d.month}月" if lang == "zh" else _EN_MONTHS[d.month - 1]
        prev_month = d.month
        days = []
        for _ in range(7):
            if d > today:
                days.append(None)
            else:
                c = counts.get(d, 0)
                total += c
                lv = 0 if not c or not peak else max(1, min(4, -(-c * 4 // peak)))
                days.append({"k": d.isoformat(), "c": c, "lv": lv})
            d += timedelta(days=1)
        weeks.append({"m": month_label, "days": days})
    return {"weeks": weeks, "total": total}


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
        # 工作台：问候语 + 近一年笔记热力图 + 最近修改
        cards = []
        quick_actions = []
        all_notes = search_user_notes(current_user, "")
        recent_notes = all_notes[:config.RECENT_NOTES_LIMIT]
        recent_shares = []
        note_count = len(all_notes)
        share_count = 0
        share_views = 0
        greeting = t(lang, _greeting_key(time.localtime().tm_hour))
        greeting = f"{greeting}，{current_user}" if lang == "zh" else f"{greeting}, {current_user}"
        heatmap = _build_heatmap(current_user, lang)
    else:
        cards = []
        quick_actions = []
        note_count = 0
        share_count = 0
        share_views = 0
        greeting = ""
        heatmap = None
        recent_notes = []
        recent_shares = []
        if feature_enabled("world_notes"):
            cards.append(("/world/", "fa-globe", t(lang, "home_public_notes"), t(lang, "home_public_notes_desc")))
        cards.append(("/login", "fa-right-to-bracket", t(lang, "home_login"), t(lang, "home_login_desc")))
        if feature_enabled("open_register"):
            cards.append(("/register", "fa-user-plus", t(lang, "home_register"), t(lang, "home_register_desc")))
        cards.append(("/count", "fa-chart-simple", t(lang, "home_stats"), t(lang, "home_stats_desc")))
    return render_template("home.html", site_name=config.SITE_NAME or "如形の笔记", cards=cards,
                           recent_notes=recent_notes, recent_shares=recent_shares,
                           current_user=current_user, show_benben=feature_enabled("benben"),
                           quick_actions=quick_actions, note_count=note_count,
                           share_count=share_count, share_views=share_views,
                           greeting=greeting, heatmap=heatmap,
                           notice=read_notice_first_line())


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
        feature_groups=get_grouped_features(),
        show_public=feature_enabled("world_notes"),
        show_benben=feature_enabled("benben"),
        is_admin_page=bool(user and is_admin(user)),
    )


@bp.route("/disclaimer")
def disclaimer():
    lang = getattr(g, "lang", "zh")
    content = read_disclaimer(lang)
    return render_template("disclaimer.html", content=content)