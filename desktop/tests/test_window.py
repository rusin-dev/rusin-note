"""tests for src.core.window / WebView 原生壳（不启动真实 GUI）"""
from __future__ import annotations

import logging
import time

import pytest
import webview

from src.core.data import DataService
from src.core.site import DEFAULT_SITE_URL
from src.core.window import (
    DEFAULT_HEIGHT,
    DEFAULT_WIDTH,
    KEY_HEIGHT,
    KEY_MAXIMIZED,
    KEY_SITE_URL,
    KEY_WIDTH,
    KEY_X,
    KEY_Y,
    MIN_SIZE,
    ShellApi,
    _build_menu,
    _MENU_TEXTS,
    _reload,
    _run_update_check,
    check_for_update,
    load_geometry,
    run,
    save_geometry,
    show_setup,
)
from src.modules import updater

logger = logging.getLogger("rusin.tests.window")


class FakeEvent:
    def __init__(self):
        self.handlers = []

    def __iadd__(self, handler):
        self.handlers.append(handler)
        return self

    def fire(self):
        for handler in self.handlers:
            handler()


class FakeEvents:
    def __init__(self):
        self.maximized = FakeEvent()
        self.restored = FakeEvent()
        self.minimized = FakeEvent()
        self.closing = FakeEvent()


class FakeWindow:
    def __init__(self, url="about:blank", width=1000, height=700, x=10, y=20):
        self._url = url
        self.width = width
        self.height = height
        self.x = x
        self.y = y
        self.events = FakeEvents()
        self.loaded_urls = []
        self.loaded_html = []
        self.destroyed = False
        self.fullscreen_toggled = 0
        self.dialogs = []
        self.dialog_answer = False

    def create_confirmation_dialog(self, title, message):
        self.dialogs.append((title, message))
        return self.dialog_answer

    def get_current_url(self):
        return self._url

    def load_url(self, url):
        self._url = url
        self.loaded_urls.append(url)

    def load_html(self, html):
        self._url = "about:blank"
        self.loaded_html.append(html)

    def destroy(self):
        self.destroyed = True

    def toggle_fullscreen(self):
        self.fullscreen_toggled += 1


@pytest.fixture
def service(tmp_path) -> DataService:
    return DataService.local(tmp_path / "data")


@pytest.fixture
def window() -> FakeWindow:
    return FakeWindow()


class TestShellApiConnect:
    def test_valid_url_saved_and_loaded(self, service, window):
        api = ShellApi(service, logger)
        api.window = window
        result = api.connect("https://note.example.com/")
        assert result == {"ok": True, "url": "https://note.example.com"}
        assert service.config.get(KEY_SITE_URL) == "https://note.example.com"
        assert window.loaded_urls == ["https://note.example.com"]

    def test_blank_uses_default_site(self, service, window):
        api = ShellApi(service, logger)
        api.window = window
        assert api.connect("   ") == {"ok": True, "url": DEFAULT_SITE_URL}
        assert service.config.get(KEY_SITE_URL) == DEFAULT_SITE_URL

    def test_invalid_url_rejected_without_side_effects(self, service, window):
        api = ShellApi(service, logger)
        api.window = window
        service.config.set(KEY_SITE_URL, "https://keep.example.com")
        assert api.connect("javascript:alert(1)") == {"ok": False, "reason": "invalid"}
        assert service.config.get(KEY_SITE_URL) == "https://keep.example.com"
        assert window.loaded_urls == []

    def test_scheme_added_when_missing(self, service, window):
        api = ShellApi(service, logger)
        api.window = window
        assert api.connect("note.example.com")["url"] == "https://note.example.com"

    def test_works_before_window_attached(self, service):
        api = ShellApi(service, logger)
        assert api.connect("https://note.example.com")["ok"] is True
        assert service.config.get(KEY_SITE_URL) == "https://note.example.com"


class TestGeometry:
    def test_defaults_when_unset(self, service):
        geometry = load_geometry(service)
        assert geometry == {
            "width": DEFAULT_WIDTH, "height": DEFAULT_HEIGHT,
            "x": None, "y": None, "maximized": False,
        }

    def test_reads_persisted_values(self, service):
        service.config.set(KEY_WIDTH, 1024)
        service.config.set(KEY_HEIGHT, 768)
        service.config.set(KEY_X, -100)
        service.config.set(KEY_Y, 40)
        service.config.set(KEY_MAXIMIZED, True)
        assert load_geometry(service) == {
            "width": 1024, "height": 768, "x": -100, "y": 40, "maximized": True,
        }

    def test_clamps_below_minimum(self, service):
        service.config.set(KEY_WIDTH, 10)
        service.config.set(KEY_HEIGHT, 10)
        geometry = load_geometry(service)
        assert geometry["width"] == MIN_SIZE[0]
        assert geometry["height"] == MIN_SIZE[1]

    def test_corrupt_values_fall_back(self, service):
        service.config.set(KEY_WIDTH, "wide")
        service.config.set(KEY_HEIGHT, None)
        service.config.set(KEY_X, "left")
        geometry = load_geometry(service)
        assert geometry["width"] == DEFAULT_WIDTH
        assert geometry["height"] == DEFAULT_HEIGHT
        assert geometry["x"] is None

    def test_save_persists_geometry(self, service, window):
        save_geometry(window, service, False, logger)
        assert service.config.get(KEY_WIDTH) == 1000
        assert service.config.get(KEY_HEIGHT) == 700
        assert service.config.get(KEY_X) == 10
        assert service.config.get(KEY_Y) == 20
        assert service.config.get(KEY_MAXIMIZED) is False

    def test_maximized_keeps_normal_size(self, service, window):
        service.config.set(KEY_WIDTH, 1024)
        service.config.set(KEY_HEIGHT, 768)
        save_geometry(window, service, True, logger)
        assert service.config.get(KEY_MAXIMIZED) is True
        assert service.config.get(KEY_WIDTH) == 1024
        assert service.config.get(KEY_HEIGHT) == 768

    def test_save_swallows_errors(self, service, window, monkeypatch):
        def boom(*args, **kwargs):
            raise OSError("disk full")

        monkeypatch.setattr(service.config, "set", boom)
        save_geometry(window, service, False, logger)


class TestSetupAndReload:
    def test_show_setup_prefills_current_site(self, service, window):
        service.config.set(KEY_SITE_URL, "https://note.example.com")
        show_setup(window, service)
        assert len(window.loaded_html) == 1
        assert "https://note.example.com" in window.loaded_html[0]

    def test_show_setup_without_site_uses_default(self, service, window):
        show_setup(window, service)
        assert DEFAULT_SITE_URL in window.loaded_html[0]

    def test_reload_reloads_http_page(self, service, window):
        window.load_url("https://note.example.com/user/alice/abc")
        _reload(window, service)
        assert window.loaded_urls[-1] == "https://note.example.com/user/alice/abc"

    def test_reload_from_setup_goes_to_site(self, service, window):
        service.config.set(KEY_SITE_URL, "https://note.example.com")
        _reload(window, service)
        assert window.loaded_urls == ["https://note.example.com"]

    def test_reload_from_setup_without_site_shows_setup(self, service, window):
        _reload(window, service)
        assert window.loaded_urls == []
        assert len(window.loaded_html) == 1


class TestMenu:
    def test_menu_structure(self, service, window):
        texts = _MENU_TEXTS["zh"]
        menus = _build_menu(window, service, texts, logger)
        assert [m.title for m in menus] == [texts["file"], texts["view"]]
        assert len(menus[0].items) == 4
        assert len(menus[1].items) == 2

    def test_quit_action_destroys_window(self, service, window):
        menus = _build_menu(window, service, _MENU_TEXTS["zh"], logger)
        menus[0].items[-1].function()
        assert window.destroyed is True

    def test_fullscreen_action_toggles(self, service, window):
        menus = _build_menu(window, service, _MENU_TEXTS["zh"], logger)
        menus[1].items[-1].function()
        assert window.fullscreen_toggled == 1

    def test_both_languages_have_same_keys(self):
        assert set(_MENU_TEXTS["zh"]) == set(_MENU_TEXTS["en"])


class TestUpdateCheck:
    @pytest.fixture
    def texts(self):
        return _MENU_TEXTS["zh"]

    def test_new_version_opens_download_page(self, service, window, texts, monkeypatch):
        monkeypatch.setattr(updater, "get_current_version", lambda: "1.0.0")
        monkeypatch.setattr(updater, "get_latest_version", lambda site: "1.2.0")
        opened = []
        monkeypatch.setattr("src.core.window.webbrowser.open", opened.append)
        window.dialog_answer = True
        _run_update_check(window, service, texts, logger, "https://note.example.com")
        assert opened == ["https://note.example.com/downloads"]
        assert "1.2.0" in window.dialogs[0][1]

    def test_new_version_declined_does_not_open(self, service, window, texts, monkeypatch):
        monkeypatch.setattr(updater, "get_current_version", lambda: "1.0.0")
        monkeypatch.setattr(updater, "get_latest_version", lambda site: "1.2.0")
        opened = []
        monkeypatch.setattr("src.core.window.webbrowser.open", opened.append)
        window.dialog_answer = False
        _run_update_check(window, service, texts, logger, "https://note.example.com")
        assert opened == []

    def test_up_to_date_reports_current_version(self, service, window, texts, monkeypatch):
        monkeypatch.setattr(updater, "get_current_version", lambda: "1.2.0")
        monkeypatch.setattr(updater, "get_latest_version", lambda site: "1.2.0")
        opened = []
        monkeypatch.setattr("src.core.window.webbrowser.open", opened.append)
        _run_update_check(window, service, texts, logger, "https://note.example.com")
        assert opened == []
        assert "1.2.0" in window.dialogs[0][1]

    def test_network_failure_is_reported_not_raised(self, service, window, texts, monkeypatch):
        def boom(site):
            raise OSError("offline")

        monkeypatch.setattr(updater, "get_current_version", lambda: "1.0.0")
        monkeypatch.setattr(updater, "get_latest_version", boom)
        _run_update_check(window, service, texts, logger, "https://note.example.com")
        assert window.dialogs[0][1] == texts["update_failed"]

    def test_without_site_goes_to_setup(self, service, window, texts):
        check_for_update(window, service, texts, logger)
        assert len(window.loaded_html) == 1

    def test_with_site_runs_in_background(self, service, window, texts, monkeypatch):
        service.config.set(KEY_SITE_URL, "https://note.example.com")
        called = []
        monkeypatch.setattr(
            "src.core.window._run_update_check",
            lambda *args: called.append(args),
        )
        check_for_update(window, service, texts, logger)
        for _ in range(100):
            if called:
                break
            time.sleep(0.01)
        assert called and called[0][-1] == "https://note.example.com"


class TestRunWiring:
    """验证 run() 交给 pywebview 的参数（不启动真实 GUI）"""

    @pytest.fixture
    def captured(self, monkeypatch, window):
        calls = {}

        def fake_create_window(*args, **kwargs):
            calls["create"] = (args, kwargs)
            return window

        def fake_start(*args, **kwargs):
            calls["start"] = (args, kwargs)

        monkeypatch.setattr(webview, "create_window", fake_create_window)
        monkeypatch.setattr(webview, "start", fake_start)
        monkeypatch.setitem(webview.settings, "OPEN_EXTERNAL_LINKS_IN_BROWSER", False)
        monkeypatch.setitem(webview.settings, "ALLOW_DOWNLOADS", False)
        return calls

    def test_first_run_shows_setup(self, service, tmp_path, captured, window):
        run(service, tmp_path, logger)
        kwargs = captured["create"][1]
        assert kwargs["url"] is None
        assert "setupForm" in kwargs["html"]
        assert kwargs["js_api"] is not None

    def test_configured_site_loads_directly(self, service, tmp_path, captured):
        service.config.set(KEY_SITE_URL, "https://note.example.com")
        run(service, tmp_path, logger)
        kwargs = captured["create"][1]
        assert kwargs["url"] == "https://note.example.com"
        assert kwargs["html"] is None

    def test_session_persisted_and_links_external(self, service, tmp_path, captured):
        run(service, tmp_path, logger)
        start_kwargs = captured["start"][1]
        assert start_kwargs["private_mode"] is False
        assert start_kwargs["storage_path"] == str(tmp_path / "webview")
        assert webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] is True
        assert webview.settings["ALLOW_DOWNLOADS"] is True
        assert start_kwargs["menu"]

    def test_geometry_restored(self, service, tmp_path, captured):
        service.config.set(KEY_WIDTH, 1024)
        service.config.set(KEY_HEIGHT, 768)
        service.config.set(KEY_MAXIMIZED, True)
        run(service, tmp_path, logger)
        kwargs = captured["create"][1]
        assert (kwargs["width"], kwargs["height"]) == (1024, 768)
        assert kwargs["maximized"] is True
        assert kwargs["text_select"] is True

    def test_closing_saves_geometry(self, service, tmp_path, captured, window):
        run(service, tmp_path, logger)
        window.events.closing.fire()
        assert service.config.get(KEY_WIDTH) == window.width
        assert service.config.get(KEY_HEIGHT) == window.height

    def test_maximized_event_tracked(self, service, tmp_path, captured, window):
        run(service, tmp_path, logger)
        window.events.maximized.fire()
        window.events.closing.fire()
        assert service.config.get(KEY_MAXIMIZED) is True
        window.events.restored.fire()
        window.events.closing.fire()
        assert service.config.get(KEY_MAXIMIZED) is False