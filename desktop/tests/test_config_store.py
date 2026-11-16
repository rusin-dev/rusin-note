"""tests for src.modules.storage.config / JsonConfigStore"""
import json
from pathlib import Path

import pytest

from src.modules.storage.config import (
    ConfigKeyNotFoundError,
    InvalidConfigKeyError,
    JsonConfigStore,
)


@pytest.fixture
def store(tmp_path: Path) -> JsonConfigStore:
    return JsonConfigStore(tmp_path / "data" / "config.json")


class TestGetSet:
    def test_set_then_get_returns_value(self, store):
        store.set("ui.theme", "dark")
        assert store.get("ui.theme") == "dark"

    def test_get_missing_key_returns_default(self, store):
        assert store.get("ai_copilot.model", default="gpt") == "gpt"
        assert store.get("ai_copilot.model") is None

    def test_set_overwrites_existing_key(self, store):
        store.set("ui.theme", "dark")
        store.set("ui.theme", "light")
        assert store.get("ui.theme") == "light"

    @pytest.mark.parametrize(
        "value",
        ["str", 42, 3.14, True, None, ["a", "b"], {"k": "v"}],
    )
    def test_supports_json_value_types(self, store, value):
        store.set("core.value", value)
        assert store.get("core.value") == value


class TestPersistence:
    def test_data_persists_as_flat_json_file(self, store):
        store.set("ui.theme", "dark")
        raw = json.loads(store.path.read_text(encoding="utf-8"))
        assert raw == {"ui.theme": "dark"}

    def test_reload_from_disk_sees_previous_writes(self, store):
        store.set("updater.channel", "stable")
        reopened = JsonConfigStore(store.path)
        assert reopened.get("updater.channel") == "stable"

    def test_missing_file_is_treated_as_empty(self, tmp_path: Path):
        store = JsonConfigStore(tmp_path / "nope" / "config.json")
        assert store.get("a.b") is None
        assert store.keys() == []


class TestDeleteAndKeys:
    def test_delete_removes_key(self, store):
        store.set("ui.theme", "dark")
        store.delete("ui.theme")
        assert store.get("ui.theme") is None

    def test_delete_missing_key_raises(self, store):
        with pytest.raises(ConfigKeyNotFoundError):
            store.delete("ui.missing")

    def test_keys_returns_sorted_full_keys(self, store):
        store.set("ui.theme", "dark")
        store.set("ai_copilot.model", "gpt")
        assert store.keys() == ["ai_copilot.model", "ui.theme"]

    def test_keys_filters_by_module_id(self, store):
        store.set("ui.theme", "dark")
        store.set("ui.locale", "zh")
        store.set("updater.channel", "stable")
        assert store.keys("ui") == ["ui.locale", "ui.theme"]
        assert store.keys("none") == []


class TestKeyValidation:
    @pytest.mark.parametrize(
        "bad",
        ["nodot", "a.b.c", ".leading", "trailing.", "", "mod. bad"],
    )
    def test_rejects_invalid_keys(self, store, bad):
        with pytest.raises(InvalidConfigKeyError):
            store.set(bad, 1)

    @pytest.mark.parametrize("ok", ["ui.theme", "ai_copilot.api_base", "Mod-1.data_2"])
    def test_accepts_valid_keys(self, store, ok):
        store.set(ok, 1)
        assert store.get(ok) == 1
