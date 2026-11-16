"""桌面客户端下载：/downloads 落地页、安装包下载与客户端更新检查清单。

落地页匿名可读并经页面缓存；安装包用 send_file(conditional=True) 流式发送，
支持 Range 断点续传，响应带 nosniff 与 Content-Disposition: attachment。
"""
from flask import Blueprint, abort, g, jsonify, render_template, request, send_file

from app.core import config
from app.core.extensions import cache, limiter
from app.core.feature_flags import is_admin, require_feature
from app.core.i18n import t
from app.core.middleware import get_current_user
from app.core.utils import format_size
from app.apps.common.helpers import page_cache_key
from app.apps.downloads import service

bp = Blueprint("downloads", __name__)


def _not_found():
    abort(404, description=t(getattr(g, "lang", "zh"), "downloads_err_not_found"))


@bp.route("/downloads")
@require_feature("downloads")
@limiter.limit(lambda: f"{config.GET_RATE_MAX} per {config.GET_RATE_WINDOW} second")
@cache.cached(timeout=config.CACHE_DEFAULT_TIMEOUT, make_cache_key=page_cache_key)
def downloads_page():
    manifest = service.read_manifest()
    artifacts = manifest["artifacts"]
    for artifact in artifacts:
        artifact["size_text"] = format_size(artifact["size"])
    user = get_current_user()
    lang = getattr(g, "lang", "zh")
    return render_template(
        "downloads.html",
        title=t(lang, "downloads_title"),
        manifest=manifest,
        artifacts=artifacts,
        platforms=service.PLATFORMS,
        show_admin_hint=bool(user and is_admin(user)),
    )


@bp.route("/downloads/file/<artifact_id>")
@require_feature("downloads")
@limiter.limit(lambda: f"{config.DOWNLOADS_RATE_MAX} per {config.DOWNLOADS_RATE_WINDOW} second")
def downloads_file(artifact_id):
    artifact = service.get_artifact(artifact_id)
    if artifact is None:
        _not_found()
    path = service.resolve_file(artifact)
    if path is None:
        _not_found()
    response = send_file(
        path,
        as_attachment=True,
        download_name=artifact["file"],
        mimetype="application/octet-stream",
        conditional=True,
        max_age=86400,
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@bp.route("/downloads/manifest.json")
@require_feature("downloads")
@limiter.limit(lambda: f"{config.GET_RATE_MAX} per {config.GET_RATE_WINDOW} second")
def downloads_manifest():
    """客户端更新检查：产物 url 给绝对地址，桌面端无需自己拼站点前缀。"""
    manifest = service.read_manifest()
    root = request.url_root.rstrip("/")
    response = jsonify({
        "version": manifest["version"],
        "channel": manifest["channel"],
        "released_at": manifest["released_at"],
        "notes": manifest["notes"],
        "artifacts": [
            {
                "id": a["id"], "platform": a["platform"], "arch": a["arch"],
                "file": a["file"], "size": a["size"], "sha256": a["sha256"],
                "url": root + a["url"],
            }
            for a in manifest["artifacts"]
        ],
    })
    response.headers["Cache-Control"] = "public, max-age=60"
    return response