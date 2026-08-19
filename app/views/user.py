"""私有笔记与分享管理：/user/<u>、/user/<u>/<id>、/user/<u>/shares/*"""
import re
from flask import Blueprint, abort, g, redirect, render_template, request, url_for

from .. import config
from ..extensions import cache, limiter
from ..i18n import t
from ..middleware import get_current_user
from ..notes import (
    generate_random_id,
    get_note_mtime,
    get_note_size,
    list_user_notes,
    note_exists,
    read_note,
    validate_note_id,
    validate_username,
    write_note,
)
from ..store import (
    create_share,
    delete_share,
    list_user_shares,
)
from ..utils import format_note_time, format_size, render_latex_head, render_markdown_html
from ._helpers import build_note_context, check_note_id


bp = Blueprint("user", __name__)


def _require_auth(username: str):
    if get_current_user() != username:
        abort(401)


@bp.route("/user/<username>", methods=["GET"])
@bp.route("/user/<username>/", methods=["GET"])
@limiter.limit(lambda: f"{config.GET_RATE_MAX} per {config.GET_RATE_WINDOW} second")
@cache.cached(timeout=config.CACHE_TIMEOUT_NOTES)
def user_root(username):
    if not validate_username(username):
        abort(400)
    _require_auth(username)
    notes = list_user_notes(username)
    items = []
    for nid in notes:
        mtime = get_note_mtime(username, nid)
        size = get_note_size(username, nid)
        items.append({
            "id": nid,
            "mtime": format_note_time(mtime) if mtime else "",
            "size": format_size(size) if size is not None else "",
        })
    return render_template("notes/user_list.html", username=username, items=items)


@bp.route("/user/<username>/new", methods=["GET"])
@limiter.limit(lambda: f"{config.GET_RATE_MAX} per {config.GET_RATE_WINDOW} second")
def user_new(username):
    if not validate_username(username):
        abort(400)
    _require_auth(username)
    new_id = generate_random_id()
    return redirect(url_for("user.user_note_get", username=username, note_id=new_id))


@bp.route("/user/<username>/<note_id>", methods=["GET"])
@bp.route("/user/<username>/<note_id>/", methods=["GET"])
@limiter.limit(lambda: f"{config.GET_RATE_MAX} per {config.GET_RATE_WINDOW} second")
def user_note_get(username, note_id):
    if not validate_username(username):
        abort(400)
    check_note_id(note_id)
    _require_auth(username)
    content = read_note(username, note_id)
    ctx = build_note_context(note_id, username=username, mtime=get_note_mtime(username, note_id))
    return render_template(
        "notes/note_edit.html",
        note_id=note_id,
        username=username,
        content=content,
        is_world=False,
        action_url=url_for("user.user_note_post", username=username, note_id=note_id),
        **ctx,
    )


@bp.route("/user/<username>/<note_id>", methods=["POST"])
@bp.route("/user/<username>/<note_id>/", methods=["POST"])
@limiter.limit(lambda: f"{config.SAVE_RATE_MAX} per {config.SAVE_RATE_WINDOW} second")
def user_note_post(username, note_id):
    if not validate_username(username):
        abort(400)
    check_note_id(note_id)
    _require_auth(username)
    content = request.form.get("content", "")
    if not write_note(username, note_id, content):
        abort(500)
    cache.delete(f"/user/{username}/{note_id}")
    cache.delete(f"/user/{username}/{note_id}/md")
    cache.delete(f"/user/{username}/{note_id}.md")
    return redirect(url_for("user.user_note_get", username=username, note_id=note_id))


@bp.route("/user/<username>/<note_id>/md", methods=["GET"])
@bp.route("/user/<username>/<note_id>.md", methods=["GET"])
@limiter.limit(lambda: f"{config.GET_RATE_MAX} per {config.GET_RATE_WINDOW} second")
@cache.cached(timeout=config.CACHE_TIMEOUT_NOTES)
def user_md(username, note_id):
    if not validate_username(username):
        abort(400)
    check_note_id(note_id)
    _require_auth(username)
    content = read_note(username, note_id)
    lang = getattr(g, "lang", "zh")
    return render_template(
        "notes/note_md.html",
        note_id=note_id,
        html_content=render_markdown_html(content),
        title_label=t(lang, "note_private_prefix"),
        back_url=url_for("user.user_note_get", username=username, note_id=note_id),
        back_label=t(lang, "md_back_edit"),
        latex_head=render_latex_head(),
        username=username,
    )


@bp.route("/user/<username>/shares", methods=["GET"])
@bp.route("/user/<username>/shares/", methods=["GET"])
@limiter.limit(lambda: f"{config.GET_RATE_MAX} per {config.GET_RATE_WINDOW} second")
def shares_get(username):
    if not validate_username(username):
        abort(400)
    _require_auth(username)
    return _render_shares(username, error="")


@bp.route("/user/<username>/shares", methods=["POST"])
@bp.route("/user/<username>/shares/", methods=["POST"])
@limiter.limit(lambda: f"{config.RATE_MAX} per {config.RATE_WINDOW} second")
def shares_post(username):
    if not validate_username(username):
        abort(400)
    _require_auth(username)
    note_id = request.form.get("note_id", "").strip()
    editable = request.form.get("editable", "0") in ("1", "on", "true")
    if len(note_id) > config.MAX_NOTE_ID_LENGTH:
        return _render_shares(username, error=t(getattr(g, "lang", "zh"), "err_url_invalid")), 400
    if not validate_note_id(note_id):
        return _render_shares(username, error=t(getattr(g, "lang", "zh"), "err_share_invalid_note")), 400
    if not note_exists(username, note_id):
        return _render_shares(username, error=t(getattr(g, "lang", "zh"), "err_share_note_missing")), 400
    create_share(username, note_id, editable)
    cache.delete(f"/user/{username}/shares")
    return redirect(url_for("user.shares_get", username=username))


@bp.route("/user/<username>/shares/delete", methods=["POST"])
@limiter.limit(lambda: f"{config.RATE_MAX} per {config.RATE_WINDOW} second")
def shares_delete(username):
    if not validate_username(username):
        abort(400)
    _require_auth(username)
    token = request.form.get("token", "").strip()
    if not re.match(f"^{config.SHARE_TOKEN_PATTERN}$", token):
        abort(400)
    if not delete_share(username, token):
        return _render_shares(username, error=t(getattr(g, "lang", "zh"), "err_share_delete")), 400
    cache.delete(f"/user/{username}/shares")
    return redirect(url_for("user.shares_get", username=username))


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