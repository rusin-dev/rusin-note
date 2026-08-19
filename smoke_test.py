"""Rusin-Note 冒烟测试：对当前 storage 后端跑核心流程（用 Flask test client）"""
import re
import time

from app import create_app


def get_csrf(client, url):
    r = client.get(url)
    m = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', r.get_data(as_text=True))
    assert m, f"未找到 csrf_token in {url} (status {r.status_code})"
    return m.group(1)


def main():
    app = create_app()
    app.config["TESTING"] = True
    client = app.test_client()
    uname = "smoke" + str(time.time_ns())[-12:]

    # 首页
    r = client.get("/")
    assert r.status_code == 200, f"GET / -> {r.status_code}"

    # 公开笔记
    r = client.get("/world")
    assert r.status_code == 302, f"GET /world -> {r.status_code}"
    loc = r.headers["Location"]
    nid = loc.rsplit("/", 1)[-1]
    csrf = get_csrf(client, loc)
    r = client.post(loc, data={"content": "# 测试\n\n公开笔记内容", "csrf_token": csrf})
    assert r.status_code == 302, f"POST world note -> {r.status_code}"
    r = client.get(loc + "/md")
    assert r.status_code == 200 and "公开笔记内容" in r.get_data(as_text=True), "world md 渲染失败"

    # 注册
    csrf = get_csrf(client, "/register")
    r = client.post("/register", data={
        "username": uname, "password": "Passw0rd!x",
        "confirm": "Passw0rd!x", "csrf_token": csrf,
    })
    assert r.status_code == 302, f"register -> {r.status_code}"

    # 登录（拿到会话 cookie）
    csrf = get_csrf(client, "/login")
    r = client.post("/login", data={
        "username": uname, "password": "Passw0rd!x", "csrf_token": csrf,
    })
    assert r.status_code == 302, f"login -> {r.status_code}"
    assert uname in client.get("/").get_data(as_text=True), "登录后首页未显示用户名"

    # 私有笔记（/new 302 跳转到新笔记页）
    r = client.get(f"/user/{uname}/new")
    assert r.status_code == 302, f"/user/new -> {r.status_code}"
    loc = r.headers["Location"]
    uid = loc.rstrip("/").rsplit("/", 1)[-1]
    assert client.get(loc).status_code == 200
    csrf = get_csrf(client, f"/user/{uname}/{uid}")
    r = client.post(f"/user/{uname}/{uid}", data={
        "note_id": uid, "content": "私有笔记内容", "csrf_token": csrf,
    })
    assert r.status_code == 302, f"save private note -> {r.status_code}"
    r = client.get(f"/user/{uname}/{uid}")
    assert "私有笔记内容" in r.get_data(as_text=True), "私有笔记读取失败"

    # 笔记列表
    r = client.get(f"/user/{uname}/")
    assert r.status_code == 200 and uid in r.get_data(as_text=True), "笔记列表缺失"

    # 分享
    csrf = get_csrf(client, f"/user/{uname}/shares")
    r = client.post(f"/user/{uname}/shares", data={
        "note_id": uid, "editable": "1", "csrf_token": csrf,
    })
    assert r.status_code == 302, f"create share -> {r.status_code}"
    share_html = client.get(f"/user/{uname}/shares").get_data(as_text=True)
    m = re.search(r'/share/([A-Za-z0-9]+)', share_html)
    assert m, "分享链接未出现在列表"
    token = m.group(1)
    r = client.get(f"/share/{token}")
    assert r.status_code == 200, f"GET share -> {r.status_code}"

    # 犇犇
    csrf = get_csrf(client, "/benben")
    r = client.post("/benben", data={"content": "第一条犇犇", "csrf_token": csrf})
    assert r.status_code == 302, f"benben post -> {r.status_code}"
    r = client.get("/benben")
    assert "第一条犇犇" in r.get_data(as_text=True), "犇犇列表缺失"

    # 统计
    r = client.get("/count")
    assert r.status_code == 200, f"GET /count -> {r.status_code}"

    # 登出
    r = client.get("/logout")
    assert r.status_code == 302, f"logout -> {r.status_code}"

    from app import storage as _st
    print(f"[{_st.kind}] 全部冒烟测试通过")


if __name__ == "__main__":
    main()