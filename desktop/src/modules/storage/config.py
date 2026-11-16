"""扁平 KV 配置存储，键名规范为 <module_id>.<data_id>，落盘为单个 JSON 文件"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

_KEY_PATTERN = re.compile(r"^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$")


class ConfigError(Exception):
    """配置存储错误基类"""


class InvalidConfigKeyError(ConfigError):
    """非法配置键名"""


class ConfigKeyNotFoundError(ConfigError):
    """配置键不存在"""


class JsonConfigStore:
    def __init__(self, path: Path):
        self.path = Path(path)

    def get(self, key: str, default: Any = None) -> Any:
        self._validate_key(key)
        return self._load().get(key, default)

    def set(self, key: str, value: Any) -> None:
        self._validate_key(key)
        data = self._load()
        data[key] = value
        self._save(data)

    def delete(self, key: str) -> None:
        self._validate_key(key)
        data = self._load()
        if key not in data:
            raise ConfigKeyNotFoundError(f"配置键不存在: {key}")
        del data[key]
        self._save(data)

    def keys(self, module_id: str | None = None) -> list[str]:
        if module_id is None:
            return sorted(self._load())
        return sorted(
            k for k in self._load() if k.split(".", 1)[0] == module_id
        )

    def _validate_key(self, key: str) -> None:
        if not _KEY_PATTERN.match(key):
            raise InvalidConfigKeyError(
                f"非法配置键（应为 <module_id>.<data_id>）: {key!r}"
            )

    def _load(self) -> dict:
        if not self.path.is_file():
            return {}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _save(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        os.replace(tmp, self.path)
