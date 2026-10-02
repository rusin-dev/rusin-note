# Zeabur

> 开始前的准备（SECRET_KEY、环境变量）见 [部署总览](index.md)。

## 持久化数据（避免重新部署清空）

使用 Zeabur 从 GitHub 自动部署时，应用目录会在每次部署时重新构建。为了避免剪贴板、用户、分享链接和犇犇动态被清空，请把运行数据写入持久化卷：

1. 在 Zeabur 项目中打开当前服务。
2. 进入 `Storage` / `Volumes`，新增一个 Volume。
3. 将 Volume 挂载路径设置为 `/data`。
4. 进入 `Environment Variables`，新增环境变量 `RUSIN_DATA_DIR=/data`。
5. 重新部署服务。

不要将 Volume 挂载到项目根目录，否则可能覆盖部署出来的应用代码。设置完成后，运行数据会保存在 `/data` 下：

```plaintext
/data/index.db          # SQLite 索引：笔记 / KV / 图床 / 附件元数据（快速查找）
/data/notes/<用户>/<ID>.json   # 笔记内容（JSON）
/data/images/
/data/attachments/
/data/users.json
/data/sessions.json
/data/shares.json
/data/benben.json
/data/comments.json
/data/note_tags.json
/data/note_folders.json
/data/note_pins.json
/data/todos.json
/data/feature_flags.json
/data/orgs.json
/data/org_members.json
/data/org_invites.json
/data/org_join_requests.json
/data/.secret_key      # 自动生成的 SECRET_KEY（未设置 RUSIN_SECRET_KEY 时）
/data/plugins/         # 已安装的插件
/data/log/
```

> 本地/VPS 默认使用 `sqlite` 后端：SQLite（`index.db`）只保存索引元数据用于快速
> 列表 / 排序 / 检索 / 统计，笔记与各集合的**具体内容仍以 JSON 落盘**。首次启动时
> 会自动完成两套迁移：旧版纯文本笔记（`notes/<用户>/<ID>.txt` → `.json`）与散落在
> 项目根目录的旧运行数据（→ `data/`）。另：键 `note_titles.json` 虽在存储层登记，
> 但当前代码不读写，新部署不会生成该文件。

## 启用 Redis（页面缓存 + 共享限流）

Zeabur 是 PaaS 平台，不需要也不建议在容器里 `apt install redis`（构建产物每次重新部署会重建，装了也存不住）；标准做法是添加一个托管 Redis 服务，Zeabur 会自动把连接信息注入到其他服务：

1. 在 Zeabur 项目中打开 **Market** / **Marketplace**，搜索并添加 **Redis** 服务（内置 `redis/redis-stack-server` 镜像，Zeabur 会为它生成随机密码）。
2. 添加完成后，Zeabur 会自动向项目内其他服务注入 `REDIS_CONNECTION_STRING`、`REDIS_HOST`、`REDIS_PORT`、`REDIS_PASSWORD` 等变量（也可在 Redis 服务的「操作指南/Instructions」里查看连接信息）。
3. 回到本服务，进入 **Variables / 环境变量**，新增变量（跨服务引用，自动拼出带密码的连接串）：

   ```plaintext
   REDIS_URL = ${REDIS_CONNECTION_STRING}
   ```

   等价于 `redis://:密码@服务名:6379`。
4. 重新部署服务。启动时应用会主动 `PING` Redis：连通则页面缓存（首页/笔记/犇犇等）切换为 Redis 共享后端、限流计数也存入 Redis（多实例共享）；未连通则日志输出 `Redis 缓存不可达（…），已降级到 SimpleCache` 并退回进程内缓存，不影响功能。

> 说明：Redis 只负责缓存与限流；剪贴板、用户、分享、犇犇等业务数据仍由上面挂载的 `/data` 卷（`file` 后端）保存，两者互不影响。若追求数据多实例共享 / 不丢，可改用 `postgres` 或 `upstash` 后端（见 [存储后端说明](storage-backends.md)）。
