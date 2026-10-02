# 插件系统

插件以 zip 包形式分发：把 `*.plugin.zip` 投放到运行时目录（`RUSIN_DATA_DIR`）即可，服务启动时自动解压安装并加载其中的 Flask 蓝图，安装完成后插件包自动删除。**无服务器部署（只读文件系统）不支持插件系统。**

## 插件包结构

```plaintext
+ desc.json          元信息
+ icon.ico           图标（可选，文件名须与 desc.icon 一致）
+ src/
  + __init__.py      必须定义 APP_ROUTER / OVERRIDE / ENV_VARIBLES
  + app.py           必须包含 Blueprint 实例（APP_ROUTER 可指向其它 .py 文件）
  + templates/       模板（以蓝图名为命名空间，避免与主站/其它插件重名覆盖）
  + static/          静态文件（访问路径 /<蓝图名>/static/<文件名>）
```

`desc.json` 示例：

```json
{
  "name": "示范插件",
  "version": "v0.1",
  "upstream_repo": "https://github.com/rusin-dev/template-plug",
  "icon": "icon.ico",
  "namespace": "template_plug",
  "auth_token": "sk-ccccddddddd"
}
```

- `namespace`：命名空间（`^[a-zA-Z0-9_\-]+$`），也是安装目录 `plugins/<namespace>` 与冲突检查的依据；
- `upstream_repo`：上游仓库，用于自动更新（可直接指向 zip 文件；GitHub 仓库地址会自动尝试 `main` / `master` 归档）；
- `auth_token`：认证令牌。**缺失时插件会被拒绝安装**，如确认信任须以 `--skip-auth` 启动参数（或环境变量 `RUSIN_PLUGIN_SKIP_AUTH=1`）显式放行。

`src/__init__.py` 模板：

```python
APP_ROUTER = "app.py"    # 承载 Blueprint 的文件（缺省 app.py）
OVERRIDE = False         # 复写主站静态文件的声明，形如
# OVERRIDE = {"source": {"static/dst.css": "static/src.css"}}
ENV_VARIBLES = []        # 声明依赖的环境变量名（缺失时启动日志警告）
```

## 加载与更新流程

- **Phase 1（安装）**：启动时扫描运行时目录的 `*.plugin.zip`，解压校验后安装到 `plugins/<namespace>/`，并把 `auth_token` 与 `last_update` 回写进 `desc.json`，随后删除插件包。校验项：zip 路径穿越与解压体积防护、根目录只允许 `desc.json` / 图标 / `src/`、auth_token 检查、命名空间冲突检查（不同来源的插件抢占同一命名空间必须声明 `OVERRIDE`，同源更新不受限制）、`src/app.py` 必须含 Blueprint（缺失记错误日志、插件不加载，不影响主站启动）。
- **Phase 2（更新）**：后台线程（默认每 6 小时）逐个检查 `plugins/*/desc.json`，`last_update` 距今超过 3 天则请求 `upstream_repo`（3 秒超时）；拿到新包后落为 `<namespace>.plugin.zip` 并重跑 Phase 1——新插件热加载，已加载插件更新文件后提示重启生效。

## 配置与安全

- config.json `plugins` 段：`enabled`（总开关，默认 `true`）、`update_interval_hours`（更新检查周期，默认 6）、`update_stale_days`（触发上游检查的间隔天数，默认 3）。完整说明见 [配置项详解](configuration.md)。
- 插件是在服务进程内执行的 Python 代码，**只安装可信来源的插件**：auth_token 机制即为服务端校验插件来源预留（缺失时须显式 `--skip-auth` 放行）。
- 插件蓝图在短链 catch-all 之前注册，插件的单段路由不会被 `/<id>` 抢匹配；蓝图名与主程序或其它插件冲突时该蓝图拒绝加载并在日志报错。
- 插件自己的 POST 表单需自行包含 `{{ csrf_token() }}`（全站启用 CSRF 防护）。
