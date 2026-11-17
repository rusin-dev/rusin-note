"""清除 Windows「来自 Internet」标记（Mark-of-the-Web）。

浏览器下载的 ZIP 会带 ``Zone.Identifier`` 备用数据流，用资源管理器解压时该
标记会传给解出的每个文件。.NET 拒绝加载带此标记的程序集，pythonnet 初始化
随即抛 ``Failed to resolve Python.Runtime.Loader.Initialize``，pywebview 连
窗口都起不来（用户侧表现为「Unhandled exception in script」弹窗）。

冻结后的应用在导入 webview 之前先把标记清掉，用户无需手动右键「解除锁定」；
开发态（源码目录）不处理，避免改动工作区。
"""
from __future__ import annotations

import os
import sys

# 资源管理器下载后会写入的备用数据流；Zone.Identifier 是让 .NET 拒绝加载的元凶
_DOWNLOAD_STREAMS = ("Zone.Identifier", "SmartScreen")
# 只处理可能被 CLR 加载的程序集（避免遍历整棵树去改无关文件）
_ASSEMBLY_SUFFIXES = (".dll", ".exe", ".pyd")


def _app_root() -> str:
    """冻结应用的装载目录。

    onedir 为 exe 旁边的 ``_internal``（pythonnet 的 dll 都在这里），onefile 为
    每次启动解包的临时目录；两者都由 PyInstaller 的 ``sys._MEIPASS`` 给出。
    """
    meipass = getattr(sys, "_MEIPASS", "")
    if meipass and os.path.isdir(meipass):
        return meipass
    return os.path.dirname(os.path.realpath(sys.executable))


def _strip_download_streams(path: str) -> bool:
    """删除单个文件上的下载标记；返回是否真的删掉了东西。"""
    removed = False
    for stream in _DOWNLOAD_STREAMS:
        stream_path = f"{path}:{stream}"
        try:
            if os.path.exists(stream_path):
                os.remove(stream_path)
                removed = True
        except OSError:
            # 只读目录 / 无权限 / 非 NTFS：静默跳过，不影响启动
            pass
    return removed


def clear_mark_of_the_web(root: str | None = None) -> int:
    """递归清除 ``root`` 下程序集文件的下载标记，返回被清理的文件数。

    * 仅 Windows 生效，其它平台直接返回 0；
    * 未显式传入 ``root`` 时只对冻结应用生效（开发态不动源码目录）；
    * 任何异常都不外抛——这只是启动前的尽力修复，失败仍按原样启动。
    """
    if sys.platform != "win32":
        return 0
    if root is None:
        if not getattr(sys, "frozen", False):
            return 0
        root = _app_root()
    if not root or not os.path.isdir(root):
        return 0

    cleared = 0
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            if not name.lower().endswith(_ASSEMBLY_SUFFIXES):
                continue
            if _strip_download_streams(os.path.join(dirpath, name)):
                cleared += 1
    return cleared
