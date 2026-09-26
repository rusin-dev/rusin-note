"""静态资源路由：/favicon.ico、/image/<name>（内置静态资源）、/image/<username>/<id>（用户图床）、/attachment/<username>/<id>（用户附件）

附件（``/attachment/<u>/<id>``）访问约定（#191）：
- **默认禁止匿名下载**（config：``attachments.allow_anonymous_download=false``），
  未登录访客返回 401；
- **单用户同时下载限制 1 个队列**（config：``attachments.max_concurrent_downloads``，
  默认 1），超出返回 429 + ``Retry-After``——这是针对「发起上千个慢速连接
  （如 1KB/s）、或用 100 线程同时下载 100 个文件」的防护，IP 限流（单位时间
  请求数）拦不住这种模式；超限直接拒绝而非排队（排队同样占用 worker）；
- 下载按块产出，响应结束或客户端中断即释放并发名额（见 app/concurrency.py）；
- 响应缓存为 ``private``，避免共享缓存把需登录的附件回放给未登录访客。
"""
import os
import re

from flask import Blueprint, Response, abort, g

from .. import config
from ..attachments import (
    read_attachment,
    read_attachment_meta,
    stream_attachment,
    try_acquire_download,
    validate_attachment_id,
)
from ..extensions import limiter
from ..i18n import t
from ..images import read_image, validate_image_id
from ..logger import create_logger
from ..theme import get_favicon

bp = Blueprint("static_routes", __name__)

logger = create_logger("static_routes")


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


_USERNAME_RE = re.compile(r"^[a-zA-Z0-9_\-]+$")


def _content_disposition(filename: str) -> str:
    """构造 Content-Disposition：过滤引号/反斜杠/控制字符，避免响应头被破坏"""
    safe = re.sub(r'[\x00-\x1f\x7f"\\]', "_", str(filename or "")) or "attachment"
    return f'inline; filename="{safe}"'


@bp.route("/attachment/<username>/<attachment_id>")
@limiter.limit(lambda: f"{config.ATTACHMENT_DOWNLOAD_RATE_MAX} per "
                       f"{config.ATTACHMENT_DOWNLOAD_RATE_WINDOW} second")
def attachment_user(username, attachment_id):
    """服务用户附件（/attachment/<username>/<id>）

    未登录访客默认被拒（401）；通过认证后受「单用户同时下载上限」约束，
    超出返回 429（附 Retry-After），避免单个账号用大量慢速连接占满 worker。
    """
    lang = getattr(g, "lang", "zh")
    if not _USERNAME_RE.match(username):
        abort(404)
    if not validate_attachment_id(attachment_id):
        abort(404)

    viewer = getattr(g, "current_user", None)
    if not viewer and not config.ATTACHMENTS_ALLOW_ANONYMOUS_DOWNLOAD:
        logger.warning("匿名下载附件被拒绝：ip=%s path=/attachment/%s/%s",
                       getattr(g, "client_ip", "?"), username, attachment_id)
        abort(401, description=t(lang, "err_attachment_download_login_required"))

    slot = try_acquire_download(viewer, getattr(g, "client_ip", None))
    if slot is None:
        abort(429, description=t(lang, "err_attachment_download_busy",
                                 max=config.MAX_CONCURRENT_ATTACHMENT_DOWNLOADS))

    try:
        data = read_attachment(username, attachment_id)
        if data is None:
            abort(404)
        meta = read_attachment_meta(username, attachment_id)
        content_type = meta.get("content_type", "application/octet-stream") if meta else "application/octet-stream"
        filename = meta.get("filename", attachment_id) if meta else attachment_id
        resp = Response(stream_attachment(data, slot), mimetype=content_type)
        resp.headers["Content-Disposition"] = _content_disposition(filename)
        resp.headers["Content-Length"] = str(len(data))
        # 附件需登录才能下载：只能私有缓存（public 会被共享缓存回放给未登录访客）
        resp.headers["Cache-Control"] = "private, max-age=86400"
        # 兜底释放：正常传完由生成器 finally 释放，这里覆盖「响应被提前关闭」的路径
        resp.call_on_close(slot.release)
        return resp
    except Exception:
        # 出错/404/任何异常都必须归还名额，否则该用户会被永久占用一个槽位
        slot.release()
        raise


