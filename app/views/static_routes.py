"""静态资源路由：/favicon.ico、/image/（站点静态图 + 用户图床）、/attachment/（用户附件）"""
import os
import re

from flask import Blueprint, abort, Response

from .. import config
from ..attachments import attachment_content_type, read_attachment, read_attachment_meta, validate_attachment_id
from ..extensions import limiter
from ..images import image_mimetype, read_image, validate_image_id
from ..notes import validate_username
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


@bp.route("/image/<username>/<image_id>")
@limiter.limit(lambda: f"{config.GET_RATE_MAX} per {config.GET_RATE_WINDOW} second")
def user_image(username, image_id):
    """用户图床图片（笔记内 Markdown 引用）。

    公开可读、不设登录：分享链接 / 公开笔记 / 只读页都要能渲染图片，
    访问控制依赖 image_id 的随机不可猜性（与分享 token 同一模型）。
    不挂 require_feature——功能停用时已写入笔记的图片不应集体裂图。
    ID 不可变，允许浏览器长缓存。"""
    if not validate_username(username) or not validate_image_id(image_id):
        abort(404)
    data = read_image(username, image_id)
    if not data:
        abort(404)
    resp = Response(data, mimetype=image_mimetype(image_id))
    resp.headers["Cache-Control"] = "public, max-age=86400"
    return resp


@bp.route("/attachment/<username>/<attachment_id>")
@limiter.limit(lambda: f"{config.GET_RATE_MAX} per {config.GET_RATE_WINDOW} second")
def user_attachment(username, attachment_id):
    """用户附件（笔记内 Markdown 链接）。

    公开可读、不设登录：分享链接 / 公开笔记 / 只读页都要能下载附件，
    访问控制依赖 attachment_id 的随机不可猜性（与分享 token 同一模型）。
    不挂 require_feature——功能停用时已写入笔记的附件不应集体失效。
    ID 不可变，允许浏览器长缓存。"""
    if not validate_username(username) or not validate_attachment_id(attachment_id):
        abort(404)
    data = read_attachment(username, attachment_id)
    if not data:
        abort(404)
    # 读取元数据获取 filename 和 content_type
    meta = read_attachment_meta(username, attachment_id)
    if meta:
        filename = meta.get("filename", attachment_id)
        content_type = meta.get("content_type", "application/octet-stream")
    else:
        filename = attachment_id
        content_type = attachment_content_type(attachment_id)
    resp = Response(data, mimetype=content_type)
    resp.headers["Cache-Control"] = "public, max-age=86400"
    # 设置 Content-Disposition 以便浏览器下载
    resp.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    return resp
