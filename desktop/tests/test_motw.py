"""tests for src.core.motw / 清除 Windows 下载标记（Mark-of-the-Web）

背景：浏览器下载的 ZIP 带 Zone.Identifier 备用数据流，解压后继承到每个文件；
带该标记的 ``Python.Runtime.dll`` 会被 .NET 拒绝加载，pythonnet 初始化失败，
pywebview 起不来。冻结应用启动前调用 ``clear_mark_of_the_web`` 自愈。
"""
import os
import sys
from pathlib import Path

import pytest

from src.core.motw import clear_mark_of_the_web

windows_only = pytest.mark.skipif(sys.platform != "win32", reason="仅 Windows 有备用数据流")


def _add_mark(path: Path) -> str:
    """给文件写入 Zone.Identifier 备用数据流，返回流路径。"""
    stream_path = f"{path}:Zone.Identifier"
    with open(stream_path, "w", encoding="ascii") as handle:
        handle.write("[ZoneTransfer]\r\nZoneId=3\r\n")
    return stream_path


class TestGuards:
    def test_missing_root_is_noop(self, tmp_path):
        assert clear_mark_of_the_web(str(tmp_path / "does-not-exist")) == 0

    def test_dev_mode_does_not_touch_source_tree(self):
        """未冻结且未显式给 root 时不做任何事（开发态不动源码目录）。"""
        assert clear_mark_of_the_web() == 0


@windows_only
class TestStripping:
    def test_strips_assemblies_only(self, tmp_path):
        dll = tmp_path / "_internal" / "pythonnet" / "runtime" / "Python.Runtime.dll"
        dll.parent.mkdir(parents=True)
        dll.write_bytes(b"assembly")
        note = tmp_path / "readme.txt"
        note.write_text("hello", encoding="utf-8")
        dll_stream = _add_mark(dll)
        note_stream = _add_mark(note)

        assert clear_mark_of_the_web(str(tmp_path)) == 1
        assert not os.path.exists(dll_stream), "程序集上的下载标记应被清除"
        assert os.path.exists(note_stream), "非程序集文件不处理（避免无谓写盘）"

    def test_idempotent(self, tmp_path):
        exe = tmp_path / "app.exe"
        exe.write_bytes(b"binary")
        _add_mark(exe)
        assert clear_mark_of_the_web(str(tmp_path)) == 1
        assert clear_mark_of_the_web(str(tmp_path)) == 0, "第二次已无标记可清"

    def test_unmarked_tree_is_noop(self, tmp_path):
        (tmp_path / "a.dll").write_bytes(b"x")
        (tmp_path / "b.pyd").write_bytes(b"y")
        assert clear_mark_of_the_web(str(tmp_path)) == 0

    def test_read_only_file_does_not_raise(self, tmp_path):
        dll = tmp_path / "locked.dll"
        dll.write_bytes(b"x")
        _add_mark(dll)
        os.chmod(dll, 0o444)
        try:
            # 只读属性不清除，也不能让启动流程抛异常
            assert clear_mark_of_the_web(str(tmp_path)) in (0, 1)
        finally:
            os.chmod(dll, 0o666)
