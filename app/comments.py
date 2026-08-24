"""评论系统：笔记/分享页面的评论功能

评论存储走 storage 后端的通用 KV 接口（file: comments.json / memory / upstash / postgres）。
"""
import re

from . import config
from .logger import create_logger

logger = create_logger("comments")

# 评论目标类型
TARGET_SHARE = "share"
TARGET_NOTE = "note"

# 正则校验：target_type 只能是 share 或 note
_TARGET_TYPE_RE = re.compile(r'^(share|note)$')


def validate_target_type(target_type: str) -> bool:
    """校验评论目标类型"""
    return bool(_TARGET_TYPE_RE.match(target_type))


def validate_target_id(target_id: str) -> bool:
    """校验评论目标 ID（分享 token 或笔记 ID）"""
    if not isinstance(target_id, str) or len(target_id) > config.MAX_NOTE_ID_LENGTH:
        return False
    # 分享 token 只包含字母数字和下划线/连字符
    # 笔记 ID 格式为 username/note_id，允许斜杠
    return bool(re.match(r'^[a-zA-Z0-9_\-/]+$', target_id))


def validate_comment_content(content: str) -> tuple[bool, str]:
    """校验评论内容，返回 (是否合法, 错误信息键)"""
    if not content or not content.strip():
        return False, "err_comment_empty"
    if len(content) > config.COMMENTS_MAX_LENGTH:
        return False, "err_comment_too_long"
    return True, ""


def get_comment_url(target_type: str, target_id: str) -> str:
    """生成评论页面 URL"""
    if target_type == TARGET_SHARE:
        return f"/comments/share/{target_id}"
    else:
        return f"/comments/note/{target_id}"


def get_comment_count(target_type: str, target_id: str) -> int:
    """获取指定目标的评论数量"""
    from .store import count_comments
    return count_comments(target_type, target_id)


def get_comment_page(target_type: str, target_id: str, page: int, page_size: int):
    """获取评论分页"""
    from .store import get_comments
    return get_comments(target_type, target_id, page, page_size)


def add_comment(target_type: str, target_id: str, username: str, content: str,
                ip: str = "", is_anonymous: bool = False) -> bool:
    """添加评论"""
    from .store import add_comment as store_add_comment
    return store_add_comment(target_type, target_id, username, content, ip, is_anonymous)


def get_comment_cooldown(username: str) -> float:
    """获取用户发布评论的冷却时间"""
    from .store import get_comment_cooldown as store_get_cooldown
    return store_get_cooldown(username)


def mark_comment_post(username: str):
    """记录用户发布评论的时间"""
    from .store import mark_comment_post as store_mark_post
    store_mark_post(username)
