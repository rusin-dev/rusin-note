"""视图层共享的工具：note 上下文构建、页面缓存键等"""
from flask import abort, g, request

from app.core import config
from app.core.extensions import cache
from app.core.i18n import LANGS, t
from app.core.middleware import get_current_user
from app.core.notes import validate_note_id
from app.core.theme import THEME_VARS
from app.core.utils import format_note_time, render_latex_head


def require_auth(username: str) -> None:
    """断言当前登录用户与路径用户名一致，否则 401。"""
    if get_current_user() != username:
        abort(401)


def check_note_id(note_id: str) -> None:
    """校验剪贴板名称（笔记 ID）。

    长度超过 MAX_NOTE_ID_LENGTH 时以 400 结束并提示「URL 不合法」；
    含点的视为文件类路径返回 404；其余非法名称返回通用 400。
    """
    if validate_note_id(note_id):
        return
    if len(note_id) > config.MAX_NOTE_ID_LENGTH:
        abort(400, description=t(getattr(g, "lang", "zh"), "err_url_invalid"))
    if "." in note_id:
        abort(404)
    abort(400)


def page_cache_key(*_args, **_kwargs) -> str:
    """页面缓存键 = 路径 + 访问者 + 语言 + 简洁模式（Flask-Caching 透传视图参数，签名须兼容）

    缓存命中不执行视图：键不含访问者会绕过私有笔记的登录校验；
    不含语言/简洁模式会把错误文案/界面发给其它访问者。
    """
    user = getattr(g, "current_user", None) or "anon"
    lang = getattr(g, "lang", "zh")
    simple = "1" if getattr(g, "simple_mode", False) else "0"
    return f"page:{request.path}:{user}:{lang}:{simple}"


def delete_cache_keys(keys) -> None:
    """逐键删除缓存。不用 delete_many：SimpleCache 的 delete_many 在遇到
    首个不存在的键时中断（ignore_errors=False 默认值），会漏删后面的键。"""
    for key in keys:
        cache.delete(key)


def purge_page_cache(paths, viewers=(None,)) -> None:
    """删除 paths × viewers × 全部语言 × 两种简洁模式的页面缓存键。

    viewers 只需覆盖会产生对应键的访问者：私有页只有笔记所有者能写入
    200 缓存，公开页传 (None, 操作者) 即可，其余访问者的旧键靠 TTL 过期。
    """
    delete_cache_keys([
        f"page:{path}:{viewer or 'anon'}:{lang}:{simple}"
        for path in paths
        for viewer in viewers
        for lang in LANGS
        for simple in ("0", "1")
    ])


def build_note_context(
    note_id,
    username=None,
    is_world=False,
    mtime=None,
    hint_text=None,
    is_share=False,
):
    """构造 note_edit.html / note_md.html 共享的模板变量。"""
    lang = getattr(g, "lang", "zh")

    if hint_text is None:
        hint_text = t(lang, "note_save_hint")

    if is_share:
        title_prefix = t(lang, "note_share_prefix")
    elif is_world:
        title_prefix = t(lang, "note_public_prefix")
    else:
        title_prefix = t(lang, "note_private_prefix")

    full_title = f"{title_prefix} {note_id}"
    if config.SITE_NAME:
        full_title = f"{full_title} | {config.SITE_NAME}"

    if mtime:
        last_edited = f'{t(lang, "note_last_edited")}{format_note_time(mtime)}'
    else:
        last_edited = t(lang, "note_never_edited")

    l10n = {
        "saving": t(lang, "save_status_saving"),
        "saved": t(lang, "save_status_saved"),
        "failedStatus": t(lang, "save_status_failed"),
        "netError": t(lang, "save_status_net_error"),
        "savedHint": t(lang, "save_hint_saved"),
        "retryHint": t(lang, "save_hint_retry"),
        "failedMsg": t(lang, "save_failed_msg"),
        "livePreview": t(lang, "note_live_preview"),
        "previewOffHint": t(lang, "note_live_preview_hint"),
        "previewShow": t(lang, "preview_show"),
        "previewEdit": t(lang, "preview_edit"),
        "refLabel": t(lang, "note_refs_label"),
        "refRecent": t(lang, "note_refs_recent"),
        "refNoMatch": t(lang, "note_refs_no_match"),
        "imgUploading": t(lang, "note_images_uploading"),
        "imgDone": t(lang, "note_images_done"),
        "imgFailed": t(lang, "note_images_failed"),
        "attUploading": t(lang, "note_attachments_uploading"),
        "attDone": t(lang, "note_attachments_done"),
        "attFailed": t(lang, "note_attachments_failed"),
    }

    return {
        "theme_vars": THEME_VARS,
        "simple_mode": getattr(g, "simple_mode", False),
        "site_name": config.SITE_NAME,
        "title_prefix": title_prefix,
        "full_title": full_title,
        "hint_text": hint_text,
        "last_edited": last_edited,
        "l10n": l10n,
        "latex_head": render_latex_head(),
        "live_preview_default": config.LIVE_PREVIEW_DEFAULT,
        "md_manual_url": config.MARKDOWN_MANUAL_URL,
    }