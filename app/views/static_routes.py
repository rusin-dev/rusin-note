"""静态资源路由：/favicon.ico"""
from flask import Blueprint, abort, Response

from ..theme import get_favicon

bp = Blueprint("static_routes", __name__)


@bp.route("/favicon.ico")
def favicon():
    data = get_favicon()
    if not data:
        abort(404)
    return Response(data, mimetype="image/x-icon")