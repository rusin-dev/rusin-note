"""入口：python -m app（跨平台默认使用 waitress）

Linux 生产建议：gunicorn 'app.wsgi:app' -b 0.0.0.0:$PORT --workers 2 --threads 4

WAF（nginx + ModSecurity + OWASP CRS）的规则集下载与配置生成只在本入口执行，
这样 gunicorn 多 worker 不会重复下载；其它部署方式用 ``python -m app.core.waf``
手动供给。启动参数 ``--waf-refresh`` 强制重新下载并校验规则集。
"""
import os
import sys

from waitress import serve

from app import create_app
from app.core import waf

if __name__ == "__main__":
    app = create_app()
    port = int(os.environ.get("PORT", 8080))
    for line in waf.format_status(waf.provision_waf(force_download="--waf-refresh" in sys.argv)):
        print(line, flush=True)
    print(f"服务已启动：http://localhost:{port}/", flush=True)
    serve(app, host="0.0.0.0", port=port)
