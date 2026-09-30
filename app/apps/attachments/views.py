"""笔记附件 App：管理页 /user/<u>/attachments、编辑器上传 API 与下载服务 /attachment/<u>/<id>

附件业务逻辑（类型校验 / 配额 / 读写 / 并发闸门）见 app.apps.attachments.service。

附件（``/attachment/<u>/<id>``）访问约定（#191）：
- **默认禁止匿名下载**（config：``attachments.allow_anonymous_download=false``），
  未登录访客返回 401；
- **单用户同时下载限制 1 个队列**（config：``attachments.max_concurrent_downloads``，
  默认 1），超出返回 429 + ``Retry-After``——这是针对「发起上千个慢速连接
  （如 1KB/s）、或用 100 线程同时下载 100 个文件」的防护，IP 限流（单位时间
  请求数）拦不住这种模式；超限直接拒绝而非排队（排队同样占用 worker）；
- 下载按块产出，响应结束或客户端中断即释放并发名额（见 app/core/concurrency.py）；
- 响应缓存为 ``private``，避免共享缓存把需登录的附件回放给未登录访客。

当前下载权限策略为「登录用户凭链接即可下载」（只拦匿名），如需「仅本人可下载」
须在 attachment_user 中补所有权校验。
"""
import re

from flask import (
    Blueprint, Response, abort, g, jsonify, redirect, render_template, request, url_for,
)

from app.core import config
from app.core.extensions import limiter
from app.core.feature_flags import require_feature
from app.core.i18n import t
from app.core.logger import create_logger
from app.core.notes import validate_username
from app.core.utils import format_note_time, format_size
from app.apps.attachments.service import (
    attachment_content_type,
    attachment_url,
    delete_attachment,
    generate_attachment_id,
    get_attachment_mtime,
    get_attachment_size,
    list_user_attachments,
    note_attachment_quota_ok,
    read_attachment,
    read_attachment_meta,
    stream_attachment,
    try_acquire_download,
    try_acquire_upload,
    user_attachment_usage,
    validate_attachment_id,
    validate_attachment_type,
    write_attachment,
)
from app.apps.common.helpers import require_auth

bp = Blueprint("attachments", __name__)

logger = create_logger("attachments")

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

    与图床一致，刻意不加 @require_feature("note_attachments")：停用开关只关上传
    与管理入口，已有附件要继续可下载。
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


# ---------- 笔记附件：/user/<u>/attachments（管理页 + 编辑器上传 API） ----------
# 必须注册在 /user/<username>/<note_id> 之前，否则 attachments 会被当作笔记 ID
@bp.route("/user/<username>/attachments", methods=["GET"])
@require_feature("note_attachments")
@limiter.limit(lambda: f"{config.GET_RATE_MAX} per {config.GET_RATE_WINDOW} second")
def attachments_page(username):
    if not validate_username(username):
        abort(400)
    require_auth(username)
    return _render_attachments(username, error="")


@bp.route("/user/<username>/attachments", methods=["POST"])
@require_feature("note_attachments")
@limiter.limit(lambda: f"{config.RATE_MAX} per {config.RATE_WINDOW} second")
def attachments_upload(username):
    """编辑器上传附件（multipart，file 字段 + csrf_token）：
    校验链：类型黑名单 → 单文件大小 → 单笔记配额（携带编辑器内容时）→ 用户配额。
    成功返回 JSON {url, name, id}。

    #191：读取请求体（慢速上传的耗时段）之前先占用「单用户并发上传」槽位（默认 1 个），
    慢速连接（如 1KB/s）会长期占用 worker，仅靠单位时间请求数限流拦不住；
    超出并发上限时中止读取并直接返回 429 JSON（供编辑器 fetch 展示）。
    """
    if not validate_username(username):
        abort(400)
    require_auth(username)
    lang = getattr(g, "lang", "zh")
    slot = try_acquire_upload(username)
    if slot is None:
        # 直接返回 JSON（编辑器 fetch 需要），并提示客户端稍后重试
        resp = jsonify({"error": t(lang, "err_attachment_upload_busy",
                                   max=config.MAX_CONCURRENT_ATTACHMENT_UPLOADS)})
        resp.headers["Retry-After"] = "1"
        return resp, 429
    try:
        file = request.files.get("file")
        if not file or not file.filename:
            return jsonify({"error": t(lang, "err_attachment_no_file")}), 400

        from werkzeug.utils import secure_filename
        filename = secure_filename(file.filename) or "unnamed"

        # 类型校验（黑名单）
        is_valid, error_key = validate_attachment_type(filename)
        if not is_valid:
            return jsonify({"error": t(lang, error_key)}), 400

        # 读取数据
        data = file.read()
        if not data:
            return jsonify({"error": t(lang, "err_attachment_empty")}), 400

        # 大小校验（单个文件）
        if len(data) > config.MAX_ATTACHMENT_SIZE_BYTES:
            return jsonify({"error": t(lang, "err_attachment_too_large",
                                       max=config.MAX_ATTACHMENT_SIZE_KB)}), 400

        # 单笔记配额校验（编辑器上传会携带当前内容，用于估算插入后的附件总量）
        editor_content = request.form.get("content", "")
        if editor_content and not note_attachment_quota_ok(username, editor_content, len(data)):
            return jsonify({"error": t(lang, "err_attachment_note_quota",
                                       total=config.MAX_ATTACHMENT_PER_NOTE_KB)}), 400

        # 配额校验（用户总量）
        if user_attachment_usage(username) + len(data) > config.MAX_ATTACHMENT_TOTAL_BYTES:
            return jsonify({"error": t(lang, "err_attachment_quota",
                                       total=f"{config.MAX_ATTACHMENT_TOTAL_KB} KB")}), 400

        # 生成 ID
        attachment_id = generate_attachment_id(filename)

        # 写入存储
        content_type = attachment_content_type(filename)
        if not write_attachment(username, attachment_id, data, filename, content_type):
            return jsonify({"error": t(lang, "err_attachment_upload")}), 500

        return jsonify({
            "url": attachment_url(username, attachment_id),
            "name": filename,
            "id": attachment_id,
        })
    finally:
        slot.release()


@bp.route("/user/<username>/attachments/delete", methods=["POST"])
@require_feature("note_attachments")
@limiter.limit(lambda: f"{config.RATE_MAX} per {config.RATE_WINDOW} second")
def attachments_delete(username):
    if not validate_username(username):
        abort(400)
    require_auth(username)
    attachment_id = request.form.get("attachment_id", "").strip()
    if not validate_attachment_id(attachment_id):
        abort(400)
    if not delete_attachment(username, attachment_id):
        return _render_attachments(username, error=t(getattr(g, "lang", "zh"),
                                                     "err_attachment_upload")), 400
    return redirect(url_for("attachments.attachments_page", username=username))


def _render_attachments(username, error):
    lang = getattr(g, "lang", "zh")
    rows = []
    for attachment_id in list_user_attachments(username):
        meta = read_attachment_meta(username, attachment_id)
        mtime = get_attachment_mtime(username, attachment_id)
        size = get_attachment_size(username, attachment_id)
        rows.append({
            "id": attachment_id,
            "url": attachment_url(username, attachment_id),
            "filename": meta.get("filename", attachment_id) if meta else attachment_id,
            "content_type": meta.get("content_type", "application/octet-stream") if meta else "application/octet-stream",
            "mtime": format_note_time(mtime) if mtime else "",
            "size": format_size(size) if size is not None else "",
        })
    rows.sort(key=lambda r: r["filename"])
    usage_text = t(lang, "attachments_usage",
                   used=format_size(user_attachment_usage(username)),
                   total=format_size(config.MAX_ATTACHMENT_TOTAL_BYTES),
                   count=len(rows))
    return render_template(
        "attachments/attachment_list.html",
        username=username,
        rows=rows,
        usage_text=usage_text,
        error=error,
        max_size_kb=config.MAX_ATTACHMENT_SIZE_KB,
    )
