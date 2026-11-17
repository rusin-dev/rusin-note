# 桌面客户端（rusin-note-desktop）

桌面端是 rusin-note 网页版的 **WebView 原生壳**：一个独立窗口直接加载你的站点，不用开浏览器、不用找标签页。

**笔记数据全部存放在网页版**，桌面端本地不保存任何笔记、附件或同步状态。本地数据目录只放三样东西：客户端配置（站点地址、窗口几何）、日志、WebView 会话数据（Cookie / localStorage，用于保持登录态）。换一台电脑装桌面端、登录同一账号，看到的就是同一份笔记。

代码在独立仓库 `<owner>/rusin-note-desktop`，是一个独立的 uv 项目（自己的 `pyproject.toml` 与 `uv.lock`）。拆出独立仓库是为了让 `releases/latest` 只包含桌面端版本，并避免网页版的 tag 与发布节奏互相干扰；网页版 monorepo 的 `desktop/` 只是迁移期副本。

## 用户指南

### 安装

1. 打开站点的 `/downloads` 页面，按你的系统下载安装包：
   - **Windows**：单个 `rusin-note-desktop-<版本>-windows-x64.exe`，**下载后直接双击运行**，不需要解压，也不写注册表；
   - **macOS**：`.zip`，解压后把 `rusin-note-desktop.app` 拖到「应用程序」；
   - **Linux**：`.tar.gz`，解压后运行目录里的 `rusin-note-desktop`。
2. Windows 首次启动需要把内置运行时解到临时目录，约 2–3 秒才出窗口（之后每次启动仍需重新解包，稍慢于免解压版）；如果系统弹出 SmartScreen「Windows 已保护你的电脑」，点「更多信息 → 仍要运行」。
3. 首次运行会显示「连接站点」页，填入你的 rusin-note 地址（例如 `https://note.example.com`），点击连接。
4. 在窗口里正常登录即可。登录态会被保存，下次启动直接进入站点。

Windows 需要 [WebView2 运行时](https://developer.microsoft.com/microsoft-edge/webview2/)（Win10/11 通常已随 Edge 预装）；Linux 需要 GTK3 与 WebKit2GTK 4.1。

### Windows：0.1.0 / 0.1.1 解压版启动报 `Failed to resolve Python.Runtime.Loader.Initialize`

> 0.1.2 起 Windows 改为单个 `.exe`，不再解压，不会触发该问题。以下仅针对旧的解压版。

症状：双击 `rusin-note-desktop.exe` 弹出「Unhandled exception in script」，日志里是：

```plaintext
RuntimeError: Failed to resolve Python.Runtime.Loader.Initialize from
...\_internal\pythonnet\runtime\Python.Runtime.dll
```

原因：浏览器会给下载的 ZIP 打上「来自 Internet」标记（`Zone.Identifier` 备用数据流），用资源管理器解压时这个标记会继承给每个文件；Windows 的 .NET 拒绝加载带该标记的程序集，而 pythonnet（WebView 的 .NET 桥）正好依赖它，于是初始化失败。

处理：

- **0.1.1**：程序启动时会自动清除安装目录里的下载标记，无需任何操作。
- **0.1.0**：解压后手动解除锁定，任选一种——
  - 右键下载的 ZIP → 属性 → 勾选「解除锁定」→ 重新解压（推荐，先解锁再解压）；
  - 或对已解压目录执行：`Get-ChildItem .\rusin-note-desktop -Recurse -File | Unblock-File`。
- 直接换成 0.1.2 的单文件 `.exe` 即可永久绕开。

### 菜单

| 菜单 | 作用 |
|---|---|
| 文件 → 更改站点地址… | 重新打开连接页，切换到另一个 rusin-note 实例 |
| 文件 → 检查更新… | 读取站点 `/downloads/manifest.json`，发现新版本时询问是否打开下载页 |
| 文件 → 退出 | 关闭窗口 |
| 视图 → 重新加载 | 刷新当前页面（站点不可达时回到连接页） |
| 视图 → 全屏 | 切换全屏 |

窗口大小、位置与最大化状态会在关闭时记住，下次启动还原。同一时刻只允许一个实例运行（重复启动会直接退出），避免两个进程并发写同一份配置。

站点内的外部链接（含第三方登录跳转）交给系统浏览器打开，附件下载正常保存到系统下载目录。

### 本地数据目录

| 系统 | 路径 |
|---|---|
| Windows | `%APPDATA%\rusin-note-desktop\` |
| macOS | `~/Library/Application Support/rusin-note-desktop/` |
| Linux | `$XDG_DATA_HOME/rusin-note-desktop/`（默认 `~/.local/share/rusin-note-desktop/`） |

目录内为 `config.json`（客户端配置）、`logs/desktop.log`（滚动日志，4 MB × 3）、`webview/`（会话数据）、`instance.lock`（单实例锁）。

环境变量：

- `RUSIN_DESKTOP_DATA_DIR`：覆盖数据目录，便于便携运行与测试；
- `RUSIN_DESKTOP_DEBUG`：设为 `1` 开启 WebView 调试日志（默认关闭）。

> `webview/` 内含登录 Cookie，等同于浏览器配置文件，不要把它放进公共备份或共享目录。删除该目录即退出登录。

### 更新

桌面端不自动更新。菜单「检查更新…」会把随包携带的 `data/metadata.json`（版本 + 渠道）与站点清单比对：渠道必须一致（`stable` 只认 `stable`），版本更高时提示打开 `/downloads` 下载新包。Windows 直接替换那个 `.exe`，macOS / Linux 覆盖解压即可；配置与登录态都存在数据目录里，不受影响。

## 管理员：发布安装包

安装包**不进 Git**，托管在 `<owner>/rusin-note-desktop` 仓库的 **GitHub Releases** 资产上（Release 资产独立存储，不会让仓库历史膨胀）。

### 1. 构建

在 `rusin-note-desktop` 仓库根目录（需要 [uv](https://docs.astral.sh/uv/)）：

```bash
uv sync                              # 安装依赖（含 dev 组的 PyInstaller）
uv run python release/build.py       # 构建当前平台
```

产物落在 `dist/downloads/`：

```plaintext
dist/downloads/
├─ rusin-note-desktop-0.1.2-windows-x64.exe       安装包（Windows 单文件，免解压）
├─ rusin-note-desktop-0.1.2-macos-arm64.zip       安装包（内含 .app）
├─ rusin-note-desktop-0.1.2-linux-x64.tar.gz      安装包
└─ manifest-windows-x64.json                      该平台分清单（含 size 与 sha256）
```

Windows 走 PyInstaller 的 onefile 模式（`release/rusin-note-desktop-onefile.spec`），直接产出单个 `.exe`——下载即用，也顺带绕开了「解压后程序集带下载标记导致 pythonnet 加载失败」的问题；macOS / Linux 仍为 onedir + 压缩包（`.app` 与动态库目录不适合单文件）。onefile 每次启动都要解包到临时目录，首次出窗口约 2–3 秒（onedir 约 1.4 秒），这是换取「一个 exe」的代价。

常用参数：`--version`（默认取 `pyproject.toml`）、`--channel stable|beta`、`--notes "更新说明"`、`--released-at YYYY-MM-DD`。

三个平台各自构建后，把分清单与安装包放到同一目录再合并：

```bash
uv run python release/build.py --merge dist/downloads
```

合并会校验各平台版本/渠道一致，按 Windows → macOS → Linux 排序产出 `manifest.json`。

### 2. 发布与投放

安装包有两种来源，二选一（也可同时配置，远程优先）：

#### A. GitHub Releases（推荐，Vercel / Lambda 等无服务器部署唯一可行方式）

安装包不进 Git，但可以挂在 **GitHub Release 资产**上——Release 资产独立存储，不会让仓库历史膨胀，且支持 HTTPS、Range 断点续传与匿名下载。

1. 在发布桌面端的仓库（建议独立仓库，如 `<owner>/rusin-note-desktop`）打标签并发 Release，附件包含 `manifest.json` 与各平台安装包；
2. 网页版配置仓库名（环境变量优先，便于在 Vercel 上切换而不用改代码）：

   ```json
   "downloads": {
     "github_repo": "rusin-dev/rusin-note-desktop"
   }
   ```

   或设置环境变量 `RUSIN_DOWNLOADS_GITHUB_REPO=rusin-dev/rusin-note-desktop`。

3. 应用会读取：

   ```plaintext
   https://github.com/<owner>/<repo>/releases/latest/download/manifest.json
   ```

   并把 `/downloads/file/<id>` 实现为 **302** 跳转到同一 Release 的资产地址——安装包字节不经过应用服务器，不会消耗 Vercel 带宽。落地页、`/downloads/manifest.json` 与桌面端「检查更新」行为完全不变。

细节与注意事项：

- **安装包地址由清单地址同目录推导**：`…/releases/latest/download/manifest.json` → `…/releases/latest/download/<文件名>`。清单也可以为单条产物显式提供 `url`，但只接受 https 且主机限定为 `github.com` / `*.githubusercontent.com`，防止清单被篡改后变成任意跳转。
- **beta 渠道**：`releases/latest` 只指向最新正式版（预发布会被 GitHub 排除），beta 需要显式指定 tag 地址：

  ```json
  "downloads": {
    "manifest_url": "https://github.com/<owner>/<repo>/releases/download/v0.2.0-beta.1/manifest.json"
  }
  ```

  `manifest_url` 优先级高于 `github_repo`。
- **缓存**：远程清单默认进程内缓存 300 秒（`downloads.manifest_cache_seconds`），避免每次请求都出网；拉取失败时回退到上一次成功结果，首次失败则显示「暂无安装包」。
- **无出网环境不会崩**：拉取超时 8 秒、清单上限 256 KB，失败只降级为空状态。

#### B. 本地目录投放（VPS）

把整个目录的内容复制到网页版数据目录下的 `downloads/`（即 `config.json` 的 `downloads.dir`，默认 `<RUSIN_DATA_DIR>/downloads/`）：

```plaintext
<RUSIN_DATA_DIR>/downloads/
├─ manifest.json
├─ rusin-note-desktop-0.1.2-windows-x64.exe
├─ rusin-note-desktop-0.1.2-macos-arm64.zip
└─ rusin-note-desktop-0.1.2-linux-x64.tar.gz
```

投放后立即生效（服务层不缓存清单，落地页展示延迟由视图缓存 TTL 决定）。清单缺失时 `/downloads` 显示「暂无安装包」，不会报错。该方式下安装包由应用自身 `send_file` 流式发送，支持 Range，适合 VPS。

> 无服务器平台的文件系统只读且不持久，**不要**用方式 B；请用方式 A（GitHub Releases），或把 `/downloads` 指向自建 VPS 站点。

### 3. CI 自动构建（独立仓库）

桌面端源码与发布都放在独立仓库 `<owner>/rusin-note-desktop`，不放在网页版 monorepo 里。这样 `releases/latest` 只包含桌面端版本，网页版的 tag 不会把安装包清单挤掉，仓库历史也不会被二进制污染。

该仓库的 `.github/workflows/release.yml`：

- 推 `v*` 标签 → 三平台矩阵构建（各平台先跑自己的测试）→ `release` 作业合并清单，把 `manifest.json` 与各平台安装包一起挂到该 Release；
- 标签带 `-` 后缀（如 `v0.2.0-beta.1`）自动归入 `beta` 渠道并标记为 pre-release，**不会**成为 `releases/latest`；
- PR 只跑单元测试，不构建；
- 手动触发（workflow_dispatch）可填版本/渠道/更新说明，产物保留在 Actions artifact。

发布一个新版本：

```bash
git tag v0.2.0          # 预发布用 v0.2.0-beta.1
git push origin v0.2.0
```

网页版无需重新部署——它在请求时读取 `releases/latest/download/manifest.json`（缓存 `downloads.manifest_cache_seconds`，默认 5 分钟），新版 Release 发布后片刻即生效。

### 4. 校验与安全

清单是外部输入，服务层逐项校验：产物 id 只允许小写字母数字与 `_-`、文件名须匹配后缀白名单、sha256 须为 64 位小写十六进制、产物路径做 realpath 越界防护、体积超过 `downloads.max_file_mb` 的条目直接丢弃。下载响应带 `Content-Disposition: attachment`、`X-Content-Type-Options: nosniff`，支持 Range 断点续传，并按 `downloads.download_rate_limit` 限流。

落地页公开显示每个安装包的完整 SHA256，用户可自行校验：

```bash
sha256sum rusin-note-desktop-0.1.0-windows-x64.zip
```

相关配置项见 [配置项详解](configuration.md#桌面客户端下载)。

## 开发者

源码在独立仓库 `<owner>/rusin-note-desktop`（从网页版 monorepo 的 `desktop/` 拆出），仓库根目录结构：

```plaintext
rusin-note-desktop/
├─ main.py                  入口（uv run python main.py）
├─ pyproject.toml / uv.lock  独立 uv 项目，Python >= 3.12
├─ data/metadata.json       随包版本信息（构建时写入）
├─ src/
│  ├─ app.py                数据目录 → 单实例锁 → 配置 → 窗口
│  ├─ core/
│  │  ├─ window.py          WebView 原生壳、菜单、窗口几何、更新检查
│  │  ├─ setup.py           首次运行「连接站点」页（自包含 HTML）
│  │  ├─ site.py            站点 URL 规范化与校验
│  │  ├─ data.py            DataService（仅客户端配置）
│  │  └─ logger.py          滚动文件日志
│  └─ modules/
│     ├─ storage/config.py  JSON 配置存储（原子写入）
│     ├─ updater.py         站点清单拉取与版本比较
│     └─ ai_copilot/        AI provider 适配（保留模块，尚未接入壳）
├─ release/
│  ├─ build.py              构建 + 打包 + 清单生成/合并
│  └─ rusin-note-desktop.spec  PyInstaller onedir 配置
└─ tests/                   pytest（network 标记的用例依赖真实站点）
```

```bash
uv sync                                   # 安装依赖
uv run python main.py                     # 运行桌面端
uv run pytest tests/ -q -m "not network"  # 单元测试（跳过联网用例）
uv run pytest tests/ -q                   # 含联网用例
uv run python release/build.py            # 构建当前平台安装包
```

桌面端**只用 uv**（`uv run` / `uv sync` / `uv pip install`），不要用 pip 直接装依赖或另建虚拟环境。

技术要点：

- WebView 由 [pywebview](https://pywebview.flowrl.com/) 提供，Windows 走 EdgeChromium/WebView2（pythonnet），macOS 走 Cocoa/WebKit，Linux 走 GTK/WebKit2GTK；
- `webview.start(private_mode=False, storage_path=<数据目录>/webview)` 保留 Cookie 与 localStorage，这是「比浏览器更方便」的关键——登录态跨启动保持；
- `OPEN_EXTERNAL_LINKS_IN_BROWSER=True` 让外链与 OAuth 跳转走系统浏览器，`ALLOW_DOWNLOADS=True` 允许附件下载；
- 窗口几何在 `closing` 事件里落盘（最大化时不写尺寸，避免还原后尺寸失真）；
- PyInstaller 为 onedir 模式，pywebview 自带的 hook 会收集 WebView2 DLL 与 JS 资源，spec 只额外补平台相关的 hiddenimports 与 `data/metadata.json`。