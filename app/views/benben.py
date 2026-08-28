"""犇犇（用户动态）：/benben（GET 查看 / POST 发布）

POST 受全局 POST 限流约束（限流在蓝图层显式标注）。
"""
from flask import Blueprint, abort, g, redirect, render_template, request

from .. import config
from ..extensions import cache, limiter
from ..i18n import LANGS
from ..middleware import get_client_ip, get_current_user
from ..store import (
    add_benben_post,
    get_benben_cooldown,
    get_benben_posts,
    mark_benben_post,
)
from ..i18n import t
from ..feature_flags import require_feature
from ..utils import render_latex_head, render_markdown_html
from ._helpers import delete_cache_keys


bp = Blueprint("benben", __name__)


def _benben_cache_key():
    """分页 + 访问者 + 语言：页面文案依赖语言、导航栏依赖登录用户（见 _helpers.page_cache_key）"""
    user = getattr(g, "current_user", None) or "anon"
    lang = getattr(g, "lang", "zh")
    return f"benben:page:{request.args.get('page', '1')}:{user}:{lang}"


@bp.route("/benben", methods=["GET"])
@require_feature("benben")
@limiter.limit(lambda: f"{config.GET_RATE_MAX} per {config.GET_RATE_WINDOW} second")
@cache.cached(timeout=config.CACHE_TIMEOUT_BENBEN, make_cache_key=_benben_cache_key)
def benben_get():
    try:
        page = max(1, int(request.args.get("page", "1")))
    except (TypeError, ValueError):
        page = 1
    posts, has_more = get_benben_posts(page, config.BENBEN_PAGE_SIZE)
    items = []
    from ..utils import format_note_time
    for post in posts:
        if not isinstance(post, dict):
            continue
        ts = post.get("time", 0)
        time_str = format_note_time(ts) if isinstance(ts, (int, float)) and ts > 0 else ""
        items.append({
            "username": post.get("username", ""),
            "time": ts,
            "time_str": time_str,
            "content": post.get("content", ""),
            "content_html": render_markdown_html(post.get("content", "")),
        })
    return render_template(
        "benben/benben.html",
        items=items,
        page=page,
        has_more=has_more,
        error="",
        prefill="",
        max_length=config.BENBEN_MAX_LENGTH,
        page_size=config.BENBEN_PAGE_SIZE,
        current_user=get_current_user(),
        preview_l10n={
            "loadFailed": t(getattr(g, "lang", "zh"), "preview_load_failed"),
            "renderFailed": t(getattr(g, "lang", "zh"), "preview_render_failed"),
        },
        latex_head=render_latex_head(),
    )


@bp.route("/benben", methods=["POST"])
@require_feature("benben")
@limiter.limit(lambda: f"{config.RATE_MAX} per {config.RATE_WINDOW} second")
def benben_post():
    current_user = get_current_user()
    if not current_user:
        return redirect("/login")

    content = request.form.get("content", "").strip()

    def _render_err(msg_key, **kw):
        from ..i18n import t
        from ..utils import format_note_time
        lang = getattr(g, "lang", "zh")
        posts, has_more = get_benben_posts(1, config.BENBEN_PAGE_SIZE)
        items = []
        for p in posts:
            if not isinstance(p, dict):
                continue
            ts = p.get("time", 0)
            time_str = format_note_time(ts) if isinstance(ts, (int, float)) and ts > 0 else ""
            items.append({
                "username": p.get("username", ""),
                "time": ts,
                "time_str": time_str,
                "content": p.get("content", ""),
                "content_html": render_markdown_html(p.get("content", "")),
            })
        err_msg = t(lang, msg_key, **kw)
        return render_template(
            "benben/benben.html",
            items=items,
            page=1,
            has_more=has_more,
            error=err_msg,
            prefill=content,
            max_length=config.BENBEN_MAX_LENGTH,
            page_size=config.BENBEN_PAGE_SIZE,
            current_user=get_current_user(),
            preview_l10n={
                "loadFailed": t(lang, "preview_load_failed"),
                "renderFailed": t(lang, "preview_render_failed"),
            },
            latex_head=render_latex_head(),
        ), 400

    if not content:
        return _render_err("err_benben_empty")

    if len(content) > config.BENBEN_MAX_LENGTH:
        return _render_err("err_benben_too_long", max=config.BENBEN_MAX_LENGTH)

    remaining = get_benben_cooldown(current_user)
    if remaining > 0:
        return _render_err("err_benben_cooldown", sec=int(remaining) + 1)

    add_benben_post(current_user, content, get_client_ip())
    mark_benben_post(current_user)
    # 新动态把旧内容顶到第 2 页：清掉匿名与发布者视角的第 1 页，
    # 其余访问者的键靠 60s TTL 过期
    delete_cache_keys([
        f"benben:page:1:{viewer}:{lang}"
        for viewer in ("anon", current_user)
        for lang in LANGS
    ])
    return redirect("/benben")
