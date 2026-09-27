"""分享 App：分享查看/编辑 /share/<token>，与用户分享管理 /user/<u>/shares。"""
import re

from flask import Blueprint, abort, g, redirect, render_template, request, url_for

from app.core import config
from app.core.extensions import cache, limiter
from app.core.i18n import t
from app.core.feature_flags import require_feature
from app.core.middleware import get_current_user
from app.core.notes import (
    list_user_notes,
    note_exists,
    read_note,
    validate_note_id,
    validate_username,
    write_note,
)
from app.core.store import (
    create_share,
    delete_share,
    get_share,
    increment_share_views,
    list_user_shares,
)
from app.core.utils import render_latex_head, render_markdown_html
from app.apps.common.helpers import (
    build_note_context,
    page_cache_key,
    purge_page_cache,
    require_auth,
)


bp = Blueprint("share", __name__)


def _resolve_share(token):
    share = get_share(token)
    if share is None:
        abort(404)
    return share


@bp.route("/share/<token>", methods=["GET"])
@bp.route("/share/<token>/", methods=["GET"])
@require_feature("share_links")
@limiter.limit(lambda: f"{config.GET_RATE_MAX} per {config.GET_RATE_WINDOW} second")
def share_view_get(token):
    share = _resolve_share(token)
    increment_share_views(token)
    note_id = share.get("note_id", "")
    content = read_note(share.get("owner", ""), note_id)
    if share.get("editable"):
        lang = getattr(g, "lang", "zh")
        ctx = build_note_context(
            note_id, is_share=True, mtime=None,
            hint_text=t(lang, "share_edit_hint"),
        )
        return render_template(
            "notes/note_edit.html",
            note_id=note_id,
            content=content,
            is_world=False,
            action_url=url_for("share.share_view_post", token=token),
            is_share=True,
            comment_url=f"/comments/share/{token}",
            **ctx,
        )
    lang = getattr(g, "lang", "zh")
    return render_template(
        "notes/note_md.html",
        note_id=note_id,
        html_content=render_markdown_html(content),
        title_label=t(lang, "note_share_prefix"),
        back_url=url_for("share.share_view_get", token=token),
        back_label=t(lang, "md_refresh"),
        latex_head=render_latex_head(),
    )


@bp.route("/share/<token>", methods=["POST"])
@bp.route("/share/<token>/", methods=["POST"])
@require_feature("share_links")
@limiter.limit(lambda: f"{config.SAVE_RATE_MAX} per {config.SAVE_RATE_WINDOW} second")
def share_view_post(token):
    share = _resolve_share(token)
    if not share.get("editable"):
        abort(403)
    content = request.form.get("content", "")
    if not write_note(share.get("owner", ""), share.get("note_id", ""), content):
        abort(500)
    # 首页显示最近编辑的笔记，也需要刷新
    purge_page_cache(
        ["/", f"/share/{token}", f"/share/{token}.md", f"/share/{token}/md"],
        viewers=(None, get_current_user()),
    )
    return redirect(url_for("share.share_view_get", token=token))


@bp.route("/share/<token>/md", methods=["GET"])
@bp.route("/share/<token>.md", methods=["GET"])
@require_feature("share_links")
@limiter.limit(lambda: f"{config.GET_RATE_MAX} per {config.GET_RATE_WINDOW} second")
@cache.cached(timeout=config.CACHE_TIMEOUT_NOTES, make_cache_key=page_cache_key)
def share_md(token):
    share = _resolve_share(token)
    increment_share_views(token)
    note_id = share.get("note_id", "")
    content = read_note(share.get("owner", ""), note_id)
    lang = getattr(g, "lang", "zh")
    return render_template(
        "notes/note_md.html",
        note_id=note_id,
        html_content=render_markdown_html(content),
        title_label=t(lang, "note_share_prefix"),
        back_url=url_for("share.share_view_get", token=token),
        back_label=t(lang, "md_back_share"),
        latex_head=render_latex_head(),
    )


# ---------- 用户分享管理：/user/<u>/shares ----------
# 必须注册在 /user/<username>/<note_id> 之前，否则 shares 会被当作笔记 ID。
@bp.route("/user/<username>/shares", methods=["GET"])
@bp.route("/user/<username>/shares/", methods=["GET"])
@require_feature("share_links")
@limiter.limit(lambda: f"{config.GET_RATE_MAX} per {config.GET_RATE_WINDOW} second")
def shares_get(username):
    if not validate_username(username):
        abort(400)
    require_auth(username)
    return _render_shares(username, error="")


@bp.route("/user/<username>/shares", methods=["POST"])
@bp.route("/user/<username>/shares/", methods=["POST"])
@require_feature("share_links")
@limiter.limit(lambda: f"{config.RATE_MAX} per {config.RATE_WINDOW} second")
def shares_post(username):
    if not validate_username(username):
        abort(400)
    require_auth(username)
    note_id = request.form.get("note_id", "").strip()
    editable = request.form.get("editable", "0") in ("1", "on", "true")
    if len(note_id) > config.MAX_NOTE_ID_LENGTH:
        return _render_shares(username, error=t(getattr(g, "lang", "zh"), "err_url_invalid")), 400
    if not validate_note_id(note_id):
        return _render_shares(username, error=t(getattr(g, "lang", "zh"), "err_share_invalid_note")), 400
    if not note_exists(username, note_id):
        return _render_shares(username, error=t(getattr(g, "lang", "zh"), "err_share_note_missing")), 400
    create_share(username, note_id, editable)
    purge_page_cache([f"/user/{username}/shares", f"/user/{username}/shares/"],
                     viewers=(username,))
    return redirect(url_for("share.shares_get", username=username))


@bp.route("/user/<username>/shares/delete", methods=["POST"])
@require_feature("share_links")
@limiter.limit(lambda: f"{config.RATE_MAX} per {config.RATE_WINDOW} second")
def shares_delete(username):
    if not validate_username(username):
        abort(400)
    require_auth(username)
    token = request.form.get("token", "").strip()
    if not re.match(f"^{config.SHARE_TOKEN_PATTERN}$", token):
        abort(400)
    if not delete_share(username, token):
        return _render_shares(username, error=t(getattr(g, "lang", "zh"), "err_share_delete")), 400
    purge_page_cache([f"/user/{username}/shares", f"/user/{username}/shares/"],
                     viewers=(username,))
    return redirect(url_for("share.shares_get", username=username))


def _render_shares(username, error):
    my_shares = list_user_shares(username)
    notes = list_user_notes(username)
    rows = []
    for tok, s in sorted(my_shares, key=lambda kv: kv[1].get("created_at", 0), reverse=True):
        rows.append({
            "note_id": s.get("note_id", ""),
            "token": tok,
            "editable": bool(s.get("editable")),
            "views": s.get("views", 0),
        })
    return render_template(
        "share/share_list.html",
        username=username,
        rows=rows,
        notes=notes,
        error=error,
    )