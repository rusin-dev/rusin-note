"""统一数据接口：桌面端只持久化客户端配置，笔记数据一律在网页版"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from src.modules.storage.config import JsonConfigStore


@runtime_checkable
class ConfigStore(Protocol):
    """扁平 KV 配置抽象契约，键名规范为 <module_id>.<data_id>"""

    def get(self, key: str, default: Any = None) -> Any: ...

    def set(self, key: str, value: Any) -> None: ...

    def delete(self, key: str) -> None: ...

    def keys(self, module_id: str | None = None) -> list[str]: ...


class DataService:
    """应用唯一数据入口：config 子接口管理客户端配置（站点地址、窗口几何等）"""

    def __init__(self, config: ConfigStore):
        self._config = config

    @classmethod
    def local(cls, data_dir: Path) -> "DataService":
        """装配本地实现：data_dir/config.json"""
        return cls(config=JsonConfigStore(Path(data_dir) / "config.json"))

    @property
    def config(self) -> ConfigStore:
        return self._config