"""笔记图床：格式校验（魔数嗅探）、ID 生成与读写/配额（存储后端无关）

扩展名由内容魔数决定，不信任上传方声明；不支持可内嵌脚本的 SVG。
图片不可变、无跨实例读改写，无需存储锁。
"""
import random
import re

from app.core import config
from app.core.logger import create_logger
from app.core.storage import StorageError, storage

logger = create_logger("images")

_IMAGE_ID_RE = re.compile(r'^[a-zA-Z0-9_\-]+\.(png|jpg|jpeg|gif|webp)$')

_IMAGE_MIME = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}


def sniff_image_format(data) -> str | None:
    """按魔数嗅探图片格式，返回扩展名（统一 jpg，无 jpeg），非图片返回 None"""
    if not isinstance(data, (bytes, bytearray)) or len(data) < 12:
        return None
    data = bytes(data)
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


def validate_image_id(image_id: str) -> bool:
    if not isinstance(image_id, str) or len(image_id) > config.MAX_NOTE_ID_LENGTH + 5:
        return False
    return bool(_IMAGE_ID_RE.match(image_id))


def generate_image_id(ext: str) -> str:
    rid = ''.join(random.choices(config.ID_CHARSET, k=config.ID_LENGTH))
    return f"{rid}.{ext}"


def image_mimetype(image_id: str) -> str:
    import os
    return _IMAGE_MIME.get(os.path.splitext(image_id)[1].lower(), "application/octet-stream")


def image_url(username: str, image_id: str) -> str:
    return f"/image/{username}/{image_id}"


# ---------- 读写接口（StorageError 兜底，仿 notes.py 风格） ----------
def read_image(username: str, image_id: str) -> bytes | None:
    if not validate_image_id(image_id):
        return None
    try:
        return storage.read_image(username, image_id)
    except StorageError as e:
        logger.error(f"[错误] 读取图片 {username}/{image_id} 失败: {e}")
        return None


def write_image(username: str, image_id: str, data: bytes) -> bool:
    try:
        return storage.write_image(username, image_id, data)
    except StorageError as e:
        logger.error(f"[错误] 写入图片 {username}/{image_id} 失败: {e}")
        return False


def delete_image(username: str, image_id: str) -> bool:
    if not validate_image_id(image_id):
        return False
    try:
        return storage.delete_image(username, image_id)
    except StorageError as e:
        logger.error(f"[错误] 删除图片 {username}/{image_id} 失败: {e}")
        return False


def list_user_images(username: str) -> list[str]:
    try:
        return [iid for iid in storage.list_images(username) if validate_image_id(iid)]
    except StorageError as e:
        logger.error(f"[错误] 列出图片 {username} 失败: {e}")
        return []


def get_image_mtime(username: str, image_id: str):
    try:
        return storage.image_mtime(username, image_id)
    except StorageError:
        return None


def get_image_size(username: str, image_id: str) -> int | None:
    try:
        return storage.image_size(username, image_id)
    except StorageError:
        return None


def user_image_usage(username: str) -> int:
    """该用户图床已用字节数（配额计算）"""
    try:
        return int(storage.image_usage(username) or 0)
    except StorageError as e:
        logger.error(f"[错误] 统计图片用量 {username} 失败: {e}")
        return 0
