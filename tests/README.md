# tests/

Rusin-Note 的测试统一使用 **pytest + logging** 组织。所有端到端测试默认使用
临时 `RUSIN_DATA_DIR`（`file` 后端），不会污染本地数据。

## 运行方式

```bash
pip install -r requirements-dev.txt
pytest tests/                 # 运行全部测试
pytest tests/test_folders.py  # 只运行某个模块
pytest tests/ -q -k images    # 按关键字筛选
```

`pytest.ini` 已开启 `log_cli`，断言结果与场景步骤会直接打印。

## 文件说明

| 文件 | 说明 |
|---|---|
| `conftest.py` | 环境隔离与共享 fixtures：导入 app 前固定 `RUSIN_STORAGE=file` 与临时数据目录；`reset_runtime_state()` 清空 app 各模块的全部内存缓存；提供 `data_dir` / `app` / `client` / `anon` / `ctx` fixtures |
| `support.py` | 共享 HTTP 辅助（CSRF 解析、注册登录、建笔记、列表顺序、图床上传、置顶）与 `expect()`（logging + assert） |
| `test_frontend.py` | 前端语法检查（复用 `frontend_check.py`）：Jinja2 + 内联 JS/CSS + JSON |
| `test_folders.py` | 笔记文件夹树：路径规范化、树构建、`?folder=` 筛选、功能开关 |
| `test_images.py` | 图床：魔数校验、上传/读取、大小/配额/格式校验、XSS 白名单 |
| `test_org.py` | 组织：创建 / 加入 / 邀请审批 / 角色权限 / 组织笔记 |
| `test_pins.py` | 笔记置顶：开关、排序、筛选联动、持久化 |
| `test_user_settings.py` | 用户设置：简洁模式 / 修改密码 / 修改用户名（跨子系统数据迁移） |
| `frontend_check.py` | 前端语法检查 CLI（无 pytest 依赖，CI `frontend` job 直接调用；检查逻辑由 `test_frontend.py` 复用） |

## 约定

- **隔离**：`app` 的多个模块在导入时缓存了内存字典（用户 / 会话 / 标签 / 文件夹 /
  置顶 / 待办 / 功能开关 / 统计等）。`conftest.reset_runtime_state()` 会显式清空
  这些缓存并把 file 后端指向新的临时目录，因此每个测试类之间互不影响。
- **共享状态**：pytest 会为每个测试方法创建新的类实例，跨方法的共享数据不能挂在
  `self` 上，应使用 class 级 `ctx` fixture（一个 `SimpleNamespace`）。
- **断言**：统一用 `support.expect(condition, message)`；它通过 `logging` 记录
  结果，失败时抛出 AssertionError，pytest 会给出清晰的失败信息。
- **限流**：`app` fixture 已关闭限流（`limiter.enabled = False`），测试中可放心
  多次注册 / 登录 / 保存。

新增测试请以 `test_*.py` 命名放入本目录，并复用 `conftest.py` / `support.py`。
