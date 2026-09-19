"""笔记文件夹树状图端到端测试（pytest + logging）。

覆盖：多级文件夹名校验与规范化、树构建、编辑页保存嵌套路径、列表页树状
标记与嵌套顺序、``?folder=`` 子树筛选、功能开关门控与 file 后端持久化。

运行：``pytest tests/test_folders.py``
"""
from __future__ import annotations

import json
import logging
import os

from app.config import MAX_FOLDER_DEPTH, MAX_FOLDER_NAME_LENGTH
from app.extensions import cache
from app.feature_flags import FEATURE_KEYS, set_flags
from app.folders import (
    build_folder_tree,
    folder_in_subtree,
    get_note_folder,
    parse_folder_input,
    valid_folder,
)
from support import create_note, expect, list_order, logout, register_and_login

logger = logging.getLogger("rusin.tests.folders")

USER = "folderer"
OTHER = "viewer9"


class TestFolderHelpers:
    """A/B：纯函数（路径校验、规范化、树构建）。"""

    def test_valid_folder(self):
        logger.info("=== [A] 文件夹路径校验 / 规范化 ===")
        expect(valid_folder("工作") and valid_folder("a-b_c"), "合法单段")
        expect(valid_folder("工作/项目A/需求") and valid_folder("a/b"), "合法多级")
        expect(not valid_folder("a//b") and not valid_folder("/a")
               and not valid_folder("a/") and not valid_folder("/"),
               "拒绝空段与首尾斜杠")
        expect(not valid_folder("a" * (MAX_FOLDER_NAME_LENGTH + 1)), "拒绝超长")
        expect(not valid_folder("/".join(["a"] * (MAX_FOLDER_DEPTH + 1)))
               and valid_folder("/".join(["a"] * MAX_FOLDER_DEPTH)), "拒绝超深")

    def test_parse_folder_input(self):
        expect(parse_folder_input("  工作 / 项目A ") == "工作/项目A"
               and parse_folder_input("a//b") == "a/b"
               and parse_folder_input("/a/") == "a", "规范化去空白/合并斜杠")
        expect(parse_folder_input("a b") == "" and parse_folder_input("") == "", "非法输入归为空")

    def test_folder_in_subtree(self):
        expect(folder_in_subtree("工作/项目A", "工作")
               and folder_in_subtree("工作", "工作")
               and not folder_in_subtree("工作A", "工作")
               and folder_in_subtree("任意", ""), "子树匹配")

    def test_build_folder_tree(self):
        logger.info("=== [B] build_folder_tree 结构 ===")
        items = [
            {"id": "n1", "folder": "工作/项目A"},
            {"id": "n2", "folder": "工作/项目B"},
            {"id": "n3", "folder": "工作"},
            {"id": "n4", "folder": ""},
            {"id": "n5", "folder": "生活"},
        ]
        tree = build_folder_tree(items)
        expect(tree["total"] == 5 and [x["id"] for x in tree["notes"]] == ["n4"],
               "total 与未归类分离")
        expect([c["name"] for c in tree["children"]] == ["工作", "生活"], "同层按名称升序")
        work = tree["children"][0]
        expect(work["count"] == 3 and [x["id"] for x in work["notes"]] == ["n3"],
               "子树计数含自身与后代")
        expect([g["name"] for g in work["children"]] == ["项目A", "项目B"]
               and work["children"][0]["path"] == "工作/项目A", "中间层与完整 path")
        expect([x["id"] for x in work["children"][0]["notes"]] == ["n1"], "组内保持传入顺序")


class TestFolderE2E:
    """C-H：端到端保存、渲染、筛选、隔离与持久化。"""

    def test_save_and_render_tree(self, ctx):
        logger.info("=== [C] 编辑页保存嵌套路径 + 列表页树 ===")
        register_and_login(ctx.client, USER)
        ctx.notes["a"] = create_note(ctx.client, USER, "A", folder="工作/项目A")
        ctx.notes["b"] = create_note(ctx.client, USER, "B", folder="工作")
        ctx.notes["c"] = create_note(ctx.client, USER, "C", folder="")
        expect(get_note_folder(USER, ctx.notes["a"]) == "工作/项目A"
               and get_note_folder(USER, ctx.notes["b"]) == "工作", "嵌套路径读回")

        html = ctx.client.get(f"/user/{USER}").get_data(as_text=True)
        expect('class="folder-tree"' in html and "tree-children" in html, "渲染树容器")
        expect("项目A" in html and "未归类" in html, "含文件夹名与未归类")
        expect(html.count('class="tree-toggle"') >= 3, "树节点用 button 折叠")
        expect("folder=__uncat__" not in html, "未归类节点无筛选链接")
        order = list_order(ctx.client, USER)
        expect(sorted(order) == sorted(ctx.notes.values()) and len(order) == 3, "树形下笔记链接齐全")

    def test_folder_subtree_filter(self, ctx):
        logger.info("=== [D] ?folder= 子树筛选 ===")
        expect(sorted(list_order(ctx.client, USER, "?folder=工作"))
               == sorted([ctx.notes["a"], ctx.notes["b"]]), "父文件夹含子文件夹笔记")
        expect(list_order(ctx.client, USER, "?folder=%E5%B7%A5%E4%BD%9C/%E9%A1%B9%E7%9B%AEA")
               == [ctx.notes["a"]], "子文件夹只含自身笔记")
        expect(ctx.notes["c"] not in list_order(ctx.client, USER, "?folder=工作"),
               "未归类不匹配工作子树")
        html = ctx.client.get(f"/user/{USER}?folder=%E5%B7%A5%E4%BD%9C").get_data(as_text=True)
        expect("folder-breadcrumb" in html, "筛选时有面包屑")

    def test_invalid_input_normalized(self, ctx):
        logger.info("=== [E] 非法输入处理 ===")
        note_d = create_note(ctx.client, USER, "D", folder="a//b")
        ctx.notes["d"] = note_d
        expect(get_note_folder(USER, note_d) == "a/b", "非法路径片段被规范化保存")

    def test_user_isolation(self, ctx):
        logger.info("=== [F] 用户隔离 ===")
        logout(ctx.client)
        register_and_login(ctx.client, OTHER)
        ctx.notes["own"] = create_note(ctx.client, OTHER, "别人的", folder="他人/私有")
        html = ctx.client.get(f"/user/{OTHER}").get_data(as_text=True)
        expect(ctx.notes["own"] in html and ctx.notes["a"] not in html, "他人列表只含自己笔记")
        expect("他人" in html and "工作" not in html, "他人文件夹树独立")

    def test_feature_flag_gating(self, ctx):
        logger.info("=== [G] 功能开关 note_folders ===")
        set_flags({k: (k != "note_folders") for k in FEATURE_KEYS})
        cache.clear()
        html = ctx.client.get(f"/user/{OTHER}").get_data(as_text=True)
        expect('class="folder-tree"' not in html, "停用后不渲染树")
        expect("?folder=" not in html, "停用后无文件夹筛选链接")
        set_flags({k: True for k in FEATURE_KEYS})
        cache.clear()
        html = ctx.client.get(f"/user/{OTHER}").get_data(as_text=True)
        expect('class="folder-tree"' in html, "重新启用后树恢复")

    def test_persistence(self, ctx):
        logger.info("=== [H] 持久化 ===")
        path = os.path.join(ctx.data_dir, "note_folders.json")
        expect(os.path.exists(path), "note_folders.json 已落盘")
        with open(path, encoding="utf-8") as handle:
            stored = json.load(handle)
        expect(stored.get(USER, {}).get(ctx.notes["a"]) == "工作/项目A"
               and stored.get(USER, {}).get(ctx.notes["d"]) == "a/b",
               "落盘结构为 {用户: {笔记: 路径}}")
