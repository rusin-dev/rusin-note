"""静态资源路由：/favicon.ico、/image/"""
import os
import re

from flask import Blueprint, abort, Response

from ..theme import get_favicon

bp = Blueprint("static_routes", __name__)


@bp.route("/favicon.ico")
def favicon():
    data = get_favicon()
    if not data:
        abort(404)
    return Response(data, mimetype="image/x-icon")


_IMAGE_NAME_RE = re.compile(r"^[a-zA-Z0-9_\-]+\.(png|jpg|jpeg|gif|svg|ico|webp)$")


@bp.route("/image/<name>")
def image(name):
    if not _IMAGE_NAME_RE.match(name):
        abort(404)
    path = os.path.join("image", name)
    if not os.path.isfile(path):
        abort(404)
    with open(path, "rb") as f:
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