# rusin-note-desktop

<div align="center">
  <p><i>把 rusin-note 装到桌面上：WebView 原生壳，笔记数据全部存放在网页版</i></p>
</div>

<p align="center">
  <a href="https://www.python.org/">
    <img src="https://img.shields.io/badge/Python-3.12%2B-3776AB?style=for-the-badge&amp;logo=python&amp;logoColor=white" alt="Python 3.12+">
  </a>
</p>

<p align="center">
  <b>中文</b> | <a href="docs/README.en.md">English</a>
</p>

## 这是什么

rusin-note 网页版的桌面客户端。一个独立窗口直接加载你的站点，不用开浏览器、不用找标签页。

**本地不保存笔记。** 笔记、附件、同步全部由网页版负责，本地数据目录只放客户端配置（站点地址、窗口几何）、日志与 WebView 会话数据（用于保持登录态）。换台电脑装客户端、登录同一账号，看到的就是同一份笔记。

特性：

- 原生窗口加载站点，登录态跨启动保持
- 首次运行引导填站点地址，随时可从菜单切换实例
- 记住窗口大小 / 位置 / 最大化状态，单实例运行
- 外链与第三方登录交给系统浏览器，附件正常下载
- 菜单「检查更新」比对站点 `/downloads/manifest.json`，发现新版本引导下载
- 免安装：解压即用，不写注册表

> 本项目是 [rusin-note](../README.md) 的 monorepo 子目录，与网页版共用仓库但互不依赖。安装包由网页版 `/downloads` 页面自托管分发。

## 快速开始

需要 [uv](https://docs.astral.sh/uv/) 与 Python 3.12+。

```bash
uv sync                    # 安装依赖
uv run python main.py      # 运行桌面端
```

首次运行会显示「连接站点」页，填入你的 rusin-note 地址（如 `https://note.example.com`）并连接，然后在窗口里登录。

平台运行时要求：Windows 需 [WebView2](https://developer.microsoft.com/microsoft-edge/webview2/)（Win10/11 通常已预装）；Linux 需 GTK3 与 WebKit2GTK 4.1。

## 测试

```bash
uv run pytest tests/ -q -m "not network"   # 单元测试（跳过联网用例）
uv run pytest tests/ -q                    # 含联网用例（依赖真实站点）
```

## 构建安装包

```bash
uv run python release/build.py                        # 构建当前平台
uv run python release/build.py --merge dist/downloads # 合并各平台清单
```

产物在 `dist/downloads/`（安装包 + `manifest.json`），整目录投放到网页版数据目录的 `downloads/` 下即完成发布。详见 [桌面客户端文档](../docs/desktop.md)。

## 目录结构

```plaintext
desktop/
├─ main.py                  入口
├─ data/metadata.json       随包版本信息（构建时写入）
├─ src/
│  ├─ app.py                数据目录 → 单实例锁 → 配置 → 窗口
│  ├─ core/                 window / setup / site / data / logger
│  └─ modules/              storage（仅配置）/ updater / ai_copilot
├─ release/                 build.py + PyInstaller spec
└─ tests/                   pytest
```

## 约定

- **只用 uv**：安装 / 运行一律 `uv sync`、`uv run ...`、`uv pip install ...`，不要直接用 pip 或另建虚拟环境。
- `uv.lock` 必须入库以保证构建可复现；`build/`、`dist/` 为构建产物，不入库。
- 客户端配置键形如 `site.url`、`window.width`，只允许 `模块.键名` 两段（见 `src/modules/storage/config.py`）。

## 许可

见 [LICENSE](LICENSE)。