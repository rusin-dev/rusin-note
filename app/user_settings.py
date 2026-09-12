"""用户设置：界面偏好（简洁模式）、密码修改、登录用户名变更（含数据迁移）

登录用户名同时是笔记 / 图床 / 附件的存储命名空间（见 AGENTS.md「路径安全」），
改名本质是一次数据迁移：先把旧命名空间下的二进制资源复制到新命名空间并校验，
再删除旧数据；同时调用各存储模块的 rename_user_* 迁移以用户名为键的 KV 数据。
资源复制失败时不删除旧数据，用户可重试（低频操作，允许「尽力而为 + 可重试」）。
"""
from .auth import (
    check_password_complexity,
    generate_salt,
    hash_password,
    verify_password,
)
from .logger import create_logger
from .notes import (
    list_user_notes,
    note_exists,
    read_note,
    validate_username,
    write_note,
)
from .store import (
    delete_sessions_if,
    get_user,
    rename_user_records,
    update_user,
)
from .tags import rename_user_note_tags
from .folders import rename_user_note_folders
from .pins import rename_user_note_pins

logger = create_logger("user_settings")


# ---------- 界面偏好 ----------
def get_simple_mode(username: str) -> bool:
    """用户是否启用简洁模式（未登录/记录缺失时为 False）"""
    if not username:
        return False
    user = get_user(username)
    return bool(user.get("simple_mode")) if isinstance(user, dict) else False


def set_simple_mode(username: str, enabled: bool) -> bool:
    return update_user(username, {"simple_mode": bool(enabled)})


# ---------- 密码修改 ----------
def change_password(username: str, current: str, new: str, confirm: str,
                    keep_token_hash: str | None = None, lang: str = "zh"):
    """校验并修改密码。成功返回 None，失败返回 (i18n 键, 格式化参数) 元组。

    修改成功后（keep_token_hash 给定时）注销该用户的其它会话：密码变更通常
    意味着旧密码可能已泄漏，应让其它设备重新登录。
    """
    user = get_user(username)
    salt = user.get("salt") if isinstance(user, dict) else None
    hashed = user.get("hash") if isinstance(user, dict) else None
    if not isinstance(salt, str) or not isinstance(hashed, str):
        return ("err_login_failed", {})
    if not verify_password(current, salt, hashed):
        return ("err_settings_password_wrong", {})
    if new != confirm:
        return ("err_password_mismatch", {})
    if not check_password_complexity(new):
        from .config import get_password_requirements_description
        return ("err_password_weak",
                {"req": get_password_requirements_description(lang)})

    new_salt = generate_salt()
    new_hash = hash_password(new, new_salt)
    if not update_user(username, {"salt": new_salt, "hash": new_hash}):
        return ("err_settings_save_failed", {})

    if keep_token_hash:
        delete_sessions_if(
            lambda token_hash, sess: isinstance(sess, dict)
            and sess.get("username") == username
            and token_hash != keep_token_hash
        )
    return None


# ---------- 用户名变更（数据迁移） ----------
def _copy_notes(old: str, new: str) -> bool:
    """把 old 的笔记逐篇复制到 new（不删除旧数据）。"""
    for note_id in list_user_notes(old):
        content = read_note(old, note_id)
        if not content and not note_exists(old, note_id):
            continue
        if not write_note(new, note_id, content):
            return False
    return True


def _delete_notes(old: str) -> None:
    """删除 old 命名空间下的笔记。write_note 的删除钩子会顺手清理旧标签/
    文件夹/置顶，因此必须在这些元数据迁移完成之后调用。"""
    for note_id in list_user_notes(old):
        if note_exists(old, note_id):
            write_note(old, note_id, "")


def _migrate_images(old: str, new: str) -> bool:
    from .images import (
        delete_image,
        list_user_images,
        read_image,
        write_image,
    )
    image_ids = list_user_images(old)
    for image_id in image_ids:
        data = read_image(old, image_id)
        if data is None:
            continue
        if not write_image(new, image_id, data):
            return False
    for image_id in image_ids:
        delete_image(old, image_id)
    return True


def _migrate_attachments(old: str, new: str) -> bool:
    from .attachments import (
        delete_attachment,
        list_user_attachments,
        read_attachment,
        read_attachment_meta,
        write_attachment,
    )
    attachment_ids = list_user_attachments(old)
    for attachment_id in attachment_ids:
        data = read_attachment(old, attachment_id)
        if data is None:
            continue
        meta = read_attachment_meta(old, attachment_id) or {}
        if not write_attachment(
            new,
            attachment_id,
            data,
            meta.get("filename", ""),
            meta.get("content_type", "application/octet-stream"),
        ):
            return False
    for attachment_id in attachment_ids:
        delete_attachment(old, attachment_id)
    return True


def rename_user(old: str, new: str, password: str):
    """把用户 old 改名为 new（含全部数据迁移）。成功返回 None，失败返回
    (i18n 键, 格式化参数) 元组。

    需要密码二次确认；新用户名须合法、未被占用。二进制资源先复制后删除，
    复制失败即中止（旧数据保留，改名为幂等可重试的低频操作）。
    """
    new = (new or "").strip()
    if new == old:
        return ("err_settings_username_same", {})
    if not validate_username(new):
        return ("err_username_invalid", {})
    if get_user(new) is not None:
        return ("err_username_taken", {})

    user = get_user(old)
    salt = user.get("salt") if isinstance(user, dict) else None
    hashed = user.get("hash") if isinstance(user, dict) else None
    if not isinstance(salt, str) or not isinstance(hashed, str):
        return ("err_login_failed", {})
    if not verify_password(password, salt, hashed):
        return ("err_settings_password_wrong", {})

    # 1) 笔记与二进制资源：先复制到新命名空间（失败则旧数据不动）
    if not _copy_notes(old, new):
        logger.error(f"[错误] 迁移笔记失败: {old} -> {new}")
        return ("err_settings_rename_failed", {})
    if not _migrate_images(old, new):
        logger.error(f"[错误] 迁移图床失败: {old} -> {new}")
        return ("err_settings_rename_failed", {})
    if not _migrate_attachments(old, new):
        logger.error(f"[错误] 迁移附件失败: {old} -> {new}")
        return ("err_settings_rename_failed", {})

    # 2) 以用户名为键/字段的 KV 数据。标签/文件夹/置顶须在删除旧笔记之前
    #    迁移：write_note 的删除钩子会按旧用户名清理这些条目。
    if not rename_user_note_tags(old, new):
        return ("err_settings_rename_failed", {})
    if not rename_user_note_folders(old, new):
        return ("err_settings_rename_failed", {})
    if not rename_user_note_pins(old, new):
        return ("err_settings_rename_failed", {})

    # 3) 清理旧命名空间笔记（此时删除钩子已无旧标签/文件夹/置顶可清）
    _delete_notes(old)

    # 4) 最后移动 users 记录本身与其余子系统的用户标识
    if not rename_user_records(old, new):
        return ("err_settings_rename_failed", {})

    logger.info(f"[设置] 用户改名成功: {old} -> {new}")
    return None
