"""内置静态资源 App：/favicon.ico 与 /image/<name>（logo 等）。

用户图床与附件分别在 images / attachments App 中服务。
"""
import os
import re

from flask import Blueprint, Response, abort

from app.core.theme import get_favicon

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
    """服务 app/static/image/ 目录下的静态资源（logo 等）"""
    if not _STATIC_NAME_RE.match(name):
        abort(404)
    static_root = os.path.realpath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "static", "image")
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
