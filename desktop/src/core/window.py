"""WebView 原生壳：把 rusin-note 网页版装进桌面窗口。

桌面端不保存任何笔记数据——笔记、附件、同步全部由网页版负责。本地只落盘
客户端配置（站点地址、窗口几何）与 WebView 会话数据（保持登录态）。
"""
from __future__ import annotations

import logging
import os
import threading
import webbrowser
from pathlib import Path

import webview
from webview.menu import Menu, MenuAction, MenuSeparator

from src.core.data import DataService
from src.core.setup import render_setup_html, ui_lang
from src.core.site import DEFAULT_SITE_URL, normalize_site_url
from src.modules import updater

KEY_SITE_URL = "site.url"
KEY_WIDTH = "window.width"
KEY_HEIGHT = "window.height"
KEY_X = "window.x"
KEY_Y = "window.y"
KEY_MAXIMIZED = "window.maximized"

DEFAULT_WIDTH = 1280
DEFAULT_HEIGHT = 860
MIN_SIZE = (420, 320)

_MENU_TEXTS = {
    "zh": {
        "file": "文件",
        "view": "视图",
        "change_site": "更改站点地址…",
        "quit": "退出",
        "reload": "重新加载",
        "fullscreen": "全屏",
        "check_update": "检查更新…",
        "update_title": "发现新版本",
        "update_body": "检测到新版本 {latest}（当前 {current}）。是否打开下载页？",
        "current_title": "检查更新",
        "current_body": "已是最新版本 {current}。",
        "update_failed": "检查更新失败，请稍后重试。",
    },
    "en": {
        "file": "File",
        "view": "View",
        "change_site": "Change site…",
        "quit": "Quit",
        "reload": "Reload",
        "fullscreen": "Fullscreen",
        "check_update": "Check for updates…",
        "update_title": "Update available",
        "update_body": "Version {latest} is available (you have {current}). Open the download page?",
        "current_title": "Check for updates",
        "current_body": "You are on the latest version {current}.",
        "update_failed": "Could not check for updates. Please try again later.",
    },
}


class ShellApi:
    """暴露给设置页 JS 的接口（页面内以 pywebview.api.* 调用）"""

    def __init__(self, service: DataService, logger: logging.Logger):
        self._service = service
        self._logger = logger
        self.window = None

    def connect(self, raw_url: str) -> dict:
        """保存站点地址并跳转；留空则用官方演示站。"""
        text = (raw_url or "").strip()
        url = normalize_site_url(text) if text else DEFAULT_SITE_URL
        if url is None:
            return {"ok": False, "reason": "invalid"}
        self._service.config.set(KEY_SITE_URL, url)
        self._logger.info("站点地址已设为 %s", url)
        if self.window is not None:
            self.window.load_url(url)
        return {"ok": True, "url": url}


def _int_or(value, default: int | None) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def load_geometry(service: DataService) -> dict:
    """读取上次窗口几何；缺失或非法值回退到默认尺寸。"""
    config = service.config
    width = max(MIN_SIZE[0], _int_or(config.get(KEY_WIDTH), DEFAULT_WIDTH))
    height = max(MIN_SIZE[1], _int_or(config.get(KEY_HEIGHT), DEFAULT_HEIGHT))
    return {
        "width": width,
        "height": height,
        "x": _int_or(config.get(KEY_X), None),
        "y": _int_or(config.get(KEY_Y), None),
        "maximized": bool(config.get(KEY_MAXIMIZED, False)),
    }


def save_geometry(window, service: DataService, maximized: bool,
                  logger: logging.Logger) -> None:
    """窗口关闭前记录几何。最大化时不覆盖尺寸，以便还原后仍是原来的大小。"""
    try:
        service.config.set(KEY_MAXIMIZED, bool(maximized))
        if not maximized:
            service.config.set(KEY_WIDTH, window.width)
            service.config.set(KEY_HEIGHT, window.height)
            service.config.set(KEY_X, window.x)
            service.config.set(KEY_Y, window.y)
    except Exception:
        logger.exception("保存窗口几何失败")


def show_setup(window, service: DataService) -> None:
    """回到站点设置页（已配置过则预填当前地址）。"""
    current = normalize_site_url(service.config.get(KEY_SITE_URL) or "")
    window.load_html(render_setup_html(current or DEFAULT_SITE_URL))


def _reload(window, service: DataService) -> None:
    """重新加载当前页；停留在设置页时回到已配置站点（没有则回设置页）。"""
    current = window.get_current_url() or ""
    if current.startswith(("http://", "https://")):
        window.load_url(current)
        return
    site_url = normalize_site_url(service.config.get(KEY_SITE_URL) or "")
    if site_url:
        window.load_url(site_url)
    else:
        show_setup(window, service)


def _run_update_check(window, service: DataService, texts: dict,
                      logger: logging.Logger, site_url: str) -> None:
    """执行一次更新检查并按结果提示；发现新版本时打开站点下载页。"""
    try:
        current = updater.get_current_version()
        latest = updater.get_latest_version(site_url)
    except Exception as exc:
        logger.warning("检查更新失败: %s", exc)
        window.create_confirmation_dialog(texts["current_title"], texts["update_failed"])
        return
    if not updater.is_newer(latest, current):
        window.create_confirmation_dialog(
            texts["current_title"], texts["current_body"].format(current=current)
        )
        return
    logger.info("发现新版本 %s（当前 %s）", latest, current)
    if window.create_confirmation_dialog(
        texts["update_title"],
        texts["update_body"].format(latest=latest, current=current),
    ):
        webbrowser.open(site_url + "/downloads")


def check_for_update(window, service: DataService, texts: dict,
                     logger: logging.Logger) -> None:
    """在后台线程检查更新，避免网络请求卡住界面。"""
    site_url = normalize_site_url(service.config.get(KEY_SITE_URL) or "")
    if not site_url:
        show_setup(window, service)
        return
    threading.Thread(
        target=_run_update_check,
        args=(window, service, texts, logger, site_url),
        name="rusin-update-check",
        daemon=True,
    ).start()


def _build_menu(window, service: DataService, texts: dict,
                logger: logging.Logger) -> list[Menu]:
    return [
        Menu(texts["file"], [
            MenuAction(texts["change_site"], lambda: show_setup(window, service)),
            MenuAction(texts["check_update"],
                       lambda: check_for_update(window, service, texts, logger)),
            MenuSeparator(),
            MenuAction(texts["quit"], window.destroy),
        ]),
        Menu(texts["view"], [
            MenuAction(texts["reload"], lambda: _reload(window, service)),
            MenuAction(texts["fullscreen"], window.toggle_fullscreen),
        ]),
    ]


def _debug_enabled() -> bool:
    return os.environ.get("RUSIN_DESKTOP_DEBUG", "").strip().lower() in ("1", "true", "yes")


def run(service: DataService, data_dir: Path, logger: logging.Logger) -> None:
    """创建原生窗口并进入事件循环，直到窗口关闭才返回。"""
    # 外链交给系统浏览器：第三方登录（OAuth）与 target=_blank 在壳内会走不通
    webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True
    webview.settings["ALLOW_DOWNLOADS"] = True

    texts = _MENU_TEXTS[ui_lang()]
    site_url = normalize_site_url(service.config.get(KEY_SITE_URL) or "")
    geometry = load_geometry(service)
    api = ShellApi(service, logger)

    window = webview.create_window(
        "rusin-note",
        url=site_url,
        html=None if site_url else render_setup_html(DEFAULT_SITE_URL),
        js_api=api,
        width=geometry["width"],
        height=geometry["height"],
        x=geometry["x"],
        y=geometry["y"],
        min_size=MIN_SIZE,
        maximized=geometry["maximized"],
        text_select=True,
        zoomable=True,
        background_color="#FFFFFF",
    )
    api.window = window

    state = {"maximized": geometry["maximized"]}
    window.events.maximized += lambda: state.update(maximized=True)
    window.events.restored += lambda: state.update(maximized=False)
    window.events.minimized += lambda: state.update(maximized=False)
    window.events.closing += lambda: save_geometry(window, service, state["maximized"], logger)

    logger.info("桌面端启动：站点=%s 数据目录=%s", site_url or "(首次运行设置)", data_dir)
    # private_mode=False + storage_path：保留 Cookie/localStorage，免得每次启动都要重新登录
    webview.start(
        menu=_build_menu(window, service, texts, logger),
        private_mode=False,
        storage_path=str(data_dir / "webview"),
        debug=_debug_enabled(),
    )