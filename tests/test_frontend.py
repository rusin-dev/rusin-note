"""前端资源静态语法检查的 pytest 封装。

真正的检查逻辑在 :mod:`tests.frontend_check`（也可单独作为 CLI 运行）；
本模块只负责在 pytest 会话中断言“没有语法错误”，并逐条记录错误日志。
"""
from __future__ import annotations

import logging
from pathlib import Path

from frontend_check import ROOT, collect_errors

logger = logging.getLogger("rusin.tests.frontend")


def test_frontend_syntax():
    errors = collect_errors()
    for path, line, message in errors:
        try:
            rel = Path(path).relative_to(ROOT)
        except ValueError:
            rel = Path(path)
        logger.error("%s:%s: %s", rel.as_posix(), line, message)
    assert not errors, f"发现 {len(errors)} 处前端语法错误"
