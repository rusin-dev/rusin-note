"""视图层共享的工具：note 上下文构建、页面缓存键等"""
from flask import abort, g, request

from .. import config
from ..extensions import cache
from ..i18n import LANGS, t
from ..notes import validate_note_id
from ..theme import get_theme_script, THEME_VARS
from ..utils import format_note_time, render_latex_head


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
    """页面缓存键：请求路径 + 访问者 + 语言。

    Flask-Caching 调用 make_cache_key 时会透传视图参数，签名须兼容
    （*_args/**_kwargs），否则键构造抛异常、缓存被静默禁用。

    缓存页面的内容同时依赖三者：
    - 语言（g.lang）：zh/en 两套文案不同，不区分会把首个访问者的语言
      发给所有人（首页缓存长达 30 分钟）；
    - 访问者（g.current_user）：导航栏按登录用户渲染，且私有笔记页的
      登录校验在视图内部——Flask-Caching 命中缓存时不会执行视图，键不
      按访问者隔离的话，命中即绕过校验把缓存里的私有内容发给任何人。
    """
    user = getattr(g, "current_user", None) or "anon"
    lang = getattr(g, "lang", "zh")
    return f"page:{request.path}:{user}:{lang}"


def delete_cache_keys(keys) -> None:
    """逐键删除缓存。不用 delete_many：SimpleCache 的 delete_many 在遇到
    首个不存在的键时中断（ignore_errors=False 默认值），会漏删后面的键。"""
    for key in keys:
        cache.delete(key)


def purge_page_cache(paths, viewers=(None,)) -> None:
    """删除 paths × viewers × 全部语言的页面缓存键（配合 page_cache_key）。

    viewers 只需覆盖会产生对应键的访问者：私有页只有笔记所有者能写入
    200 缓存，公开页传 (None, 操作者) 即可，其余访问者的旧键靠 TTL 过期。
    """
    delete_cache_keys([
        f"page:{path}:{viewer or 'anon'}:{lang}"
        for path in paths
        for viewer in viewers
        for lang in LANGS
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
        "theme_script": get_theme_script(lang),
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