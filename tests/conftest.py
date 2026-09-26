"""pytest 全局配置：环境隔离、运行时状态重置、共享 fixtures。

所有端到端测试统一使用临时 ``RUSIN_DATA_DIR``（``file`` 后端），每个测试类
获得独立的数据目录，互不污染。日志统一走标准 ``logging``（``pytest.ini`` 中
``log_cli`` 已开启，运行时直接打印）。

隔离要点
--------
``app`` 的多个模块（store / tags / folders / pins / todos / feature_flags /
notes）在导入时缓存了内存字典，仅切换临时目录并不足以隔离；本文件的
:func:`reset_runtime_state` 会显式清空这些缓存并把 file 后端指向新的目录。
"""
from __future__ import annotations

import logging
import os
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent
TESTS_DIR = Path(__file__).resolve().parent
for _path in (str(ROOT), str(TESTS_DIR)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

# ---------------------------------------------------------------------------
# 必须在任何 app 模块被导入之前固定存储后端与数据目录
# ---------------------------------------------------------------------------
os.environ["RUSIN_STORAGE"] = "file"
for _var in ("KV_REST_API_URL", "KV_REST_API_TOKEN", "DATABASE_URL", "RUSIN_SECRET_KEY"):
    os.environ.pop(_var, None)
os.environ["RUSIN_DATA_DIR"] = tempfile.mkdtemp(prefix="rusin-pytest-bootstrap-")

# Windows 控制台默认 GBK，强制 UTF-8 避免中文日志乱码
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):  # pragma: no cover
        pass

logger = logging.getLogger("rusin.tests")


def _clear_locked(mapping, lock) -> None:
    with lock:
        mapping.clear()


def reset_runtime_state(data_dir) -> None:
    """清空全部进程内缓存，并把 file 后端指向 ``data_dir``。

    这是测试隔离的核心：仅设置 ``RUSIN_DATA_DIR`` 无法清除各模块已导入的
    内存缓存，必须显式清空（``load_*()`` 在空目录下不会清空历史数据，因为
    ``storage.get`` 返回 ``None``）。
    """
    from app import config as app_config
    from app import store, tags, folders, pins, todos, notes, feature_flags
    from app import concurrency
    from app.extensions import cache, limiter

    app_config.DATA_DIR = str(data_dir)

    # ---- store：用户 / 会话 / 分享 / 犇犇 / 评论 / 组织 ----
    _clear_locked(store.users, store.users_lock)
    _clear_locked(store.sessions, store.sessions_lock)
    _clear_locked(store.shares, store.shares_lock)
    _clear_locked(store.benben_posts, store.benben_lock)
    _clear_locked(store.benben_last_post, store.benben_cooldown_lock)
    _clear_locked(store.comments_data, store.comments_lock)
    _clear_locked(store.comments_last_post, store.comments_cooldown_lock)
    _clear_locked(store.orgs, store.orgs_lock)
    _clear_locked(store.org_members, store.org_members_lock)
    _clear_locked(store.org_invites, store.org_invites_lock)
    _clear_locked(store.org_join_requests, store.org_join_requests_lock)

    # ---- 笔记元数据 ----
    _clear_locked(tags.note_tags, tags.tags_lock)
    _clear_locked(folders.note_folders, folders.folders_lock)
    _clear_locked(pins.note_pins, pins.pins_lock)
    _clear_locked(todos.user_todos, todos.todos_lock)

    # ---- 各类时间戳 / 脏标记，强制下次访问重新加载 ----
    store._last_users_reload = 0.0
    store._benben_last_resync = 0.0
    store._comments_last_resync = 0.0
    store._VIEWS_DIRTY = False
    store._VIEWS_PENDING = 0
    store._last_views_flush = time.time()
    notes._stats_cache = None
    notes._stats_cache_time = 0.0
    feature_flags._state = {}
    feature_flags._state_loaded = False
    feature_flags._last_reload = 0.0

    # ---- 扩展：关闭限流、清空缓存 ----
    limiter.enabled = False
    try:
        limiter.reset()
    except Exception:  # pragma: no cover - 不同版本 API 兜底
        pass
    # ---- 并发闸门（附件下载/上传）在途计数清零，避免跨测试类泄漏 ----
    concurrency.reset_all()
    try:
        cache.clear()
    except Exception:  # pragma: no cover - 尚未绑定 Flask app 时忽略
        pass


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="class")
def data_dir(tmp_path_factory, request):
    """每个测试类独立的临时数据目录，并重置全部运行时状态。"""
    label = request.cls.__name__ if request.cls else request.node.name
    directory = tmp_path_factory.mktemp(f"rusin-{label}-")
    reset_runtime_state(directory)
    logger.info("测试数据目录：%s", directory)
    yield directory
    reset_runtime_state(directory)


@pytest.fixture(scope="class")
def app(data_dir):
    """Flask 测试应用（TESTING 模式，关闭限流）。"""
    from app import create_app
    from app.extensions import cache

    application = create_app()
    application.config.update(TESTING=True)
    with application.app_context():
        cache.clear()
    logger.info("Flask 测试应用已创建")
    return application


@pytest.fixture(scope="class")
def client(app):
    """已登录/可登录的测试客户端，在同一个测试类内保持会话。"""
    return app.test_client()


@pytest.fixture(scope="class")
def anon(app):
    """匿名测试客户端（独立 Cookie，用于公开页面读取）。"""
    return app.test_client()


@pytest.fixture(scope="class")
def ctx(app, client, anon, data_dir) -> SimpleNamespace:
    """测试类共享的场景上下文（跨测试方法保存状态）。

    pytest 会为每个测试方法创建新的类实例，因此跨方法共享的数据不能放在
    ``self`` 上，而应挂在这个类级 fixture 返回的对象上。
    """
    return SimpleNamespace(
        app=app,
        client=client,
        anon=anon,
        data_dir=data_dir,
        notes={},
    )
