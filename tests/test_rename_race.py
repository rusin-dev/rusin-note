"""用户名改名 TOCTOU 防护：目标名先占位，失败释放。"""
from __future__ import annotations

import logging

import app.apps.user.service as user_service
from app.core.notes import read_note
from app.core.store import get_user, register_user
from support import DEFAULT_PASSWORD, create_note, expect, register_and_login

logger = logging.getLogger("rusin.tests.rename_race")


class TestRenameRace:
    def test_target_cannot_be_registered_during_copy(self, ctx, monkeypatch):
        logger.info("=== [A] 复制期间目标名不可被抢注 ===")
        register_and_login(ctx.client, "race_old")
        note_id = create_note(ctx.client, "race_old", "secret content")
        attempted = {}

        original = user_service._copy_notes

        def copy_with_race(old, new):
            attempted["ok"] = register_user(new, {"salt": "s", "hash": "h"})
            return original(old, new)

        monkeypatch.setattr(user_service, "_copy_notes", copy_with_race)
        err = user_service.rename_user("race_old", "race_new", DEFAULT_PASSWORD)
        expect(err is None, "改名成功")
        expect(attempted["ok"] is False, "目标名已被占位，注册被拒")
        record = get_user("race_new") or {}
        expect(record and "reserved_by" not in record, "目标名最终是真实账号记录")
        expect(read_note("race_new", note_id) == "secret content", "笔记已迁移到新命名空间")

    def test_failed_rename_releases_reservation(self, ctx, monkeypatch):
        logger.info("=== [B] 迁移失败释放占位，不留下幻影账号 ===")
        register_and_login(ctx.client, "race_old2")
        monkeypatch.setattr(user_service, "_copy_notes", lambda old, new: False)
        err = user_service.rename_user("race_old2", "race_new2", DEFAULT_PASSWORD)
        expect(err is not None, "迁移失败返回错误")
        expect(get_user("race_new2") is None, "失败后占位已释放")
        expect(register_user("race_new2", {"salt": "s2", "hash": "h2"}),
               "目标名可被正常注册")
