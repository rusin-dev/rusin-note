"""评论系统：/comments/<target_type>/<target_id>（GET 查看 / POST 发布）

支持两种目标类型：
- share: 分享笔记评论
- note: 用户笔记评论

POST 受全局 POST 限流约束（限流在蓝图层显式标注）。
"""
from flask import Blueprint, g, redirect, render_template, request

from .. import config
from ..extensions import cache, limiter
from ..i18n import LANGS, t
from ..middleware import get_client_ip, get_current_user
from ..feature_flags import require_feature
from ..comments import (
    add_comment,
    get_comment_count,
    get_comment_cooldown,
    get_comment_page,
    get_comment_url,
    mark_comment_post,
    validate_comment_content,
    validate_target_id,
    validate_target_type,
    TARGET_SHARE,
    TARGET_NOTE,
)
from ..utils import render_latex_head, render_markdown_html, format_note_time
from ..store import get_share
from ._helpers import delete_cache_keys


bp = Blueprint("comments", __name__)


def _comments_cache_key(**kwargs):
    """分页 + 访问者 + 语言 + 目标：页面文案依赖语言、导航栏依赖登录用户"""
    user = getattr(g, "current_user", None) or "anon"
    lang = getattr(g, "lang", "zh")
    target_type = kwargs.get("target_type", request.view_args.get("target_type", ""))
    target_id = kwargs.get("target_id", request.view_args.get("target_id", ""))
    return f"comments:{target_type}:{target_id}:page:{request.args.get('page', '1')}:{user}:{lang}"


@bp.route("/comments/<target_type>/<path:target_id>", methods=["GET"])
@require_feature("comments")
@limiter.limit(lambda: f"{config.GET_RATE_MAX} per {config.GET_RATE_WINDOW} second")
@cache.cached(timeout=config.CACHE_TIMEOUT_BENBEN, make_cache_key=_comments_cache_key)
def comments_get(target_type: str, target_id: str):
    # 校验目标类型
    if not validate_target_type(target_type):
        return render_template("errors/404.html"), 404

    # 校验目标 ID
    if not validate_target_id(target_id):
        return render_template("errors/404.html"), 404

    # 对于分享类型，校验分享链接是否存在
    if target_type == TARGET_SHARE:
        share = get_share(target_id)
        if not share:
            return render_template("errors/404.html"), 404
        target_title = f"分享 {target_id[:8]}..."
    else:
        # 笔记类型：目标 ID 格式为 username/note_id
        parts = target_id.split("/", 1)
        if len(parts) != 2:
            return render_template("errors/404.html"), 404
        target_title = f"笔记 {parts[1]}"

    try:
        page = max(1, int(request.args.get("page", "1")))
    except (TypeError, ValueError):
        page = 1

    posts, has_more = get_comment_page(target_type, target_id, page, config.COMMENTS_PAGE_SIZE)
    items = []
    for post in posts:
        if not isinstance(post, dict):
            continue
        ts = post.get("time", 0)
        time_str = format_note_time(ts) if isinstance(ts, (int, float)) and ts > 0 else ""
        is_anonymous = post.get("is_anonymous", False)
        username = post.get("username", "")
        display_name = "匿名用户" if is_anonymous and not username else username
        items.append({
            "username": display_name,
            "time": ts,
            "time_str": time_str,
            "content_html": render_markdown_html(post.get("content", "")),
            "is_anonymous": is_anonymous,
        })

    current_user = get_current_user()
    comment_count = get_comment_count(target_type, target_id)

    return render_template(
        "comments/comments.html",
        target_type=target_type,
        target_id=target_id,
        target_title=target_title,
        items=items,
        page=page,
        has_more=has_more,
        error="",
        prefill="",
        max_length=config.COMMENTS_MAX_LENGTH,
        page_size=config.COMMENTS_PAGE_SIZE,
        current_user=current_user,
        comment_count=comment_count,
        preview_l10n={
            "loadFailed": t(getattr(g, "lang", "zh"), "preview_load_failed"),
            "renderFailed": t(getattr(g, "lang", "zh"), "preview_render_failed"),
        },
        latex_head=render_latex_head(),
    )


@bp.route("/comments/<target_type>/<path:target_id>", methods=["POST"])
@require_feature("comments")
@limiter.limit(lambda: f"{config.RATE_MAX} per {config.RATE_WINDOW} second")
def comments_post(target_type: str, target_id: str):
    # 校验目标类型
    if not validate_target_type(target_type):
        return render_template("errors/404.html"), 404

    # 校验目标 ID
    if not validate_target_id(target_id):
        return render_template("errors/404.html"), 404

    # 对于分享类型，校验分享链接是否存在
    if target_type == TARGET_SHARE:
        share = get_share(target_id)
        if not share:
            return render_template("errors/404.html"), 404
        target_title = f"分享 {target_id[:8]}..."
    else:
        # 笔记类型：目标 ID 格式为 username/note_id
        parts = target_id.split("/", 1)
        if len(parts) != 2:
            return render_template("errors/404.html"), 404
        target_title = f"笔记 {parts[1]}"

    current_user = get_current_user()
    content = request.form.get("content", "").strip()
    is_anonymous = not current_user

    def _render_err(msg_key, **kw):
        lang = getattr(g, "lang", "zh")
        posts, has_more = get_comment_page(target_type, target_id, 1, config.COMMENTS_PAGE_SIZE)
        items = []
        for p in posts:
            if not isinstance(p, dict):
                continue
            ts = p.get("time", 0)
            time_str = format_note_time(ts) if isinstance(ts, (int, float)) and ts > 0 else ""
            is_anon = p.get("is_anonymous", False)
            uname = p.get("username", "")
            display_name = "匿名用户" if is_anon and not uname else uname
            items.append({
                "username": display_name,
                "time": ts,
                "time_str": time_str,
                "content_html": render_markdown_html(p.get("content", "")),
                "is_anonymous": is_anon,
            })
        err_msg = t(lang, msg_key, **kw)
        comment_count = get_comment_count(target_type, target_id)
        return render_template(
            "comments/comments.html",
            target_type=target_type,
            target_id=target_id,
            target_title=target_title,
            items=items,
            page=1,
            has_more=has_more,
            error=err_msg,
            prefill=content,
            max_length=config.COMMENTS_MAX_LENGTH,
            page_size=config.COMMENTS_PAGE_SIZE,
            current_user=current_user,
            comment_count=comment_count,
            preview_l10n={
                "loadFailed": t(lang, "preview_load_failed"),
                "renderFailed": t(lang, "preview_render_failed"),
            },
            latex_head=render_latex_head(),
        ), 400

    # 未登录用户可以匿名评论
    username = current_user if current_user else ""

    # 校验评论内容
    valid, err_key = validate_comment_content(content)
    if not valid:
        return _render_err(err_key, max=config.COMMENTS_MAX_LENGTH)

    # 检查冷却时间（使用用户名或 IP 作为冷却键）
    cooldown_key = username if username else f"anon:{get_client_ip()}"
    remaining = get_comment_cooldown(cooldown_key)
    if remaining > 0:
        return _render_err("err_comment_cooldown", sec=int(remaining) + 1)

    # 发布评论
    ok = add_comment(
        target_type=target_type,
        target_id=target_id,
        username=username,
        content=content,
        ip=get_client_ip(),
        is_anonymous=is_anonymous or not username,
    )

    if not ok:
        return _render_err("err_comment_upload")

    # 记录发布时间
    mark_comment_post(cooldown_key)

    # 清除缓存
    lang = getattr(g, "lang", "zh")
    delete_cache_keys([
        f"comments:{target_type}:{target_id}:page:1:{viewer}:{lang}"
        for viewer in ("anon", username or "anon")
        for lang in LANGS
    ])

    return redirect(get_comment_url(target_type, target_id))
