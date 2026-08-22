"""私有笔记与分享管理：/user/<u>、/user/<u>/<id>、/user/<u>/shares/*"""
import re
from flask import Blueprint, abort, g, jsonify, redirect, render_template, request, url_for

from .. import config
from ..extensions import cache, limiter
from ..i18n import t
from ..feature_flags import feature_enabled, require_feature
from ..middleware import get_current_user
from ..notes import (
    generate_random_id,
    get_note_mtime,
    get_note_size,
    list_user_notes,
    note_exists,
    read_note,
    search_user_notes,
    validate_note_id,
    validate_username,
    write_note,
)
from ..folders import (
    get_note_folder,
    get_user_note_folders,
    list_user_folders,
    parse_folder_input,
    set_note_folder,
)
from ..pins import get_user_pins, toggle_note_pin
from ..store import (
    create_share,
    delete_share,
    list_user_shares,
)
from ..tags import (
    count_user_tags,
    get_note_tags,
    get_user_note_tags,
    parse_tag_input,
    set_note_tags,
)
from ..utils import format_note_time, format_size, render_latex_head, render_markdown_html
from ._helpers import build_note_context, check_note_id, page_cache_key, purge_page_cache


bp = Blueprint("user", __name__)


def _require_auth(username: str):
    if get_current_user() != username:
        abort(401)


def _list_view_filtered() -> bool:
    """?tag= / ?folder= 筛选视图不缓存：置顶切换、标签/文件夹保存等写操作
    只清理未过滤的基础缓存键，筛选变体若参与缓存会向刚操作完的用户展示
    过期内容（写后立即可见优先于这部分缓存收益；未过滤列表仍正常缓存）。"""
    return bool((request.args.get("tag") or "").strip()
                or (request.args.get("folder") or "").strip())


@bp.route("/user/<username>", methods=["GET"])
@bp.route("/user/<username>/", methods=["GET"])
@limiter.limit(lambda: f"{config.GET_RATE_MAX} per {config.GET_RATE_WINDOW} second")
@cache.cached(timeout=config.CACHE_TIMEOUT_NOTES, make_cache_key=page_cache_key,
              unless=_list_view_filtered)
def user_root(username):
    if not validate_username(username):
        abort(400)
    _require_auth(username)
    notes = list_user_notes(username)
    # 笔记标签 / 文件夹 / 置顶（仅私有笔记）：筛选云 + ?tag= / ?folder= 组合筛选
    tags_enabled = feature_enabled("note_tags")
    folders_enabled = feature_enabled("note_folders")
    pins_enabled = feature_enabled("note_pins")
    user_tags = get_user_note_tags(username) if tags_enabled else {}
    user_folders = get_user_note_folders(username) if folders_enabled else {}
    user_pins = get_user_pins(username) if pins_enabled else {}
    tag_cloud = count_user_tags(username, note_ids=set(notes)) if tags_enabled else []
    folder_cloud = list_user_folders(username, note_ids=set(notes)) if folders_enabled else []
    active_tag = (request.args.get("tag") or "").strip()[:config.MAX_TAG_LENGTH] if tags_enabled else ""
    active_folder = (request.args.get("folder") or "").strip()[:config.MAX_FOLDER_NAME_LENGTH] if folders_enabled else ""
    # 排序：置顶笔记在前（组内按置顶时间倒序），其余按修改时间倒序
    rows = []
    for nid in notes:
        if active_tag and active_tag not in user_tags.get(nid, []):
            continue
        if active_folder and user_folders.get(nid) != active_folder:
            continue
        rows.append((nid, get_note_mtime(username, nid) or 0, get_note_size(username, nid)))
    rows.sort(key=lambda r: (1, user_pins.get(r[0], 0)) if r[0] in user_pins else (0, r[1]),
              reverse=True)
    items = []
    for nid, mtime, size in rows:
        items.append({
            "id": nid,
            "mtime": format_note_time(mtime) if mtime else "",
            "size": format_size(size) if size is not None else "",
            "tags": user_tags.get(nid, []),
            "folder": user_folders.get(nid, "") if folders_enabled else "",
            "pinned": nid in user_pins,
        })
    return render_template(
        "notes/user_list.html",
        username=username,
        items=items,
        tags_enabled=tags_enabled,
        tag_cloud=tag_cloud,
        active_tag=active_tag,
        folders_enabled=folders_enabled,
        folder_cloud=folder_cloud,
        active_folder=active_folder,
        pins_enabled=pins_enabled,
    )


@bp.route("/user/<username>/new", methods=["GET"])
@limiter.limit(lambda: f"{config.GET_RATE_MAX} per {config.GET_RATE_WINDOW} second")
def user_new(username):
    if not validate_username(username):
        abort(400)
    _require_auth(username)
    new_id = generate_random_id()
    return redirect(url_for("user.user_note_get", username=username, note_id=new_id))


@bp.route("/user/<username>/refs", methods=["GET"])
@limiter.limit(lambda: f"{config.GET_RATE_MAX} per {config.GET_RATE_WINDOW} second")
def user_refs_search(username):
    """快捷引用搜索 API（#87）：返回当前用户笔记中 ID / 首行标题匹配 q 的笔记。

    必须注册在 /user/<username>/<note_id> 之前，否则 refs 会被当作笔记 ID。
    结果含笔记标题，不缓存（按查询词与登录用户隔离）。
    """
    if not validate_username(username):
        abort(400)
    _require_auth(username)
    if not feature_enabled("note_refs"):
        abort(404)
    q = (request.args.get("q") or "").strip()[:64]
    return jsonify({"items": search_user_notes(username, q)})


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
    # 快捷引用（#87）：仅在自己的笔记编辑页启用 # 自动补全与预览链接化
    note_refs = None
    if feature_enabled("note_refs"):
        note_refs = {
            "api": url_for("user.user_refs_search", username=username),
            "ids": list_user_notes(username),
            "prefix": f"/user/{username}",
        }
    # 笔记标签 / 文件夹（仅私有笔记编辑页；world/share 复用本模板但不启用）
    note_tags_enabled = feature_enabled("note_tags")
    note_tags_value = ", ".join(get_note_tags(username, note_id)) if note_tags_enabled else ""
    note_folders_enabled = feature_enabled("note_folders")
    note_folder_value = get_note_folder(username, note_id) if note_folders_enabled else ""
    folder_options = sorted({f for f in get_user_note_folders(username).values() if f}) \
        if note_folders_enabled else []
    return render_template(
        "notes/note_edit.html",
        note_id=note_id,
        username=username,
        content=content,
        is_world=False,
        action_url=url_for("user.user_note_post", username=username, note_id=note_id),
        note_refs=note_refs,
        note_tags_enabled=note_tags_enabled,
        note_tags_value=note_tags_value,
        note_folders_enabled=note_folders_enabled,
        note_folder_value=note_folder_value,
        folder_options=folder_options,
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
    # 标签与文件夹随内容一起保存；内容为空即删除笔记，两者已由 write_note
    # 的删除钩子清理，这里只更新仍存在笔记的归属
    if content:
        if feature_enabled("note_tags"):
            set_note_tags(username, note_id, parse_tag_input(request.form.get("tags", "")))
        if feature_enabled("note_folders"):
            set_note_folder(username, note_id, parse_folder_input(request.form.get("folder", "")))
    # 私有页缓存键按访问者隔离，且只有所有者能写入 200 缓存，清理即精确命中；
    # /user/<username> 笔记列表也依赖笔记内容（mtime/size），一并刷新
    purge_page_cache(
        [f"/user/{username}", f"/user/{username}/",
         f"/user/{username}/{note_id}", f"/user/{username}/{note_id}/",
         f"/user/{username}/{note_id}.md", f"/user/{username}/{note_id}/md"],
        viewers=(username,),
    )
    return redirect(url_for("user.user_note_get", username=username, note_id=note_id))


@bp.route("/user/<username>/<note_id>/pin", methods=["POST"])
@require_feature("note_pins")
@limiter.limit(lambda: f"{config.RATE_MAX} per {config.RATE_WINDOW} second")
def user_note_pin(username, note_id):
    """列表页图钉开关：切换置顶状态后回到列表页（保留 tag/folder 筛选）。"""
    if not validate_username(username):
        abort(400)
    check_note_id(note_id)
    _require_auth(username)
    if not note_exists(username, note_id):
        abort(404)
    toggle_note_pin(username, note_id)
    purge_page_cache([f"/user/{username}", f"/user/{username}/"], viewers=(username,))
    args = {}
    for param in ("tag", "folder"):
        value = (request.form.get(param) or "").strip()
        if value:
            args[param] = value
    return redirect(url_for("user.user_root", username=username, **args))


@bp.route("/user/<username>/<note_id>/md", methods=["GET"])
@bp.route("/user/<username>/<note_id>.md", methods=["GET"])
@limiter.limit(lambda: f"{config.GET_RATE_MAX} per {config.GET_RATE_WINDOW} second")
@cache.cached(timeout=config.CACHE_TIMEOUT_NOTES, make_cache_key=page_cache_key)
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
        html_content=render_markdown_html(
            content, ref_namespace=username, ref_url_prefix=f"/user/{username}"),
        title_label=t(lang, "note_private_prefix"),
        back_url=url_for("user.user_note_get", username=username, note_id=note_id),
        back_label=t(lang, "md_back_edit"),
        latex_head=render_latex_head(),
        username=username,
    )


@bp.route("/user/<username>/shares", methods=["GET"])
@bp.route("/user/<username>/shares/", methods=["GET"])
@require_feature("share_links")
@limiter.limit(lambda: f"{config.GET_RATE_MAX} per {config.GET_RATE_WINDOW} second")
def shares_get(username):
    if not validate_username(username):
        abort(400)
    _require_auth(username)
    return _render_shares(username, error="")


@bp.route("/user/<username>/shares", methods=["POST"])
@bp.route("/user/<username>/shares/", methods=["POST"])
@require_feature("share_links")
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
    purge_page_cache([f"/user/{username}/shares", f"/user/{username}/shares/"],
                     viewers=(username,))
    return redirect(url_for("user.shares_get", username=username))


@bp.route("/user/<username>/shares/delete", methods=["POST"])
@require_feature("share_links")
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
    purge_page_cache([f"/user/{username}/shares", f"/user/{username}/shares/"],
                     viewers=(username,))
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