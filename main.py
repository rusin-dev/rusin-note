#!/usr/bin/env python3
"""
极简笔记服务器 - 纯文本终端输出，无Emoji乱码
"""

import os
import re
import html
import urllib.parse
from http.server import HTTPServer, BaseHTTPRequestHandler

PORT = 8000
NOTES_DIR = "notes"
os.makedirs(NOTES_DIR, exist_ok=True)


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


class NoteHandler(BaseHTTPRequestHandler):
    def log_request(self, code='-', size='-'):
        if code != 200:
            super().log_request(code, size)

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
        parsed = urllib.parse.urlparse(self.path)
        note_id = parsed.path.lstrip("/")
        if not note_id:
            self.send_error(400, "Missing note ID")
            return
        if not re.match(r'^[\w\-_\u4e00-\u9fff]+$', note_id):
            self.send_error(400, "Invalid note ID")
            return

        content_length = int(self.headers.get("Content-Length", 0))
        if content_length > 1024 * 1024:
            self.send_error(413, "Content too large")
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
        """极简白板页面，完全复刻 rusin-note 风格"""
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


def run_server(port=PORT):
    server_address = ("", port)
    httpd = HTTPServer(server_address, NoteHandler)
    print("[启动] 极简笔记服务已启动")
    print(f"[地址] http://localhost:{port}")
    print(f"[目录] 笔记保存在 ./{NOTES_DIR}/")
    print("[提示] 按 Ctrl+C 停止服务")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[停止] 服务已停止")
        httpd.shutdown()


if __name__ == "__main__":
    run_server()
