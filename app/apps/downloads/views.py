"""桌面客户端下载：/downloads 落地页、安装包下载与客户端更新检查清单。

落地页匿名可读并经页面缓存。安装包有两种来源：本地投放时用
send_file(conditional=True) 流式发送（支持 Range 断点续传、nosniff 与
Content-Disposition: attachment）；远程清单（GitHub Releases）模式只返回 302，
让浏览器直连 CDN/Release 资产，避免安装包流量经过应用服务器。
"""
from flask import Blueprint, abort, g, jsonify, redirect, render_template, request, send_file

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
        artifact["size_text"] = format_size(artifact["size"]) if artifact["size"] else ""
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
    # 远程清单：只做 302，让浏览器直连 Release/CDN，不让安装包流量过本机
    remote_url = artifact.get("remote_url")
    if remote_url:
        response = redirect(remote_url, code=302)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response
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
    # 优先使用配置的站点外部基址；未配置时才退回请求 Host（清单只含下载地址）
    root = (config.SITE_BASE_URL or request.url_root).rstrip("/")
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