"""静态资源路由：/favicon.ico、/image/、/upload"""
import io
import os
import random
import re
from pathlib import Path

from flask import Blueprint, abort, request, Response, jsonify

from .. import config
from ..extensions import limiter
from ..feature_flags import require_feature
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
    # 路径安全校验：name 已受正则约束（仅允许字母数字下划线连字符和后缀名），
    # 在拼接后再用 resolve() + startswith() 做纵深防御，防止符号链接穿越。
    upload_root = Path(config.UPLOAD_DIR).resolve()
    try:
        upload_path = (upload_root / name).resolve()
        if not str(upload_path).startswith(str(upload_root)):
            abort(404)
    except (OSError, ValueError):
        abort(404)
    if upload_path.is_file():
        return Response(upload_path.read_bytes(), mimetype="image/gif")
    # 回退 static image/
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


# ---------- 图片上传路由 ----------
_ALLOWED_IMAGE_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp", "image/bmp"}
_ID_CHARS = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"


def _generate_upload_id() -> str:
    """生成 10 位图片 ID：前缀 i_ + 8 位随机字符"""
    return "i_" + "".join(random.choices(_ID_CHARS, k=8))


def _convert_to_compressed_gif(data: bytes) -> bytes:
    """将图片数据转换为高压缩 GIF（最小体积策略）"""
    from PIL import Image
    img = Image.open(io.BytesIO(data))
    # 转为 RGB（去掉 alpha 通道）
    if img.mode in ("RGBA", "P", "LA"):
        background = Image.new("RGB", img.size, (255, 255, 255))
        if img.mode == "P":
            img = img.convert("RGBA")
        background.paste(img, mask=img.split()[-1] if img.mode == "RGBA" else None)
        img = background
    elif img.mode != "RGB":
        img = img.convert("RGB")
    # 缩小到最大 800px（保持比例）
    max_size = 800
    if max(img.size) > max_size:
        ratio = max_size / max(img.size)
        new_size = (int(img.size[0] * ratio), int(img.size[1] * ratio))
        img = img.resize(new_size, Image.LANCZOS)
    # 量化降色（256 色调色板，大幅压缩）
    img = img.quantize(colors=256, method=Image.Quantize.MEDIANCUT)
    # 输出 GIF
    buf = io.BytesIO()
    img.save(buf, format="GIF", optimize=True)
    return buf.getvalue()


@bp.route("/upload", methods=["POST"])
@limiter.limit(lambda: f"{config.UPLOAD_RATE_MAX} per {config.UPLOAD_RATE_WINDOW} second")
@require_feature("image_upload")
def upload_image():
    """接收图片上传，转换为压缩 GIF，返回访问 URL"""
    if "file" not in request.files:
        return jsonify({"error": "no file provided"}), 400
    file = request.files["file"]
    if not file.filename:
        return jsonify({"error": "empty filename"}), 400
    # 大小校验
    content_length = request.content_length
    if content_length is not None and content_length > config.MAX_UPLOAD_BYTES:
        return jsonify({"error": "file too large"}), 413
    # MIME 类型校验
    mime = file.content_type or ""
    if mime not in _ALLOWED_IMAGE_TYPES:
        return jsonify({"error": "unsupported image type"}), 400
    # 读取数据
    data = file.read()
    if len(data) > config.MAX_UPLOAD_BYTES:
        return jsonify({"error": "file too large"}), 413
    # 转换并压缩为 GIF
    try:
        gif_data = _convert_to_compressed_gif(data)
    except Exception:
        return jsonify({"error": "failed to process image"}), 400
    # 生成唯一 ID
    upload_id = _generate_upload_id()
    filename = upload_id + ".gif"
    # 确保 uploads/ 目录存在
    os.makedirs(config.UPLOAD_DIR, exist_ok=True)
    dest_path = os.path.join(config.UPLOAD_DIR, filename)
    with open(dest_path, "wb") as f:
        f.write(gif_data)
    return jsonify({"url": f"/image/{filename}"})
