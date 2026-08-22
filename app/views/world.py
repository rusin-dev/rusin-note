"""公开笔记：/world、/world/<id>（GET/POST）、/world/<id>/md、/world/<id>.md

GET 与 POST 拆分为不同函数以分别配置限流（GET 走 GET 限流，POST 走 SAVE 限流）。
"""
from flask import Blueprint, abort, g, redirect, render_template, request, url_for

from .. import config
from ..extensions import cache, limiter
from ..i18n import t
from ..feature_flags import require_feature
from ..notes import (
    generate_random_id,
    get_note_mtime,
    read_note,
    write_note,
)
from ..middleware import get_current_user
from ..utils import render_latex_head, render_markdown_html
from ._helpers import build_note_context, check_note_id, page_cache_key, purge_page_cache


bp = Blueprint("world", __name__)


@bp.route("/world", methods=["GET"])
@bp.route("/world/", methods=["GET"])
@require_feature("world_notes")
@limiter.limit(lambda: f"{config.GET_RATE_MAX} per {config.GET_RATE_WINDOW} second")
def world_new():
    new_id = generate_random_id()
    return redirect(url_for("world.world_note_get", note_id=new_id))


@bp.route("/world/<note_id>", methods=["GET"])
@require_feature("world_notes")
@limiter.limit(lambda: f"{config.GET_RATE_MAX} per {config.GET_RATE_WINDOW} second")
def world_note_get(note_id):
    check_note_id(note_id)
    content = read_note("public", note_id)
    ctx = build_note_context(note_id, is_world=True, mtime=get_note_mtime("public", note_id))
    return render_template(
        "notes/note_edit.html",
        note_id=note_id,
        content=content,
        is_world=True,
        action_url=url_for("world.world_note_post", note_id=note_id),
        **ctx,
    )


@bp.route("/world/<note_id>", methods=["POST"])
@require_feature("world_notes")
@limiter.limit(lambda: f"{config.SAVE_RATE_MAX} per {config.SAVE_RATE_WINDOW} second")
def world_note_post(note_id):
    check_note_id(note_id)
    content = request.form.get("content", "")
    if not write_note("public", note_id, content):
        abort(500)
    # /world/<id> 编辑页虽未缓存，一并清理保持对称；/<id>.md 是短链渲染入口
    purge_page_cache(
        [f"/world/{note_id}", f"/world/{note_id}.md", f"/world/{note_id}/md",
         f"/{note_id}.md"],
        viewers=(None, get_current_user()),
    )
    return redirect(url_for("world.world_note_get", note_id=note_id))


@bp.route("/world/<note_id>/md", methods=["GET"])
@bp.route("/world/<note_id>.md", methods=["GET"])
@require_feature("world_notes")
@limiter.limit(lambda: f"{config.GET_RATE_MAX} per {config.GET_RATE_WINDOW} second")
@cache.cached(timeout=config.CACHE_TIMEOUT_NOTES, make_cache_key=page_cache_key)
def world_md(note_id):
    check_note_id(note_id)
    content = read_note("public", note_id)
    lang = getattr(g, "lang", "zh")
    return render_template(
        "notes/note_md.html",
        note_id=note_id,
        # 公开笔记里的 #id 快捷引用解析到其它公开笔记（#87）
        html_content=render_markdown_html(
            content, ref_namespace="public", ref_url_prefix="/world"),
        title_label=t(lang, "note_public_prefix"),
        back_url=url_for("world.world_note_get", note_id=note_id),
        back_label=t(lang, "md_back_edit"),
        latex_head=render_latex_head(),
    )