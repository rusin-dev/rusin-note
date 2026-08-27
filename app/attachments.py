"""笔记附件：文件类型校验（黑名单模式）、ID 生成与读写/配额（存储后端无关）

附件与笔记一样按 (username, attachment_id) 二维寻址，attachment_id 形如
``<随机串>.<扩展名>``，扩展名由上传文件的原始文件名决定。

文件类型校验采用黑名单模式：默认禁止所有可执行文件扩展名，其余文件类型都允许上传。
黑名单可通过 config.json 的 attachments.blocked_extensions 字段配置。

读写直接走 storage 后端的附件专用 API（file: attachments/<user>/<id> 二进制文件 +
<meta.json> 元数据；postgres: storage_attachments BYTEA 表；memory/upstash: 基类
base64-KV 默认实现）。附件内容不可变（ID 随机），无跨实例读改写，无需存储锁。
"""
import os
import random
import re

from . import config
from .logger import create_logger
from .storage import StorageError, storage

logger = create_logger("attachments")

# 附件 ID 正则：随机串 + . + 扩展名
_ATTACHMENT_ID_RE = re.compile(r'^[a-zA-Z0-9_\-]+\.[a-zA-Z0-9_\-]+$')

# 构建黑名单集合（包含点，用于快速查找）
_blocked_extensions_set = set()
for _ext in config.ATTACHMENT_BLOCKED_EXTENSIONS:
    _blocked_extensions_set.add(f".{_ext.lower()}")


def is_extension_blocked(filename: str) -> bool:
    """检查文件扩展名是否在黑名单中"""
    if not filename:
        return False
    _, ext = os.path.splitext(filename.lower())
    return ext in _blocked_extensions_set


def validate_attachment_type(filename: str) -> tuple[bool, str]:
    """验证附件类型，返回 (是否合法, 错误消息键)"""
    if not filename:
        return False, "err_attachment_no_filename"
    
    if is_extension_blocked(filename):
        return False, "err_attachment_blocked_type"
    
    return True, ""


def validate_attachment_id(attachment_id: str) -> bool:
    """校验附件 ID 格式"""
    if not isinstance(attachment_id, str) or len(attachment_id) > config.MAX_NOTE_ID_LENGTH + 5:
        return False
    return bool(_ATTACHMENT_ID_RE.match(attachment_id))


def generate_attachment_id(filename: str) -> str:
    """生成附件 ID：随机串 + 原文件扩展名"""
    # 提取扩展名
    _, ext = os.path.splitext(filename)
    if not ext:
        ext = ".bin"
    # 确保扩展名以点开头
    if not ext.startswith("."):
        ext = f".{ext}"
    rid = ''.join(random.choices(config.ID_CHARSET, k=config.ID_LENGTH))
    return f"{rid}{ext}"


def attachment_content_type(filename: str) -> str:
    """根据文件扩展名推断 Content-Type"""
    _, ext = os.path.splitext(filename.lower())
    mime_map = {
        ".pdf": "application/pdf",
        ".doc": "application/msword",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".xls": "application/vnd.ms-excel",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".ppt": "application/vnd.ms-powerpoint",
        ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ".txt": "text/plain",
        ".csv": "text/csv",
        ".json": "application/json",
        ".xml": "application/xml",
        ".zip": "application/zip",
        ".rar": "application/x-rar-compressed",
        ".7z": "application/x-7z-compressed",
        ".tar": "application/x-tar",
        ".gz": "application/gzip",
        ".mp3": "audio/mpeg",
        ".mp4": "video/mp4",
        ".avi": "video/x-msvideo",
        ".mov": "video/quicktime",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".gif": "image/gif",
        ".webp": "image/webp",
    }
    return mime_map.get(ext, "application/octet-stream")


def attachment_url(username: str, attachment_id: str) -> str:
    """生成附件访问 URL"""
    return f"/attachment/{username}/{attachment_id}"


# ---------- 读写接口（StorageError 兜底，仿 notes.py 风格） ----------
def read_attachment(username: str, attachment_id: str) -> bytes | None:
    """读取附件数据"""
    if not validate_attachment_id(attachment_id):
        return None
    try:
        return storage.read_attachment(username, attachment_id)
    except StorageError as e:
        logger.error(f"[错误] 读取附件 {username}/{attachment_id} 失败: {e}")
        return None


def read_attachment_meta(username: str, attachment_id: str) -> dict | None:
    """读取附件元数据"""
    if not validate_attachment_id(attachment_id):
        return None
    try:
        return storage.read_attachment_meta(username, attachment_id)
    except StorageError as e:
        logger.error(f"[错误] 读取附件元数据 {username}/{attachment_id} 失败: {e}")
        return None


def write_attachment(username: str, attachment_id: str, data: bytes,
                     filename: str = "", content_type: str = "application/octet-stream") -> bool:
    """写入附件"""
    try:
        return storage.write_attachment(username, attachment_id, data, filename, content_type)
    except StorageError as e:
        logger.error(f"[错误] 写入附件 {username}/{attachment_id} 失败: {e}")
        return False


def delete_attachment(username: str, attachment_id: str) -> bool:
    """删除附件"""
    if not validate_attachment_id(attachment_id):
        return False
    try:
        return storage.delete_attachment(username, attachment_id)
    except StorageError as e:
        logger.error(f"[错误] 删除附件 {username}/{attachment_id} 失败: {e}")
        return False


def list_user_attachments(username: str) -> list[str]:
    """列出用户所有附件 ID"""
    try:
        return [aid for aid in storage.list_attachments(username) if validate_attachment_id(aid)]
    except StorageError as e:
        logger.error(f"[错误] 列出附件 {username} 失败: {e}")
        return []


def get_attachment_mtime(username: str, attachment_id: str):
    """获取附件修改时间"""
    try:
        return storage.attachment_mtime(username, attachment_id)
    except StorageError:
        return None


def get_attachment_size(username: str, attachment_id: str) -> int | None:
    """获取附件大小"""
    try:
        return storage.attachment_size(username, attachment_id)
    except StorageError:
        return None


def user_attachment_usage(username: str) -> int:
    """该用户附件已用字节数（配额计算）"""
    try:
        return int(storage.attachment_usage(username) or 0)
    except StorageError as e:
        logger.error(f"[错误] 统计附件用量 {username} 失败: {e}")
        return 0
