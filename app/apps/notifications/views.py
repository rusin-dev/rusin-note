"""站内通知页面与未读 API。"""
from flask import Blueprint, abort, jsonify, redirect, render_template, request, url_for

from app.core import config
from app.core.extensions import limiter
from app.core.notes import validate_username
from app.apps.common.helpers import require_auth
from app.apps.notifications import service

bp = Blueprint("notifications", __name__)


@bp.route("/user/<username>/notifications", methods=["GET"])
@limiter.limit(lambda: f"{config.GET_RATE_MAX} per {config.GET_RATE_WINDOW} second")
def notifications_get(username):
    if not validate_username(username):
        abort(400)
    require_auth(username)
    items = service.list_for_user(username)
    return render_template(
        "notifications/list.html",
        username=username,
        items=items,
        unread=sum(1 for item in items if not item.get("read")),
    )


@bp.route("/user/<username>/notifications/read", methods=["POST"])
@limiter.limit(lambda: f"{config.RATE_MAX} per {config.RATE_WINDOW} second")
def notifications_read(username):
    if not validate_username(username):
        abort(400)
    require_auth(username)
    if request.form.get("all") == "1":
        service.mark_all_read(username)
    else:
        service.mark_read(username, (request.form.get("id") or "").strip())
    return redirect(url_for("notifications.notifications_get", username=username))


@bp.route("/user/<username>/notifications/unread", methods=["GET"])
@limiter.limit(lambda: f"{config.GET_RATE_MAX} per {config.GET_RATE_WINDOW} second")
def notifications_unread(username):
    if not validate_username(username):
        abort(400)
    require_auth(username)
    return jsonify({"count": service.unread_count(username)})
