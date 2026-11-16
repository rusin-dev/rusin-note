# 贡献指南 | Contributing Guide

感谢你有兴趣为 rusin-note-desktop 做出贡献。本文档说明在 `desktop/` 子目录工作的约定；仓库整体流程见 [根贡献指南](../docs/CONTRIBUTING.md)。

> 桌面端是 rusin-note 网页版的 **WebView 原生壳**，**本地不保存笔记**。笔记、附件与同步全部由网页版负责，本地数据目录只放客户端配置、日志与 WebView 会话数据。请不要重新引入本地笔记存储或 Git 笔记同步——这类改动会直接违背产品定位，先开 Issue 讨论。

## 开始之前

- **提 Issue**：新功能、较大的重构、以及行为变更，先开 Issue 讨论范围和方案。
- **可以直接提 PR 的**：错别字与文档修正、明确的小 bug 修复。
- **不建议的**：未经讨论的依赖升级、目录结构大改、批量格式化既有代码。

## 环境搭建

项目使用 [uv](https://docs.astral.sh/uv/) 管理依赖和虚拟环境，Python 版本要求 **3.12 及以上**（见 `.python-version` 与 `pyproject.toml`）。

**所有依赖安装和运行操作都通过 `uv` 完成**，不要直接对系统 Python 使用 `pip`，也不要把 `.venv/` 提交到仓库。

```bash
# 安装 uv 本体（仅首次，推荐按 uv 官方文档的方式安装）
pip install uv

# 克隆 monorepo 后进入桌面端子目录
git clone <repo-url>
cd rusin-note/desktop

# 创建虚拟环境并安装依赖（含 dev 组的 pytest 与 PyInstaller）
uv sync

# 验证环境，应输出 Python 3.12+
uv run python --version

# 运行桌面端（首次启动会显示「连接站点」页）
uv run python main.py
```

新增或移除依赖请用 `uv add` / `uv remove`，它们会同步更新 `pyproject.toml` 和 `uv.lock`，请把这两个文件的改动一起提交（`uv.lock` 必须入库以保证构建可复现）：

```bash
uv add <package>      # 添加依赖
uv remove <package>   # 移除依赖
```

只临时装进环境、不写进 `pyproject.toml` 时用 `uv pip install <package>`（例如调试工具）。

平台运行时要求：Windows 需 WebView2（Win10/11 通常已预装）；Linux 需 GTK3 与 WebKit2GTK 4.1（PyGObject 编译还需 `libgirepository1.0-dev`、`gir1.2-webkit2-4.1`、`libcairo2-dev`、`pkg-config`、`gcc`、`python3-dev`）。

## 项目结构

```
main.py                 程序入口
data/metadata.json      随包版本信息（构建时由 release/build.py 写入）
src/
  app.py                应用装配：数据目录 → 单实例锁 → 配置 → 窗口
  core/                 与具体功能无关的基础设施
    window.py           WebView 原生壳、菜单、窗口几何、更新检查
    setup.py            首次运行「连接站点」页（自包含 HTML，无外部资源）
    site.py             站点 URL 规范化与校验
    data.py             DataService（仅客户端配置）
    logger.py           日志（RotatingFileHandler 轮转）
  modules/              功能模块，一个目录一件事
    ai_copilot/         AI 副驾驶，按后端拆分（openai / anthropic / ollama），尚未接入壳
    storage/            客户端配置存储（config.py，原子写入）
    updater.py          更新检查：读站点 /downloads/manifest.json
release/
  build.py              构建 + 打包 + 清单生成/合并
  rusin-note-desktop.spec  PyInstaller onedir 配置
tests/                  pytest（network 标记的用例依赖真实站点）
```

约定：

- 新的独立功能放在 `src/modules/<功能名>/` 下，模块内部通过 `__init__.py` 暴露必要接口，不要把实现细节散落到调用方。
- 跨功能复用的通用能力（日志、配置、窗口装配等）放在 `src/core/`。
- 同一类后端的多种实现参照 `ai_copilot` 的目录形态：各实现独立成文件，公共抽象放在 `base.py`。
- 客户端配置键只允许 `模块.键名` 两段（`src/modules/storage/config.py` 的 `_KEY_PATTERN`），如 `site.url`、`window.width`。
- pywebview 的 `Window` 没有可写的 `menu` 属性，也没有 `reload` 方法：菜单经 `webview.start(menu=...)` 传入，刷新用 `get_current_url()` + `load_url()`。改动窗口逻辑前先确认 API 存在。

## 测试与构建

```bash
uv run pytest tests/ -q -m "not network"   # 单元测试（跳过联网用例）
uv run pytest tests/ -q                    # 含联网用例（依赖真实站点，站点未部署时会 skip）
uv run python release/build.py             # 构建当前平台安装包 + 分清单
uv run python release/build.py --merge dist/downloads   # 合并为站点投放用的 manifest.json
```

- 改动 `src/` 必须补或改对应测试；窗口逻辑用 `tests/test_window.py` 里的 FakeWindow/FakeEvents 打桩，不要在单元测试里创建真实窗口。
- 构建产物在 `dist/`、中间文件在 `build/`，两者都不入库。
- 发布流程（投放到网页版 `<DATA_DIR>/downloads/`）见 [桌面客户端文档](../docs/desktop.md)。

## 开发流程

1. 从 **`dev`** 切出分支（仓库的活跃开发分支），分支名体现改动类型：`feat/desktop-fullscreen`、`fix/desktop-geometry`。
2. 提交信息沿用仓库现有风格，即 Conventional Commits 的前缀加中文描述：

   ```
   feat: 桌面端支持全屏切换
   fix: 修复最大化时窗口尺寸被写坏
   docs: 补充安装包发布说明
   ```

   一次提交只做一件事；功能未定型时可用 `WIP:` 前缀标记。
3. 本地确认改动可运行、测试通过、没有引入回归后再推送。
4. PR 的目标分支同样选 `dev`；**不要直接向 `main` 提 PR**。PR 描述请说明：改动目的、如何验证、关联的 Issue 编号（`Closes #123`）。
5. 及时 rebase 或合并 `dev` 的更新，减少冲突。PR 会触发 CodeQL 静态扫描，若报警请先修复并在 PR 描述中说明。
6. 维护者审阅后才会合并；请勿自行合并自己的 PR，除非只是修正文档笔误。

## 代码风格

以下约定来自仓库现有代码，请保持一致：

- 每个模块文件顶部写一段中文 docstring，说明该文件的职责（如 `"""日志入口"""`）。
- 函数带类型标注，返回值也标注（参考 `src/core/logger.py` 的 `get_logger(name: str, filename: str) -> Logger`）。
- 注释和文档字符串用中文；标识符用英文。
- 默认不写注释，只在「为什么」不明显时补一行：隐藏约束、微妙的不变量、针对某个 bug 的 workaround。
- 只在系统边界（网络响应、用户输入、外部配置文件）做校验，内部调用不过度防御。
- 不要在 PR 里夹带全仓库的格式改动。

## 许可证

提交贡献即表示你同意该贡献按仓库 `LICENSE`（GPL-3.0）中的条款发布，且你有权这样授权。请勿提交包含第三方专有代码或凭据（API Key、Token）的内容。