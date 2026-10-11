"""内置 Web wiki：/docs 公开浏览 + /admin/wiki 管理维护

- 公开页（/docs、/docs/<slug>）匿名可读，经页面缓存（写操作后主动清除）；
- 管理路由仅功能开关管理员可访问，非管理员一律 404（不泄漏管理页存在）；
- Markdown 渲染统一走 utils.render_markdown_html（bleach 清洗）。
"""
from flask import Blueprint, abort, g, redirect, render_template, request, url_for

from app.core import config
from app.core.extensions import cache, limiter
from app.core.feature_flags import is_admin, require_feature
from app.core.i18n import t
from app.core.middleware import get_current_user
from app.core.utils import format_note_time, render_latex_head, render_markdown_html
from app.apps.common.helpers import page_cache_key
from app.apps.wiki import service

bp = Blueprint("wiki", __name__)

# 服务层错误码 → (i18n 键, HTTP 状态, 格式化参数)
_ERRORS = {
    "slug_invalid": ("wiki_err_slug_invalid", 400, lambda: {"depth": config.WIKI_MAX_SLUG_DEPTH}),
    "slug_conflict": ("wiki_err_slug_conflict", 400, dict),
    "not_found": ("wiki_err_not_found", 404, dict),
    "too_large": ("wiki_err_too_large", 400, lambda: {"kb": config.WIKI_MAX_PAGE_KB}),
    "too_many_pages": ("wiki_err_too_many_pages", 400, lambda: {"max": config.WIKI_MAX_PAGES}),
    "has_children": ("wiki_err_has_children", 400, dict),
    "title_required": ("wiki_err_title_required", 400, dict),
    "storage": ("wiki_err_storage", 500, dict),
    "rev_not_found": ("wiki_err_rev_not_found", 404, dict),
}


def _err_message(err: str) -> str:
    key, _status, fmt = _ERRORS.get(err, _ERRORS["storage"])
    return t(getattr(g, "lang", "zh"), key, **fmt())


def _err_status(err: str) -> int:
    return _ERRORS.get(err, _ERRORS["storage"])[1]


def _require_admin() -> str:
    user = get_current_user()
    if not user or not is_admin(user):
        abort(404)
    return user


def _purge() -> None:
    """wiki 写操作后整体清空页面缓存。

    公开页缓存键含访问者身份（page_cache_key），逐键清除只能覆盖匿名键，
    已登录访问者的旧内容会滞留到 TTL；wiki 管理写入频率极低，与
    admin.features_post 一致直接 cache.clear()（多实例靠各自 TTL 收敛）。
    """
    cache.clear()


def _public_ctx() -> dict:
    user = get_current_user()
    return {
        "is_wiki_admin": bool(user and is_admin(user)),
        "latex_head": render_latex_head(),
        "tree": service.get_tree(),
        "page_count": len(service.list_pages()),
    }


# ---------- 公开浏览 ----------
@bp.route("/docs", methods=["GET"])
@require_feature("wiki")
@limiter.limit(lambda: f"{config.GET_RATE_MAX} per {config.GET_RATE_WINDOW} second")
@cache.cached(timeout=config.CACHE_TIMEOUT_NOTES, make_cache_key=page_cache_key)
def wiki_home():
    home = service.get_page(config.WIKI_HOME_SLUG)
    ctx = _public_ctx()
    if home:
        return render_template(
            "wiki/view.html", page=home, slug=config.WIKI_HOME_SLUG,
            content_html=render_markdown_html(home["content"]),
            updated_str=format_note_time(home["updated_at"]) if home["updated_at"] else "",
            **ctx,
        )
    return render_template("wiki/index.html", pages=service.list_pages(), **ctx)


@bp.route("/docs/<path:slug>", methods=["GET"])
@require_feature("wiki")
@limiter.limit(lambda: f"{config.GET_RATE_MAX} per {config.GET_RATE_WINDOW} second")
@cache.cached(timeout=config.CACHE_TIMEOUT_NOTES, make_cache_key=page_cache_key)
def wiki_view(slug: str):
    slug = service.normalize_slug(slug)
    page = service.get_page(slug) if service.validate_slug(slug) else None
    if page is None:
        return render_template("errors/404.html"), 404
    return render_template(
        "wiki/view.html", page=page, slug=slug,
        content_html=render_markdown_html(page["content"]),
        updated_str=format_note_time(page["updated_at"]) if page["updated_at"] else "",
        **_public_ctx(),
    )


# ---------- 管理：页面列表 ----------
@bp.route("/admin/wiki", methods=["GET"])
@require_feature("wiki")
@limiter.limit(lambda: f"{config.GET_RATE_MAX} per {config.GET_RATE_WINDOW} second")
def wiki_admin_index():
    _require_admin()
    return render_template(
        "wiki/admin.html",
        pages=service.list_pages(),
        tree=service.get_tree(),
        msg=request.args.get("msg", ""),
    )


# ---------- 管理：新建 / 编辑 ----------
@bp.route("/admin/wiki/edit", methods=["GET", "POST"])
@require_feature("wiki")
@limiter.limit(lambda: f"{config.RATE_MAX} per {config.RATE_WINDOW} second")
def wiki_create():
    user = _require_admin()
    if request.method == "GET":
        return render_template(
            "wiki/edit.html", page=None, slug=service.normalize_slug(request.args.get("slug", "")),
            error="", max_kb=config.WIKI_MAX_PAGE_KB, depth=config.WIKI_MAX_SLUG_DEPTH,
        )
    slug = service.normalize_slug(request.form.get("slug", ""))
    title = request.form.get("title", "")
    content = request.form.get("content", "")
    if not service.validate_slug(slug):
        return render_template(
            "wiki/edit.html", page=None, slug=slug, error=_err_message("slug_invalid"),
            max_kb=config.WIKI_MAX_PAGE_KB, depth=config.WIKI_MAX_SLUG_DEPTH,
        ), 400
    if service.get_page(slug) is not None:
        return render_template(
            "wiki/edit.html", page=None, slug=slug, error=_err_message("slug_conflict"),
            max_kb=config.WIKI_MAX_PAGE_KB, depth=config.WIKI_MAX_SLUG_DEPTH,
        ), 400
    ok, err = service.save_page(slug, title, content, user)
    if not ok:
        return render_template(
            "wiki/edit.html", page=None, slug=slug, error=_err_message(err),
            max_kb=config.WIKI_MAX_PAGE_KB, depth=config.WIKI_MAX_SLUG_DEPTH,
        ), _err_status(err)
    _purge()
    return redirect(url_for("wiki.wiki_view", slug=slug))


@bp.route("/admin/wiki/edit/<path:slug>", methods=["GET", "POST"])
@require_feature("wiki")
@limiter.limit(lambda: f"{config.RATE_MAX} per {config.RATE_WINDOW} second")
def wiki_edit(slug: str):
    user = _require_admin()
    slug = service.normalize_slug(slug)
    page = service.get_page(slug) if service.validate_slug(slug) else None
    if page is None:
        abort(404)
    if request.method == "GET":
        return render_template(
            "wiki/edit.html", page=page, slug=slug, error="",
            max_kb=config.WIKI_MAX_PAGE_KB, depth=config.WIKI_MAX_SLUG_DEPTH,
        )
    ok, err = service.save_page(slug, request.form.get("title", ""),
                                request.form.get("content", ""), user)
    if not ok:
        return render_template(
            "wiki/edit.html", page={"title": request.form.get("title", page["title"]),
                                    "content": request.form.get("content", page["content"])},
            slug=slug, error=_err_message(err),
            max_kb=config.WIKI_MAX_PAGE_KB, depth=config.WIKI_MAX_SLUG_DEPTH,
        ), _err_status(err)
    _purge()
    return redirect(url_for("wiki.wiki_view", slug=slug))


# ---------- 管理：移动 / 删除 ----------
@bp.route("/admin/wiki/move/<path:slug>", methods=["POST"], strict_slashes=False)
@require_feature("wiki")
@limiter.limit(lambda: f"{config.RATE_MAX} per {config.RATE_WINDOW} second")
def wiki_move(slug: str):
    user = _require_admin()
    slug = service.normalize_slug(slug)
    new_slug = service.normalize_slug(request.form.get("new_slug", ""))
    ok, err = service.move_page(slug, new_slug, user)
    if not ok:
        abort(_err_status(err), description=_err_message(err))
    _purge()
    return redirect(url_for("wiki.wiki_view", slug=new_slug))


@bp.route("/admin/wiki/delete/<path:slug>", methods=["POST"], strict_slashes=False)
@require_feature("wiki")
@limiter.limit(lambda: f"{config.RATE_MAX} per {config.RATE_WINDOW} second")
def wiki_delete(slug: str):
    _require_admin()
    slug = service.normalize_slug(slug)
    ok, err = service.delete_page(slug)
    if not ok:
        abort(_err_status(err), description=_err_message(err))
    _purge()
    return redirect(url_for("wiki.wiki_admin_index"))


# ---------- 管理：版本历史 / 回滚 ----------
@bp.route("/admin/wiki/history/<path:slug>", methods=["GET"])
@require_feature("wiki")
@limiter.limit(lambda: f"{config.GET_RATE_MAX} per {config.GET_RATE_WINDOW} second")
def wiki_history(slug: str):
    _require_admin()
    slug = service.normalize_slug(slug)
    page = service.get_page(slug) if service.validate_slug(slug) else None
    if page is None:
        abort(404)
    revs = service.get_revisions(slug)
    for rev in revs:
        rev["time_str"] = format_note_time(rev["ts"]) if rev["ts"] else ""
        rev["content_html"] = render_markdown_html(rev["content"])
    return render_template(
        "wiki/history.html", page=page, slug=slug, revisions=revs,
        latex_head=render_latex_head(),
        updated_str=format_note_time(page["updated_at"]) if page["updated_at"] else "",
        msg=request.args.get("msg", ""),
    )


@bp.route("/admin/wiki/rollback/<path:slug>", methods=["POST"], strict_slashes=False)
@require_feature("wiki")
@limiter.limit(lambda: f"{config.RATE_MAX} per {config.RATE_WINDOW} second")
def wiki_rollback(slug: str):
    user = _require_admin()
    slug = service.normalize_slug(slug)
    ok, err = service.rollback_page(slug, request.form.get("rev_id", ""), user)
    if not ok:
        abort(_err_status(err), description=_err_message(err))
    _purge()
    return redirect(url_for("wiki.wiki_history", slug=slug,
                            msg=t(getattr(g, "lang", "zh"), "wiki_rolled_back_ok")))
