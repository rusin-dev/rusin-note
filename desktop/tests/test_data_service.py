"""tests for src.core.data / DataService 统一数据接口（仅客户端配置）"""
from pathlib import Path

import pytest

from src.core.data import ConfigStore, DataService
from src.modules.storage.config import JsonConfigStore


@pytest.fixture
def service(tmp_path: Path) -> DataService:
    return DataService.local(tmp_path / "data")


class TestProtocols:
    def test_json_config_store_satisfies_config_store(self, tmp_path):
        assert isinstance(JsonConfigStore(tmp_path / "c.json"), ConfigStore)


class TestConfigThroughService:
    def test_set_get_persists_under_data_dir(self, service, tmp_path):
        service.config.set("site.url", "https://note.example.com")
        assert (tmp_path / "data" / "config.json").is_file()
        assert service.config.get("site.url") == "https://note.example.com"

    def test_config_survives_new_service(self, service, tmp_path):
        service.config.set("updater.channel", "stable")
        reopened = DataService.local(tmp_path / "data")
        assert reopened.config.get("updater.channel") == "stable"

    def test_missing_key_returns_default(self, service):
        assert service.config.get("window.width", 1280) == 1280

    def test_delete_and_keys(self, service):
        service.config.set("window.width", 1280)
        service.config.set("window.height", 800)
        service.config.set("site.url", "https://note.example.com")
        assert service.config.keys("window") == ["window.height", "window.width"]
        service.config.delete("window.width")
        assert service.config.keys("window") == ["window.height"]


class TestDependencyInjection:
    def test_accepts_custom_config_store(self, tmp_path):
        class InMemoryConfig:
            def __init__(self):
                self.data: dict[str, object] = {}

            def get(self, key, default=None):
                return self.data.get(key, default)

            def set(self, key, value):
                self.data[key] = value

            def delete(self, key):
                del self.data[key]

            def keys(self, module_id=None):
                return sorted(self.data)

        fake = InMemoryConfig()
        service = DataService(config=fake)
        service.config.set("site.url", "https://note.example.com")
        assert service.config.get("site.url") == "https://note.example.com"
        assert fake.data == {"site.url": "https://note.example.com"}


class TestNoLocalNoteStorage:
    def test_service_exposes_no_note_repository(self, service):
        assert not hasattr(service, "notes")

    def test_data_dir_holds_only_config(self, service, tmp_path):
        service.config.set("site.url", "https://note.example.com")
        assert [p.name for p in (tmp_path / "data").iterdir()] == ["config.json"]