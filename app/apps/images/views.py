"""笔记图床 App：管理页 /user/<u>/images 与公开服务 /image/<u>/<id>

图床业务逻辑（校验/配额/存储）见 app.apps.images.service。
"""
import re

from flask import (
    Blueprint, Response, abort, g, jsonify, redirect, render_template, request, url_for,
)

from app.core import config
from app.core.extensions import limiter
from app.core.feature_flags import require_feature
from app.core.i18n import t
from app.core.notes import validate_username
from app.core.utils import format_note_time, format_size
from app.apps.images.service import (
    delete_image,
    generate_image_id,
    get_image_mtime,
    get_image_size,
    image_mimetype,
    image_url,
    list_user_images,
    read_image,
    sniff_image_format,
    user_image_usage,
    validate_image_id,
    write_image,
)
from app.apps.common.helpers import require_auth

bp = Blueprint("images", __name__)

_USERNAME_RE = re.compile(r"^[a-zA-Z0-9_\-]+$")


@bp.route("/image/<username>/<image_id>")
def image_user(username, image_id):
    """服务用户图床图片（/image/<username>/<id>）"""
    if not _USERNAME_RE.match(username):
        abort(404)
    if not validate_image_id(image_id):
        abort(404)
    data = read_image(username, image_id)
    if data is None:
        abort(404)
    resp = Response(data, mimetype=image_mimetype(image_id))
    resp.headers["Cache-Control"] = "public, max-age=86400"
    return resp


# ---------- 笔记图床管理：/user/<u>/images（管理页 + 编辑器上传 API） ----------
# 必须注册在 /user/<username>/<note_id> 之前，否则 images 会被当作笔记 ID
@bp.route("/user/<username>/images", methods=["GET"])
@require_feature("note_images")
@limiter.limit(lambda: f"{config.GET_RATE_MAX} per {config.GET_RATE_WINDOW} second")
def images_page(username):
    if not validate_username(username):
        abort(400)
    require_auth(username)
    return _render_images(username, error="")


@bp.route("/user/<username>/images", methods=["POST"])
@require_feature("note_images")
@limiter.limit(lambda: f"{config.RATE_MAX} per {config.RATE_WINDOW} second")
def images_upload(username):
    """编辑器粘贴/拖拽上传（multipart，file 字段 + csrf_token）：
    校验链 魔数 → 单图大小 → 用户配额，成功返回 JSON {url, name}。"""
    if not validate_username(username):
        abort(400)
    require_auth(username)
    lang = getattr(g, "lang", "zh")
    file = request.files.get("file")
    data = file.read() if file is not None else b""
    ext = sniff_image_format(data)
    if ext is None:
        return jsonify({"error": t(lang, "err_image_format")}), 400
    if len(data) > config.MAX_IMAGE_SIZE_BYTES:
        return jsonify({"error": t(lang, "err_image_too_large",
                                   max=config.MAX_IMAGE_SIZE_KB)}), 400
    if user_image_usage(username) + len(data) > config.MAX_IMAGE_TOTAL_BYTES:
        return jsonify({"error": t(lang, "err_image_quota",
                                   total=f"{config.MAX_IMAGE_TOTAL_KB} KB")}), 400
    image_id = generate_image_id(ext)
    if not write_image(username, image_id, data):
        return jsonify({"error": t(lang, "err_image_upload")}), 500
    return jsonify({"url": image_url(username, image_id), "name": image_id})


@bp.route("/user/<username>/images/delete", methods=["POST"])
@require_feature("note_images")
@limiter.limit(lambda: f"{config.RATE_MAX} per {config.RATE_WINDOW} second")
def images_delete(username):
    if not validate_username(username):
        abort(400)
    require_auth(username)
    image_id = request.form.get("image_id", "").strip()
    if not validate_image_id(image_id):
        abort(400)
    if not delete_image(username, image_id):
        return _render_images(username, error=t(getattr(g, "lang", "zh"),
                                                "err_image_upload")), 400
    return redirect(url_for("images.images_page", username=username))


def _render_images(username, error):
    lang = getattr(g, "lang", "zh")
    rows = []
    for image_id in list_user_images(username):
        mtime = get_image_mtime(username, image_id)
        size = get_image_size(username, image_id)
        rows.append({
            "id": image_id,
            "url": image_url(username, image_id),
            "mtime": format_note_time(mtime) if mtime else "",
            "size": format_size(size) if size is not None else "",
        })
    rows.sort(key=lambda r: r["id"])
    usage_text = t(lang, "images_usage",
                   used=format_size(user_image_usage(username)),
                   total=format_size(config.MAX_IMAGE_TOTAL_BYTES),
                   count=len(rows))
    return render_template(
        "images/image_list.html",
        username=username,
        rows=rows,
        usage_text=usage_text,
        error=error,
    )
