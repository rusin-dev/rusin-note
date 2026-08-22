"""笔记图床功能端到端测试：魔数校验、multipart 上传、公开读取与缓存头、
大小/配额/格式校验链、笔记保留字、bleach img 白名单与危险协议拦截、
管理页列表与删除、功能开关门控（服务不裂图）、用户隔离与 file 后端落盘。

运行：python images_test.py
自动使用临时 RUSIN_DATA_DIR，不影响现有数据目录。
"""
import io
import json
import os
import re
import sys
import tempfile

# 隔离数据目录（必须在导入 app 之前设置）
DATA_DIR = tempfile.mkdtemp(prefix="rusin-images-test-")
os.environ["RUSIN_DATA_DIR"] = DATA_DIR

from app import create_app, config as cfg  # noqa: E402
from app.extensions import limiter         # noqa: E402
from app.feature_flags import FEATURE_KEYS, set_flags  # noqa: E402
from app.images import (                   # noqa: E402
    generate_image_id, sniff_image_format, validate_image_id,
)
from app.notes import validate_note_id     # noqa: E402

USER = "picasso"
OTHER = "viewer5"
PASSWORD = "TestPass1!"

PNG = b"\x89PNG\r\n\x1a\n" + b"IHDR" + os.urandom(64)
JPEG = b"\xff\xd8\xff\xe0" + b"JFIF" + os.urandom(60)
GIF = b"GIF89a" + os.urandom(60)
WEBP = b"RIFF" + b"\x24\x00\x00\x00" + b"WEBPVP8 " + os.urandom(40)
FAKE = b"#!/bin/sh\necho not-an-image\n" + os.urandom(48)


def csrf_of(html: str) -> str:
    m = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', html)
    assert m, "页面中未找到 csrf_token"
    return m.group(1)


def register_and_login(client, username):
    r = client.get("/register")
    assert r.status_code == 200, f"注册页不可访问: {r.status_code}"
    r = client.post("/register", data={
        "username": username, "password": PASSWORD, "confirm": PASSWORD,
        "csrf_token": csrf_of(r.get_data(as_text=True))})
    assert r.status_code in (200, 302), f"注册 {username} 失败: {r.status_code}"
    r = client.get("/login")
    r = client.post("/login", data={
        "username": username, "password": PASSWORD,
        "csrf_token": csrf_of(r.get_data(as_text=True))})
    assert r.status_code in (200, 302), f"登录 {username} 失败: {r.status_code}"


def create_note(client, username, content=""):
    """创建一篇笔记，返回 (note_id, 编辑页 csrf)"""
    loc = client.get(f"/user/{username}/new").headers["Location"]
    note_id = loc.rstrip("/").rsplit("/", 1)[-1]
    csrf = csrf_of(client.get(loc).get_data(as_text=True))
    r = client.post(loc, data={"content": content, "csrf_token": csrf})
    assert r.status_code == 302, "保存笔记失败"
    return note_id, csrf


def upload(client, username, csrf, data, filename="shot.png", mime="image/png"):
    return client.post(f"/user/{username}/images", data={
        "file": (io.BytesIO(data), filename, mime),
        "csrf_token": csrf,
    }, content_type="multipart/form-data")


def main():
    passed = []

    def check(label, cond):
        assert cond, f"FAIL: {label}"
        passed.append(label)
        print(f"  [ok] {label}")

    app = create_app()
    app.config["TESTING"] = True
    limiter.enabled = False
    client = app.test_client()

    # ===== A. 魔数嗅探与 ID 校验（模块级） =====
    print("[A] 图片格式嗅探")
    check("识别 PNG", sniff_image_format(PNG) == "png")
    check("识别 JPEG（统一为 jpg）", sniff_image_format(JPEG) == "jpg")
    check("识别 GIF", sniff_image_format(GIF) == "gif")
    check("识别 WebP", sniff_image_format(WEBP) == "webp")
    check("非图片内容返回 None", sniff_image_format(FAKE) is None)
    check("过短数据返回 None", sniff_image_format(b"\x89PNG") is None)
    check("SVG 文本返回 None", sniff_image_format(b"<svg onload=alert(1)>") is None)
    iid = generate_image_id("png")
    check("生成的 ID 合法且带扩展名", validate_image_id(iid) and iid.endswith(".png"))
    check("非法 ID 被拒", validate_image_id("../evil.png") is False
          and validate_image_id("a.png.exe") is False and validate_image_id("") is False)

    # ===== B. 上传与公开读取 =====
    print("[B] 上传与读取")
    register_and_login(client, USER)
    note_id, csrf = create_note(client, USER)
    r = upload(client, USER, csrf, PNG)
    assert r.status_code == 200, f"上传失败: {r.status_code} {r.get_data(as_text=True)[:200]}"
    payload = json.loads(r.get_data(as_text=True))
    check("上传返回 JSON url/name", payload["url"].startswith(f"/image/{USER}/")
          and validate_image_id(payload["name"]))
    img_path = payload["url"]

    anon = app.test_client()  # 匿名读取（分享/公开页渲染的前提）
    r = anon.get(img_path)
    check("匿名可读取图片且字节一致", r.status_code == 200 and r.get_data() == PNG)
    check("Content-Type 与长缓存头", r.headers.get("Content-Type") == "image/png"
          and "max-age=86400" in r.headers.get("Cache-Control", ""))
    check("非法图片 ID -> 404", anon.get(f"/image/{USER}/../evil.png").status_code == 404)
    check("不存在图片 -> 404", anon.get(f"/image/{USER}/zzzz.png").status_code == 404)
    disk = os.path.join(DATA_DIR, "images", USER, payload["name"])
    check("file 后端二进制落盘一致", os.path.isfile(disk)
          and open(disk, "rb").read() == PNG)

    # ===== C. 校验链 =====
    print("[C] 上传校验链")
    r = upload(client, USER, csrf, FAKE, filename="trojan.png")
    check("伪装扩展名的非图片 -> 400", r.status_code == 400 and "PNG / JPEG" in r.get_data(as_text=True))
    r = upload(client, USER, csrf, b"", filename="empty.png")
    check("空文件 -> 400", r.status_code == 400)
    old_size = cfg.MAX_IMAGE_SIZE_BYTES
    cfg.MAX_IMAGE_SIZE_BYTES = 8
    r = upload(client, USER, csrf, PNG)
    cfg.MAX_IMAGE_SIZE_BYTES = old_size
    check("超单图大小 -> 400", r.status_code == 400)
    old_total = cfg.MAX_IMAGE_TOTAL_BYTES
    cfg.MAX_IMAGE_TOTAL_BYTES = 1  # 已有用量立即超配额
    r = upload(client, USER, csrf, PNG)
    cfg.MAX_IMAGE_TOTAL_BYTES = old_total
    try:
        quota_err = json.loads(r.get_data(as_text=True)).get("error", "")
    except ValueError:
        quota_err = ""
    check("超用户配额 -> 400", r.status_code == 400 and quota_err.startswith("图床空间不足"))

    c2 = app.test_client()  # 未登录：先取自身会话的 csrf，再绕过 CSRF 到达鉴权
    anon_csrf = csrf_of(c2.get("/login").get_data(as_text=True))
    r = c2.post(f"/user/{USER}/images", data={
        "file": (io.BytesIO(PNG), "x.png", "image/png"),
        "csrf_token": anon_csrf}, content_type="multipart/form-data")
    check("未登录上传 -> 401", r.status_code == 401)

    # ===== D. 路由保留字 =====
    print("[D] 路由与保留字")
    check("images 成为保留笔记 ID", validate_note_id("images") is False)
    r = client.get(f"/user/{USER}/images")
    check("/user/<u>/images 是管理页而非笔记", r.status_code == 200
          and "image-grid" in r.get_data(as_text=True))

    # ===== E. Markdown 渲染（bleach 白名单 + 危险协议拦截） =====
    print("[E] Markdown 渲染")
    r = client.post(f"/user/{USER}/{note_id}", data={
        "content": f"# 带图笔记\n\n![截图]({img_path})\n\n![x](javascript:alert(1))\n",
        "csrf_token": csrf})
    assert r.status_code == 302
    html = client.get(f"/user/{USER}/{note_id}.md").get_data(as_text=True)
    check("合法图片渲染为 img 标签", f'<img alt="截图" src="{img_path}"' in html)
    check("javascript: 协议被 bleach 拦截", "javascript:" not in html)

    # ===== F. 管理页 =====
    print("[F] 管理页")
    html = client.get(f"/user/{USER}/images").get_data(as_text=True)
    check("列表展示图片与用量", payload["name"] in html and "已用" in html)
    r = client.post(f"/user/{USER}/images/delete", data={
        "image_id": payload["name"], "csrf_token": csrf})
    assert r.status_code == 302, f"删除失败: {r.status_code}"
    check("删除后图片不可访问", anon.get(img_path).status_code == 404)

    # ===== G. 功能开关门控 =====
    print("[G] 功能开关 note_images")
    r = upload(client, USER, csrf, GIF)
    assert r.status_code == 200
    gif_url = json.loads(r.get_data(as_text=True))["url"]
    set_flags({k: (k != "note_images") for k in FEATURE_KEYS})
    cache_html = client.get(f"/user/{USER}/{note_id}").get_data(as_text=True)
    check("停用后编辑器不上传（IMAGES_API 为空）", 'const IMAGES_API = "";' in cache_html)
    check("停用后上传路由 -> 404", upload(client, USER, csrf, PNG).status_code == 404)
    check("停用后管理页 -> 404", client.get(f"/user/{USER}/images").status_code == 404)
    check("停用后已传图片仍可访问（不裂图）", anon.get(gif_url).status_code == 200)
    set_flags({k: True for k in FEATURE_KEYS})
    cache_html = client.get(f"/user/{USER}/{note_id}").get_data(as_text=True)
    check("重新启用后恢复上传", f'const IMAGES_API = "/user/{USER}/images";' in cache_html)

    # ===== H. 用户隔离 =====
    print("[H] 用户隔离")
    client.get("/logout")
    register_and_login(client, OTHER)
    _, other_csrf = create_note(client, OTHER)
    r = upload(client, OTHER, other_csrf, WEBP, filename="d.webp", mime="image/webp")
    assert r.status_code == 200
    other_url = json.loads(r.get_data(as_text=True))["url"]
    check("他人图片正常存取", anon.get(other_url).status_code == 200
          and anon.get(other_url).get_data() == WEBP)
    html = client.get(f"/user/{OTHER}/images").get_data(as_text=True)
    check("管理页只含自己的图片", other_url.split("/")[-1] in html and img_path.split("/")[-1] not in html)

    print(f"\n全部通过：{len(passed)} 项检查")


if __name__ == "__main__":
    try:
        main()
    except AssertionError as e:
        print(f"\n{e}")
        sys.exit(1)
