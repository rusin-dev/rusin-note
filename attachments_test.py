"""笔记附件功能端到端测试：文件类型黑名单、multipart 上传、公开读取与缓存头、
大小/配额/格式校验链、笔记保留字、管理页列表与删除、功能开关门控、用户隔离。

运行：python attachments_test.py
自动使用临时 RUSIN_DATA_DIR，不影响现有数据目录。
"""
import io
import json
import os
import re
import sys
import tempfile

# 隔离数据目录（必须在导入 app 之前设置）
DATA_DIR = tempfile.mkdtemp(prefix="rusin-attachments-test-")
os.environ["RUSIN_DATA_DIR"] = DATA_DIR

from app import create_app, config as cfg  # noqa: E402
from app.extensions import limiter         # noqa: E402
from app.feature_flags import FEATURE_KEYS, set_flags  # noqa: E402
from app.attachments import (              # noqa: E402
    generate_attachment_id, validate_attachment_id, validate_attachment_type,
    is_extension_blocked,
)
from app.notes import validate_note_id     # noqa: E402

USER = "testuser"
OTHER = "otheruser"
PASSWORD = "TestPass1!"

PDF_DATA = b"%PDF-1.4\n" + b"\x00" * 100
TXT_DATA = b"Hello, this is a test file.\n" + b"\x00" * 50
EXE_DATA = b"MZ" + b"\x00" * 100  # Windows executable
SH_DATA = b"#!/bin/bash\necho hello\n" + b"\x00" * 50
ZIP_DATA = b"PK" + b"\x00" * 100  # ZIP archive


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


def upload_attachment(client, username, csrf, data, filename="document.pdf"):
    return client.post(f"/user/{username}/attachments", data={
        "file": (io.BytesIO(data), filename, "application/octet-stream"),
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

    # ===== A. 文件类型校验（黑名单模式） =====
    print("[A] 文件类型校验")
    check("PDF 允许", validate_attachment_type("document.pdf") == (True, ""))
    check("TXT 允许", validate_attachment_type("readme.txt") == (True, ""))
    check("DOCX 允许", validate_attachment_type("report.docx") == (True, ""))
    check("EXE 被禁止", validate_attachment_type("program.exe") == (False, "err_attachment_blocked_type"))
    check("BAT 被禁止", validate_attachment_type("script.bat") == (False, "err_attachment_blocked_type"))
    check("SH 被禁止", validate_attachment_type("script.sh") == (False, "err_attachment_blocked_type"))
    check("ZIP 被禁止", validate_attachment_type("archive.zip") == (False, "err_attachment_blocked_type"))
    check("空文件名被拒", validate_attachment_type("") == (False, "err_attachment_no_filename"))
    check("is_extension_blocked 正确", is_extension_blocked("test.exe") and not is_extension_blocked("test.pdf"))

    aid = generate_attachment_id("document.pdf")
    check("生成的 ID 合法且带扩展名", validate_attachment_id(aid) and aid.endswith(".pdf"))
    check("非法 ID 被拒", validate_attachment_id("../evil.pdf") is False
          and validate_attachment_id("") is False)

    # ===== B. 上传与公开读取 =====
    print("[B] 上传与读取")
    register_and_login(client, USER)
    note_id, csrf = create_note(client, USER)
    r = upload_attachment(client, USER, csrf, PDF_DATA, "report.pdf")
    assert r.status_code == 200, f"上传失败: {r.status_code} {r.get_data(as_text=True)[:200]}"
    payload = json.loads(r.get_data(as_text=True))
    check("上传返回 JSON url/name/id", payload["url"].startswith(f"/attachment/{USER}/")
          and validate_attachment_id(payload["id"])
          and payload["name"] == "report.pdf")
    att_path = payload["url"]

    anon = app.test_client()  # 匿名读取
    r = anon.get(att_path)
    check("匿名可读取附件且字节一致", r.status_code == 200 and r.get_data() == PDF_DATA)
    check("Content-Disposition 包含文件名", "report.pdf" in r.headers.get("Content-Disposition", ""))
    check("长缓存头", "max-age=86400" in r.headers.get("Cache-Control", ""))
    check("非法附件 ID -> 404", anon.get(f"/attachment/{USER}/../evil.pdf").status_code == 404)
    check("不存在附件 -> 404", anon.get(f"/attachment/{USER}/zzzz.pdf").status_code == 404)

    # ===== C. 校验链 =====
    print("[C] 上传校验链")
    r = upload_attachment(client, USER, csrf, EXE_DATA, "trojan.exe")
    try:
        exe_err = json.loads(r.get_data(as_text=True)).get("error", "")
    except ValueError:
        exe_err = ""
    check("可执行文件被禁止 -> 400", r.status_code == 400 and "可执行文件" in exe_err)
    r = upload_attachment(client, USER, csrf, b"", filename="empty.pdf")
    check("空文件 -> 400", r.status_code == 400)
    old_size = cfg.MAX_ATTACHMENT_SIZE_BYTES
    cfg.MAX_ATTACHMENT_SIZE_BYTES = 8
    r = upload_attachment(client, USER, csrf, PDF_DATA, "big.pdf")
    cfg.MAX_ATTACHMENT_SIZE_BYTES = old_size
    check("超单文件大小 -> 400", r.status_code == 400)
    old_total = cfg.MAX_ATTACHMENT_TOTAL_BYTES
    cfg.MAX_ATTACHMENT_TOTAL_BYTES = 1  # 已有用量立即超配额
    r = upload_attachment(client, USER, csrf, PDF_DATA, "over.pdf")
    cfg.MAX_ATTACHMENT_TOTAL_BYTES = old_total
    try:
        quota_err = json.loads(r.get_data(as_text=True)).get("error", "")
    except ValueError:
        quota_err = ""
    check("超用户配额 -> 400", r.status_code == 400 and quota_err.startswith("附件空间不足"))

    c2 = app.test_client()  # 未登录
    anon_csrf = csrf_of(c2.get("/login").get_data(as_text=True))
    r = c2.post(f"/user/{USER}/attachments", data={
        "file": (io.BytesIO(PDF_DATA), "x.pdf", "application/octet-stream"),
        "csrf_token": anon_csrf}, content_type="multipart/form-data")
    check("未登录上传 -> 401", r.status_code == 401)

    # ===== D. 路由保留字 =====
    print("[D] 路由与保留字")
    check("attachments 成为保留笔记 ID", validate_note_id("attachments") is False)
    r = client.get(f"/user/{USER}/attachments")
    check("/user/<u>/attachments 是管理页而非笔记", r.status_code == 200
          and "attachment-grid" in r.get_data(as_text=True))

    # ===== E. Markdown 渲染（附件链接） =====
    print("[E] Markdown 渲染")
    r = client.post(f"/user/{USER}/{note_id}", data={
        "content": f"# 带附件笔记\n\n[报告]({att_path})\n\n",
        "csrf_token": csrf})
    assert r.status_code == 302
    html = client.get(f"/user/{USER}/{note_id}.md").get_data(as_text=True)
    check("附件链接渲染为 a 标签", f'<a href="{att_path}">报告</a>' in html)

    # ===== F. 管理页 =====
    print("[F] 管理页")
    html = client.get(f"/user/{USER}/attachments").get_data(as_text=True)
    check("列表展示附件与用量", payload["id"] in html and "已用" in html)
    r = client.post(f"/user/{USER}/attachments/delete", data={
        "attachment_id": payload["id"], "csrf_token": csrf})
    assert r.status_code == 302, f"删除失败: {r.status_code}"
    check("删除后附件不可访问", anon.get(att_path).status_code == 404)

    # ===== G. 功能开关门控 =====
    print("[G] 功能开关 note_attachments")
    r = upload_attachment(client, USER, csrf, TXT_DATA, "readme.txt")
    assert r.status_code == 200
    txt_url = json.loads(r.get_data(as_text=True))["url"]
    set_flags({k: (k != "note_attachments") for k in FEATURE_KEYS})
    cache_html = client.get(f"/user/{USER}/{note_id}").get_data(as_text=True)
    check("停用后编辑器不上传（ATTACHMENTS_API 为空）", 'const ATTACHMENTS_API = "";' in cache_html)
    check("停用后上传路由 -> 404", upload_attachment(client, USER, csrf, PDF_DATA).status_code == 404)
    check("停用后管理页 -> 404", client.get(f"/user/{USER}/attachments").status_code == 404)
    check("停用后已传附件仍可访问", anon.get(txt_url).status_code == 200)
    set_flags({k: True for k in FEATURE_KEYS})
    cache_html = client.get(f"/user/{USER}/{note_id}").get_data(as_text=True)
    check("重新启用后恢复上传", f'const ATTACHMENTS_API = "/user/{USER}/attachments";' in cache_html)

    # ===== H. 用户隔离 =====
    print("[H] 用户隔离")
    csrf = csrf_of(client.get("/").get_data(as_text=True))
    client.post("/logout", data={"csrf_token": csrf})
    register_and_login(client, OTHER)
    _, other_csrf = create_note(client, OTHER)
    r = upload_attachment(client, OTHER, other_csrf, TXT_DATA, "other.txt")
    assert r.status_code == 200
    other_url = json.loads(r.get_data(as_text=True))["url"]
    check("他人附件正常存取", anon.get(other_url).status_code == 200
          and anon.get(other_url).get_data() == TXT_DATA)
    html = client.get(f"/user/{OTHER}/attachments").get_data(as_text=True)
    check("管理页只含自己的附件", other_url.split("/")[-1] in html and att_path.split("/")[-1] not in html)

    print(f"\n全部通过：{len(passed)} 项检查")


if __name__ == "__main__":
    try:
        main()
    except AssertionError as e:
        print(f"\n{e}")
        sys.exit(1)
