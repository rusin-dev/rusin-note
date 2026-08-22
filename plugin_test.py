"""插件系统端到端测试：构造示例插件包，验证 Phase 1 安装 / 蓝图加载 /
OVERRIDE 复写 / auth_token 检查 / 命名空间冲突 / Phase 2 上游更新。

运行：python plugin_test.py
自动使用临时 RUSIN_DATA_DIR，不影响现有数据目录。
"""
import io
import json
import os
import sys
import tempfile
import threading
import zipfile
from http.server import BaseHTTPRequestHandler, HTTPServer

# 隔离数据目录（必须在导入 app 之前设置）
DATA_DIR = tempfile.mkdtemp(prefix="rusin-plugin-test-")
os.environ["RUSIN_DATA_DIR"] = DATA_DIR

from app import create_app          # noqa: E402
from app import plugins             # noqa: E402


# ---------- 插件包构造工具 ----------
def make_zip(path, namespace, *, name=None, version="v0.1", auth_token="sk-test-token",
             upstream_repo=None, override=False, app_py=None, tpl_body=None,
             css_body=None, extra_top=None, raw_entries=None):
    name = name or namespace
    app_py = app_py or (
        "from flask import Blueprint, render_template\n"
        f'bp = Blueprint("{namespace}", __name__, '
        'template_folder="templates", static_folder="static")\n'
        f"@bp.route('/{namespace}')\n"
        "@bp.route('/plug-home')\n"
        "def index():\n"
        f"    return render_template('plug.html', message='{version}')\n"
    )
    tpl_body = tpl_body or "<h1>PLUGIN-{{ message }}</h1>"
    css_body = css_body or f"body{{content:'{namespace}';}}"
    init_py = (
        'APP_ROUTER = "app.py"\n'
        f"OVERRIDE = {override!r}\n"
        "ENV_VARIBLES = []\n"
    )
    desc = {"name": name, "version": version, "namespace": namespace,
            "icon": "icon.ico"}
    if upstream_repo:
        desc["upstream_repo"] = upstream_repo
    if auth_token is not None:
        desc["auth_token"] = auth_token

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("desc.json", json.dumps(desc, ensure_ascii=False))
        zf.writestr("icon.ico", b"\x00\x00\x01\x00fake-icon")
        zf.writestr("src/__init__.py", init_py)
        zf.writestr("src/app.py", app_py)
        zf.writestr("src/templates/plug.html", tpl_body)
        zf.writestr("src/static/style.css", css_body)
        if extra_top:
            zf.writestr(extra_top, "pwned")
        for arcname, data in (raw_entries or {}).items():
            zf.writestr(arcname, data)  # 用于构造穿越/异常条目
    with open(path, "wb") as f:
        f.write(buf.getvalue())
    return path


def zip_path(fname):
    return os.path.join(DATA_DIR, fname)


def read_desc(namespace):
    with open(os.path.join(DATA_DIR, "plugins", namespace, "desc.json"),
              encoding="utf-8") as f:
        return json.load(f)


def main():
    passed = []

    def check(label, cond):
        assert cond, f"FAIL: {label}"
        passed.append(label)
        print(f"  [ok] {label}")

    # ===== A. 正常安装（含 auth_token）：解压、删 zip、回写 desc、蓝图可用 =====
    print("[A] 正常安装")
    make_zip(zip_path("demo.plugin.zip"), "template_plug", name="示范插件", version="v0.1")
    app = create_app()
    app.config["TESTING"] = True
    client = app.test_client()

    check("插件包解压后自动删除", not os.path.exists(zip_path("demo.plugin.zip")))
    check("安装到 plugins/<namespace>/",
          os.path.isdir(os.path.join(DATA_DIR, "plugins", "template_plug", "src")))
    desc = read_desc("template_plug")
    check("desc.json 回写 auth_token", desc.get("auth_token") == "sk-test-token")
    check("desc.json 回写 last_update", bool(desc.get("last_update")))

    r = client.get("/template_plug")
    check("插件路由（蓝图）可访问", r.status_code == 200 and "PLUGIN-v0.1" in r.get_data(as_text=True))
    r = client.get("/plug-home")
    check("单段路由未被短链 catch-all 抢匹配", r.status_code == 200)
    r = client.get("/template_plug/static/style.css")
    check("插件静态文件可访问", r.status_code == 200)
    r = client.get("/")
    check("主站首页不受影响", r.status_code == 200)

    # ===== B. OVERRIDE 静态复写 =====
    print("[B] OVERRIDE 复写")
    make_zip(zip_path("overrider.plugin.zip"), "override_plug", version="v0.2",
             override={"source": {"static/dst.css": "static/style.css"}},
             css_body="body{color:red}", app_py=(
                 "from flask import Blueprint\n"
                 "bp = Blueprint('override_plug', __name__, static_folder='static')\n"))
    app2 = create_app()
    client2 = app2.test_client()
    r = client2.get("/static/dst.css")
    check("OVERRIDE 命中主站路径返回插件文件",
          r.status_code == 200 and "color:red" in r.get_data(as_text=True))
    check("zip 已删除", not os.path.exists(zip_path("overrider.plugin.zip")))
    ns_list = [p["namespace"] for p in plugins.list_plugins()]
    check("两个插件均已加载", "template_plug" in ns_list and "override_plug" in ns_list)

    # ===== C. auth_token 缺失：默认拒绝，--skip-auth / 环境变量放行 =====
    print("[C] auth_token 检查")
    make_zip(zip_path("noauth.plugin.zip"), "noauth_plug", auth_token=None)
    plugins.install_plugin_archives()
    check("无 auth_token 且未 skip-auth → 拒绝安装（保留 zip 待处理）",
          os.path.exists(zip_path("noauth.plugin.zip"))
          and not os.path.isdir(os.path.join(DATA_DIR, "plugins", "noauth_plug")))
    os.remove(zip_path("noauth.plugin.zip"))

    make_zip(zip_path("noauth.plugin.zip"), "noauth_plug", auth_token=None)
    os.environ["RUSIN_PLUGIN_SKIP_AUTH"] = "1"
    plugins.install_plugin_archives()
    check("设置 RUSIN_PLUGIN_SKIP_AUTH=1 后放行",
          os.path.isdir(os.path.join(DATA_DIR, "plugins", "noauth_plug")))
    os.environ.pop("RUSIN_PLUGIN_SKIP_AUTH")

    # ===== D. 命名空间冲突：不同来源未声明 OVERRIDE 拒绝，声明后放行 =====
    print("[D] 命名空间冲突")
    make_zip(zip_path("rogue.plugin.zip"), "template_plug", name="恶意抢占", version="v9.9")
    plugins.install_plugin_archives()
    check("不同来源抢占命名空间且未声明 OVERRIDE → 拒绝",
          os.path.exists(zip_path("rogue.plugin.zip")) and read_desc("template_plug")["version"] == "v0.1")
    os.remove(zip_path("rogue.plugin.zip"))

    make_zip(zip_path("declared.plugin.zip"), "template_plug", name="显式覆盖", version="v0.5",
             override={"source": {"static/dst.css": "static/style.css"}})
    plugins.install_plugin_archives()
    check("声明 OVERRIDE 后允许覆盖安装", read_desc("template_plug")["version"] == "v0.5")

    # ===== E. app.py 无 Blueprint：安装成功但加载报 err =====
    print("[E] Blueprint 缺失")
    make_zip(zip_path("nobp.plugin.zip"), "nobp_plug",
             app_py="answer = 42\n")
    app3 = create_app()
    app3.test_client().get("/")
    check("zip 已消费", not os.path.exists(zip_path("nobp.plugin.zip")))
    check("无 Blueprint 的插件不进入已加载列表",
          "nobp_plug" not in [p["namespace"] for p in plugins.list_plugins()])

    # ===== F. zip-slip 路径穿越防护 =====
    print("[F] zip-slip 防护")
    make_zip(zip_path("evil.plugin.zip"), "evil_plug",
             raw_entries={"../evil.txt": "pwned"})
    plugins.install_plugin_archives()
    check("穿越条目被拒绝且未逃逸",
          os.path.exists(zip_path("evil.plugin.zip"))
          and not os.path.exists(os.path.join(DATA_DIR, "evil.txt"))
          and not os.path.isdir(os.path.join(DATA_DIR, "plugins", "evil_plug")))
    os.remove(zip_path("evil.plugin.zip"))

    # ===== G. 未声明的写入区域（根目录多余文件）=====
    print("[G] 写入区域检查")
    make_zip(zip_path("hack.plugin.zip"), "hack_plug", extra_top="hack.sh")
    plugins.install_plugin_archives()
    check("根目录多余文件被拒绝",
          os.path.exists(zip_path("hack.plugin.zip"))
          and not os.path.isdir(os.path.join(DATA_DIR, "plugins", "hack_plug")))
    os.remove(zip_path("hack.plugin.zip"))

    # ===== H. Phase 2 上游更新：过期 → 拉取 → 重跑 Phase 1 =====
    print("[H] 上游更新")
    make_zip(zip_path("upd.plugin.zip"), "upd_plug", version="v0.1")
    plugins.install_plugin_archives()
    app4 = create_app()
    r = app4.test_client().get("/upd_plug")
    check("v0.1 先加载", r.status_code == 200 and "PLUGIN-v0.1" in r.get_data(as_text=True))

    class ZipHandler(BaseHTTPRequestHandler):
        payload = b""

        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Length", str(len(self.payload)))
            self.end_headers()
            self.wfile.write(self.payload)

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), ZipHandler)
    port = server.server_address[1]
    upstream = f"http://127.0.0.1:{port}/upd.plugin.zip"
    new_zip = make_zip(zip_path("unused.plugin.zip"), "upd_plug", version="v0.2",
                       upstream_repo=upstream)
    ZipHandler.payload = open(new_zip, "rb").read()
    threading.Thread(target=server.serve_forever, daemon=True).start()

    # 把已安装插件的 upstream 指到本地服务，并把 last_update 回拨到过期
    desc_path = os.path.join(DATA_DIR, "plugins", "upd_plug", "desc.json")
    with open(desc_path, encoding="utf-8") as f:
        desc = json.load(f)
    desc["upstream_repo"] = upstream
    desc["last_update"] = "2020/1/1"
    with open(desc_path, "w", encoding="utf-8") as f:
        json.dump(desc, f, ensure_ascii=False)
    os.remove(new_zip)

    downloaded = plugins.check_updates_once()
    check("过期插件从上游拉到更新包", downloaded == 1
          and os.path.exists(zip_path("upd_plug.plugin.zip")))
    check("检查后 last_update 已刷新", read_desc("upd_plug")["last_update"] != "2020/1/1")

    plugins.install_plugin_archives()  # 重跑 Phase 1
    check("同源更新覆盖安装为 v0.2（重启后生效）",
          read_desc("upd_plug")["version"] == "v0.2"
          and not os.path.exists(zip_path("upd_plug.plugin.zip")))
    server.shutdown()

    print(f"\n[plugins] 全部 {len(passed)} 项测试通过（数据目录：{DATA_DIR}）")


if __name__ == "__main__":
    main()
