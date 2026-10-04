"""笔记批量导入 / 导出（仅标准库 zipfile/io/json）

导出 ZIP（每篇 notes/<id>.md + manifest.json 记录归类）或单文件 Markdown
（rusin-note-id 注释标记）。导入接受 .zip/.md/.txt，同名跳过不覆盖，
受 note_transfer 大小/数量上限约束。
"""
import io
import json
import os
import time
import zipfile

from app.core import config
from app.core.logger import create_logger
from app.core.notes import (
    generate_random_id, note_exists, read_note, validate_note_id, write_note,
)
from app.core.folders import set_note_folder
from app.core.tags import set_note_tags

logger = create_logger("notes.transfer")

MANIFEST_NAME = "manifest.json"
MAX_FILE_BYTES = config.NOTE_TRANSFER_MAX_FILE_BYTES
MAX_NOTES = config.NOTE_TRANSFER_MAX_NOTES
MAX_NOTE_BYTES = config.MAX_CONTENT_BYTES


def _safe_stem(name: str) -> str:
    """从 zip 条目 / 文件名取笔记 ID 候选（去目录、去扩展名）。"""
    base = os.path.basename(name)
    stem = os.path.splitext(base)[0]
    return stem.strip()


def build_export_zip(username: str, note_ids=None) -> tuple[bytes, str]:
    """把用户笔记打包为 ZIP（含 manifest.json）。note_ids 为空表示全部。"""
    from app.core.notes import list_user_notes_detailed
    from app.core.folders import get_user_note_folders
    from app.core.tags import get_user_note_tags
    detailed = list_user_notes_detailed(username)
    if note_ids:
        wanted = set(note_ids)
        detailed = [row for row in detailed if row["id"] in wanted]
    folders = get_user_note_folders(username)
    tags = get_user_note_tags(username)

    manifest = []
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for row in detailed:
            nid = row["id"]
            content = read_note(username, nid)
            zf.writestr(f"notes/{nid}.md", content)
            manifest.append({
                "id": nid,
                "title": row.get("title", ""),
                "folder": folders.get(nid, ""),
                "tags": tags.get(nid, []),
                "mtime": row.get("mtime"),
            })
        zf.writestr(MANIFEST_NAME, json.dumps({
            "app": "rusin-note", "version": 1,
            "exported_at": int(time.time()), "count": len(manifest),
            "notes": manifest,
        }, ensure_ascii=False, indent=2))
    return buf.getvalue(), f"{username}-notes.zip"


def build_export_md(username: str, note_ids=None) -> tuple[bytes, str]:
    """把用户笔记拼接为单个 Markdown 文件（每篇前用注释标记原 ID）。"""
    from app.core.notes import list_user_notes_detailed
    detailed = list_user_notes_detailed(username)
    if note_ids:
        wanted = set(note_ids)
        detailed = [row for row in detailed if row["id"] in wanted]
    parts = [f"# {username} 的笔记导出（共 {len(detailed)} 篇）\n"]
    for row in detailed:
        nid = row["id"]
        content = read_note(username, nid)
        parts.append(f"\n\n---\n\n<!-- rusin-note-id: {nid} -->\n\n{content}\n")
    return "".join(parts).encode("utf-8"), f"{username}-notes.md"


def _alloc_note_id(username: str, candidate: str) -> str | None:
    """为导入挑选笔记 ID：候选非法/为空则随机生成新 ID；
    候选合法但已被占用返回 None（跳过，绝不覆盖既有笔记）。"""
    if candidate:
        if not validate_note_id(candidate):
            candidate = ""
        elif note_exists(username, candidate):
            return None
    if not candidate:
        while True:
            candidate = generate_random_id()
            if not note_exists(username, candidate):
                return candidate
    return candidate


def _persist_note(username: str, candidate_id: str, content: str,
                  folder: str = "", tags=None) -> str | None:
    """写入一篇导入笔记并还原归类信息，返回最终笔记 ID；同名冲突被跳过时返回 None。"""
    nid = _alloc_note_id(username, candidate_id)
    if nid is None:
        return None
    write_note(username, nid, content)
    if folder:
        set_note_folder(username, nid, folder)
    if tags:
        set_note_tags(username, nid, [str(x) for x in tags if str(x).strip()])
    return nid


def _import_from_zip(username: str, raw: bytes) -> dict:
    result = {"imported": [], "skipped": 0, "error": None}
    try:
        zf = zipfile.ZipFile(io.BytesIO(raw))
    except (zipfile.BadZipFile, OSError):
        result["error"] = "not_a_zip"
        return result
    with zf:
        names = zf.namelist()
        meta_by_id = {}
        if MANIFEST_NAME in names:
            try:
                manifest = json.loads(zf.read(MANIFEST_NAME).decode("utf-8"))
                for item in manifest.get("notes", []):
                    if isinstance(item, dict) and item.get("id"):
                        meta_by_id[str(item["id"])] = item
            except (ValueError, KeyError):
                pass

        md_names = [n for n in names
                    if n.lower().endswith((".md", ".txt")) and not n.endswith("/")]
        if len(md_names) > MAX_NOTES:
            result["error"] = "too_many_notes"
            return result
        for name in md_names:
            stem = _safe_stem(name)
            try:
                content = zf.read(name).decode("utf-8")
            except (KeyError, UnicodeDecodeError, OSError):
                result["skipped"] += 1
                continue
            if len(content.encode("utf-8")) > MAX_NOTE_BYTES:
                result["skipped"] += 1
                continue
            meta = meta_by_id.get(stem, {})
            nid = _persist_note(username, stem, content,
                                folder=meta.get("folder", ""), tags=meta.get("tags"))
            if nid is None:
                result["skipped"] += 1
            else:
                result["imported"].append(nid)
    return result


def _import_from_text(username: str, raw: bytes) -> dict:
    """单文件导入：按 ``<!-- rusin-note-id: X -->`` 注释拆分为多篇，否则整体作为一篇。"""
    import re
    result = {"imported": [], "skipped": 0, "error": None}
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("utf-8", errors="replace")
    marker = re.compile(r"<!--\s*rusin-note-id:\s*([A-Za-z0-9_\-]+)\s*-->")
    matches = list(marker.finditer(text))
    if not matches:
        if len(text.encode("utf-8")) > MAX_NOTE_BYTES:
            result["error"] = "too_large"
            return result
        nid = _persist_note(username, "", text.strip())
        result["imported"].append(nid)
        return result
    if len(matches) > MAX_NOTES:
        result["error"] = "too_many_notes"
        return result
    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        body = re.sub(r"^---\s*", "", body).strip()  # 去掉导出分隔线残留
        if len(body.encode("utf-8")) > MAX_NOTE_BYTES:
            result["skipped"] += 1
            continue
        nid = _persist_note(username, m.group(1), body)
        if nid is None:
            result["skipped"] += 1
        else:
            result["imported"].append(nid)
    return result


def import_notes(username: str, filename: str, raw: bytes) -> dict:
    """按文件类型分派导入；返回 {imported:[ids], skipped:int, error:str|None}。"""
    if len(raw) > MAX_FILE_BYTES:
        return {"imported": [], "skipped": 0, "error": "too_large"}
    ext = os.path.splitext(filename or "")[1].lower()
    if ext == ".zip":
        return _import_from_zip(username, raw)
    if ext in (".md", ".markdown", ".txt"):
        return _import_from_text(username, raw)
    return {"imported": [], "skipped": 0, "error": "unsupported_type"}
