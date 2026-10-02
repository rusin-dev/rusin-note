# AWS Lambda

> 需要信用卡，不推荐。开始前的准备见 [部署总览](index.md)。

项目根目录提供 `lambda_handler.py`（基于 Mangum 适配 WSGI）：

1. 打包仓库上传（包含 `templates/`、`config.json` 等）；
2. 处理程序设为 `lambda_handler.handler`，配 API Gateway 代理集成；
3. 环境变量与 Vercel 相同（`RUSIN_SECRET_KEY`，`DATABASE_URL`）；
4. 内存建议 ≥ 512MB（Markdown 渲染需要）。

> 无服务器环境会自动跳过后台线程与本地 WAF 供给；未配置持久化后端时数据落 `memory`，冷启动即清空。详见 [存储后端说明](storage-backends.md)。
