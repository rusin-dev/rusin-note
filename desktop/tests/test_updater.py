"""updater 模块测试：更新检查走站点 /downloads/manifest.json（安装包站点自托管）"""

import json
from pathlib import Path

import pytest
import requests

from src.modules import updater
from src.modules.updater import (
    fetch_manifest,
    get_current_channel,
    get_current_version,
    get_latest_version,
    is_newer,
)

METADATA_FILE = Path(__file__).resolve().parents[1] / "data" / "metadata.json"
SITE = "https://note.example.com"


def _metadata() -> dict:
    return json.loads(METADATA_FILE.read_text(encoding="utf-8"))


def _manifest(version="1.2.3", channel="stable", **extra) -> dict:
    data = {"version": version, "channel": channel, "artifacts": []}
    data.update(extra)
    return data


class _FakeResponse:
    def __init__(self, status_code: int, payload):
        self.status_code = status_code
        self._payload = payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} Client Error")

    def json(self):
        return self._payload


@pytest.fixture
def fake_get(monkeypatch):
    calls: dict = {}

    def _install(payload=None, status_code=200):
        def fake(url, headers=None, timeout=None):
            calls["url"] = url
            calls["headers"] = headers
            calls["timeout"] = timeout
            return _FakeResponse(status_code, payload)

        monkeypatch.setattr(updater.requests, "get", fake)
        return calls

    return _install


class TestMetadata:
    def test_current_version_matches_metadata_file(self):
        assert get_current_version() == _metadata()["version"]

    def test_current_channel_matches_metadata_file(self):
        assert get_current_channel() == _metadata()["channel"]
        assert get_current_channel() in updater.CHANNELS


class TestFetchManifest:
    def test_request_targets_site_manifest(self, fake_get):
        calls = fake_get(_manifest())
        fetch_manifest(SITE)
        assert calls["url"] == SITE + "/downloads/manifest.json"
        assert calls["headers"]["User-Agent"] == updater._USER_AGENT
        assert calls["timeout"] == 10.0

    def test_trailing_slash_normalized(self, fake_get):
        calls = fake_get(_manifest())
        fetch_manifest(SITE + "/")
        assert calls["url"] == SITE + "/downloads/manifest.json"

    def test_channel_defaults_to_metadata(self, fake_get):
        fake_get(_manifest(channel=_metadata()["channel"]))
        assert fetch_manifest(SITE)["channel"] == _metadata()["channel"]

    def test_beta_channel_accepted(self, fake_get):
        fake_get(_manifest(version="2.0.0-rc.1", channel="beta"))
        assert fetch_manifest(SITE, channel="beta")["version"] == "2.0.0-rc.1"

    def test_channel_mismatch_raises_lookup(self, fake_get):
        fake_get(_manifest(channel="beta"))
        with pytest.raises(LookupError):
            fetch_manifest(SITE, channel="stable")

    def test_missing_version_raises_lookup(self, fake_get):
        fake_get(_manifest(version=""))
        with pytest.raises(LookupError):
            fetch_manifest(SITE)

    def test_non_dict_payload_raises_lookup(self, fake_get):
        fake_get(["not", "a", "dict"])
        with pytest.raises(LookupError):
            fetch_manifest(SITE)

    def test_unknown_channel_raises_value_error(self):
        with pytest.raises(ValueError):
            fetch_manifest(SITE, channel="nightly")

    def test_http_error_propagates(self, fake_get):
        fake_get(status_code=404)
        with pytest.raises(requests.HTTPError):
            fetch_manifest(SITE)

    def test_get_latest_version_strips_whitespace(self, fake_get):
        fake_get(_manifest(version=" 1.2.3 "))
        assert get_latest_version(SITE) == "1.2.3"


class TestIsNewer:
    @pytest.mark.parametrize("candidate, current, expected", [
        ("1.2.4", "1.2.3", True),
        ("1.3.0", "1.2.9", True),
        ("2.0.0", "1.9.9", True),
        ("1.10.0", "1.9.0", True),
        ("1.2.3", "1.2.3", False),
        ("1.2.3", "1.2.4", False),
        ("1.2", "1.2.0", False),
        ("1.2.0", "1.2", False),
        ("v1.2.4", "1.2.3", True),
        ("2.0.0", "2.0.0-rc.1", True),
        ("2.0.0-rc.2", "2.0.0-rc.1", True),
        ("2.0.0-rc.1", "2.0.0-rc.2", False),
        ("2.0.0-rc.1", "2.0.0", False),
        ("2.0.0-beta", "2.0.0-alpha", True),
        ("2.0.0+build.5", "2.0.0", False),
        ("1.2.3", "", True),
    ])
    def test_comparison(self, candidate, current, expected):
        assert is_newer(candidate, current) is expected


@pytest.mark.network
def test_manifest_against_official_demo():
    """官方演示站尚未部署 /downloads 时跳过（该功能随本站发布上线）"""
    try:
        manifest = fetch_manifest("https://note.rusin7.com")
    except requests.RequestException:
        pytest.skip("站点不可达或尚未部署 /downloads")
    assert manifest["channel"] in updater.CHANNELS
    assert manifest["version"]