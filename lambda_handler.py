"""AWS Lambda 无服务器入口（API Gateway 代理集成，经 Mangum 适配 WSGI）

部署：
1. 将本仓库打包上传（含 templates/、config.json 等）；
2. 处理程序设为 lambda_handler.handler；
3. 环境变量：KV_REST_API_URL / KV_REST_API_TOKEN（或 RUSIN_STORAGE=memory）、
   RUSIN_SECRET_KEY；内存 ≥ 512MB（Markdown 渲染需要）。
"""
from app import create_app
from mangum import Mangum

app = create_app()
handler = Mangum(app)