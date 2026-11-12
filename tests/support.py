"""端到端测试共享工具：HTTP 表单辅助 + 断言日志封装。

这些辅助函数统一了各测试模块中重复的 CSRF 解析、注册登录、创建笔记、
解析列表顺序等操作；:func:`expect` 在断言的同时通过 ``logging`` 输出结果。
"""
from __future__ import annotations

import io
import logging
import re

logger = logging.getLogger("rusin.tests")

DEFAULT_PASSWORD = "TestPass1!"

_CSRF_RE = re.compile(r'name="csrf_token"[^>]*value="([^"]+)"')
# 列表页中笔记链接（排除 /new、/images、/attachments、/settings、/shares 等入口）
_ENTRY_IDS = {"new", "images", "attachments", "settings", "shares", "todos",
              "export", "import", "notifications", "gitee"}


def expect(condition, message: str) -> None:
    """断言 ``condition`` 为真，并用 logging 记录结果。"""
    if condition:
        logger.info("  [PASS] %s", message)
    else:
        logger.error("  [FAIL] %s", message)
    assert condition, message


def csrf_of(html: str) -> str:
    """从 HTML 表单中提取 csrf_token。"""
    match = _CSRF_RE.search(html)
    assert match, "页面中未找到 csrf_token"
    return match.group(1)


def csrf_from(client, path: str) -> str:
    """访问 ``path`` 并提取其中的 csrf_token。"""
    return csrf_of(client.get(path).get_data(as_text=True))


def _captcha_data(html: str) -> dict:
    """开启验证码时读取一次性 token 并求解，返回可并入表单的字段。

    自动识别图形码（captcha 文本）与滑动拼图（captcha_x + captcha_traj）：
    滑动拼图按服务端阻尼曲线反解滑块位移，并合成类人轨迹（避免测试 IP 累积
    风险分触发升级/标记）。
    """
    token_match = re.search(r'name="captcha_token"[^>]*value="([^"]+)"', html)
    if not token_match:
        return {}
    token = token_match.group(1)
    if 'name="captcha_x"' in html:
        return _solve_slide(token)
    from app.core import captcha
    return {"captcha_token": token, "captcha": captcha.peek(token)}


def _solve_slide(token: str) -> dict:
    """反解滑动拼图：二分求使曲线输出=缺口 target 的滑块位移 d，合成类人轨迹。"""
    import json
    from app.core import slide_captcha
    sec = slide_captcha.peek(token)
    curve, S, target = sec.get("curve", []), sec.get("S", 0), sec.get("t", 0)
    lo, hi = 0.0, float(S)
    for _ in range(60):
        mid = (lo + hi) / 2
        if slide_captcha.curve_value(curve, mid) < target:
            lo = mid
        else:
            hi = mid
    d = round((lo + hi) / 2, 2)
    return {"captcha_token": token, "captcha_x": str(d),
            "captcha_traj": json.dumps(_human_traj(d))}


def _human_traj(d: float, n: int = 42, dur: float = 1150.0) -> list:
    """合成类人拖动轨迹：smoothstep 缓入缓出 + 手部抖动 + 末段微 overshoot。"""
    traj = []
    for i in range(n):
        p = i / (n - 1)
        ease = p * p * (3 - 2 * p)
        x = d * ease
        if i > n * 0.8:
            x += 1.2 if i % 2 else -0.8  # 末段微修正
        x += 0.5 if i % 3 else -0.4
        y = 2.0 + (i % 5) * 0.8
        t = dur * p + (i % 4) * 3
        traj.append({"x": round(x, 2), "y": round(y, 2), "t": round(t, 1)})
    traj[-1]["x"] = round(d, 2)
    return traj


def register(client, username: str, password: str = DEFAULT_PASSWORD, agree: bool = True):
    """注册新用户（自动获取并回填 CSRF token 与图形验证码；agree=False 时不勾选服务条款）。"""
    page = client.get("/register")
    assert page.status_code == 200, f"注册页不可访问: {page.status_code}"
    html = page.get_data(as_text=True)
    data = {
        "username": username,
        "password": password,
        "confirm": password,
        "csrf_token": csrf_of(html),
        **_captcha_data(html),
    }
    if agree:
        data["agree_terms"] = "1"
    return client.post("/register", data=data)


def login(client, username: str, password: str = DEFAULT_PASSWORD):
    """登录（自动回填 CSRF token；图形验证码开启时自动读取答案一并提交）。"""
    page = client.get("/login")
    html = page.get_data(as_text=True)
    data = {
        "username": username,
        "password": password,
        "csrf_token": csrf_of(html),
        **_captcha_data(html),
    }
    return client.post("/login", data=data)


def register_and_login(client, username: str, password: str = DEFAULT_PASSWORD) -> None:
    response = register(client, username, password)
    assert response.status_code in (200, 302), f"注册 {username} 失败: {response.status_code}"
    response = login(client, username, password)
    assert response.status_code in (200, 302), f"登录 {username} 失败: {response.status_code}"


def logout(client) -> None:
    """注销当前会话。"""
    csrf = csrf_of(client.get("/").get_data(as_text=True))
    client.post("/logout", data={"csrf_token": csrf})


def create_note(client, username: str, content: str = "", folder: str | None = None) -> str:
    """创建一篇笔记并返回其 ID（可同时设置文件夹）。"""
    location = client.get(f"/user/{username}/new").headers["Location"]
    note_id = location.rstrip("/").rsplit("/", 1)[-1]
    data = {
        "content": content,
        "csrf_token": csrf_of(client.get(location).get_data(as_text=True)),
    }
    if folder:
        data["folder"] = folder
    response = client.post(location, data=data)
    assert response.status_code == 302, f"保存笔记失败: {response.status_code}"
    return note_id


def list_order(client, username: str, query: str = "") -> list[str]:
    """解析列表页笔记链接的出现顺序（排除入口链接）。"""
    html = client.get(f"/user/{username}{query}").get_data(as_text=True)
    ids = re.findall(rf'href="/user/{username}/([a-z0-9]+)"', html)
    return [i for i in ids if i not in _ENTRY_IDS]


def upload_image(client, username: str, csrf: str, data: bytes,
                 filename: str = "shot.png", mime: str = "image/png"):
    """以 multipart 表单上传图片。"""
    return client.post(f"/user/{username}/images", data={
        "file": (io.BytesIO(data), filename, mime),
        "csrf_token": csrf,
    }, content_type="multipart/form-data")


def upload_attachment(client, username: str, csrf: str, data: bytes,
                      filename: str = "doc.pdf", mime: str = "application/pdf",
                      content: str | None = None):
    """以 multipart 表单上传附件（可选携带编辑器内容，用于单笔记配额估算）。"""
    payload = {
        "file": (io.BytesIO(data), filename, mime),
        "csrf_token": csrf,
    }
    if content is not None:
        payload["content"] = content
    return client.post(f"/user/{username}/attachments", data=payload,
                       content_type="multipart/form-data")


def pin_note(client, username: str, note_id: str, tag: str | None = None,
             folder: str | None = None, csrf: str | None = None):
    """切换笔记置顶状态（可在请求中保留筛选项）。"""
    data = {"csrf_token": csrf or csrf_of(client.get(f"/user/{username}").get_data(as_text=True))}
    if tag:
        data["tag"] = tag
    if folder:
        data["folder"] = folder
    return client.post(f"/user/{username}/{note_id}/pin", data=data)
