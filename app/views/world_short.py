"""公开笔记短链：/<id> → /world/<id>、/<id>.md → Markdown 渲染

catch-all 路由，必须在所有具名路由之后注册（views/__init__.py 末尾）。
"""
from flask import Blueprint, abort, redirect, render_template, url_for

from .. import config
from ..extensions import limiter
from ..notes import read_note, validate_note_id
from ..utils import render_markdown_html


bp = Blueprint("world_short", __name__)


@bp.route("/<note_id>", methods=["GET"])
@limiter.limit(lambda: f"{config.GET_RATE_MAX} per {config.GET_RATE_WINDOW} second")
def short_link(note_id):
    if "." in note_id:
        abort(404)
    if not validate_note_id(note_id):
        abort(400)
    return redirect(url_for("world.world_note_get", note_id=note_id))


@bp.route("/<note_id>.md", methods=["GET"])
@limiter.limit(lambda: f"{config.GET_RATE_MAX} per {config.GET_RATE_WINDOW} second")
def short_link_md(note_id):
    if not validate_note_id(note_id):
        abort(400)
    content = read_note("public", note_id)
    html_content = render_markdown_html(content)
    return render_template(
        "notes/note_md.html",
        note_id=note_id,
        html_content=html_content,
        title_label=None,
        back_url=url_for("world.world_note_get", note_id=note_id),
        back_label=None,
    )