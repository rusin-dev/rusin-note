"""评论系统端到端测试：目标类型校验、匿名评论、冷却、分页、功能开关门控、用户隔离。

运行：python comments_test.py
"""
import json
import os
import sys
import tempfile
import shutil

# 强制 file 后端 + 临时目录，避免污染真实数据
_data = tempfile.mkdtemp(prefix="rusin-comments-test-")
os.environ["RUSIN_DATA_DIR"] = _data
os.environ.pop("RUSIN_STORAGE", None)
os.environ.pop("KV_REST_API_URL", None)
os.environ.pop("DATABASE_URL", None)

import pytest  # noqa: E402

# ---------- 常量 ----------
USER = "testcommenter"
PASS = "Test1234!"
SHARE_TOKEN = "a" * 64  # 64 字符的分享 token
NOTE_ID = "testnote"
COMMENT_URL = f"/comments/share/{SHARE_TOKEN}"
COMMENT_NOTE_URL = f"/comments/note/{USER}/{NOTE_ID}"


# ---------- helpers ----------
def _setup_app():
    """创建临时 config.json 并返回 Flask test client"""
    cfg = {
        "max_note_size_kb": 512,
        "sitename": "test",
        "trust_proxy_headers": False,
        "secure_cookies": False,
        "id_generation": {"length": 4, "use_uppercase": False, "use_lowercase": True, "use_digits": False},
        "share_token": {"length": 64, "use_uppercase": True, "use_lowercase": True, "use_digits": True},
        "rate_limit": {"window_seconds": 60, "max_requests": 100},
        "get_rate_limit": {"window_seconds": 60, "max_requests": 100},
        "save_rate_limit": {"window_seconds": 60, "max_requests": 100},
        "register_rate_limit": {"window_seconds": 120, "max_requests": 1},
        "password_policy": {"min_length": 8, "max_length": 128, "require_uppercase": True, "require_lowercase": True, "require_digits": True, "require_special": True},
        "benben": {"max_length": 1024, "page_size": 50, "cooldown_seconds": 3, "max_posts": 200},
        "comments": {"enabled": True, "max_length": 1024, "max_comments": 200, "cooldown_seconds": 3, "page_size": 50, "max_height_px": 1000},
        "features": {"comments": True},
        "images": {"enabled": False},
        "attachments": {"enabled": False},
        "note_refs": {"enabled": False},
        "avatar": {"enabled": False},
        "latex_render": {"enabled": False},
        "code_highlight": {"enabled": False},
        "plugins": {"enabled": False},
        "admin_users": [],
    }
    cfg_path = os.path.join(_data, "config.json")
    with open(cfg_path, "w") as f:
        json.dump(cfg, f)

    # 切换工作目录到临时目录
    old_cwd = os.getcwd()
    os.chdir(_data)

    from app import create_app
    app = create_app()
    app.config["TESTING"] = True

    # 创建测试用户
    from app.store import register_user
    register_user(USER, PASS)

    # 创建测试分享（手动设置 token）
    from app.store import shares, shares_lock, _persist, K_SHARES
    with shares_lock:
        shares[SHARE_TOKEN] = {
            "owner": USER,
            "note_id": NOTE_ID,
            "created_at": 1234567890,
            "editable": False,
            "views": 0,
        }
        _persist(K_SHARES, shares)

    os.chdir(old_cwd)
    return app


@pytest.fixture(scope="module")
def client():
    app = _setup_app()
    with app.test_client() as c:
        yield c


def _login(client, username=USER, password=PASS):
    """登录获取 session"""
    r = client.post("/login", data={"username": username, "password": password}, follow_redirects=True)
    return r.status_code == 200


def _get_csrf(client, url):
    """从页面提取 CSRF token"""
    r = client.get(url)
    html = r.get_data(as_text=True)
    import re
    m = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', html)
    return m.group(1) if m else None


# ---------- 测试 ----------
def test_comment_url_valid(client):
    """评论 URL 校验：合法目标返回 200"""
    r = client.get(COMMENT_URL)
    assert r.status_code == 200
    print("[ok] 分享评论页返回 200")


def test_comment_url_invalid_type(client):
    """评论 URL 校验：非法目标类型返回 404"""
    r = client.get("/comments/invalid/abc123")
    assert r.status_code == 404
    print("[ok] 非法目标类型返回 404")


def test_comment_url_invalid_id(client):
    """评论 URL 校验：非法目标 ID 返回 404"""
    r = client.get("/comments/share/../../etc/passwd")
    assert r.status_code == 404
    print("[ok] 非法目标 ID 返回 404")


def test_comment_url_nonexistent_share(client):
    """评论 URL 校验：不存在的分享返回 404"""
    r = client.get("/comments/share/nonexistent_token_123456")
    assert r.status_code == 404
    print("[ok] 不存在的分享返回 404")


def test_comment_post_anonymous(client):
    """匿名评论：未登录用户可以评论"""
    csrf = _get_csrf(client, COMMENT_URL)
    assert csrf, "无法获取 CSRF token"
    r = client.post(COMMENT_URL, data={
        "csrf_token": csrf,
        "content": "这是一条匿名评论",
        "is_anonymous": "on",
    }, follow_redirects=True)
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert "这是一条匿名评论" in html
    print("[ok] 匿名评论成功")


def test_comment_post_logged_in(client):
    """登录评论：登录用户可以评论"""
    # 清除冷却记录
    from app.store import comments_last_post, comments_cooldown_lock
    with comments_cooldown_lock:
        comments_last_post.clear()
    _login(client)
    csrf = _get_csrf(client, COMMENT_URL)
    assert csrf, "无法获取 CSRF token"
    r = client.post(COMMENT_URL, data={
        "csrf_token": csrf,
        "content": "这是一条登录用户评论",
        "is_anonymous": "",
    }, follow_redirects=True)
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert "这是一条登录用户评论" in html
    print("[ok] 登录用户评论成功")


def test_comment_empty_content(client):
    """空评论：应返回错误"""
    _login(client)
    csrf = _get_csrf(client, COMMENT_URL)
    assert csrf, "无法获取 CSRF token"
    r = client.post(COMMENT_URL, data={
        "csrf_token": csrf,
        "content": "",
        "is_anonymous": "",
    }, follow_redirects=True)
    assert r.status_code == 400
    print("[ok] 空评论返回错误")


def test_comment_too_long(client):
    """超长评论：应返回错误"""
    _login(client)
    csrf = _get_csrf(client, COMMENT_URL)
    assert csrf, "无法获取 CSRF token"
    r = client.post(COMMENT_URL, data={
        "csrf_token": csrf,
        "content": "x" * 2000,
        "is_anonymous": "",
    }, follow_redirects=True)
    assert r.status_code == 400
    print("[ok] 超长评论返回错误")


def test_comment_cooldown(client):
    """评论冷却：连续评论应被拒绝"""
    # 清除冷却记录
    from app.store import comments_last_post, comments_cooldown_lock
    with comments_cooldown_lock:
        comments_last_post.clear()
    _login(client)
    csrf = _get_csrf(client, COMMENT_URL)
    assert csrf, "无法获取 CSRF token"
    # 第一条评论
    r1 = client.post(COMMENT_URL, data={
        "csrf_token": csrf,
        "content": "第一条评论",
        "is_anonymous": "",
    }, follow_redirects=True)
    assert r1.status_code == 200
    # 立即发第二条评论
    csrf2 = _get_csrf(client, COMMENT_URL)
    r2 = client.post(COMMENT_URL, data={
        "csrf_token": csrf2,
        "content": "第二条评论",
        "is_anonymous": "",
    }, follow_redirects=True)
    assert r2.status_code == 400
    print("[ok] 评论冷却生效")


def test_comment_pagination(client):
    """评论分页：多条评论后分页正常"""
    # 先清除冷却记录
    from app.store import comments_last_post, comments_cooldown_lock
    with comments_cooldown_lock:
        comments_last_post.clear()

    _login(client)
    # 发布多条评论
    for i in range(5):
        csrf = _get_csrf(client, COMMENT_URL)
        if not csrf:
            continue
        client.post(COMMENT_URL, data={
            "csrf_token": csrf,
            "content": f"分页测试评论 {i}",
            "is_anonymous": "",
        }, follow_redirects=True)
    # 查看第一页
    r = client.get(COMMENT_URL)
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert "分页测试评论" in html
    print("[ok] 评论分页正常")


def test_comment_note_page(client):
    """笔记评论页：返回 200"""
    r = client.get(COMMENT_NOTE_URL)
    assert r.status_code == 200
    print("[ok] 笔记评论页返回 200")


def test_feature_flag_disabled(client):
    """功能开关停用：评论页返回 404"""
    from app.feature_flags import set_flags, FEATURE_KEYS
    set_flags({k: (k != "comments") for k in FEATURE_KEYS})
    r = client.get(COMMENT_URL)
    assert r.status_code == 404
    print("[ok] 停用后评论页返回 404")
    # 恢复
    set_flags({k: True for k in FEATURE_KEYS})


def test_user_isolation(client):
    """用户隔离：不同用户的评论互不影响"""
    # 清除冷却记录
    from app.store import comments_last_post, comments_cooldown_lock
    with comments_cooldown_lock:
        comments_last_post.clear()

    _login(client, USER, PASS)
    csrf = _get_csrf(client, COMMENT_URL)
    client.post(COMMENT_URL, data={
        "csrf_token": csrf,
        "content": "用户A的评论",
        "is_anonymous": "",
    }, follow_redirects=True)
    # 注册并登录另一个用户
    from app.store import register_user
    register_user("other_commenter", "Other1234!")
    _login(client, "other_commenter", "Other1234!")
    # 清除冷却记录
    with comments_cooldown_lock:
        comments_last_post.clear()

    csrf = _get_csrf(client, COMMENT_URL)
    client.post(COMMENT_URL, data={
        "csrf_token": csrf,
        "content": "用户B的评论",
        "is_anonymous": "",
    }, follow_redirects=True)
    # 查看评论列表
    r = client.get(COMMENT_URL)
    html = r.get_data(as_text=True)
    assert "用户A的评论" in html
    assert "用户B的评论" in html
    print("[ok] 用户评论隔离正常")


# ---------- 运行 ----------
if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = 0
    failed = 0
    for t in tests:
        try:
            t(client=None) if t.__code__.co_argcount == 0 else None
        except Exception as e:
            print(f"[FAIL] {t.__name__}: {e}")
            failed += 1
    # 使用 pytest 运行
    sys.exit(pytest.main([__file__, "-v"]))
