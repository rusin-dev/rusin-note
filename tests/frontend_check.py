#!/usr/bin/env python3
"""前端语法检查（本地 / CI 通用）。

前端资源全部内联在 Jinja2 模板中，本脚本静态扫描并报告语法错误：

1. Jinja2 模板语法      templates/**/*.html
2. 内联 JavaScript      <script>…</script>（跳过带 src 的外链），调用 Node `--check`
3. 内联 CSS             <style>…</style> 与 templates/partials/*_css.html，检查括号 / 字符串 / 注释配平
4. JSON 语法            *.json / **/*.json

用法::

    python tests/frontend_check.py

退出码 0 = 全部通过，1 = 存在语法错误。
在 GitHub Actions 中会额外输出 ``::error file=…,line=…::…`` 注解。
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from jinja2 import Environment, TemplateSyntaxError

ROOT = Path(__file__).resolve().parent.parent  # 仓库根目录（本脚本在 tests/ 下）
TEMPLATE_DIR = ROOT / "templates"

# 跳过目录：非前端源码 / 运行时数据 / 第三方安装产物
SKIP_DIRS = {
    ".git", ".venv", "venv", "env", "__pycache__", "node_modules",
    "plugins", "log", "image", "images", "uploads",
}

SCRIPT_RE = re.compile(r"<script\b([^>]*)>(.*?)</script\s*>", re.S | re.I)
STYLE_RE = re.compile(r"<style\b[^>]*>(.*?)</style\s*>", re.S | re.I)
SRC_ATTR_RE = re.compile(r"\bsrc\s*=", re.I)
TYPE_ATTR_RE = re.compile(r"\btype\s*=\s*[\"']?([^\"'\s>]+)", re.I)
JS_MIME_RE = re.compile(r"(java|ecma)script|^module$|^text/javascript$", re.I)

JINJA_COMMENT_RE = re.compile(r"\{#.*?#\}", re.S)
JINJA_EXPR_RE = re.compile(r"\{\{.*?\}\}", re.S)
JINJA_STMT_RE = re.compile(r"\{%.*?%\}", re.S)


def line_of(text: str, index: int) -> int:
    """返回 text 中 index 所在的行号（从 1 开始）。"""
    return text.count("\n", 0, index) + 1


def blank_jinja(match: re.Match, replacement: str) -> str:
    """把 Jinja 标签替换为占位符，并保留其中的换行，保证行号不错位。"""
    raw = match.group(0)
    return replacement + "\n" * raw.count("\n")


def neutralize_jinja(code: str) -> str:
    """把 Jinja 标签替换成合法 JS/CSS 片段，使内联代码可被语法检查。

    表达式 `{{ … }}` 统一替换为 `0`（既能当数值也能当标识符前缀），
    语句 `{% … %}` 与注释 `{# … #}` 直接置空。
    """
    code = JINJA_COMMENT_RE.sub(lambda m: blank_jinja(m, ""), code)
    code = JINJA_EXPR_RE.sub(lambda m: blank_jinja(m, "0"), code)
    code = JINJA_STMT_RE.sub(lambda m: blank_jinja(m, ""), code)
    return code


def iter_files(root: Path, pattern: str):
    for path in sorted(root.rglob(pattern)):
        if any(part in SKIP_DIRS for part in path.relative_to(ROOT).parts):
            continue
        yield path


# --------------------------------------------------------------------------- #
# 1. Jinja2 模板语法
# --------------------------------------------------------------------------- #
def check_jinja(path: Path, source: str, errors: list) -> None:
    try:
        # parse 只做语法解析，不解析 include/extends，也不执行过滤器
        Environment().parse(source)
    except TemplateSyntaxError as exc:
        errors.append((path, exc.lineno or 1, f"Jinja2 语法错误: {exc.message}"))


# --------------------------------------------------------------------------- #
# 2. 内联 JavaScript（Node --check）
# --------------------------------------------------------------------------- #
def check_js(code: str, path: Path, start_line: int, errors: list) -> None:
    node = shutil.which("node")
    if not node:
        return  # 无 Node 时静默跳过（CI 会安装 node）
    with tempfile.NamedTemporaryFile(
        "w", suffix=".js", delete=False, encoding="utf-8"
    ) as tmp:
        tmp.write(code)
        tmp_path = tmp.name
    try:
        proc = subprocess.run(
            [node, "--check", tmp_path],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
    finally:
        os.unlink(tmp_path)
    if proc.returncode == 0:
        return
    detail_lines = [ln for ln in (proc.stderr or "").strip().splitlines() if ln.strip()]
    match = re.search(r":(\d+)\b", detail_lines[0]) if detail_lines else None
    nline = int(match.group(1)) if match else 1
    message = next(
        (ln.strip() for ln in detail_lines if "Error" in ln),
        detail_lines[-1].strip() if detail_lines else "JavaScript 语法错误",
    )
    errors.append((path, start_line + nline - 1, f"JavaScript 语法错误: {message}"))


# --------------------------------------------------------------------------- #
# 3. 内联 CSS（括号 / 字符串 / 注释配平）
# --------------------------------------------------------------------------- #
_CLOSERS = {"}": "{", ")": "(", "]": "["}


def css_syntax_error(code: str) -> str | None:
    """返回第一个语法问题描述，未发现问题返回 None。"""
    stack: list[tuple[str, int]] = []
    i, n = 0, len(code)
    while i < n:
        ch = code[i]
        if ch == "/" and i + 1 < n and code[i + 1] == "*":
            end = code.find("*/", i + 2)
            if end == -1:
                return "注释 /* 未闭合"
            i = end + 2
            continue
        if ch in "\"'":
            j = i + 1
            while j < n:
                if code[j] == "\\":
                    j += 2
                    continue
                if code[j] == ch:
                    break
                if code[j] == "\n":
                    return f"{code[j - 1]!r} 处字符串未闭合"
                j += 1
            if j >= n:
                return f"{ch} 字符串未闭合"
            i = j + 1
            continue
        if ch in "{([":
            stack.append((ch, i))
        elif ch in "})]":
            if not stack:
                return f"多余的 '{ch}'"
            opener, _ = stack.pop()
            if opener != _CLOSERS[ch]:
                return f"'{opener}' 与 '{ch}' 不匹配"
        i += 1
    if stack:
        opener, index = stack[-1]
        return f"'{opener}' 未闭合（第 {line_of(code, index)} 行）"
    return None


def check_css(code: str, path: Path, start_line: int, errors: list) -> None:
    problem = css_syntax_error(code)
    if problem:
        errors.append((path, start_line, f"CSS 语法错误: {problem}"))


# --------------------------------------------------------------------------- #
# 4. JSON 语法
# --------------------------------------------------------------------------- #
def check_json(path: Path, errors: list) -> None:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        errors.append((path, 1, f"无法读取: {exc}"))
        return
    try:
        json.loads(text)
    except json.JSONDecodeError as exc:
        errors.append((path, exc.lineno, f"JSON 语法错误: {exc.msg}"))


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #
def check_template(path: Path, errors: list) -> None:
    source = path.read_text(encoding="utf-8")
    check_jinja(path, source, errors)

    for match in SCRIPT_RE.finditer(source):
        attrs = match.group(1) or ""
        if SRC_ATTR_RE.search(attrs):
            continue  # 外链脚本，非本项目源码
        type_match = TYPE_ATTR_RE.search(attrs)
        if type_match and not JS_MIME_RE.search(type_match.group(1)):
            continue  # 非 JS 内容（如 application/json）
        body = match.group(2)
        if not body.strip():
            continue
        check_js(
            neutralize_jinja(body),
            path,
            line_of(source, match.start(2)),
            errors,
        )

    for match in STYLE_RE.finditer(source):
        body = match.group(1)
        if not body.strip():
            continue
        check_css(
            neutralize_jinja(body),
            path,
            line_of(source, match.start(1)),
            errors,
        )


def collect_errors() -> list:
    """扫描仓库前端资源，返回 ``[(path, line, message), ...]``。

    供 CLI（:func:`main`）与 pytest（``tests/test_frontend.py``）复用。
    """
    errors: list = []

    # 模板：Jinja2 语法 + 内联 JS/CSS
    for path in iter_files(TEMPLATE_DIR, "*.html"):
        check_template(path, errors)
        # 纯 CSS 片段（被 <style>{% include %}</style> 引入）整体按 CSS 校验
        if path.name.endswith("_css.html"):
            check_css(
                neutralize_jinja(path.read_text(encoding="utf-8")), path, 1, errors
            )

    # 全仓库 JSON
    for path in iter_files(ROOT, "*.json"):
        check_json(path, errors)

    return errors


def main() -> int:
    # Windows 控制台默认 GBK，强制 UTF-8 避免中文/符号报错
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logger = logging.getLogger("rusin.frontend")

    errors = collect_errors()
    node = shutil.which("node")
    logger.info(
        "前端语法检查：Jinja2 模板 + 内联 JS（Node %s）/ CSS + JSON",
        "已启用" if node else "未找到，已跳过",
    )

    if not errors:
        logger.info("✓ 未发现语法错误")
        return 0

    for path, line, message in errors:
        rel = path.relative_to(ROOT) if path.is_absolute() else path
        rel = Path(rel).as_posix()
        if os.environ.get("GITHUB_ACTIONS"):
            # GitHub Actions 注解必须保持精确格式，直接写 stdout
            print(f"::error file={rel},line={line}::{message}")
        else:
            logger.error("%s:%s: %s", rel, line, message)
    logger.error("✗ 共发现 %d 处语法错误", len(errors))
    return 1


if __name__ == "__main__":
    sys.exit(main())
