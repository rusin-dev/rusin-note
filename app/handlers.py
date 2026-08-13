"""HTTP 请求处理器（路由与请求处理）"""
import html
import os
import re
import urllib.parse
from http.server import BaseHTTPRequestHandler

from . import config
from . import templates
from .auth import (
    check_password_complexity,
    create_session,
    delete_session,
    generate_salt,
    get_session_user,
    hash_password,
    verify_password,
)
from .notes import (
    generate_random_id,
    get_note_path,
    list_user_notes,
    read_note,
    validate_note_id,
    validate_username,
    write_note,
    RESERVED_USERNAMES,
)
from .ratelimit import (
    is_get_rate_limited,
    is_rate_limited,
    is_save_rate_limited,
)
from .store import (
    create_share,
    delete_share,
    get_share,
    increment_share_views,
    save_users,
    users,
    users_lock,
)
from .theme import get_favicon, THEME_SCRIPT, THEME_VARS


class NoteHandler(BaseHTTPRequestHandler):
    _HTML_HEADER = "text/html; charset=utf-8"

    def log_request(self, code='-', size='-'):
        if code != 200:
            super().log_request(code, size)

    def get_client_ip(self) -> str:
        """获取客户端 IP。
        BUG-3: 仅当显式配置了可信代理（trust_proxy_headers=true）时才信任
        X-Forwarded-For / X-Real-IP 头，否则一律使用 TCP 对端地址，防止伪造头绕过限流。"""
        if config.TRUST_PROXY_HEADERS:
            forwarded = self.headers.get("X-Forwarded-For")
            if forwarded:
                ip = forwarded.split(",", 1)[0].strip()
                if ip:
                    return ip
            real_ip = self.headers.get("X-Real-IP")
            if real_ip:
                real_ip = real_ip.strip()
                if real_ip:
                    return real_ip
        return self.client_address[0]

    def get_session_cookie(self) -> str | None:
        cookie = self.headers.get("Cookie")
        if cookie:
            for pair in cookie.split(";"):
                pair = pair.strip()
                if pair.startswith("session="):
                    return pair[len("session="):]
        return None

    def get_theme(self) -> str | None:
        """从 Cookie 读取主题偏好（rusin-theme），供服务端直接渲染 data-theme，
        避免暗色模式下慢网速切换页面时闪白屏。仅接受合法值，视为不可信输入。"""
        cookie = self.headers.get("Cookie")
        if cookie:
            for pair in cookie.split(";"):
                pair = pair.strip()
                if pair.startswith("rusin-theme="):
                    value = pair[len("rusin-theme="):]
                    if value in ("dark", "light"):
                        return value
        return None

    def get_current_user(self) -> str | None:
        token = self.get_session_cookie()
        if token:
            return get_session_user(token)
        return None

    def is_authenticated(self, username: str) -> bool:
        return self.get_current_user() == username

    # ---------- 辅助响应 ----------
    def _read_form_body(self, max_bytes: int, max_fields: int = 10) -> dict | None:
        """安全读取并解析 POST 表单体。失败时直接发送 4xx 响应并返回 None。
        BUG-1: decode 使用 errors="replace"，非法 UTF-8 不再抛 UnicodeDecodeError；
        BUG-2: parse_qs 超限抛 ValueError 时返回 400；
        BUG-10: Content-Length 非数字/负数时返回 400。"""
        try:
            content_length = int(self.headers.get("Content-Length", 0))
        except (TypeError, ValueError):
            self.send_error(400, "Invalid Content-Length")
            return None
        if content_length < 0:
            self.send_error(400, "Invalid Content-Length")
            return None
        if content_length > max_bytes:
            self.send_error(413, "Request body too large")
            return None
        raw = self.rfile.read(content_length)
        post_data = raw.decode("utf-8", errors="replace")
        try:
            return urllib.parse.parse_qs(post_data, max_num_fields=max_fields)
        except ValueError:
            self.send_error(400, "Too many form fields")
            return None

    def _send_redirect(self, location):
        self.send_response(302)
        self.send_header("Location", location)
        self.end_headers()

    def _set_session_cookie(self, token: str):
        # BUG-13: Max-Age 与服务器端会话超时一致（未启用超时时为 30 天）；
        # Secure 标志由配置 secure_cookies 控制（仅 HTTPS 部署时开启）
        if config.SESSION_TIMEOUT_ENABLED:
            max_age = int(config.SESSION_TIMEOUT_SECONDS)
        else:
            max_age = config.COOKIE_MAX_AGE_DEFAULT
        cookie = f"session={token}; Path=/; Max-Age={max_age}; HttpOnly; SameSite=Lax"
        if config.SECURE_COOKIES:
            cookie += "; Secure"
        self.send_header("Set-Cookie", cookie)

    def _clear_session_cookie(self):
        cookie = "session=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax"
        if config.SECURE_COOKIES:
            cookie += "; Secure"
        self.send_header("Set-Cookie", cookie)

    # ---------- GET 请求 ----------
    def do_GET(self):
        client_ip = self.get_client_ip()
        # ADDED: GET独立限流
        if is_get_rate_limited(client_ip):
            self.send_error(429, f"Too many GET requests (max {config.GET_RATE_MAX} per {config.GET_RATE_WINDOW}s)")
            return

        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        # 首页
        if path == "/" or path == "":
            self.send_response(200)
            self.send_header("Content-Type", self._HTML_HEADER)
            self.end_headers()
            self.wfile.write(templates.render_home(self).encode("utf-8"))
            return

        # 统计页面
        if path == "/count":
            self.send_response(200)
            self.send_header("Content-Type", self._HTML_HEADER)
            self.end_headers()
            self.wfile.write(templates.render_count_page(self).encode("utf-8"))
            return

        # 免责声明
        if path == "/disclaimer":
            self.send_response(200)
            self.send_header("Content-Type", self._HTML_HEADER)
            self.end_headers()
            self.wfile.write(templates.render_disclaimer(self).encode("utf-8"))
            return

        # 注册页面
        if path == "/register":
            self.send_response(200)
            self.send_header("Content-Type", self._HTML_HEADER)
            self.end_headers()
            self.wfile.write(templates.render_register_form(self).encode("utf-8"))
            return

        # 登录页面
        if path == "/login":
            self.send_response(200)
            self.send_header("Content-Type", self._HTML_HEADER)
            self.end_headers()
            self.wfile.write(templates.render_login_form(self).encode("utf-8"))
            return

        # 登出
        if path == "/logout":
            token = self.get_session_cookie()
            if token:
                delete_session(token)
            self.send_response(302)
            self._clear_session_cookie()
            self.send_header("Location", "/")
            self.end_headers()
            return

        # 处理 favicon.ico
        if path == "/favicon.ico":
            data = get_favicon()  # BUG-16: 内存缓存，避免每次请求读磁盘
            if data:
                self.send_response(200)
                self.send_header("Content-Type", "image/x-icon")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            else:
                self.send_error(404, "Favicon not found")
            return

        # 单段短链接 -> 重定向到 /world/<名称>
        # 注意：必须放在所有固定路由（/register /login /logout /favicon.ico 等）之后
        # {剪贴板名字}.md -> 渲染为 Markdown 只读页面（与 /world/<id>/md 等价）
        md_short_match = re.match(r'^/([^/]+)\.md$', path)
        if md_short_match:
            note_id = md_short_match.group(1)
            if not validate_note_id(note_id):
                self.send_error(400, "Invalid note ID")
                return
            content = read_note("public", note_id)
            page = templates.render_markdown_page(self, note_id, content)
            self.send_response(200)
            self.send_header("Content-Type", self._HTML_HEADER)
            self.end_headers()
            self.wfile.write(page.encode("utf-8"))
            return

        short_link_match = re.match(r'^/([^/]+)$', path)
        if short_link_match:
            note_id = short_link_match.group(1)
            # 带扩展名的文件名（.html/.exe/.pdf 等）一律 404（.md 已在上方处理）
            if "." in note_id:
                self.send_error(404, "Not found")
                return
            if validate_note_id(note_id):
                self._send_redirect(f"/world/{note_id}")
                return

        # ---------- 新增：公开笔记 Markdown 渲染 /world/<id>/md ----------
        world_md_match = re.match(r'^/world/([^/]+)/md$', path)
        if world_md_match:
            note_id = world_md_match.group(1)
            if not validate_note_id(note_id):
                self.send_error(400, "Invalid note ID")
                return
            content = read_note("public", note_id)
            # 即使内容为空也渲染（显示空白）
            page = templates.render_markdown_page(self, note_id, content)
            self.send_response(200)
            self.send_header("Content-Type", self._HTML_HEADER)
            self.end_headers()
            self.wfile.write(page.encode("utf-8"))
            return

        # 公开笔记 Markdown 快捷方式：/world/<id>.md（等价于 /world/<id>/md）
        world_md_dot_match = re.match(r'^/world/([^/]+)\.md$', path)
        if world_md_dot_match:
            note_id = world_md_dot_match.group(1)
            if not validate_note_id(note_id):
                self.send_error(400, "Invalid note ID")
                return
            content = read_note("public", note_id)
            page = templates.render_markdown_page(self, note_id, content)
            self.send_response(200)
            self.send_header("Content-Type", self._HTML_HEADER)
            self.end_headers()
            self.wfile.write(page.encode("utf-8"))
            return

        # ---------- 分享只读 Markdown：/share/<token>/md ----------
        share_md_match = re.match(f'^/share/({config.SHARE_TOKEN_PATTERN})/md$', path)
        if share_md_match:
            token = share_md_match.group(1)
            share = get_share(token)
            if share is None:
                self.send_error(404, "Share not found")
                return
            increment_share_views(token)
            note_id = share.get("note_id", "")
            content = read_note(share.get("owner", ""), note_id)
            page = templates.render_markdown_page(
                self, note_id, content,
                title_label="分享笔记",
                back_url=f"/share/{token}",
                back_label="返回分享",
                navbar=templates.get_navbar(self),
            )
            self.send_response(200)
            self.send_header("Content-Type", self._HTML_HEADER)
            self.end_headers()
            self.wfile.write(page.encode("utf-8"))
            return

        # ---------- 分享只读 Markdown 快捷方式：/share/<token>.md（等价于 /share/<token>/md） ----------
        share_md_dot_match = re.match(f'^/share/({config.SHARE_TOKEN_PATTERN})\\.md$', path)
        if share_md_dot_match:
            token = share_md_dot_match.group(1)
            share = get_share(token)
            if share is None:
                self.send_error(404, "Share not found")
                return
            increment_share_views(token)
            note_id = share.get("note_id", "")
            content = read_note(share.get("owner", ""), note_id)
            page = templates.render_markdown_page(
                self, note_id, content,
                title_label="分享笔记",
                back_url=f"/share/{token}",
                back_label="返回分享",
                navbar=templates.get_navbar(self),
            )
            self.send_response(200)
            self.send_header("Content-Type", self._HTML_HEADER)
            self.end_headers()
            self.wfile.write(page.encode("utf-8"))
            return

        # ---------- 分享查看/编辑：/share/<token> ----------
        share_match = re.match(f'^/share/({config.SHARE_TOKEN_PATTERN})$', path)
        if share_match:
            token = share_match.group(1)
            share = get_share(token)
            if share is None:
                self.send_error(404, "Share not found")
                return
            increment_share_views(token)
            note_id = share.get("note_id", "")
            content = read_note(share.get("owner", ""), note_id)
            if share.get("editable"):
                page = templates.render_share_edit_page(self, token, note_id, content, share.get("owner", ""))
            else:
                page = templates.render_markdown_page(
                    self, note_id, content,
                    title_label="分享笔记",
                    back_url=f"/share/{token}",
                    back_label="刷新",
                    navbar=templates.get_navbar(self),
                )
            self.send_response(200)
            self.send_header("Content-Type", self._HTML_HEADER)
            self.end_headers()
            self.wfile.write(page.encode("utf-8"))
            return

        # 公开笔记路径：/world、/world/ 或 /world/<note_id>
        # BUG-4: 无斜杠 /world 与带斜杠 /world/ 行为一致（新建笔记）
        world_match = re.match(r'^/world(?:/([^/]+))?/?$', path)
        if world_match:
            note_id = world_match.group(1)
            if note_id is None:
                new_id = generate_random_id()
                self._send_redirect(f"/world/{new_id}")
                return

            if not validate_note_id(note_id):
                # 带扩展名的文件名（.html/.exe/.pdf 等）一律 404（.md 已在上方处理）
                if "." in note_id:
                    self.send_error(404, "Not found")
                else:
                    self.send_error(400, "Invalid note ID")
                return

            content = read_note("public", note_id)
            page = templates.render_note_page(self, note_id, content, is_world=True)
            self.send_response(200)
            self.send_header("Content-Type", self._HTML_HEADER)
            self.end_headers()
            self.wfile.write(page.encode("utf-8"))
            return

        # ---------- 私有笔记 Markdown：/user/<用户名>/<笔记ID>/md（需登录） ----------
        user_md_match = re.match(r'^/user/([^/]+)/([^/]+)/md$', path)
        if user_md_match:
            username = user_md_match.group(1)
            note_id = user_md_match.group(2)
            if not validate_username(username) or not validate_note_id(note_id):
                self.send_error(400, "Invalid username or note ID")
                return
            if not self.is_authenticated(username):
                self.send_response(401)
                self.send_header("Content-Type", self._HTML_HEADER)
                self.end_headers()
                body = "<h1>需要登录</h1><p>请先 <a href=\"/login\">登录</a> 或 <a href=\"/register\">注册</a> 以访问您的私有笔记。</p>"
                self.wfile.write(templates.render_base(self, body, "请先登录").encode("utf-8"))
                return
            content = read_note(username, note_id)
            page = templates.render_markdown_page(
                self, note_id, content,
                title_label="私有笔记",
                back_url=f"/user/{username}/{note_id}",
                back_label="返回编辑",
                navbar=templates.get_navbar(self, username),
            )
            self.send_response(200)
            self.send_header("Content-Type", self._HTML_HEADER)
            self.end_headers()
            self.wfile.write(page.encode("utf-8"))
            return

        # ---------- 私有笔记 Markdown 快捷方式：/user/<用户名>/<笔记ID>.md（需登录） ----------
        user_md_dot_match = re.match(r'^/user/([^/]+)/([^/]+)\.md$', path)
        if user_md_dot_match:
            username = user_md_dot_match.group(1)
            note_id = user_md_dot_match.group(2)
            if not validate_username(username) or not validate_note_id(note_id):
                self.send_error(400, "Invalid username or note ID")
                return
            if not self.is_authenticated(username):
                self.send_response(401)
                self.send_header("Content-Type", self._HTML_HEADER)
                self.end_headers()
                body = "<h1>需要登录</h1><p>请先 <a href=\"/login\">登录</a> 或 <a href=\"/register\">注册</a> 以访问您的私有笔记。</p>"
                self.wfile.write(templates.render_base(self, body, "请先登录").encode("utf-8"))
                return
            content = read_note(username, note_id)
            page = templates.render_markdown_page(
                self, note_id, content,
                title_label="私有笔记",
                back_url=f"/user/{username}/{note_id}",
                back_label="返回编辑",
                navbar=templates.get_navbar(self, username),
            )
            self.send_response(200)
            self.send_header("Content-Type", self._HTML_HEADER)
            self.end_headers()
            self.wfile.write(page.encode("utf-8"))
            return

        # ---------- 分享管理页面：/user/<用户名>/shares/（需登录） ----------
        shares_page_match = re.match(r'^/user/([^/]+)/shares/?$', path)
        if shares_page_match:
            username = shares_page_match.group(1)
            if not validate_username(username):
                self.send_error(400, "Invalid username")
                return
            if not self.is_authenticated(username):
                self.send_response(401)
                self.send_header("Content-Type", self._HTML_HEADER)
                self.end_headers()
                body = "<h1>需要登录</h1><p>请先 <a href=\"/login\">登录</a> 或 <a href=\"/register\">注册</a> 以访问您的分享管理。</p>"
                self.wfile.write(templates.render_base(self, body, "请先登录").encode("utf-8"))
                return
            page = templates.render_shares_page(self, username)
            self.send_response(200)
            self.send_header("Content-Type", self._HTML_HEADER)
            self.end_headers()
            self.wfile.write(page.encode("utf-8"))
            return

        # 私有用户路径：/user/<username>[/<note_id>] 或 /user/<username>/new
        # MODIFIED: 允许尾部斜杠
        user_match = re.match(r'^/user/([^/]+)(?:/([^/]+))?/?$', path)
        if user_match:
            username = user_match.group(1)
            note_id = user_match.group(2)

            if not validate_username(username):
                self.send_error(400, "Invalid username")
                return

            # 认证检查
            current_user = self.get_current_user()
            if current_user != username:
                self.send_response(401)
                self.send_header("Content-Type", self._HTML_HEADER)
                self.end_headers()
                body = "<h1>需要登录</h1><p>请先 <a href=\"/login\">登录</a> 或 <a href=\"/register\">注册</a> 以访问您的私有笔记。</p>"
                self.wfile.write(templates.render_base(self, body, "请先登录").encode("utf-8"))
                return

            if note_id == "new":
                new_id = generate_random_id()
                self._send_redirect(f"/user/{username}/{new_id}")
                return

            if note_id is None:
                notes = list_user_notes(username)
                self.send_response(200)
                self.send_header("Content-Type", self._HTML_HEADER)
                self.end_headers()
                self.wfile.write(templates.render_user_list(self, username, notes).encode("utf-8"))
                return

            if not validate_note_id(note_id):
                # 带扩展名的文件名（.html/.exe/.pdf 等）一律 404（.md 已在上方处理）
                if "." in note_id:
                    self.send_error(404, "Not found")
                else:
                    self.send_error(400, "Invalid note ID")
                return

            content = read_note(username, note_id)
            page = templates.render_note_page(self, note_id, content, username=username, is_world=False)
            self.send_response(200)
            self.send_header("Content-Type", self._HTML_HEADER)
            self.end_headers()
            self.wfile.write(page.encode("utf-8"))
            return

        # 其他路径 -> 404
        self.send_error(404, "Not found")

    # ---------- POST 请求 ----------
    def _is_save_path(self, path: str) -> bool:
        """是否为"保存笔记"类端点（BUG-14：走独立限流，避免与全局 POST 限流冲突）。
        排除 /user/<u>/shares(/delete) 管理端点。"""
        if re.match(r'^/world/[^/]+/?$', path):
            return True
        if re.match(r'^/share/[A-Za-z0-9]+/?$', path):
            return True
        if re.match(r'^/user/[^/]+/(?!shares)[^/]+/?$', path):
            return True
        return False

    def do_POST(self):
        client_ip = self.get_client_ip()
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if self._is_save_path(path):
            if is_save_rate_limited(client_ip):
                self.send_error(429, f"Too many saves (max {config.SAVE_RATE_MAX} per {config.SAVE_RATE_WINDOW}s)")
                return
        elif is_rate_limited(client_ip):
            self.send_error(429, f"Too many requests (max {config.RATE_MAX} per {config.RATE_WINDOW}s)")
            return

        # 处理注册
        if path == "/register":
            form = self._read_form_body(1024 * 10, max_fields=5)
            if form is None:
                return
            username = form.get("username", [""])[0].strip()
            password = form.get("password", [""])[0]
            confirm = form.get("confirm", [""])[0]

            if not validate_username(username):
                self.send_response(400)
                self.send_header("Content-Type", self._HTML_HEADER)
                self.end_headers()
                if username.lower() in RESERVED_USERNAMES:
                    error_msg = "该用户名是系统保留关键词，请更换（如 login/logout/register 等）"
                else:
                    error_msg = "用户名只能包含字母、数字、下划线、连字符"
                self.wfile.write(templates.render_register_form(self, error_msg).encode("utf-8"))
                return

            if password != confirm:
                self.send_response(400)
                self.send_header("Content-Type", self._HTML_HEADER)
                self.end_headers()
                self.wfile.write(templates.render_register_form(self, "两次密码不一致").encode("utf-8"))
                return

            if not check_password_complexity(password):
                req_desc = config.get_password_requirements_description()
                self.send_response(400)
                self.send_header("Content-Type", self._HTML_HEADER)
                self.end_headers()
                self.wfile.write(templates.render_register_form(
                    self, f"密码不符合要求：{req_desc}"
                ).encode("utf-8"))
                return

            # BUG-5: 检查与插入放在同一次持锁内，杜绝并发注册同名竞态；
            # BUG-11: 已存在统一提示"用户名不可用"，避免枚举已注册账号。
            with users_lock:
                if username in users:
                    self.send_response(400)
                    self.send_header("Content-Type", self._HTML_HEADER)
                    self.end_headers()
                    self.wfile.write(templates.render_register_form(self, "用户名不可用").encode("utf-8"))
                    return
                salt = generate_salt()
                hashed = hash_password(password, salt)
                users[username] = {"salt": salt, "hash": hashed}
            save_users()

            token = create_session(username)
            self.send_response(302)
            self._set_session_cookie(token)
            self.send_header("Location", f"/user/{username}/new")
            self.end_headers()
            return

        # 处理登录
        if path == "/login":
            form = self._read_form_body(1024 * 10, max_fields=5)
            if form is None:
                return
            username = form.get("username", [""])[0].strip()
            password = form.get("password", [""])[0]

            with users_lock:
                user = users.get(username)
            # BUG-7: 损坏/旧版用户数据（缺 salt/hash）按凭证错误处理，不崩线程
            salt = user.get("salt") if isinstance(user, dict) else None
            hashed = user.get("hash") if isinstance(user, dict) else None
            if not salt or not hashed or not isinstance(salt, str) or not isinstance(hashed, str):
                salt, hashed = None, None
            if salt is None or not verify_password(password, salt, hashed):
                # BUG-11: 登录失败返回 401（语义正确），避免返回 200 让客户端误判成功
                self.send_response(401)
                self.send_header("Content-Type", self._HTML_HEADER)
                self.end_headers()
                self.wfile.write(templates.render_login_form(self, "用户名或密码错误").encode("utf-8"))
                return

            token = create_session(username)
            self.send_response(302)
            self._set_session_cookie(token)
            self.send_header("Location", f"/user/{username}/")
            self.end_headers()
            return

        # ---------- 创建分享：/user/<用户名>/shares/ ----------
        shares_create_match = re.match(r'^/user/([^/]+)/shares/?$', path)
        if shares_create_match:
            username = shares_create_match.group(1)
            if not validate_username(username):
                self.send_error(400, "Invalid username")
                return
            if not self.is_authenticated(username):
                self.send_error(401, "Unauthorized")
                return
            form = self._read_form_body(1024 * 10, max_fields=5)
            if form is None:
                return
            note_id = form.get("note_id", [""])[0].strip()
            editable = form.get("editable", ["0"])[0] in ("1", "on", "true")

            if not validate_note_id(note_id):
                self.send_response(400)
                self.send_header("Content-Type", self._HTML_HEADER)
                self.end_headers()
                self.wfile.write(templates.render_shares_page(self, username, "请选择有效的笔记").encode("utf-8"))
                return
            note_path = get_note_path(username, note_id)
            if note_path is None or not os.path.exists(note_path):
                self.send_response(400)
                self.send_header("Content-Type", self._HTML_HEADER)
                self.end_headers()
                self.wfile.write(templates.render_shares_page(self, username, "笔记不存在，请选择已有的笔记").encode("utf-8"))
                return

            token = create_share(username, note_id, editable)
            self.send_response(302)
            self.send_header("Location", f"/user/{username}/shares/")
            self.end_headers()
            return

        # ---------- 删除分享：/user/<用户名>/shares/delete ----------
        shares_delete_match = re.match(r'^/user/([^/]+)/shares/delete$', path)
        if shares_delete_match:
            username = shares_delete_match.group(1)
            if not validate_username(username):
                self.send_error(400, "Invalid username")
                return
            if not self.is_authenticated(username):
                self.send_error(401, "Unauthorized")
                return
            form = self._read_form_body(1024 * 10, max_fields=5)
            if form is None:
                return
            token = form.get("token", [""])[0].strip()
            if not re.match(f'^{config.SHARE_TOKEN_PATTERN}$', token):
                self.send_error(400, "Invalid share token")
                return
            # BUG-15: 检查删除结果，未删除成功（不存在/非本人）时提示错误
            if not delete_share(username, token):
                self.send_response(400)
                self.send_header("Content-Type", self._HTML_HEADER)
                self.end_headers()
                self.wfile.write(templates.render_shares_page(self, username, "删除失败：分享不存在或无权删除").encode("utf-8"))
                return
            self.send_response(302)
            self.send_header("Location", f"/user/{username}/shares/")
            self.end_headers()
            return

        # ---------- 保存可编辑分享：/share/<token>（写回分享者原笔记） ----------
        share_save_match = re.match(f'^/share/({config.SHARE_TOKEN_PATTERN})/?$', path)
        if share_save_match:
            token = share_save_match.group(1)
            share = get_share(token)
            if share is None:
                self.send_error(404, "Share not found")
                return
            if not share.get("editable"):
                self.send_error(403, "This share is read-only")
                return
            form = self._read_form_body(config.MAX_CONTENT_BYTES, max_fields=10)
            if form is None:
                return
            content = form.get("content", [""])[0]
            # 写回分享者的原笔记
            if write_note(share.get("owner", ""), share.get("note_id", ""), content):
                self.send_response(302)
                self.send_header("Location", f"/share/{token}")
                self.end_headers()
            else:
                self.send_error(500, "Failed to save note")
            return

        # 处理公开笔记保存：/world/<note_id>
        # BUG-4: 允许尾部斜杠（GET 页面与 POST 保存行为一致）
        world_match = re.match(r'^/world/([^/]+)/?$', path)
        if world_match:
            note_id = world_match.group(1)
            if not validate_note_id(note_id):
                # 带扩展名的文件名（.html/.exe/.pdf 等）一律 404（.md 已在上方处理）
                if "." in note_id:
                    self.send_error(404, "Not found")
                else:
                    self.send_error(400, "Invalid note ID")
                return

            form = self._read_form_body(config.MAX_CONTENT_BYTES, max_fields=10)
            if form is None:
                return
            content = form.get("content", [""])[0]

            if write_note("public", note_id, content):
                self.send_response(302)
                self.send_header("Location", f"/world/{note_id}")
                self.end_headers()
            else:
                self.send_error(500, "Failed to save note")
            return

        # 处理私有笔记保存：/user/<username>/<note_id>
        user_match = re.match(r'^/user/([^/]+)/([^/]+)/?$', path)
        if user_match:
            username = user_match.group(1)
            note_id = user_match.group(2)

            if not validate_username(username) or not validate_note_id(note_id):
                # 带扩展名的文件名（.html/.exe/.pdf 等）一律 404（.md 已在上方处理）
                if "." in note_id:
                    self.send_error(404, "Not found")
                else:
                    self.send_error(400, "Invalid username or note ID")
                return

            if not self.is_authenticated(username):
                self.send_error(401, "Unauthorized")
                return

            form = self._read_form_body(config.MAX_CONTENT_BYTES, max_fields=10)
            if form is None:
                return
            content = form.get("content", [""])[0]

            if write_note(username, note_id, content):
                self.send_response(302)
                self.send_header("Location", f"/user/{username}/{note_id}")
                self.end_headers()
            else:
                self.send_error(500, "Failed to save note")
            return

        self.send_error(404, "Not found")

    def send_error(self, code, message=None, explain=None):
        self.log_error(f"code {code}, message {message}")
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        # BUG-17: message 做 HTML 转义防止注入；有响应体时设置 Content-Length
        if message:
            theme = self.get_theme()
            theme_attr = f' data-theme="{theme}"' if theme else ""
            safe_message = html.escape(str(message))
            response = (f"<html{theme_attr}><head><title>Error {code}</title>{THEME_SCRIPT}"
                        f"<style>{THEME_VARS}"
                        f"body {{ background: var(--bg); color: var(--text); font-family: -apple-system, sans-serif; padding: 40px; }}"
                        f"h1 {{ font-weight: 400; border-bottom: 1px solid var(--heading-border); padding-bottom: 10px; }}"
                        f"</style></head>"
                        f"<body><h1>{code} {safe_message}</h1></body></html>")
            body = response.encode("utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.end_headers()
