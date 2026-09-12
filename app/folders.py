"""笔记文件夹存储：内存缓存 + 统一存储层（file / memory / upstash / postgres）

文件夹归属与笔记本体分离，存通用 KV 键 note_folders（file 后端即
note_folders.json）：{username: {note_id: folder_path}}。每篇笔记至多归属
一个文件夹，空/缺省即未归类。文件夹路径用 / 分隔层级（如 工作/项目A/需求），
列表页据此渲染树状图。文件夹是派生概念：只要还有笔记引用即存在，把笔记全部
移走后文件夹自然消失，无需单独的管理入口。

写路径约定与 store.py / tags.py 一致：持 threading.Lock（进程内）+
storage.lock（跨进程/跨实例）的块内重读合并内存缓存，持久化在锁外执行。
"""
import re
import threading

from .config import MAX_FOLDER_DEPTH, MAX_FOLDER_NAME_LENGTH
from .logger import create_logger
from .storage import StorageError, storage

logger = create_logger("folders")

# 键名（与存储后端的 KV 布局一一对应；file 后端映射 note_folders.json）
K_FOLDERS = "note_folders"

# 合法文件夹单段字符：字母 / 数字 / 下划线 / 连字符 / 中日韩文字（\w 在
# Python3 的 str 模式下默认按 Unicode 匹配，已覆盖中日韩）；层级由 / 分隔
_FOLDER_SEGMENT_RE = re.compile(r'[\w\-]+')

# ---------- 内存缓存 ----------
note_folders = {}  # 格式: {username: {note_id: folder_name}}
folders_lock = threading.Lock()


def _persist(data: dict) -> bool:
    """将整个归属表写回存储后端（锁外调用）"""
    try:
        return storage.set(K_FOLDERS, data)
    except StorageError as e:
        logger.error(f"[错误] 存储写入 {K_FOLDERS} 失败: {e}")
        return False


def _read() -> dict | None:
    try:
        value = storage.get(K_FOLDERS)
    except StorageError as e:
        logger.error(f"[错误] 存储读取 {K_FOLDERS} 失败: {e}")
        return None
    return value if isinstance(value, dict) else None


def _read_merge_locked():
    """存储锁保护下重读最新数据并合并进内存缓存（多实例同步）。
    须已持有 folders_lock 与 storage.lock(K_FOLDERS)。"""
    data = _read()
    if isinstance(data, dict):
        note_folders.clear()
        note_folders.update(data)


def load_note_folders():
    with folders_lock:
        data = _read()
        if isinstance(data, dict):
            note_folders.clear()
            note_folders.update(data)


# ---------- 解析与校验 ----------
def valid_folder(name: str) -> bool:
    """文件夹路径是否合法：长度、层级数、每段字符集，且无空段/首尾斜杠。"""
    if not name or len(name) > MAX_FOLDER_NAME_LENGTH:
        return False
    parts = name.split("/")
    if len(parts) > MAX_FOLDER_DEPTH:
        return False
    return all(parts) and all(_FOLDER_SEGMENT_RE.fullmatch(p) for p in parts)


def parse_folder_input(raw: str) -> str:
    """规范化用户输入的文件夹路径：去各段首尾空白与斜杠、合并重复斜杠，再校验
    字符集/长度/层级，非法返回空串（等价于未归类）。"""
    parts = [p.strip() for p in (raw or "").split("/")]
    name = "/".join(p for p in parts if p)
    return name if valid_folder(name) else ""


def folder_in_subtree(folder: str, target: str) -> bool:
    """folder 是否等于 target 或位于其子树内（target 为空表示不过滤）。"""
    if not target:
        return True
    return folder == target or folder.startswith(target + "/")


# ---------- 读写接口 ----------
def get_user_note_folders(username: str) -> dict:
    """返回该用户全部归属的拷贝 {note_id: folder_name}"""
    with folders_lock:
        user = note_folders.get(username)
        if not isinstance(user, dict):
            return {}
        return {nid: f for nid, f in user.items() if isinstance(f, str)}


def get_note_folder(username: str, note_id: str) -> str:
    """返回单篇笔记的文件夹名，未归类或读取失败返回空串"""
    with folders_lock:
        user = note_folders.get(username)
        if not isinstance(user, dict):
            return ""
        folder = user.get(note_id)
        return folder if isinstance(folder, str) else ""


def set_note_folder(username: str, note_id: str, folder: str) -> bool:
    """跨实例安全写入单篇笔记的文件夹归属；空串即取消归类。"""
    clean = parse_folder_input(folder)
    try:
        with folders_lock:
            with storage.lock(K_FOLDERS):
                _read_merge_locked()
                user = note_folders.get(username)
                if clean:
                    if not isinstance(user, dict):
                        user = {}
                        note_folders[username] = user
                    user[note_id] = clean
                elif isinstance(user, dict):
                    user.pop(note_id, None)
                    if not user:
                        note_folders.pop(username, None)
                return _persist(note_folders)
    except StorageError as e:
        logger.error(f"[错误] 写入笔记文件夹 {username}/{note_id} 失败: {e}")
        return False


def delete_note_folder(username: str, note_id: str) -> bool:
    """删除单篇笔记的归属条目（笔记删除时调用，条目不存在也算成功）"""
    return set_note_folder(username, note_id, "")


def list_user_folders(username: str, note_ids=None) -> list:
    """统计该用户的文件夹列表 [(folder, count), ...]，按 count 降序、名称升序。
    note_ids 给定时只统计仍存在的笔记（过滤已删除笔记的残留条目）。"""
    counts: dict[str, int] = {}
    for nid, folder in get_user_note_folders(username).items():
        if not folder:
            continue
        if note_ids is not None and nid not in note_ids:
            continue
        counts[folder] = counts.get(folder, 0) + 1
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))


def build_folder_tree(items) -> dict:
    """把已排序的笔记条目构建成文件夹树，供列表页渲染树状图。

    items: [{"id": ..., "folder": "工作/项目A", ...}, ...]，保持传入顺序
    （通常为置顶优先、组内修改时间倒序）。返回
    {"children": [...], "notes": [...], "total": N}：
    - children: 同层文件夹节点，按名称升序；节点为
      {"name", "path", "count", "notes", "children"}，其中 count 为该子树
      （含自身）的笔记总数，path 为完整路径（如 工作/项目A）
    - notes: 未归类（folder 为空）的条目，保持原顺序
    - total: 全部条目数（含未归类）
    祖先节点即使没有直属笔记也会出现，保证层级完整。"""
    root = {"children": {}, "notes": [], "total": 0}
    for item in items:
        root["total"] += 1
        folder = (item.get("folder") or "").strip("/")
        if not folder:
            root["notes"].append(item)
            continue
        node = root
        for seg in folder.split("/"):
            if not seg:
                continue
            child = node["children"].get(seg)
            if child is None:
                child = {"children": {}, "notes": [], "total": 0}
                node["children"][seg] = child
            child["total"] += 1
            node = child
        node["notes"].append(item)

    def finalize(node, name, path):
        children = [
            finalize(node["children"][child_name], child_name,
                     f"{path}/{child_name}" if path else child_name)
            for child_name in sorted(node["children"])
        ]
        return {"name": name, "path": path, "count": node["total"],
                "notes": node["notes"], "children": children}

    return {
        "children": [finalize(root["children"][n], n, n) for n in sorted(root["children"])],
        "notes": root["notes"],
        "total": root["total"],
    }


load_note_folders()
