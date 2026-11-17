# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置（onedir，免安装）。

data/metadata.json 必须随包：更新检查在冻结环境下从 sys._MEIPASS 读取它。
webview 的 WebView2 原生库与 js 资源由 pywebview 自带的 PyInstaller 钩子收集。
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
    [],
    exclude_binaries=True,
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
    # Windows 用站点 favicon 作为程序图标（安装包与快捷方式沿用同一图标）
    icon=str(ROOT / "data" / "app.ico") if sys.platform == "win32" else None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="rusin-note-desktop",
)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="rusin-note-desktop.app",
        bundle_identifier="com.rusin.note.desktop",
        info_plist={
            "CFBundleName": "rusin-note",
            "CFBundleDisplayName": "rusin-note",
            "CFBundleShortVersionString": META["version"],
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "11.0",
        },
    )