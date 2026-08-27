"""功能开关（Feature Flags，#90）：注册表 + 运行时可切换状态

管理员在 /admin/features 用滑块开关决定启用哪些功能，启用的功能在
/count 数据汇总页呈现；被停用的功能在路由层直接 404。

- 注册表 FEATURES 定义全部可控功能与展示信息（顺序即页面展示顺序）；
- 默认值来自 config.json：新增功能读 features 段，历史功能沿用各自
  原有配置段（如 latex_render.enabled、avatar.enabled）；
- 运行时状态整体持久化在存储后端 KV 键 feature_flags（file 后端即
  feature_flags.json）。memory 后端（无服务器冷启动）不持久，重启后
  回退到 config.json 默认值；
- 读取走进程内缓存（TTL 5 秒，与 store.reload_users 的周期重载模式
  一致），多实例部署下各实例最多延迟一个 TTL 收敛；写入为整值覆盖，
  无需跨实例读改写锁。
"""
import threading
import time
from functools import wraps

from flask import abort

from . import config
from .logger import create_logger
from .storage import StorageError, storage

logger = create_logger("feature_flags")

FLAGS_KEY = "feature_flags"

# ---------- 功能注册表 ----------
# label 取 i18n 键 feature_<key>；icon 为 FontAwesome 类名
FEATURES = [
    {"key": "world_notes", "icon": "fa-globe"},         # 公开笔记（/world 与 /<id> 短链）
    {"key": "benben", "icon": "fa-sticky-note"},        # 犇犇动态
    {"key": "share_links", "icon": "fa-share-nodes"},   # 分享链接
    {"key": "open_register", "icon": "fa-user-plus"},   # 开放注册
    {"key": "note_refs", "icon": "fa-link"},            # 笔记快捷引用（#87）
    {"key": "note_tags", "icon": "fa-tags"},            # 笔记标签（编辑页底部标签栏 + 列表页筛选）
    {"key": "note_folders", "icon": "fa-folder"},       # 笔记文件夹（单归属归类 + 列表页筛选）
    {"key": "note_pins", "icon": "fa-thumbtack"},       # 笔记置顶（列表页图钉开关，置顶浮前）
    {"key": "heading_anchors", "icon": "fa-anchor"},    # Markdown 标题锚点（slug id + 页内 #链接 + 深链定位）
    {"key": "note_images", "icon": "fa-image"},         # 笔记图床（编辑器粘贴/拖拽上传 + /image/<u>/<id> 服务）
    {"key": "note_attachments", "icon": "fa-paperclip"}, # 笔记附件（编辑器上传 + /attachment/<u>/<id> 服务）
    {"key": "comments", "icon": "fa-comments"},         # 评论系统（笔记/分享页面评论功能）
    {"key": "latex_render", "icon": "fa-square-root-variable"},
    {"key": "code_highlight", "icon": "fa-code"},
    {"key": "avatar", "icon": "fa-user"},
    {"key": "orgs", "icon": "fa-users"},                # 组织/团队协作
    {"key": "image_upload", "icon": "fa-image"},         # 图片上传（粘贴/拖拽自动上传为压缩 GIF）
]
FEATURE_KEYS = [f["key"] for f in FEATURES]

# 历史功能的默认值沿用各自原有配置段（config.json），行为与旧版一致
_HERITAGE_DEFAULTS = {
    "note_refs": lambda: config.NOTE_REFS_ENABLED,
    "latex_render": lambda: config.LATEX_RENDER_ENABLED,
    "code_highlight": lambda: config.CODE_HIGHLIGHT_ENABLED,
    "avatar": lambda: config.AVATAR_ENABLED,
    "note_images": lambda: config.IMAGES_ENABLED,
    "note_attachments": lambda: config.ATTACHMENTS_ENABLED,
    "comments": lambda: config.COMMENTS_ENABLED,
}
_FEATURES_CFG = config.config.get("features", {})


def _default_of(key: str) -> bool:
    if key in _HERITAGE_DEFAULTS:
        try:
            return bool(_HERITAGE_DEFAULTS[key]())
        except Exception:
            return True
    return bool(_FEATURES_CFG.get(key, True))


# ---------- 运行时状态（进程内缓存 + 存储后端持久化） ----------
_state: dict = {}
_state_loaded = False
_last_reload = 0.0
_RELOAD_INTERVAL = 5.0
_guard = threading.Lock()


def _load_state(force: bool = False) -> None:
    """从存储后端加载功能状态（TTL 节流；读失败时保留现状，首次失败回退默认值）"""
    global _state, _state_loaded, _last_reload
    now = time.time()
    with _guard:
        if not force and _state_loaded and now - _last_reload < _RELOAD_INTERVAL:
            return
        try:
            stored = storage.get(FLAGS_KEY)
        except StorageError as e:
            logger.error(f"[错误] 读取功能开关失败: {e}")
            _last_reload = now
            return
        merged = {key: _default_of(key) for key in FEATURE_KEYS}
        if isinstance(stored, dict):
            # 只接受注册表内的键，注册表外的历史残留忽略
            for key in FEATURE_KEYS:
                if key in stored:
                    merged[key] = bool(stored[key])
        _state = merged
        _state_loaded = True
        _last_reload = now


def feature_enabled(key: str) -> bool:
    """查询功能是否启用（未注册的键一律返回 False，便于发现拼写错误）"""
    if key not in FEATURE_KEYS:
        return False
    _load_state()
    with _guard:
        return _state.get(key, _default_of(key))


def get_all_features() -> list:
    """返回全部功能的展示信息（key/icon/enabled），供 /count 与管理页使用"""
    _load_state()
    with _guard:
        state = dict(_state)
    return [dict(f, enabled=state.get(f["key"], _default_of(f["key"]))) for f in FEATURES]


def set_flags(new_state: dict) -> bool:
    """整体写入功能状态（仅接受注册表内的键），成功后立即刷新进程内缓存"""
    clean = {key: bool(new_state.get(key, _default_of(key))) for key in FEATURE_KEYS}
    try:
        if not storage.set(FLAGS_KEY, clean):
            logger.error("[错误] 写入功能开关失败：存储后端返回失败")
            return False
    except StorageError as e:
        logger.error(f"[错误] 写入功能开关失败: {e}")
        return False
    _load_state(force=True)
    return True


def is_admin(username) -> bool:
    """功能开关管理员：config.json 的 admin_users + 环境变量 RUSIN_ADMIN（逗号分隔）"""
    return bool(username) and username in config.ADMIN_USERS


def require_feature(key: str):
    """视图装饰器：功能被停用时返回 404（不泄漏功能存在）。

    必须放在 @bp.route 之后、@cache.cached / @limiter.limit 之前，
    保证停用判断先于缓存命中与限流计数。
    """
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if not feature_enabled(key):
                abort(404)
            return fn(*args, **kwargs)
        return wrapper
    return decorator
