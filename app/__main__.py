"""入口：python -m app（跨平台默认使用 waitress）

Linux 生产建议：gunicorn 'app.wsgi:app' -b 0.0.0.0:$PORT --workers 2 --threads 4

WAF（nginx + ModSecurity + OWASP CRS）的规则集下载与配置生成只在本入口执行，
这样 gunicorn 多 worker 不会重复下载；其它部署方式用 ``python -m app.core.waf``
手动供给。启动参数 ``--waf-refresh`` 强制重新下载并校验规则集。

启动参数 ``--debug-panel``（别名 ``--debug-for-run``）开启页面诊断面板：可视化
验证码答案/缺口、轨迹可疑度与置信度、IP 风控分、TTFB 等。因暴露敏感信息，默认
仅回环客户端可见，仅限本地排障。
"""
import os
import sys

from waitress import serve

from app import create_app
from app.core import waf

_DEBUG_FLAGS = ("--debug-panel", "--debug-for-run")

if __name__ == "__main__":
    if any(flag in sys.argv for flag in _DEBUG_FLAGS):
        os.environ["RUSIN_DEBUG_PANEL"] = "1"
        # python -m app 会先导入 app 包（config 已在导入期固化 DEBUG_PANEL），
        # 故此处直接回写模块属性，确保 create_app 与请求期读到开启状态
        from app.core import config as _cfg
        _cfg.DEBUG_PANEL = True
        print("[警告] 调试面板已开启：页面将暴露验证码答案/缺口、轨迹可疑度与 IP 风控分，"
              "仅限本地排障（默认仅回环可见）。", flush=True)
    app = create_app()
    port = int(os.environ.get("PORT", 8080))
    for line in waf.format_status(waf.provision_waf(force_download="--waf-refresh" in sys.argv)):
        print(line, flush=True)
    print(f"服务已启动：http://localhost:{port}/", flush=True)
    serve(app, host="0.0.0.0", port=port)
