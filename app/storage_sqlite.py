"""SQLite + JSON 统一存储后端（本地/VPS 默认后端）

设计目标——「SQLite 负责快速查找，JSON 负责保存内容」：

- **索引库**：``<DATA_DIR>/index.db``（SQLite，WAL 模式）保存笔记、通用 KV、
  图床、附件的元数据（标题 / 大小 / 修改时间 / 所有者等），用于快速列表、
  排序、检索、统计，无需读取内容文件；
- **内容文件**：具体内容以 JSON 落盘到 ``<DATA_DIR>/``：
  - 笔记：``notes/<user>/<id>.json`` → ``{"content", "created_at", "updated_at"}``
  - 全局集合（用户 / 会话 / 分享 / 犇犇 / 评论 / 标签 / 文件夹 / 置顶 / 待办 /
    组织 / 功能开关 …）：``<name>.json``（键布局见 ``storage.KV_FILE_MAP``）
  - 图床 / 附件保持二进制文件：``images/<user>/<id>``、``attachments/<user>/<id>``
    （附件元数据另存 ``<id>.meta.json``），与旧版 file 后端磁盘布局一致。

因此本后端复用 :class:`~app.storage.FileBackend` 的文件读写与跨进程文件锁，
只在每次写操作后同步维护 SQLite 索引，并把读取路径中可走索引的操作
（列表 / 修改时间 / 大小 / 标题检索 / 统计）改为查询索引。

无服务器平台（Vercel / Lambda）没有持久磁盘，仍应使用 upstash / postgres /
memory 后端；本后端只在本地 / VPS / 挂载持久卷的场景启用。
"""
import hashlib
import json
import os
import shutil
import sqlite3
import threading
import time

from . import config
from .config import data_path
from .storage import (
    KV_FILE_MAP,
    _RAW_TEXT_KEYS,
    FileBackend,
    StorageError,
    _json_dumps,
    _json_loads,
    title_from_content,
)

# 旧版（纯 JSON）数据根目录中的运行数据项：默认数据目录切到 data/ 时，
# 若检测到这些旧路径且 data/ 中还没有，则一次性迁移过去（见
# migrate_legacy_data_root）。
LEGACY_ROOT_ITEMS = (
    "notes", "images", "attachments", "plugins", "log",
    "users.json", "sessions.json", "shares.json", "benben.json",
    "comments.json", "note_tags.json", "note_folders.json", "note_pins.json",
    "note_titles.json", "todos.json", "feature_flags.json", "orgs.json",
    "org_members.json", "org_invites.json", "org_join_requests.json",
    ".secret_key",
)

_SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS kv_index (
        key        TEXT PRIMARY KEY,
        path       TEXT NOT NULL,
        updated_at REAL NOT NULL,
        size       INTEGER NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS notes_index (
        username   TEXT NOT NULL,
        note_id    TEXT NOT NULL,
        title      TEXT NOT NULL DEFAULT '',
        size       INTEGER NOT NULL DEFAULT 0,
        mtime      REAL NOT NULL,
        created_at REAL NOT NULL,
        PRIMARY KEY (username, note_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_notes_user_mtime ON notes_index (username, mtime DESC)",
    """
    CREATE TABLE IF NOT EXISTS images_index (
        username TEXT NOT NULL,
        image_id TEXT NOT NULL,
        size     INTEGER NOT NULL DEFAULT 0,
        mtime    REAL NOT NULL,
        PRIMARY KEY (username, image_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS attachments_index (
        username      TEXT NOT NULL,
        attachment_id TEXT NOT NULL,
        filename      TEXT NOT NULL DEFAULT '',
        content_type  TEXT NOT NULL DEFAULT 'application/octet-stream',
        size          INTEGER NOT NULL DEFAULT 0,
        mtime         REAL NOT NULL,
        PRIMARY KEY (username, attachment_id)
    )
    """,
)


def _safe_key_filename(key: str) -> str:
    """把任意 KV 键映射为安全的文件名（保留可读前缀 + 哈希后缀防碰撞）"""
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]
    readable = "".join(c if (c.isalnum() or c in "._-") else "_" for c in key)[:48]
    return f"{readable}.{digest}.json"


def _content_size(content: str) -> int:
    return len(content.encode("utf-8"))


def migrate_legacy_data_root() -> int:
    """把旧版根目录运行数据迁移到默认的 ``data/`` 目录（一次性、尽力而为）。

    仅在未显式设置 ``RUSIN_DATA_DIR``、数据目录为默认 ``data`` 且旧数据存在
    时执行；逐项复制（不覆盖 data/ 中已有内容），返回迁移项数量。
    """
    if os.environ.get("RUSIN_DATA_DIR", "").strip():
        return 0
    if os.path.abspath(config.DATA_DIR) == os.path.abspath("."):
        return 0  # 仍在使用旧目录，无需迁移
    root = os.getcwd()
    moved = 0
    for name in LEGACY_ROOT_ITEMS:
        src = os.path.join(root, name)
        dst = data_path(name)
        if not os.path.exists(src) or os.path.exists(dst):
            continue
        try:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            if os.path.isdir(src):
                shutil.copytree(src, dst)
            else:
                shutil.copy2(src, dst)
            moved += 1
        except (OSError, shutil.Error):
            continue
    return moved


class SqliteBackend(FileBackend):
    """SQLite 索引 + JSON 内容：统一数据接口的本地默认实现。"""

    kind = "sqlite"
    persistent = True

    def __init__(self):
        self._guard = threading.RLock()
        self._conn = None
        self._conn_path = None
        self._schema_ready_path = None
        # 启动即建表并完成旧版 .txt 笔记导入，保证 read_note 立即可见历史内容
        self._db()

    # ---------- SQLite 连接 / 表结构 ----------
    def _db_path(self) -> str:
        return data_path("index.db")

    def _db(self):
        path = self._db_path()
        with self._guard:
            if self._conn is not None and self._conn_path == path:
                return self._conn
            if self._conn is not None:
                try:
                    self._conn.close()
                except sqlite3.Error:
                    pass
            os.makedirs(os.path.dirname(path), exist_ok=True)
            existed = os.path.exists(path)
            try:
                conn = sqlite3.connect(path, timeout=15.0, check_same_thread=False)
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA synchronous=NORMAL")
                conn.execute("PRAGMA busy_timeout=15000")
            except sqlite3.Error as e:
                raise StorageError(f"SQLite 打开失败: {e}")
            self._conn = conn
            self._conn_path = path
            if self._schema_ready_path != path:
                self._create_schema(conn)
                self._schema_ready_path = path
                if not existed:
                    self._import_legacy_notes()
            return conn

    def _create_schema(self, conn) -> None:
        try:
            with conn:
                for ddl in _SCHEMA:
                    conn.execute(ddl)
        except sqlite3.Error as e:
            raise StorageError(f"SQLite 初始化失败: {e}")

    def _execute(self, sql: str, params=(), fetch: str | None = None):
        """执行 SQL；fetch 为 one/all 时返回查询结果，否则返回受影响行数。"""
        with self._guard:
            conn = self._db()
            try:
                cur = conn.execute(sql, params)
                if fetch == "one":
                    return cur.fetchone()
                if fetch == "all":
                    return cur.fetchall()
                conn.commit()
                return cur.rowcount
            except sqlite3.Error as e:
                try:
                    conn.rollback()
                except sqlite3.Error:
                    pass
                raise StorageError(f"SQLite 操作失败: {e}")

    # ---------- 旧版 .txt 笔记导入 ----------
    def _import_legacy_notes(self) -> None:
        """首次创建索引时，把同目录下旧版 notes/<user>/<id>.txt 导入为 JSON。"""
        base = data_path("notes")
        if not os.path.isdir(base):
            return
        try:
            usernames = os.listdir(base)
        except OSError:
            return
        for username in usernames:
            user_dir = os.path.join(base, username)
            if not os.path.isdir(user_dir):
                continue
            try:
                filenames = os.listdir(user_dir)
            except OSError:
                continue
            for fname in filenames:
                if not fname.endswith(".txt"):
                    continue
                note_id = fname[:-4]
                if not note_id:
                    continue
                txt_path = os.path.join(user_dir, fname)
                json_path = os.path.join(user_dir, f"{note_id}.json")
                if os.path.exists(json_path):
                    continue
                try:
                    with open(txt_path, "r", encoding="utf-8") as f:
                        content = f.read()
                except (OSError, UnicodeDecodeError):
                    continue
                try:
                    self.write_note(username, note_id, content)
                    os.remove(txt_path)
                except (StorageError, OSError):
                    continue

    # ---------- 通用 KV（内容 JSON + kv_index 索引） ----------
    def _kv_path(self, key: str) -> str:
        rel = KV_FILE_MAP.get(key)
        if rel is not None:
            return data_path(rel)
        return data_path("kv", _safe_key_filename(key))

    def set(self, key: str, value) -> bool:
        path = self._kv_path(key)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        raw = value if key in _RAW_TEXT_KEYS else _json_dumps(value)
        temp_path = f"{path}.{os.getpid()}.tmp"
        try:
            with open(temp_path, "w", encoding="utf-8") as f:
                f.write(raw)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp_path, path)
        except (IOError, OSError):
            try:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
            except OSError:
                pass
            return False
        try:
            self._execute(
                "INSERT INTO kv_index (key, path, updated_at, size) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET path = excluded.path, "
                "updated_at = excluded.updated_at, size = excluded.size",
                (key, path, time.time(), len(raw.encode("utf-8"))),
            )
        except StorageError:
            return False
        return True

    def delete(self, key: str) -> bool:
        path = self._kv_path(key)
        ok = True
        try:
            if os.path.exists(path):
                os.remove(path)
        except OSError:
            ok = False
        try:
            self._execute("DELETE FROM kv_index WHERE key = ?", (key,))
        except StorageError:
            ok = False
        return ok

    def list_keys(self, prefix: str) -> list:
        keys = set()
        escaped = prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        try:
            rows = self._execute(
                "SELECT key FROM kv_index WHERE key LIKE ? ESCAPE '\\'",
                (escaped + "%",), fetch="all")
            keys.update(r[0] for r in rows)
        except StorageError:
            pass
        # 兼容索引建立前就已落盘的 mapped 键
        for key in KV_FILE_MAP:
            if key.startswith(prefix) and os.path.exists(self._kv_path(key)):
                keys.add(key)
        return sorted(keys)

    def get(self, key: str):
        path = self._kv_path(key)
        if not os.path.exists(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = f.read()
        except (IOError, OSError):
            return None
        if key in _RAW_TEXT_KEYS:
            return raw
        return _json_loads(raw)

    # ---------- 笔记：JSON 内容 + notes_index 索引 ----------
    def _note_path(self, username: str, note_id: str) -> str:
        return data_path("notes", username, f"{note_id}.json")

    def read_note(self, username: str, note_id: str) -> str | None:
        self._db()  # 数据目录切换后确保索引/导入已就绪
        path = self._note_path(username, note_id)
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except FileNotFoundError:
            return None
        except (IOError, OSError, ValueError):
            return None
        if isinstance(data, dict):
            content = data.get("content")
            return content if isinstance(content, str) else None
        return data if isinstance(data, str) else None

    def write_note(self, username: str, note_id: str, content: str) -> bool:
        path = self._note_path(username, note_id)
        if content == "":
            try:
                if os.path.exists(path):
                    os.remove(path)
            except FileNotFoundError:
                pass
            except OSError:
                return False
            try:
                self._execute(
                    "DELETE FROM notes_index WHERE username = ? AND note_id = ?",
                    (username, note_id))
            except StorageError:
                return False
            return True

        now = time.time()
        created = self._note_created_at(username, note_id) or now
        os.makedirs(os.path.dirname(path), exist_ok=True)
        payload = {"content": content, "created_at": created, "updated_at": now}
        temp_path = f"{path}.{os.getpid()}.tmp"
        try:
            with open(temp_path, "w", encoding="utf-8") as f:
                f.write(_json_dumps(payload))
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp_path, path)
        except (IOError, OSError):
            try:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
            except OSError:
                pass
            return False
        try:
            self._execute(
                "INSERT INTO notes_index (username, note_id, title, size, mtime, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(username, note_id) DO UPDATE SET "
                "title = excluded.title, size = excluded.size, mtime = excluded.mtime",
                (username, note_id, title_from_content(content),
                 _content_size(content), now, created),
            )
        except StorageError:
            return False
        return True

    def _note_created_at(self, username: str, note_id: str):
        try:
            row = self._execute(
                "SELECT created_at FROM notes_index WHERE username = ? AND note_id = ?",
                (username, note_id), fetch="one")
        except StorageError:
            return None
        return row[0] if row and isinstance(row[0], (int, float)) else None

    def note_mtime(self, username: str, note_id: str) -> float | None:
        try:
            row = self._execute(
                "SELECT mtime FROM notes_index WHERE username = ? AND note_id = ?",
                (username, note_id), fetch="one")
        except StorageError:
            return None
        if row is not None:
            return row[0]
        return self._file_mtime(self._note_path(username, note_id))

    def note_size(self, username: str, note_id: str) -> int | None:
        try:
            row = self._execute(
                "SELECT size FROM notes_index WHERE username = ? AND note_id = ?",
                (username, note_id), fetch="one")
        except StorageError:
            return None
        if row is not None:
            return row[0]
        return self._file_size(self._note_path(username, note_id))

    def note_title(self, username: str, note_id: str) -> str:
        try:
            row = self._execute(
                "SELECT title FROM notes_index WHERE username = ? AND note_id = ?",
                (username, note_id), fetch="one")
        except StorageError:
            row = None
        if row is not None:
            return row[0] or ""
        return super().note_title(username, note_id)

    def list_notes(self, username: str) -> list:
        rows = self._execute(
            "SELECT note_id FROM notes_index WHERE username = ? ORDER BY mtime DESC",
            (username,), fetch="all")
        return [r[0] for r in rows]

    def iter_all_notes(self):
        rows = self._execute("SELECT username, note_id FROM notes_index", fetch="all")
        for username, note_id in rows:
            yield username, note_id

    # ---------- 统一的索引化查询接口 ----------
    def list_notes_detailed(self, username: str) -> list:
        rows = self._execute(
            "SELECT note_id, title, size, mtime FROM notes_index "
            "WHERE username = ? ORDER BY mtime DESC",
            (username,), fetch="all")
        return [{"id": r[0], "title": r[1] or "", "size": r[2], "mtime": r[3]}
                for r in rows]

    def search_notes(self, username: str, query: str = "",
                     limit: int = 8, scan_limit: int = 100) -> list:
        rows = self._execute(
            "SELECT note_id, title, mtime FROM notes_index "
            "WHERE username = ? ORDER BY mtime DESC LIMIT ?",
            (username, max(0, scan_limit)), fetch="all")
        needle = (query or "").strip().lower()
        results = []
        for note_id, title, mtime in rows:
            title = title or ""
            if needle and needle not in note_id.lower() and needle not in title.lower():
                continue
            results.append({"id": note_id, "title": title, "mtime": mtime or 0})
            if len(results) >= limit:
                break
        return results

    def notes_stats(self) -> tuple:
        rows = self._execute(
            "SELECT CASE WHEN username = 'public' THEN 1 ELSE 0 END AS is_public, "
            "COUNT(*), COALESCE(SUM(size), 0) FROM notes_index GROUP BY is_public",
            fetch="all")
        public_count = public_size = private_count = private_size = 0
        for is_public, count, size in rows:
            if is_public:
                public_count, public_size = count, int(size or 0)
            else:
                private_count, private_size = count, int(size or 0)
        return public_count, public_size, private_count, private_size

    # ---------- 图床：二进制文件 + images_index 索引 ----------
    def _image_path(self, username: str, image_id: str) -> str:
        return data_path("images", username, image_id)

    def write_image(self, username: str, image_id: str, data: bytes) -> bool:
        path = self._image_path(username, image_id)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        temp_path = f"{path}.{os.getpid()}.tmp"
        try:
            with open(temp_path, "wb") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp_path, path)
        except (IOError, OSError):
            try:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
            except OSError:
                pass
            return False
        try:
            self._execute(
                "INSERT INTO images_index (username, image_id, size, mtime) "
                "VALUES (?, ?, ?, ?) ON CONFLICT(username, image_id) DO UPDATE SET "
                "size = excluded.size, mtime = excluded.mtime",
                (username, image_id, len(data), time.time()))
        except StorageError:
            return False
        return True

    def read_image(self, username: str, image_id: str) -> bytes | None:
        try:
            with open(self._image_path(username, image_id), "rb") as f:
                return f.read()
        except (FileNotFoundError, IOError, OSError):
            return None

    def delete_image(self, username: str, image_id: str) -> bool:
        path = self._image_path(username, image_id)
        if os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                return False
        try:
            self._execute(
                "DELETE FROM images_index WHERE username = ? AND image_id = ?",
                (username, image_id))
        except StorageError:
            return False
        return True

    def image_mtime(self, username: str, image_id: str) -> float | None:
        try:
            row = self._execute(
                "SELECT mtime FROM images_index WHERE username = ? AND image_id = ?",
                (username, image_id), fetch="one")
        except StorageError:
            return None
        if row is not None:
            return row[0]
        return self._file_mtime(self._image_path(username, image_id))

    def image_size(self, username: str, image_id: str) -> int | None:
        try:
            row = self._execute(
                "SELECT size FROM images_index WHERE username = ? AND image_id = ?",
                (username, image_id), fetch="one")
        except StorageError:
            return None
        if row is not None:
            return row[0]
        return self._file_size(self._image_path(username, image_id))

    def list_images(self, username: str) -> list:
        rows = self._execute(
            "SELECT image_id FROM images_index WHERE username = ? ORDER BY image_id",
            (username,), fetch="all")
        return [r[0] for r in rows]

    def image_usage(self, username: str) -> int:
        row = self._execute(
            "SELECT COALESCE(SUM(size), 0) FROM images_index WHERE username = ?",
            (username,), fetch="one")
        return int(row[0] or 0) if row else 0

    # ---------- 附件：二进制 + 元数据 JSON + attachments_index 索引 ----------
    def _attachment_path(self, username: str, attachment_id: str) -> str:
        return data_path("attachments", username, attachment_id)

    def _attachment_meta_path(self, username: str, attachment_id: str) -> str:
        return data_path("attachments", username, f"{attachment_id}.meta.json")

    def write_attachment(self, username: str, attachment_id: str, data: bytes,
                         filename: str = "", content_type: str = "application/octet-stream") -> bool:
        path = self._attachment_path(username, attachment_id)
        meta_path = self._attachment_meta_path(username, attachment_id)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        now = time.time()
        temp_path = f"{path}.{os.getpid()}.tmp"
        try:
            with open(temp_path, "wb") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp_path, path)
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump({"n": filename, "c": content_type, "t": now, "s": len(data)},
                          f, ensure_ascii=False)
        except (IOError, OSError):
            try:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
            except OSError:
                pass
            return False
        try:
            self._execute(
                "INSERT INTO attachments_index "
                "(username, attachment_id, filename, content_type, size, mtime) "
                "VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(username, attachment_id) DO UPDATE SET "
                "filename = excluded.filename, content_type = excluded.content_type, "
                "size = excluded.size, mtime = excluded.mtime",
                (username, attachment_id, filename, content_type, len(data), now))
        except StorageError:
            return False
        return True

    def read_attachment(self, username: str, attachment_id: str) -> bytes | None:
        try:
            with open(self._attachment_path(username, attachment_id), "rb") as f:
                return f.read()
        except (FileNotFoundError, IOError, OSError):
            return None

    def read_attachment_meta(self, username: str, attachment_id: str) -> dict | None:
        try:
            row = self._execute(
                "SELECT filename, content_type, size, mtime FROM attachments_index "
                "WHERE username = ? AND attachment_id = ?",
                (username, attachment_id), fetch="one")
        except StorageError:
            row = None
        if row is not None:
            return {
                "filename": row[0] or attachment_id,
                "content_type": row[1] or "application/octet-stream",
                "size": row[2],
                "mtime": row[3],
            }
        return super().read_attachment_meta(username, attachment_id)

    def delete_attachment(self, username: str, attachment_id: str) -> bool:
        path = self._attachment_path(username, attachment_id)
        meta_path = self._attachment_meta_path(username, attachment_id)
        try:
            if os.path.exists(path):
                os.remove(path)
            if os.path.exists(meta_path):
                os.remove(meta_path)
        except OSError:
            return False
        try:
            self._execute(
                "DELETE FROM attachments_index WHERE username = ? AND attachment_id = ?",
                (username, attachment_id))
        except StorageError:
            return False
        return True

    def attachment_mtime(self, username: str, attachment_id: str) -> float | None:
        try:
            row = self._execute(
                "SELECT mtime FROM attachments_index WHERE username = ? AND attachment_id = ?",
                (username, attachment_id), fetch="one")
        except StorageError:
            return None
        if row is not None:
            return row[0]
        return self._file_mtime(self._attachment_path(username, attachment_id))

    def attachment_size(self, username: str, attachment_id: str) -> int | None:
        try:
            row = self._execute(
                "SELECT size FROM attachments_index WHERE username = ? AND attachment_id = ?",
                (username, attachment_id), fetch="one")
        except StorageError:
            return None
        if row is not None:
            return row[0]
        return self._file_size(self._attachment_path(username, attachment_id))

    def list_attachments(self, username: str) -> list:
        rows = self._execute(
            "SELECT attachment_id FROM attachments_index WHERE username = ? "
            "ORDER BY attachment_id",
            (username,), fetch="all")
        return [r[0] for r in rows]

    def attachment_usage(self, username: str) -> int:
        row = self._execute(
            "SELECT COALESCE(SUM(size), 0) FROM attachments_index WHERE username = ?",
            (username,), fetch="one")
        return int(row[0] or 0) if row else 0

    # ---------- 内部辅助 ----------
    @staticmethod
    def _file_mtime(path: str):
        try:
            return os.path.getmtime(path)
        except (IOError, OSError):
            return None

    @staticmethod
    def _file_size(path: str):
        try:
            return os.path.getsize(path)
        except (IOError, OSError):
            return None
