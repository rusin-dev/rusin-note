"""笔记置顶功能端到端测试（pytest + logging）。

覆盖：列表页图钉开关、置顶排序（置顶组内置顶时间倒序、其余修改时间倒序）、
筛选视图下的置顶与筛选参数回传、删除笔记联动清理、功能开关门控与 file 后端
持久化。

运行：``pytest tests/test_pins.py``
"""
from __future__ import annotations

import json
import logging
import os

from app.extensions import cache
from app.feature_flags import FEATURE_KEYS, set_flags
from app.pins import get_user_pins, is_pinned, set_note_pinned, toggle_note_pin
from app.tags import set_note_tags
from support import (
    create_note,
    csrf_from,
    expect,
    list_order,
    logout,
    pin_note,
    register_and_login,
)

logger = logging.getLogger("rusin.tests.pins")

USER = "pinner"
OTHER = "viewer4"


def set_file_mtime(data_dir, username: str, note_id: str, ts: float) -> None:
    """file 后端：显式设置笔记 mtime，保证排序断言确定性。"""
    os.utime(os.path.join(data_dir, "notes", username, f"{note_id}.txt"), (ts, ts))


class TestPinsModule:
    """A：pins 模块级行为。"""

    def test_module_api(self):
        logger.info("=== [A] pins 模块 ===")
        set_note_pinned(USER, "mod1", True)
        expect(isinstance(get_user_pins(USER).get("mod1"), float), "置顶写入并读到时间戳")
        expect(is_pinned(USER, "mod1") is True and is_pinned(USER, "mod2") is False, "is_pinned 查询")
        expect(toggle_note_pin(USER, "mod1") is False and toggle_note_pin(USER, "mod1") is True,
               "toggle 切换两态")
        expect(toggle_note_pin(USER, "mod1") is False and "mod1" not in get_user_pins(USER),
               "取消置顶后条目清除")
        set_note_pinned(USER, "mod1", False)  # 清理模块级测试残留


class TestPinsE2E:
    """B-J：排序、置顶浮动、筛选、联动清理、门控、隔离与持久化。"""

    def test_list_order_and_pin_toggle(self, ctx):
        logger.info("=== [B] 列表排序与图钉开关 ===")
        register_and_login(ctx.client, USER)
        ctx.notes["n1"] = create_note(ctx.client, USER, "最旧")
        ctx.notes["n2"] = create_note(ctx.client, USER, "居中")
        ctx.notes["n3"] = create_note(ctx.client, USER, "最新")
        set_file_mtime(ctx.data_dir, USER, ctx.notes["n1"], 1000)
        set_file_mtime(ctx.data_dir, USER, ctx.notes["n2"], 2000)
        set_file_mtime(ctx.data_dir, USER, ctx.notes["n3"], 3000)
        expect(list_order(ctx.client, USER)
               == [ctx.notes["n3"], ctx.notes["n2"], ctx.notes["n1"]], "默认按修改时间倒序")
        html = ctx.client.get(f"/user/{USER}").get_data(as_text=True)
        expect('class="pin-form"' in html and "/pin" in html, "列表页含图钉开关")
        expect('<li class="pinned-row">' not in html, "初始无置顶行")

    def test_pin_floats_to_top(self, ctx):
        logger.info("=== [C] 置顶浮动到最前 ===")
        response = pin_note(ctx.client, USER, ctx.notes["n1"])
        assert response.status_code == 302, f"置顶请求失败: {response.status_code}"
        expect(is_pinned(USER, ctx.notes["n1"]) is True, "模块层读到置顶")
        expect(list_order(ctx.client, USER)
               == [ctx.notes["n1"], ctx.notes["n3"], ctx.notes["n2"]], "最旧笔记置顶后排在最前")
        html = ctx.client.get(f"/user/{USER}").get_data(as_text=True)
        expect('<li class="pinned-row">' in html and "pin-btn pinned" in html,
               "置顶行高亮与图钉激活态")

    def test_pin_time_order(self, ctx):
        logger.info("=== [D] 置顶组内按置顶时间倒序 ===")
        response = pin_note(ctx.client, USER, ctx.notes["n2"])
        assert response.status_code == 302
        expect(list_order(ctx.client, USER)
               == [ctx.notes["n2"], ctx.notes["n1"], ctx.notes["n3"]], "后置顶的排更前")

    def test_unpin_restores_order(self, ctx):
        logger.info("=== [E] 取消置顶恢复排序 ===")
        response = pin_note(ctx.client, USER, ctx.notes["n2"])
        assert response.status_code == 302
        expect(list_order(ctx.client, USER)
               == [ctx.notes["n1"], ctx.notes["n3"], ctx.notes["n2"]], "取消后回到修改时间序")
        expect(is_pinned(USER, ctx.notes["n2"]) is False, "模块层确认取消")

    def test_filtered_view_pin(self, ctx):
        logger.info("=== [F] 筛选视图下的置顶 ===")
        set_note_tags(USER, ctx.notes["n1"], ["alpha"])
        set_note_tags(USER, ctx.notes["n3"], ["alpha"])
        set_note_tags(USER, ctx.notes["n2"], ["beta"])
        expect(list_order(ctx.client, USER, "?tag=alpha")
               == [ctx.notes["n1"], ctx.notes["n3"]], "筛选视图内置顶仍浮前")
        response = pin_note(ctx.client, USER, ctx.notes["n3"], tag="alpha")
        assert response.status_code == 302
        expect(response.headers["Location"].startswith(f"/user/{USER}")
               and "tag=alpha" in response.headers["Location"], "切换后重定向保留筛选参数")
        expect(list_order(ctx.client, USER, "?tag=alpha")
               == [ctx.notes["n3"], ctx.notes["n1"]], "筛选视图内后置顶的排更前")

    def test_delete_note_cleanup(self, ctx):
        logger.info("=== [G] 删除笔记联动清理 ===")
        response = ctx.client.post(f"/user/{USER}/{ctx.notes['n1']}", data={
            "content": "",
            "csrf_token": csrf_from(ctx.client, f"/user/{USER}/{ctx.notes['n1']}"),
        })
        assert response.status_code == 302
        expect(is_pinned(USER, ctx.notes["n1"]) is False
               and ctx.notes["n1"] not in get_user_pins(USER), "删除笔记后置顶条目被清理")
        expect(ctx.notes["n1"] not in list_order(ctx.client, USER), "列表不再含该笔记")

    def test_feature_flag_gating(self, ctx):
        logger.info("=== [H] 功能开关 note_pins ===")
        set_flags({k: (k != "note_pins") for k in FEATURE_KEYS})
        cache.clear()  # 管理页保存开关时会 cache.clear()，这里等价模拟
        html = ctx.client.get(f"/user/{USER}").get_data(as_text=True)
        expect('class="pin-form"' not in html and '<li class="pinned-row">' not in html,
               "停用后列表页无图钉开关")
        expect(list_order(ctx.client, USER) == [ctx.notes["n3"], ctx.notes["n2"]],
               "停用后排序退回修改时间倒序")
        csrf = csrf_from(ctx.client, f"/user/{USER}/{ctx.notes['n3']}")
        response = ctx.client.post(f"/user/{USER}/{ctx.notes['n3']}/pin",
                                   data={"csrf_token": csrf})
        expect(response.status_code == 404, "停用时 POST /pin -> 404")
        expect(is_pinned(USER, ctx.notes["n3"]) is True, "停用时不改变置顶状态")

        set_flags({k: True for k in FEATURE_KEYS})
        cache.clear()
        html = ctx.client.get(f"/user/{USER}").get_data(as_text=True)
        expect('class="pin-form"' in html, "重新启用后图钉开关恢复")

    def test_edge_and_isolation(self, ctx):
        logger.info("=== [I] 边界与用户隔离 ===")
        csrf = csrf_from(ctx.client, f"/user/{USER}/{ctx.notes['n3']}")
        response = ctx.client.post(f"/user/{USER}/zzzz/pin", data={"csrf_token": csrf})
        expect(response.status_code == 404, "置顶不存在的笔记 -> 404")

        logout(ctx.client)
        register_and_login(ctx.client, OTHER)
        ctx.notes["own"] = create_note(ctx.client, OTHER, "别人的笔记")
        response = pin_note(ctx.client, OTHER, ctx.notes["own"])
        assert response.status_code == 302
        expect(is_pinned(OTHER, ctx.notes["own"]) is True
               and set(get_user_pins(OTHER)) == {ctx.notes["own"]}
               and set(get_user_pins(USER)) == {ctx.notes["n3"]}, "置顶按用户隔离存储")
        html = ctx.client.get(f"/user/{OTHER}").get_data(as_text=True)
        expect(ctx.notes["own"] in html and ctx.notes["n3"] not in html, "他人列表页只含自己的笔记")

    def test_persistence(self, ctx):
        logger.info("=== [J] 持久化 ===")
        path = os.path.join(ctx.data_dir, "note_pins.json")
        expect(os.path.exists(path), "note_pins.json 已落盘")
        with open(path, encoding="utf-8") as handle:
            stored = json.load(handle)
        expect(isinstance(stored.get(USER, {}).get(ctx.notes["n3"]), float)
               and isinstance(stored.get(OTHER, {}).get(ctx.notes["own"]), float),
               "落盘结构为 {用户: {笔记: 置顶时间}}")
