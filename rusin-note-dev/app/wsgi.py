"""WSGI 入口：gunicorn 'app.wsgi:app'"""
from . import create_app

app = create_app()