# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 单文件打包配置（Windows：下载即用的单个 .exe）。

onefile 每次启动会把包内容解到临时目录（``sys._MEIPASS``），随包资源
（``data/metadata.json``）与 pythonnet 的 ``Python.Runtime.dll`` 都在解包目录里。
浏览器下载的 exe 会带「来自 Internet」标记，``main.py`` 在导入 webview 之前
会清掉安装目录内的该标记，因此单个 exe 双击即可运行，无需解压或解锁。
"""
import json
import sys
from pathlib import Path

ROOT = Path(SPECPATH).resolve().parent
META = json.loads((ROOT / "data" / "metadata.json").read_text(encoding="utf-8"))

hiddenimports = []
if sys.platform == "win32":
    hiddenimports += ["clr", "webview.platforms.edgechromium", "webview.platforms.winforms"]
elif sys.platform == "darwin":
    hiddenimports += ["webview.platforms.cocoa"]
else:
    hiddenimports += ["webview.platforms.gtk"]

a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[(str(ROOT / "data" / "metadata.json"), "data")],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="rusin-note-desktop",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
