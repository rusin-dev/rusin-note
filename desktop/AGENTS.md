# desktop/ 项目指南

rusin-note 桌面客户端：WebView 原生壳，**笔记数据全部存放在网页版**，本地只落盘客户端配置、日志与 WebView 会话数据。本目录是 rusin-note monorepo 的独立 uv 子项目，与网页版互不依赖。

## 约定
* 该目录为 Python 仓库，项目使用了 `uv`，所以一切安装 / 运行操作请使用：
    * `uv run ...`、`uv sync` 和 `uv pip install ...`（不要直接用 pip 或另建虚拟环境）
* Python >= 3.12；`uv.lock` 必须入库，`build/`、`dist/` 为构建产物不入库。
* 客户端配置键只允许 `模块.键名` 两段（`src/modules/storage/config.py` 的 `_KEY_PATTERN`），如 `site.url`、`window.width`。
* **不要重新引入本地笔记存储**：`DataService` 只有 `.config`，笔记/附件/同步一律由网页版负责。

## 常用命令
```bash
uv sync                                   # 安装依赖（含 dev 组 PyInstaller / pytest）
uv run python main.py                     # 运行桌面端
uv run pytest tests/ -q -m "not network"  # 单元测试（跳过联网用例）
uv run python release/build.py            # 构建当前平台安装包 + 分清单
uv run python release/build.py --merge dist/downloads   # 合并为 manifest.json
```

## 架构要点
* 入口 `main.py` → `src/app.py`：数据目录（`RUSIN_DESKTOP_DATA_DIR` 可覆盖）→ 单实例锁（msvcrt/fcntl，句柄须保持打开）→ `DataService.local` → `src/core/window.py` 的 `run()`。
* `src/core/window.py`：pywebview 原生壳。`webview.start(private_mode=False, storage_path=<数据目录>/webview)` 保留 Cookie 以保持登录态；`OPEN_EXTERNAL_LINKS_IN_BROWSER=True`、`ALLOW_DOWNLOADS=True`。菜单经 `webview.start(menu=...)` 传入（`Window` 没有可写的 `menu` 属性，也没有 `reload` 方法，刷新用 `get_current_url()` + `load_url()`）。窗口几何在 `closing` 事件落盘，最大化时不写尺寸。
* `src/core/setup.py`：首次运行「连接站点」页，自包含 HTML（无外部资源），JS 经 `pywebview.api.connect` 调 `ShellApi`；文案按 `navigator.language` 中英切换。
* `src/core/site.py`：站点 URL 规范化，只允许 http/https，拒绝凭据、空白与非 http scheme。
* `src/modules/updater.py`：更新检查走站点 `/downloads/manifest.json`（安装包站点自托管，不走 GitHub Releases），版本/渠道取随包 `data/metadata.json`（frozen 时从 `sys._MEIPASS` 读）。渠道不一致的清单直接拒绝。
* `release/build.py` + `release/rusin-note-desktop.spec` / `rusin-note-desktop.iss`：**Windows 用 Inno Setup 把 PyInstaller onedir 产物打成单个安装包 `.exe`（装完自动创建桌面/开始菜单快捷方式与卸载项，免管理员装到 `%LOCALAPPDATA%\Programs`）**，macOS / Linux 用 onedir 并压成 zip（内含 `.app`）或 tar.gz；算 sha256 后产出分清单，`--merge` 合成 GitHub Release 用的 `manifest.json`。Inno Setup 由 `find_iscc()` 定位（CI 上 `choco install innosetup` 提供），编译参数 `/DAppVersion` / `/DSourceDir` / `/DIconFile` / `/O` / `/F`。pywebview 自带 PyInstaller hook 会收集 WebView2 DLL 与 JS 资源，spec 只补平台相关 hiddenimports 与图标。
* 发布流程与配置项见仓库根 `docs/desktop.md`；CI 见 `.github/workflows/desktop-build.yml`（推 `desktop-v*` 标签或手动触发三平台构建）。