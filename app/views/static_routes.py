"""静态资源路由：/favicon.ico、/image/<name>（内置静态资源）、/image/<username>/<id>（用户图床）、/attachment/<username>/<id>（用户附件）"""
import os
import re
import stat

from flask import Blueprint, abort, request, Response

from .. import config
from ..attachments import read_attachment, read_attachment_meta, validate_attachment_id
from ..images import read_image, validate_image_id
from ..theme import get_favicon

bp = Blueprint("static_routes", __name__)


@bp.route("/favicon.ico")
def favicon():
    data = get_favicon()
    if not data:
        abort(404)
    return Response(data, mimetype="image/x-icon")


_STATIC_NAME_RE = re.compile(r"^[a-zA-Z0-9_\-]+\.(png|jpg|jpeg|gif|svg|ico|webp)$")


@bp.route("/image/<name>")
def image_static(name):
    """服务仓库 image/ 目录下的静态资源（logo 等）"""
    if not _STATIC_NAME_RE.match(name):
        abort(404)
    static_root = os.path.realpath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "image")
    )
    static_path = os.path.realpath(os.path.join(static_root, name))
    if static_path.startswith(static_root + os.sep):
        if os.path.isfile(static_path):
            with open(static_path, "rb") as f:
                data = f.read()
            mimetype = {
                ".png": "image/png",
                ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg",
                ".gif": "image/gif",
                ".svg": "image/svg+xml",
                ".ico": "image/x-icon",
                ".webp": "image/webp",
            }.get(os.path.splitext(name)[1].lower(), "application/octet-stream")
            return Response(data, mimetype=mimetype)
    abort(404)


@bp.route("/image/<username>/<image_id>")
def image_user(username, image_id):
    """服务用户图床图片（/image/<username>/<id>）"""
    if not re.match(r"^[a-zA-Z0-9_\-]+$", username):
        abort(404)
    if not validate_image_id(image_id):
        abort(404)
    data = read_image(username, image_id)
    if data is None:
        abort(404)
    from ..images import image_mimetype
    resp = Response(data, mimetype=image_mimetype(image_id))
    resp.headers["Cache-Control"] = "public, max-age=86400"
    return resp


@bp.route("/attachment/<username>/<attachment_id>")
def attachment_user(username, attachment_id):
    """服务用户附件（/attachment/<username>/<id>）"""
    if not re.match(r"^[a-zA-Z0-9_\-]+$", username):
        abort(404)
    if not validate_attachment_id(attachment_id):
        abort(404)
    data = read_attachment(username, attachment_id)
    if data is None:
        abort(404)
    meta = read_attachment_meta(username, attachment_id)
    content_type = meta.get("content_type", "application/octet-stream") if meta else "application/octet-stream"
    filename = meta.get("filename", attachment_id) if meta else attachment_id
    resp = Response(data, mimetype=content_type)
    resp.headers["Content-Disposition"] = f'inline; filename="{filename}"'
    resp.headers["Cache-Control"] = "public, max-age=86400"
    return resp


