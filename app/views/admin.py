"""功能开关管理（#90）：/admin/features 滑块开关

仅管理员（config.json admin_users / 环境变量 RUSIN_ADMIN）可访问；
非管理员一律 404，不泄漏管理页存在。切换保存后立即生效并整体清空
页面缓存（首页/犇犇等缓存页含有旧的功能入口卡片）。
"""
from flask import Blueprint, abort, redirect, render_template, request, url_for

from .. import config
from ..extensions import cache, limiter
from ..feature_flags import FEATURE_KEYS, get_all_features, is_admin, set_flags
from ..middleware import get_current_user

bp = Blueprint("admin", __name__)


def _require_admin() -> str:
    user = get_current_user()
    if not user or not is_admin(user):
        abort(404)
    return user


@bp.route("/admin/features", methods=["GET"])
@limiter.limit(lambda: f"{config.GET_RATE_MAX} per {config.GET_RATE_WINDOW} second")
def features_get():
    _require_admin()
    return render_template(
        "admin/features.html",
        features=get_all_features(),
        saved=request.args.get("saved") == "1",
    )


@bp.route("/admin/features", methods=["POST"])
@limiter.limit(lambda: f"{config.RATE_MAX} per {config.RATE_WINDOW} second")
def features_post():
    _require_admin()
    # 复选框未勾选时不提交该键，等价于停用
    state = {key: request.form.get(f"flag_{key}") == "1" for key in FEATURE_KEYS}
    if not set_flags(state):
        abort(500)
    cache.clear()
    return redirect(url_for("admin.features_get", saved="1"))
