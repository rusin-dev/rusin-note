"""tests for src.app / 数据目录与单实例锁"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from src import app


class TestDataDir:
    def test_env_override_wins(self, tmp_path, monkeypatch):
        monkeypatch.setenv(app.DATA_DIR_ENV, str(tmp_path / "custom"))
        assert app.data_dir() == (tmp_path / "custom").resolve()

    def test_windows_uses_appdata(self, tmp_path, monkeypatch):
        monkeypatch.delenv(app.DATA_DIR_ENV, raising=False)
        monkeypatch.setattr(sys, "platform", "win32")
        monkeypatch.setenv("APPDATA", str(tmp_path))
        assert app.data_dir() == tmp_path / app.APP_DIR_NAME

    def test_macos_uses_application_support(self, tmp_path, monkeypatch):
        monkeypatch.delenv(app.DATA_DIR_ENV, raising=False)
        monkeypatch.setattr(sys, "platform", "darwin")
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        assert app.data_dir() == tmp_path / "Library" / "Application Support" / app.APP_DIR_NAME

    def test_linux_uses_xdg(self, tmp_path, monkeypatch):
        monkeypatch.delenv(app.DATA_DIR_ENV, raising=False)
        monkeypatch.setattr(sys, "platform", "linux")
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
        assert app.data_dir() == tmp_path / "xdg" / app.APP_DIR_NAME

    def test_linux_falls_back_to_local_share(self, tmp_path, monkeypatch):
        monkeypatch.delenv(app.DATA_DIR_ENV, raising=False)
        monkeypatch.delenv("XDG_DATA_HOME", raising=False)
        monkeypatch.setattr(sys, "platform", "linux")
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        assert app.data_dir() == tmp_path / ".local" / "share" / app.APP_DIR_NAME


class TestSingleInstance:
    def test_lock_blocks_second_instance(self, tmp_path):
        first = app.acquire_instance_lock(tmp_path)
        assert first is not None
        try:
            assert app.acquire_instance_lock(tmp_path) is None
        finally:
            first.close()

    def test_lock_released_after_close(self, tmp_path):
        first = app.acquire_instance_lock(tmp_path)
        first.close()
        second = app.acquire_instance_lock(tmp_path)
        assert second is not None
        second.close()

    def test_creates_directory_and_lock_file(self, tmp_path):
        target = tmp_path / "nested" / "data"
        handle = app.acquire_instance_lock(target)
        try:
            assert target.is_dir()
            assert (target / "instance.lock").is_file()
        finally:
            handle.close()

    def test_separate_directories_do_not_block(self, tmp_path):
        first = app.acquire_instance_lock(tmp_path / "a")
        second = app.acquire_instance_lock(tmp_path / "b")
        try:
            assert first is not None and second is not None
        finally:
            first.close()
            second.close()