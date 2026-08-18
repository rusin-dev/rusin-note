"""视图层共享的工具：note 上下文构建等"""
from flask import abort, g

from .. import config
from ..i18n import t
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
    }