"""内置 Web wiki 存储：KV 键 wiki:pages / wiki:revisions

- ``wiki:pages``：{slug: {title, content, created_at, updated_at, updated_by}}，
  slug 以 ``/`` 表示层级（如 ``deploy/vercel``）；
- ``wiki:revisions``：{slug: [{id, ts, by, title, content}, ...]}，最新在前，
  每页最多保留 ``config.WIKI_MAX_REVISIONS`` 个历史版本。

服务层无进程内缓存：每次访问直接重读 KV（公开页读路径由视图层
``@cache.cached`` 承担），多实例部署天然一致。写路径统一锁序：
threading.Lock（进程内）→ storage.lock（跨进程/跨实例），与 store.py 约定一致。
"""
from __future__ import annotations

import re
import secrets
import threading
import time

from app.core import config
from app.core.logger import create_logger
from app.core.storage import StorageError, storage

logger = create_logger("wiki")

K_PAGES = "wiki:pages"
K_REVISIONS = "wiki:revisions"

_SEG_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_\-]*$")
MAX_SLUG_LEN = 200
MAX_TITLE_LEN = 200

wiki_lock = threading.Lock()


# ---------- 底层读写 ----------
def _read_kv(key: str) -> dict:
    try:
        value = storage.get(key)
    except StorageError as e:
        logger.error(f"[错误] 存储读取 {key} 失败: {e}")
        return {}
    return value if isinstance(value, dict) else {}


def _clean_pages(raw: dict) -> dict:
    """规整页面表，丢弃脏数据。"""
    out = {}
    for slug, page in raw.items():
        if not isinstance(slug, str) or not isinstance(page, dict):
            continue
        content = page.get("content")
        if not isinstance(content, str):
            continue
        out[slug] = {
            "title": str(page.get("title") or slug),
            "content": content,
            "created_at": float(page.get("created_at") or 0),
            "updated_at": float(page.get("updated_at") or 0),
            "updated_by": str(page.get("updated_by") or ""),
        }
    return out


def _clean_revs(raw: dict) -> dict:
    """规整修订表：仅保留结构完整的条目。"""
    out = {}
    for slug, items in raw.items():
        if not isinstance(slug, str) or not isinstance(items, list):
            continue
        revs = []
        for it in items:
            if not isinstance(it, dict):
                continue
            if not isinstance(it.get("id"), str) or not isinstance(it.get("content"), str):
                continue
            revs.append({
                "id": it["id"],
                "ts": float(it.get("ts") or 0),
                "by": str(it.get("by") or ""),
                "title": str(it.get("title") or ""),
                "content": it["content"],
            })
        if revs:
            out[slug] = revs
    return out


def _load() -> tuple[dict, dict]:
    return _clean_pages(_read_kv(K_PAGES)), _clean_revs(_read_kv(K_REVISIONS))


def _persist(pages: dict, revs: dict) -> bool:
    try:
        ok = storage.set(K_PAGES, pages)
        ok = storage.set(K_REVISIONS, revs) and ok
        return ok
    except StorageError as e:
        logger.error(f"[错误] 存储写入 wiki 失败: {e}")
        return False


# ---------- slug ----------
def validate_slug(slug: str) -> bool:
    """slug 由 1..max_slug_depth 段组成，每段以字母数字开头，仅含字母数字/-/_。"""
    if not isinstance(slug, str) or not slug or len(slug) > MAX_SLUG_LEN:
        return False
    segments = slug.split("/")
    if len(segments) > config.WIKI_MAX_SLUG_DEPTH:
        return False
    return all(_SEG_RE.match(seg) for seg in segments)


def normalize_slug(slug: str) -> str:
    return (slug or "").strip().strip("/")


def _descendants(pages: dict, slug: str) -> list[str]:
    prefix = slug + "/"
    return [s for s in pages if s.startswith(prefix)]


# ---------- 读接口 ----------
def get_page(slug: str) -> dict | None:
    pages, _ = _load()
    page = pages.get(slug)
    return dict(page) if page else None


def list_pages() -> list[dict]:
    """全部页面元数据（不含正文），按 slug 排序。"""
    pages, _ = _load()
    return [
        {"slug": s, "title": p["title"], "updated_at": p["updated_at"], "updated_by": p["updated_by"]}
        for s, p in sorted(pages.items())
    ]


def get_revisions(slug: str) -> list[dict]:
    _, revs = _load()
    return [dict(r) for r in revs.get(slug, [])]


def get_tree() -> list[dict]:
    """按 slug 层级构建目录树：[{slug, title, children: [...]}]，同级按 slug 排序。

    父页面缺失的孤儿页面挂到根级，保证侧边栏不丢页。
    """
    pages, _ = _load()
    nodes = {s: {"slug": s, "title": p["title"], "children": []} for s, p in pages.items()}
    roots = []
    for slug in sorted(nodes):
        node = nodes[slug]
        parent = slug.rsplit("/", 1)[0] if "/" in slug else ""
        if parent and parent in nodes:
            nodes[parent]["children"].append(node)
        else:
            roots.append(node)
    return roots


# ---------- 写接口 ----------
def save_page(slug: str, title: str, content: str, username: str) -> tuple[bool, str]:
    """创建或更新页面；内容有变化时旧版本进入修订历史。"""
    slug = normalize_slug(slug)
    if not validate_slug(slug):
        return False, "slug_invalid"
    title = (title or "").strip()
    if not title:
        return False, "title_required"
    title = title[:MAX_TITLE_LEN]
    content = content or ""
    if len(content.encode("utf-8")) > config.WIKI_MAX_PAGE_KB * 1024:
        return False, "too_large"
    try:
        with wiki_lock:
            with storage.lock(K_PAGES), storage.lock(K_REVISIONS):
                pages, revs = _load()
                old = pages.get(slug)
                if old is None and len(pages) >= config.WIKI_MAX_PAGES:
                    return False, "too_many_pages"
                now = time.time()
                if old is not None and (old["title"] != title or old["content"] != content):
                    _push_revision(revs, slug, old)
                if old is None:
                    pages[slug] = {
                        "title": title, "content": content,
                        "created_at": now, "updated_at": now, "updated_by": username,
                    }
                else:
                    old.update({"title": title, "content": content,
                                "updated_at": now, "updated_by": username})
                if not _persist(pages, revs):
                    return False, "storage"
        return True, ""
    except StorageError as e:
        logger.error(f"[错误] 保存 wiki 页面 {slug} 失败: {e}")
        return False, "storage"


def _push_revision(revs: dict, slug: str, old: dict) -> None:
    """把旧版本压入修订历史（最新在前，超出上限裁剪）。"""
    entry = {
        "id": secrets.token_hex(6),
        "ts": old.get("updated_at") or time.time(),
        "by": old.get("updated_by") or "",
        "title": old.get("title") or "",
        "content": old.get("content") or "",
    }
    revs[slug] = ([entry] + revs.get(slug, []))[:config.WIKI_MAX_REVISIONS]


def delete_page(slug: str) -> tuple[bool, str]:
    """删除页面及其修订历史；存在子页面时拒绝（防止目录树出现孤儿）。"""
    slug = normalize_slug(slug)
    try:
        with wiki_lock:
            with storage.lock(K_PAGES), storage.lock(K_REVISIONS):
                pages, revs = _load()
                if slug not in pages:
                    return True, ""
                if _descendants(pages, slug):
                    return False, "has_children"
                pages.pop(slug)
                revs.pop(slug, None)
                if not _persist(pages, revs):
                    return False, "storage"
        return True, ""
    except StorageError as e:
        logger.error(f"[错误] 删除 wiki 页面 {slug} 失败: {e}")
        return False, "storage"


def move_page(old_slug: str, new_slug: str, username: str) -> tuple[bool, str]:
    """移动（重命名）页面，子页面按前缀级联迁移，修订历史随迁。"""
    old_slug = normalize_slug(old_slug)
    new_slug = normalize_slug(new_slug)
    if not validate_slug(new_slug):
        return False, "slug_invalid"
    try:
        with wiki_lock:
            with storage.lock(K_PAGES), storage.lock(K_REVISIONS):
                pages, revs = _load()
                if old_slug not in pages:
                    return False, "not_found"
                if new_slug == old_slug:
                    return True, ""
                if new_slug in pages or _descendants(pages, new_slug):
                    return False, "slug_conflict"
                affected = [old_slug] + _descendants(pages, old_slug)
                for slug in affected:
                    target = new_slug + slug[len(old_slug):]
                    pages[target] = pages.pop(slug)
                    if slug in revs:
                        revs[target] = revs.pop(slug)
                if not _persist(pages, revs):
                    return False, "storage"
        return True, ""
    except StorageError as e:
        logger.error(f"[错误] 移动 wiki 页面 {old_slug} -> {new_slug} 失败: {e}")
        return False, "storage"


def rollback_page(slug: str, rev_id: str, username: str) -> tuple[bool, str]:
    """回滚到指定修订：当前版本先入历史，再用修订内容覆盖。"""
    slug = normalize_slug(slug)
    try:
        with wiki_lock:
            with storage.lock(K_PAGES), storage.lock(K_REVISIONS):
                pages, revs = _load()
                page = pages.get(slug)
                if page is None:
                    return False, "not_found"
                target = next((r for r in revs.get(slug, []) if r.get("id") == rev_id), None)
                if target is None:
                    return False, "rev_not_found"
                _push_revision(revs, slug, page)
                page.update({
                    "title": target.get("title") or page["title"],
                    "content": target["content"],
                    "updated_at": time.time(),
                    "updated_by": username,
                })
                if not _persist(pages, revs):
                    return False, "storage"
        return True, ""
    except StorageError as e:
        logger.error(f"[错误] 回滚 wiki 页面 {slug} 失败: {e}")
        return False, "storage"
