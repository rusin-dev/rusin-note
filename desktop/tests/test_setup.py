"""tests for src.core.setup / 首次运行设置页"""
from __future__ import annotations

import locale

import pytest

from src.core import setup
from src.core.setup import render_setup_html, ui_lang


class TestRendering:
    def test_contains_form_and_bridge(self):
        html = render_setup_html("https://note.example.com")
        assert 'id="setupForm"' in html
        assert 'id="siteUrl"' in html
        assert "pywebview.api.connect" in html

    def test_prefills_default_url(self):
        assert 'value="https://note.example.com"' in render_setup_html("https://note.example.com")

    def test_ships_both_languages(self):
        html = render_setup_html("https://note.example.com")
        assert "连接到你的站点" in html
        assert "Connect to your site" in html

    def test_is_self_contained(self):
        html = render_setup_html("https://note.example.com")
        assert "<script src=" not in html
        assert '<link rel="stylesheet"' not in html
        assert 'src="http' not in html
        assert 'href="http' not in html
        assert "@import" not in html

    def test_error_message_rendered(self):
        html = render_setup_html("https://note.example.com", error="站点不可达-XYZ")
        assert "站点不可达-XYZ" in html


class TestEscaping:
    @pytest.mark.parametrize("payload", [
        '"><script>alert(1)</script>',
        '" onfocus="alert(1)',
        "<img src=x onerror=alert(1)>",
        "'><svg onload=alert(1)>",
    ])
    def test_default_url_is_escaped(self, payload):
        html = render_setup_html(payload)
        assert "<script>alert(1)</script>" not in html
        assert "<img src=x onerror=alert(1)>" not in html
        assert "<svg onload=alert(1)>" not in html
        assert 'onfocus="alert(1)"' not in html

    def test_error_is_escaped(self):
        html = render_setup_html("https://note.example.com", error="<script>alert(1)</script>")
        assert "<script>alert(1)</script>" not in html
        assert "&lt;script&gt;" in html


class TestUiLang:
    @pytest.mark.parametrize("value, expected", [
        ("zh_CN", "zh"),
        ("zh_TW", "zh"),
        ("Chinese (Simplified)_China.936", "zh"),
        ("en_US", "en"),
        ("ja_JP", "en"),
        ("", "en"),
        (None, "en"),
    ])
    def test_lang_from_locale(self, monkeypatch, value, expected):
        monkeypatch.setattr(locale, "getlocale", lambda: (value, "UTF-8"))
        assert ui_lang() == expected

    def test_locale_error_falls_back_to_english(self, monkeypatch):
        def boom():
            raise ValueError("unknown locale")

        monkeypatch.setattr(locale, "getlocale", boom)
        assert ui_lang() == "en"