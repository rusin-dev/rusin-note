"""公开笔记短链：/<id> → /world/<id>、/<id>.md → Markdown 渲染

catch-all 路由，必须在所有具名路由之后注册（views/__init__.py 末尾）。
"""
from flask import Blueprint, redirect, render_template, url_for

from .. import config
from ..extensions import cache, limiter
from ..feature_flags import require_feature
from ..notes import read_note
from ..utils import render_latex_head, render_markdown_html
from ._helpers import check_note_id, page_cache_key


bp = Blueprint("world_short", __name__)


@bp.route("/<note_id>", methods=["GET"])
@require_feature("world_notes")
@limiter.limit(lambda: f"{config.GET_RATE_MAX} per {config.GET_RATE_WINDOW} second")
def short_link(note_id):
    check_note_id(note_id)
    return redirect(url_for("world.world_note_get", note_id=note_id))


@bp.route("/<note_id>.md", methods=["GET"])
@require_feature("world_notes")
@limiter.limit(lambda: f"{config.GET_RATE_MAX} per {config.GET_RATE_WINDOW} second")
@cache.cached(timeout=config.CACHE_TIMEOUT_NOTES, make_cache_key=page_cache_key)
def short_link_md(note_id):
    check_note_id(note_id)
    content = read_note("public", note_id)
    html_content = render_markdown_html(content)
    return render_template(
        "notes/note_md.html",
        note_id=note_id,
        html_content=html_content,
        title_label=None,
        back_url=url_for("world.world_note_get", note_id=note_id),
        back_label=None,
        latex_head=render_latex_head(),
    )