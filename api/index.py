"""Vercel 无服务器入口（@vercel/python 构建器自动识别 WSGI app）

部署：vercel 项目根目录，vercel.json 已将全部请求转发到本文件。
外部存储：在 Vercel 项目设置中绑定 Vercel KV（自动注入
KV_REST_API_URL / KV_REST_API_TOKEN），并设置 RUSIN_SECRET_KEY。
"""
from app import create_app

app = create_app()