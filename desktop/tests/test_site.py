"""tests for src.core.site / 站点地址规范化（首次运行设置页的外部输入）"""
import pytest

from src.core.site import DEFAULT_SITE_URL, normalize_site_url


class TestDefaults:
    def test_default_is_https_site(self):
        assert DEFAULT_SITE_URL == "https://note.rusin7.com"
        assert normalize_site_url(DEFAULT_SITE_URL) == DEFAULT_SITE_URL


class TestNormalization:
    @pytest.mark.parametrize("raw, expected", [
        ("note.example.com", "https://note.example.com"),
        ("https://note.example.com", "https://note.example.com"),
        ("http://note.example.com", "http://note.example.com"),
        ("  https://note.example.com/  ", "https://note.example.com"),
        ("https://note.example.com///", "https://note.example.com"),
        ("HTTPS://Note.Example.COM", "https://note.example.com"),
        ("https://note.example.com/?a=1#frag", "https://note.example.com"),
        ("https://note.example.com/note/", "https://note.example.com/note"),
        ("http://127.0.0.1:8080", "http://127.0.0.1:8080"),
        ("localhost:8080", "https://localhost:8080"),
    ])
    def test_normalized(self, raw, expected):
        assert normalize_site_url(raw) == expected

    def test_idempotent(self):
        for raw in ("note.example.com/", "HTTP://Example.com:8080/app/?x=1"):
            once = normalize_site_url(raw)
            assert normalize_site_url(once) == once


class TestRejected:
    @pytest.mark.parametrize("raw", [
        "",
        "   ",
        None,
        123,
        "file:///etc/passwd",
        "javascript:alert(1)",
        "ftp://note.example.com",
        "data:text/html,<script>alert(1)</script>",
        "https://",
        "https://user:pass@note.example.com",
        "https://user@note.example.com",
        "https://note.example.com:99999",
        "https://note.example.com:abc",
        "https://note .example.com",
    ])
    def test_rejected(self, raw):
        assert normalize_site_url(raw) is None