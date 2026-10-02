# 存储后端说明（无服务器关键）

> 各部署方式见 [部署总览](index.md)。

存储层（`app/core/storage.py`）是项目的统一数据接口，提供五种后端，由 `RUSIN_STORAGE` 环境变量显式指定，未指定时自动识别：

| 后端 | 启用方式 | 说明 |
|---|---|---|
| `sqlite` | 默认（本地/VPS） | SQLite（`<DATA_DIR>/index.db`）保存索引用于快速查找，笔记与集合内容以 JSON 落盘到 `<DATA_DIR>/`；旧版 file 布局自动迁移 |
| `file` | `RUSIN_STORAGE=file` | 兼容旧部署的纯文件落盘：笔记为 `notes/<用户>/<ID>.txt` 纯文本（非 JSON），集合与图床/附件布局同 sqlite 行、但没有 `index.db`；数据写入 `RUSIN_DATA_DIR` |
| `upstash` | 设置 `KV_REST_API_URL` + `KV_REST_API_TOKEN`（Upstash Redis 的 REST 接口） | 数据存于外部 KV，多实例共享、冷启动不丢；纯 HTTPS 请求，任意支持 Python 的无服务器平台可用 |
| `postgres` | 设置 `DATABASE_URL`（Neon / 任意 PostgreSQL，Vercel 绑定 Neon 后自动注入） | 数据存于 `storage_kv`、`storage_notes`、`storage_images`、`storage_attachments` 表，多实例共享、冷启动不丢；跨实例互斥用 PG advisory lock |
| `memory` | `RUSIN_STORAGE=memory`（无服务器平台未配置上述存储时自动启用） | 纯内存，重启/冷启动清空，适合体验或临时部署 |

自动识别优先级：显式 `RUSIN_STORAGE` > `KV_REST_API_URL`+`KV_REST_API_TOKEN`（upstash）> `DATABASE_URL`（postgres）> 无服务器平台（memory）> 本地（sqlite）。

## 补充说明

- 犇犇动态已从纯内存改为持久化（外部存储可用时重启不丢，最多保留 `benben.max_posts` 条，默认 200）。
- 无服务器环境（检测到 `VERCEL` / `NETLIFY` / `AWS_LAMBDA_FUNCTION_NAME` 环境变量）不启动后台守护线程，清理任务改为请求内机会式执行；日志回退到 stderr（进入平台日志流）。
- 无服务器平台强烈建议设置 `RUSIN_SECRET_KEY`；未设置时若后端可持久化（file/upstash/postgres）会自动生成并存储，否则退回随机密钥（重启后登录态失效）。
- `.env.example` 提供 `RUSIN_STORAGE`、`RUSIN_DATA_DIR`、`RUSIN_SECRET_KEY`、`RUSIN_ADMIN` 四个示例；缓存相关环境变量见上表和部署章节。
- 数据目录布局与各集合键的完整说明见 [配置项详解](../configuration.md)。
