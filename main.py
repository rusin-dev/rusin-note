#!/usr/bin/env python3
"""
rusin-note - 极简在线笔记服务 (支持多线程并发、IP限流、配置文件)
内存优化版本 - 支持 Ctrl+S 保存
"""

import os
import re
import json
import time
import html
import random
import string
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

# ---------- IP限流数据结构（优化版：使用固定大小数组） ----------
ip_requests = defaultdict(list)
ip_lock = Lock()
MAX_RECORDS_PER_IP = RATE_MAX * 2  # 限制每个IP最多保存的记录数

def cleanup_old_records(records, cutoff):
    """清理过期记录，使用手动遍历避免创建新列表"""
    i = 0
    while i < len(records):
        if records[i] <= cutoff:
            records.pop(i)
        else:
            i += 1

def is_rate_limited(ip: str) -> bool:
    """检查IP是否超过限制，若未超则记录本次请求（内存优化版）"""
    now = time.time()
    with ip_lock:
        records = ip_requests[ip]
        cutoff = now - RATE_WINDOW
        
        # 清理过期记录（原地修改）
        cleanup_old_records(records, cutoff)
        
        # 判断是否已满
        if len(records) >= RATE_MAX:
            return True
        
        # 添加当前请求时间
        records.append(now)
        
        # 如果记录数超过限制，删除最旧的记录
        if len(records) > MAX_RECORDS_PER_IP:
            del records[:len(records) - MAX_RECORDS_PER_IP]
        
        return False

# ---------- 文件操作（优化版） ----------
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
    except (IOError, OSError):
        return ""

def write_note(note_id: str, content: str) -> bool:
    """
    写入笔记内容。若 content 为空字符串，则删除对应的文件（如果存在）。
    返回 True 表示操作成功，False 表示失败。
    """
    path = get_note_path(note_id)
    if path is None:
        return False

    # 空内容：删除文件
    if content == "":
        try:
            if os.path.exists(path):
                os.remove(path)
            return True
        except OSError:
            return False

    # 非空内容：写入文件（原子替换）
    try:
        temp_path = path + ".tmp"
        with open(temp_path, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path, path)
        return True
    except (IOError, OSError):
        try:
            if os.path.exists(temp_path):
                os.remove(temp_path)
        except:
            pass
        return False

# ---------- 辅助函数 ----------
def generate_random_id(length=6) -> str:
    """生成包含大小写字母和数字的随机ID"""
    chars = string.ascii_letters + string.digits
    return ''.join(random.choices(chars, k=length))

# ---------- HTTP 处理器 ----------
class NoteHandler(BaseHTTPRequestHandler):
    # 类级别缓存常用响应头
    _HTML_HEADER = "text/html; charset=utf-8"
    
    def log_request(self, code='-', size='-'):
        if code != 200:
            super().log_request(code, size)

    def get_client_ip(self) -> str:
        """从请求头获取真实IP，支持代理"""
        forwarded = self.headers.get("X-Forwarded-For")
        if forwarded:
            ip = forwarded.split(",", 1)[0].strip()
            return ip
        real_ip = self.headers.get("X-Real-IP")
        if real_ip:
            return real_ip.strip()
        return self.client_address[0]

    def _send_redirect(self, location):
        """发送重定向响应"""
        self.send_response(302)
        self.send_header("Location", location)
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        # 根路径：生成随机ID并重定向
        if path == "/" or path == "":
            random_id = generate_random_id()
            self._send_redirect(f"/{random_id}")
            return

        note_id = path.lstrip("/")
        if not note_id:
            self._send_redirect(f"/{generate_random_id()}")
            return

        if not re.match(r'^[\w\-_\u4e00-\u9fff]+$', note_id):
            self.send_error(400, "Invalid note ID")
            return

        content = read_note(note_id)
        html_page = self.render_page(note_id, content)
        self.send_response(200)
        self.send_header("Content-Type", self._HTML_HEADER)
        self.end_headers()
        self.wfile.write(html_page.encode("utf-8"))

    def do_POST(self):
        # ----- 限流检查 -----
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
        form_data = urllib.parse.parse_qs(post_data, max_num_fields=10)
        content = form_data.get("content", [""])[0]

        # 写入笔记（若内容为空则删除文件）
        if write_note(note_id, content):
            self.send_response(302)
            self.send_header("Location", f"/{note_id}")
            self.end_headers()
        else:
            self.send_error(500, "Failed to save note")

    def render_page(self, note_id: str, content: str) -> str:
        """渲染HTML页面 - 包含 Ctrl+S 保存功能"""
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
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", sans-serif;
        }}
        form {{
            height: 100vh;
            display: flex;
            flex-direction: column;
            position: relative;
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
            padding: 8px 20px;
            border-radius: 20px;
            font-size: 14px;
            color: #333;
            cursor: pointer;
            backdrop-filter: blur(4px);
            transition: all 0.2s;
            z-index: 10;
            font-weight: 500;
        }}
        .save-btn:hover {{
            background: rgba(220, 220, 220, 0.95);
            transform: scale(1.02);
        }}
        .save-btn:active {{
            background: #ccc;
            transform: scale(0.98);
        }}
        .save-hint {{
            position: fixed;
            bottom: 80px;
            left: 50%;
            transform: translateX(-50%);
            background: rgba(0, 0, 0, 0.75);
            color: #fff;
            padding: 10px 24px;
            border-radius: 24px;
            font-size: 14px;
            letter-spacing: 0.5px;
            backdrop-filter: blur(8px);
            opacity: 0;
            transition: opacity 0.4s ease, transform 0.4s ease;
            pointer-events: none;
            z-index: 20;
            font-weight: 400;
            box-shadow: 0 4px 20px rgba(0,0,0,0.2);
        }}
        .save-hint.show {{
            opacity: 1;
            transform: translateX(-50%) translateY(0);
        }}
        .save-hint kbd {{
            background: rgba(255, 255, 255, 0.2);
            padding: 2px 12px;
            border-radius: 6px;
            margin: 0 4px;
            font-size: 13px;
            border: 1px solid rgba(255, 255, 255, 0.15);
            font-family: inherit;
        }}
        .save-status {{
            position: fixed;
            bottom: 80px;
            right: 24px;
            font-size: 14px;
            color: #4CAF50;
            opacity: 0;
            transition: opacity 0.3s ease, transform 0.3s ease;
            pointer-events: none;
            z-index: 15;
            background: rgba(255, 255, 255, 0.95);
            padding: 6px 18px;
            border-radius: 16px;
            border: 1px solid #4CAF50;
            box-shadow: 0 2px 12px rgba(0,0,0,0.08);
            transform: translateY(10px);
        }}
        .save-status.show {{
            opacity: 1;
            transform: translateY(0);
        }}
        .save-status.saving {{
            color: #ff9800;
            border-color: #ff9800;
        }}
        .save-status.error {{
            color: #f44336;
            border-color: #f44336;
        }}
        @media (max-width: 640px) {{
            textarea {{
                padding: 16px 18px;
                font-size: 15px;
            }}
            .save-btn {{
                bottom: 16px;
                right: 16px;
                padding: 6px 16px;
                font-size: 13px;
            }}
            .save-hint {{
                bottom: 70px;
                padding: 8px 16px;
                font-size: 12px;
                white-space: nowrap;
            }}
            .save-status {{
                bottom: 70px;
                right: 16px;
                font-size: 12px;
                padding: 4px 14px;
            }}
        }}
    </style>
</head>
<body>
    <form method="POST" action="/{escaped_id}" id="noteForm">
        <textarea name="content" id="noteContent" autofocus spellcheck="true">{escaped_content}</textarea>
        <button type="button" class="save-btn" id="saveBtn"> 保存</button>
    </form>
    
    <div class="save-hint" id="saveHint">
         按 <kbd>Ctrl</kbd> + <kbd>S</kbd> 快速保存
    </div>
    <div class="save-status" id="saveStatus"></div>

    <script>
        (function() {{
            const form = document.getElementById('noteForm');
            const textarea = document.getElementById('noteContent');
            const saveBtn = document.getElementById('saveBtn');
            const saveHint = document.getElementById('saveHint');
            const saveStatus = document.getElementById('saveStatus');
            let saveTimeout = null;
            let statusTimeout = null;
            let hintTimeout = null;
            let isSaving = false;

            // 显示保存提示
            function showHint(message) {{
                if (message) {{
                    saveHint.innerHTML = message;
                }}
                saveHint.classList.add('show');
                clearTimeout(hintTimeout);
                hintTimeout = setTimeout(function() {{
                    saveHint.classList.remove('show');
                }}, 4000);
            }}

            // 显示保存状态
            function showStatus(message, type = '') {{
                saveStatus.textContent = message;
                saveStatus.className = 'save-status show';
                if (type) {{
                    saveStatus.classList.add(type);
                }}
                clearTimeout(statusTimeout);
                statusTimeout = setTimeout(function() {{
                    saveStatus.classList.remove('show');
                }}, 2500);
            }}

            // 页面加载后显示提示
            setTimeout(function() {{
                showHint(' 按 <kbd>Ctrl</kbd> + <kbd>S</kbd> 快速保存');
            }}, 600);

            // 用户输入时显示提示
            let inputTimer = null;
            textarea.addEventListener('input', function() {{
                clearTimeout(inputTimer);
                inputTimer = setTimeout(function() {{
                    showHint(' 按 <kbd>Ctrl</kbd> + <kbd>S</kbd> 快速保存');
                }}, 3000);
            }});

            // 焦点进入文本框时显示提示
            textarea.addEventListener('focus', function() {{
                showHint(' 按 <kbd>Ctrl</kbd> + <kbd>S</kbd> 快速保存');
            }});

            // Ctrl+S 保存
            document.addEventListener('keydown', function(e) {{
                if ((e.ctrlKey || e.metaKey) && e.key === 's') {{
                    e.preventDefault();
                    saveNote();
                }}
                // Escape 隐藏提示
                if (e.key === 'Escape') {{
                    saveHint.classList.remove('show');
                    saveStatus.classList.remove('show');
                }}
            }});

            // 点击保存按钮
            saveBtn.addEventListener('click', function(e) {{
                e.preventDefault();
                saveNote();
            }});

            function saveNote() {{
                if (isSaving) return;
                isSaving = true;
                
                // 显示保存中
                showStatus(' 保存中...', 'saving');
                
                const content = textarea.value;
                
                // 使用 fetch 异步提交
                fetch(window.location.href, {{
                    method: 'POST',
                    headers: {{
                        'Content-Type': 'application/x-www-form-urlencoded',
                    }},
                    body: 'content=' + encodeURIComponent(content)
                }})
                .then(response => {{
                    isSaving = false;
                    if (response.ok) {{
                        showStatus('已保存', '');
                        showHint(' 已保存！按 <kbd>Ctrl</kbd> + <kbd>S</kbd> 再次保存');
                    }} else {{
                        showStatus(' 保存失败 (' + response.status + ')', 'error');
                        showHint(' 保存失败，请重试');
                    }}
                }})
                .catch(error => {{
                    isSaving = false;
                    showStatus(' 网络错误', 'error');
                    showHint(' 保存失败：' + error.message);
                }});
            }}

            // 自动调整文本框高度（适应内容）
            function autoResize() {{
                textarea.style.height = 'auto';
                textarea.style.height = textarea.scrollHeight + 'px';
            }}
            // 初始调整
            setTimeout(autoResize, 100);
            textarea.addEventListener('input', autoResize);
        }})();
    </script>
</body>
</html>"""

    def send_error(self, code, message=None, explain=None):
        """优化错误响应"""
        self.log_error(f"code {code}, message {message}")
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        if message:
            response = f"<html><head><title>Error {code}</title></head><body><h1>{code} {message}</h1></body></html>"
            self.wfile.write(response.encode("utf-8"))


# ---------- 启动服务器 ----------
def run_server(port=8080):
    server_address = ("", port)
    httpd = ThreadingHTTPServer(server_address, NoteHandler)
    print("[启动] rusin-note 服务已启动 (内存优化版)")
    print(f"[地址] http://localhost:{port}")
    print(f"[目录] 笔记保存在 ./{NOTES_DIR}/")
    print(f"[限制] 每个笔记最大 {MAX_CONTENT_BYTES//1024//1024}MB")
    print(f"[限流] 每个IP {RATE_MAX} 次 / {RATE_WINDOW} 秒 (仅POST)")
    print("[提示] 按 Ctrl+C 停止服务")
    print("[快捷键] 在笔记页面按 Ctrl+S 保存内容")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[停止] 服务已停止")
        httpd.shutdown()


if __name__ == "__main__":
    run_server()