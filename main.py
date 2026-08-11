#!/usr/bin/env python3
"""
rusin-note - 极简在线笔记服务 (支持多线程并发、IP限流、配置文件)
"""

import os
import re
import json
import time
import html
import urllib.parse
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from collections import defaultdict
from threading import Lock

# ---------- 加载配置 ----------
CONFIG_FILE = "config.json"
DEFAULT_CONFIG = {
    "max_note_size_mb": 5,
    "rate_limit": {
        "window_seconds": 60,
        "max_requests": 30
    }
}

def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"[警告] 读取配置文件失败，使用默认配置: {e}")
    return DEFAULT_CONFIG

config = load_config()
MAX_CONTENT_BYTES = config.get("max_note_size_mb", 5) * 1024 * 1024
RATE_WINDOW = config.get("rate_limit", {}).get("window_seconds", 60)
RATE_MAX = config.get("rate_limit", {}).get("max_requests", 30)

# ---------- 笔记存储 ----------
NOTES_DIR = "notes"
os.makedirs(NOTES_DIR, exist_ok=True)

# ---------- IP限流数据结构 ----------
ip_requests = defaultdict(list)  # ip -> [timestamp1, timestamp2, ...]
ip_lock = Lock()

def is_rate_limited(ip: str) -> bool:
    """检查IP是否超过限制，若未超则记录本次请求"""
    now = time.time()
    with ip_lock:
        # 清理过期记录（保留窗口内的）
        records = ip_requests[ip]
        # 保留大于 now - RATE_WINDOW 的记录
        cutoff = now - RATE_WINDOW
        # 因为记录是按时间顺序追加的，可以二分优化，但数据量小直接遍历
        records[:] = [t for t in records if t > cutoff]
        # 判断是否已满
        if len(records) >= RATE_MAX:
            return True
        # 添加当前请求时间
        records.append(now)
        return False

# ---------- 文件操作 ----------
def get_note_path(note_id: str):
    if not re.match(r'^[\w\-_\u4e00-\u9fff]+$', note_id):
        return None
    safe_id = os.path.basename(note_id)
    return os.path.join(NOTES_DIR, f"{safe_id}.txt")


def read_note(note_id: str) -> str:
    path = get_note_path(note_id)
    if path is None:
        return ""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return ""


def write_note(note_id: str, content: str) -> bool:
    path = get_note_path(note_id)
    if path is None:
        return False
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return True
    except IOError:
        return False

# ---------- HTTP 处理器 ----------
class NoteHandler(BaseHTTPRequestHandler):
    def log_request(self, code='-', size='-'):
        if code != 200:
            super().log_request(code, size)

    def get_client_ip(self) -> str:
        """从请求头获取真实IP，支持代理"""
        # 尝试从 X-Forwarded-For 获取
        forwarded = self.headers.get("X-Forwarded-For")
        if forwarded:
            # 取第一个IP（最原始的客户端）
            ip = forwarded.split(",")[0].strip()
            return ip
        real_ip = self.headers.get("X-Real-IP")
        if real_ip:
            return real_ip.strip()
        # 否则直接取连接地址
        return self.client_address[0]

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path == "/" or path == "":
            self.send_response(302)
            self.send_header("Location", "/welcome")
            self.end_headers()
            return

        note_id = path.lstrip("/")
        if not note_id:
            self.send_response(302)
            self.send_header("Location", "/welcome")
            self.end_headers()
            return

        if not re.match(r'^[\w\-_\u4e00-\u9fff]+$', note_id):
            self.send_error(400, "Invalid note ID")
            return

        content = read_note(note_id)
        html_page = self.render_page(note_id, content)
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(html_page.encode("utf-8"))

    def do_POST(self):
        # ----- 限流检查（仅针对POST） -----
        client_ip = self.get_client_ip()
        if is_rate_limited(client_ip):
            self.send_error(429, f"Too many requests (max {RATE_MAX} per {RATE_WINDOW}s)")
            return

        parsed = urllib.parse.urlparse(self.path)
        note_id = parsed.path.lstrip("/")
        if not note_id:
            self.send_error(400, "Missing note ID")
            return
        if not re.match(r'^[\w\-_\u4e00-\u9fff]+$', note_id):
            self.send_error(400, "Invalid note ID")
            return

        content_length = int(self.headers.get("Content-Length", 0))
        if content_length > MAX_CONTENT_BYTES:
            self.send_error(413, f"Content too large (max {MAX_CONTENT_BYTES//1024//1024}MB)")
            return

        post_data = self.rfile.read(content_length).decode("utf-8")
        form_data = urllib.parse.parse_qs(post_data)
        content = form_data.get("content", [""])[0]

        if write_note(note_id, content):
            self.send_response(302)
            self.send_header("Location", f"/{note_id}")
            self.end_headers()
        else:
            self.send_error(500, "Failed to save note")

    def render_page(self, note_id: str, content: str) -> str:
        escaped_content = html.escape(content)
        escaped_id = html.escape(note_id)

        return f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>rusin-note</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            background: #ffffff;
            height: 100vh;
            overflow: hidden;
        }}
        form {{
            height: 100vh;
            display: flex;
            flex-direction: column;
        }}
        textarea {{
            flex: 1;
            width: 100%;
            border: none;
            padding: 20px 24px;
            font-size: 16px;
            line-height: 1.7;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", sans-serif;
            resize: none;
            outline: none;
            background: #ffffff;
            color: #111;
        }}
        .save-btn {{
            position: fixed;
            bottom: 24px;
            right: 24px;
            background: rgba(240, 240, 240, 0.85);
            border: 1px solid #ddd;
            padding: 6px 18px;
            border-radius: 20px;
            font-size: 14px;
            color: #333;
            cursor: pointer;
            backdrop-filter: blur(4px);
            transition: background 0.2s;
        }}
        .save-btn:hover {{
            background: rgba(220, 220, 220, 0.95);
        }}
        .save-btn:active {{
            background: #ccc;
        }}
    </style>
</head>
<body>
    <form method="POST" action="/{escaped_id}">
        <textarea name="content" autofocus spellcheck="true">{escaped_content}</textarea>
        <input type="submit" value="Save" class="save-btn">
    </form>
    <script>
        document.addEventListener('keydown', function(e) {{
            if ((e.ctrlKey || e.metaKey) && e.key === 's') {{
                e.preventDefault();
                document.forms[0].submit();
            }}
        }});
        document.querySelector('textarea').focus();
    </script>
</body>
</html>"""

# ---------- 启动服务器 ----------
def run_server(port=8000):
    server_address = ("", port)
    httpd = ThreadingHTTPServer(server_address, NoteHandler)
    print("[启动] rusin-note 服务已启动")
    print(f"[地址] http://localhost:{port}")
    print(f"[目录] 笔记保存在 ./{NOTES_DIR}/")
    print(f"[限制] 每个笔记最大 {MAX_CONTENT_BYTES//1024//1024}MB")
    print(f"[限流] 每个IP {RATE_MAX} 次 / {RATE_WINDOW} 秒 (仅POST)")
    print("[提示] 按 Ctrl+C 停止服务")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[停止] 服务已停止")
        httpd.shutdown()


if __name__ == "__main__":
    run_server()