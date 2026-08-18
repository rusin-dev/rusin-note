"""入口：python -m app（跨平台默认使用 waitress）

Linux 生产建议：gunicorn 'app.wsgi:app' -b 0.0.0.0:$PORT --workers 2 --threads 4
"""
import os

from waitress import serve

from . import create_app

if __name__ == "__main__":
    app = create_app()
    port = int(os.environ.get("PORT", 8080))
    print(f"服务已启动：http://localhost:{port}/")
    serve(app, host="0.0.0.0", port=port)