"""服务器启动（TimedThreadingHTTPServer 与 run_server）"""
import os
import time
from http.server import ThreadingHTTPServer
from threading import Thread

from . import config
from .auth import purge_expired_sessions, session_cleanup_loop
from .handlers import NoteHandler
from .notes import note_cleanup_loop, purge_expired_notes
from .store import NOTES_BASE, flush_share_views, users
from .logger import create_logger

print("服务已启动：http://localhost:8080/")

logger = create_logger("server")

def share_views_flush_loop():
    """后台线程：定期将内存中的分享视图计数写盘（BUG-06）"""
    while True:
        time.sleep(config.SHARE_VIEWS_FLUSH_INTERVAL)
        try:
            flush_share_views()
        except Exception as e:
            logger.error(f"[错误] 分享视图刷新失败: {e}")


class TimedThreadingHTTPServer(ThreadingHTTPServer):
    """带 socket 超时的 ThreadingHTTPServer，防止慢速连接挂起线程（BUG-008）"""

    def get_request(self):
        sock, addr = super().get_request()
        sock.settimeout(config.SOCKET_TIMEOUT)
        return sock, addr


def run_server(port=None):
    if port is None:
        port = int(os.environ.get("PORT", 8080))
    server_address = ("0.0.0.0", port)
    httpd = TimedThreadingHTTPServer(server_address, NoteHandler)
    # BUG-8: 清理线程无条件启动（仅启用会话超时时执行删除逻辑），
    # 避免 sessions.json 在超时关闭时无限增长
    purge_expired_sessions()  # 启动时清理一次过期会话
    Thread(target=session_cleanup_loop, daemon=True).start()
    # BUG-06: 分享视图计数批量持久化线程（无条件启动，无脏数据时为空操作）
    Thread(target=share_views_flush_loop, daemon=True).start()
    if config.NOTE_EXPIRATION_ENABLED:
        purge_expired_notes()  # 启动时清理一次过期笔记
        Thread(target=note_cleanup_loop, daemon=True).start()
    logger.info("[启动] rusin-note 服务已启动 (公开+私有笔记)")
    logger.info(f"[地址] http://localhost:{port}")
    logger.info(f"[目录] 笔记保存在 ./{NOTES_BASE}/ (public/ 为公开笔记)")
    logger.info(f"[限制] 每个笔记最大 {config.MAX_CONTENT_BYTES//1024}KB")
    logger.info(f"[限流] POST: 每个IP {config.RATE_MAX} 次 / {config.RATE_WINDOW} 秒")
    logger.info(f"[限流] GET:  每个IP {config.GET_RATE_MAX} 次 / {config.GET_RATE_WINDOW} 秒")
    logger.info(f"[限流] 保存: 每个IP {config.SAVE_RATE_MAX} 次 / {config.SAVE_RATE_WINDOW} 秒 (笔记保存独立限流)")
    logger.info(f"[限流] 注册: 每个IP {config.REGISTER_RATE_MAX} 次 / {config.REGISTER_RATE_WINDOW} 秒 (防止批量注册)")
    logger.info(f"[连接] socket 超时: {config.SOCKET_TIMEOUT} 秒 (防止慢速连接挂起线程)")
    logger.info("[公开笔记] 访问 /world/<id> 即可匿名编辑")
    logger.info("[私有笔记] 注册登录后访问 /user/<username>/<id>")
    logger.info("[快捷] 访问 /<名称> 自动重定向到 /world/<名称> (如 /数字 或 /abc)")
    logger.info("[快捷] 访问 /<名称>.md 直接渲染为 Markdown，其他扩展名 (.html/.exe/.pdf 等) 一律 404")
    logger.info("[统计] 访问 /count 查看笔记统计")
    logger.info("[免责] 访问 /disclaimer 查看免责声明 (支持Markdown)")
    logger.info("[Markdown] 访问 /world/<id>/md 渲染公开笔记为只读 Markdown (已启用XSS防护)")
    logger.info("[Markdown] 访问 /user/<用户名>/<笔记ID>/md 渲染私有笔记为只读 Markdown (需登录)")
    logger.info("[Markdown] 全部支持 .md 后缀快捷方式: /world/<id>.md /user/<用户名>/<笔记ID>.md /share/<token>.md")
    logger.info("[分享] 访问 /user/<用户名>/shares/ 管理分享链接 (创建/删除/查看次数)")
    logger.info(f"[分享] 分享链接: /share/<{config.SHARE_TOKEN_LENGTH}位token> (只读或可编辑，保存将写回分享者原笔记)")
    if config.SESSION_TIMEOUT_ENABLED:
        logger.info(f"[超时] 会话超时已启用，超时时间 {config.SESSION_TIMEOUT_MINUTES} 分钟")
    else:
        logger.info("[超时] 会话超时未启用")
    if config.NOTE_EXPIRATION_ENABLED:
        logger.info(f"[过期] 笔记自动清除已启用，保存超过 {config.NOTE_EXPIRATION_HOURS} 小时未修改的剪贴板将被删除")
    else:
        logger.info("[过期] 笔记自动清除未启用")
    if config.LATEX_RENDER_ENABLED:
        logger.info("[LaTeX] LaTeX 公式渲染已启用 (KaTeX 洛谷同款, $...$ 行内 / $$...$$ 块级)")
    else:
        logger.info("[LaTeX] LaTeX 公式渲染未启用")

    # 检查依赖状态
    if not config.MARKDOWN_AVAILABLE:
        logger.warning("[警告] Markdown 库未安装，Markdown 渲染功能将降级为纯文本 (pip install markdown)")
    if not config.BLEACH_AVAILABLE:
        logger.warning("[警告] Bleach 库未安装，Markdown 渲染将不进行安全清洗，请尽快安装 (pip install bleach)")

    # 检查历史遗留的 public 用户（与公开笔记目录冲突，需手动移除）
    for bad_name in ("public",):
        if bad_name in users:
            logger.warning(f"[严重警告] users.json 中存在用户名 '{bad_name}'，它与公开笔记存储目录冲突，"
                  f"请立即手动从 users.json 中删除该用户！")

    logger.info("[提示] 按 Ctrl+C 停止服务")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        logger.info("\n[停止] 服务已停止")
        httpd.shutdown()
