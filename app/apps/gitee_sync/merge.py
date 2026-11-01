"""Gitee 同步的三方比较与保守文本合并。"""
from __future__ import annotations

import difflib

_EDIT_TAGS = {"replace", "delete", "insert"}


def _edits(base: str, changed: str) -> list[tuple[int, int, list[str]]]:
    base_lines = base.splitlines(keepends=True)
    changed_lines = changed.splitlines(keepends=True)
    matcher = difflib.SequenceMatcher(a=base_lines, b=changed_lines, autojunk=False)
    edits = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag in _EDIT_TAGS:
            edits.append((i1, i2, changed_lines[j1:j2]))
    return edits


def _overlaps(left: tuple[int, int, list], right: tuple[int, int, list]) -> bool:
    a1, a2, _ = left
    b1, b2, _ = right
    if a1 == a2 or b1 == b2:
        return a1 == b1 or (a1 == a2 and b1 < a1 < b2) or (b1 == b2 and a1 < b1 < a2)
    return max(a1, b1) < min(a2, b2)


def three_way_merge(base: str, local: str, remote: str) -> str | None:
    """合并两侧相对 base 的非重叠行修改；同一区域双方都改时返回 None。"""
    local_edits = _edits(base, local)
    remote_edits = _edits(base, remote)
    for left in local_edits:
        for right in remote_edits:
            if _overlaps(left, right):
                return None

    result = base.splitlines(keepends=True)
    combined = local_edits + remote_edits
    for start, end, replacement in sorted(
            combined, key=lambda item: (item[0], item[1]), reverse=True):
        result[start:end] = replacement
    return "".join(result)


def decide(base: str | None, local: str | None, remote: str | None):
    """返回 (动作, 合并结果)。

    动作：noop / push / pull / delete_local / delete_remote / merge / conflict。
    None 表示该侧不存在；base 与某一侧相同代表该侧相对基线未修改。
    """
    if local == remote:
        return "noop", None
    if local == base:
        return ("pull", None) if remote is not None else ("delete_local", None)
    if remote == base:
        return ("push", None) if local is not None else ("delete_remote", None)
    if local is None or remote is None:
        return "conflict", None
    merged = three_way_merge(base or "", local, remote)
    if merged is None:
        return "conflict", None
    return "merge", merged
