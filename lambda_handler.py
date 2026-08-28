"""AWS Lambda 入口（基于 Mangum 将 WSGI Flask 应用适配为 Lambda handler）

使用方式：
    部署到 AWS Lambda，处理程序填：lambda_handler.handler
    同时创建 HTTP API（API Gateway V2）并启用 Proxy 集成。
"""
from mangum import Mangum

from app import create_app

_wsgi_app = create_app()
handler = Mangum(_wsgi_app, lifespan="off")
