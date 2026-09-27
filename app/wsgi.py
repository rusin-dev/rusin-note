"""WSGI 入口：gunicorn 'app.wsgi:app'"""
from app import create_app

app = create_app()