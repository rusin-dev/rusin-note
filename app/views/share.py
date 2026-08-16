"""分享查看/编辑：/share/<token>、/share/<token>/md、/share/<token>.md"""
from flask import Blueprint, abort, g, redirect, render_template, request, url_for

from .. import config
from ..extensions import limiter
from ..i18n import t
from ..notes import read_note, write_note
from ..store import get_share, increment_share_views
from ..utils import render_latex_head, render_markdown_html
from ._helpers import build_note_context


bp = Blueprint("share", __name__)


def _resolve_share(token):
    share = get_share(token)
    if share is None:
        abort(404)
    return share


@bp.route("/share/<token>", methods=["GET"])
@bp.route("/share/<token>/", methods=["GET"])
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
@limiter.limit(lambda: f"{config.SAVE_RATE_MAX} per {config.SAVE_RATE_WINDOW} second")
def share_view_post(token):
    share = _resolve_share(token)
    if not share.get("editable"):
        abort(403)
    content = request.form.get("content", "")
    if not write_note(share.get("owner", ""), share.get("note_id", ""), content):
        abort(500)
    return redirect(url_for("share.share_view_get", token=token))


@bp.route("/share/<token>/md", methods=["GET"])
@bp.route("/share/<token>.md", methods=["GET"])
@limiter.limit(lambda: f"{config.GET_RATE_MAX} per {config.GET_RATE_WINDOW} second")
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