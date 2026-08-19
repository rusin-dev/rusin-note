"""统一存储层：file / memory / upstash / postgres 四种可插拔后端

为无服务器部署（Vercel / AWS Lambda / Netlify 等）提供不依赖本机磁盘的持久化：

- file 后端（默认，本地/VPS）：保持原有 JSON 文件落盘布局不变；
- upstash 后端：Upstash Redis / Vercel KV 的 REST API（环境变量
  KV_REST_API_URL + KV_REST_API_TOKEN），多实例共享同一份数据，纯 HTTPS 请求，
  不依赖任何驱动，所有支持 Python 的无服务器平台通用；
- postgres 后端：Neon / 任意 PostgreSQL（环境变量 DATABASE_URL，psycopg 驱动），
  Vercel Marketplace 绑定 Neon 后自动注入连接串，零配置切换；
- memory 后端：纯内存，任何平台可用，数据随实例销毁（冷启动清空）。

选择优先级（RUSIN_STORAGE 显式指定 > KV 环境变量自动识别 > DATABASE_URL
自动识别 > 无服务器平台默认 memory > 本地默认 file）。
"""
import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from contextlib import contextmanager
from copy import deepcopy

from .config import SERVERLESS, data_path

try:
    import fcntl  # POSIX 跨进程文件锁
    _HAS_FCNTL = True
except ImportError:
    _HAS_FCNTL = False
    try:
        import msvcrt  # Windows 跨进程文件锁
    except ImportError:
        msvcrt = None

try:
    import psycopg  # postgres 后端（Neon），未安装时其余后端仍可用
    _HAS_PSYCOPG = True
except ImportError:
    psycopg = None
    _HAS_PSYCOPG = False


class StorageError(Exception):
    """后端读写失败（网络错误、超时、锁获取失败等）"""


# ---------- 通用 KV 键（值统一为 JSON 可序列化对象） ----------
# file 后端将它们映射为数据目录下的具体文件
KV_FILE_MAP = {
    "users.json": "users.json",
    "sessions.json": "sessions.json",
    "shares.json": "shares.json",
    "benben:posts": "benben.json",
    "secret_key": ".secret_key",
}
# .secret_key 以纯文本（非 JSON）存储，与旧版文件格式兼容
_RAW_TEXT_KEYS = {"secret_key"}

# 笔记键前缀：note:<username>:<note_id>
NOTE_KEY_PREFIX = "note:"


def _note_key(username: str, note_id: str) -> str:
    return f"{NOTE_KEY_PREFIX}{username}:{note_id}"


def parse_note_key(key: str):
    """解析笔记键为 (username, note_id)，非法键返回 None"""
    if not key.startswith(NOTE_KEY_PREFIX):
        return None
    rest = key[len(NOTE_KEY_PREFIX):]
    username, sep, note_id = rest.partition(":")
    if not sep or not username or not note_id:
        return None
    return username, note_id


def _json_dumps(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _json_loads(raw: str):
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        raise StorageError("存储数据损坏（非法 JSON）")


# ======================================================================
# 后端基类
# ======================================================================
class StorageBackend:
    kind = "abstract"
    persistent = False  # 是否跨实例/重启持久

    def get(self, key: str):
        raise NotImplementedError

    def set(self, key: str, value) -> bool:
        raise NotImplementedError

    def delete(self, key: str) -> bool:
        raise NotImplementedError

    def list_keys(self, prefix: str) -> list:
        raise NotImplementedError

    # ---------- 笔记专用（布局/格式各后端自洽） ----------
    def read_note(self, username: str, note_id: str) -> str | None:
        raise NotImplementedError

    def write_note(self, username: str, note_id: str, content: str) -> bool:
        """content 为空串时删除笔记，否则写入"""
        raise NotImplementedError

    def note_mtime(self, username: str, note_id: str) -> float | None:
        raise NotImplementedError

    def note_size(self, username: str, note_id: str) -> int | None:
        raise NotImplementedError

    def list_notes(self, username: str) -> list:
        raise NotImplementedError

    def iter_all_notes(self):
        """遍历全部笔记，产出 (username, note_id)"""
        raise NotImplementedError

    # ---------- 跨进程/跨实例互斥 ----------
    @contextmanager
    def lock(self, name: str):
        raise NotImplementedError


# ======================================================================
# file 后端：保持原有磁盘布局（users.json / sessions.json / shares.json /
# benben.json / notes/<user>/<id>.txt / .secret_key）
# ======================================================================
class FileBackend(StorageBackend):
    kind = "file"
    persistent = True

    def _kv_path(self, key: str) -> str | None:
        rel = KV_FILE_MAP.get(key)
        if rel is None:
            return None
        return data_path(rel)

    def get(self, key: str):
        path = self._kv_path(key)
        if path is None:
            return None
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

    def set(self, key: str, value) -> bool:
        path = self._kv_path(key)
        if path is None:
            return False
        raw = value if key in _RAW_TEXT_KEYS else _json_dumps(value)
        temp_path = f"{path}.{os.getpid()}.tmp"
        try:
            with open(temp_path, "w", encoding="utf-8") as f:
                f.write(raw)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp_path, path)
            return True
        except (IOError, OSError):
            try:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
            except OSError:
                pass
            return False

    def delete(self, key: str) -> bool:
        path = self._kv_path(key)
        if path is None:
            return False
        try:
            if os.path.exists(path):
                os.remove(path)
            return True
        except OSError:
            return False

    def list_keys(self, prefix: str) -> list:
        return [k for k in KV_FILE_MAP if k.startswith(prefix) and os.path.exists(self._kv_path(k))]

    # ---------- 笔记：notes/<user>/<id>.txt（纯文本，mtime 来自文件系统） ----------
    def _note_path(self, username: str, note_id: str) -> str:
        return data_path("notes", username, f"{note_id}.txt")

    def read_note(self, username: str, note_id: str) -> str | None:
        try:
            with open(self._note_path(username, note_id), "r", encoding="utf-8") as f:
                return f.read()
        except FileNotFoundError:
            return None
        except (IOError, OSError):
            return None

    def write_note(self, username: str, note_id: str, content: str) -> bool:
        path = self._note_path(username, note_id)
        if content == "":
            try:
                if os.path.exists(path):
                    os.remove(path)
                return True
            except FileNotFoundError:
                return True
            except OSError:
                return False
        os.makedirs(os.path.dirname(path), exist_ok=True)
        temp_path = f"{path}.{os.getpid()}.tmp"
        try:
            with open(temp_path, "w", encoding="utf-8") as f:
                f.write(content)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp_path, path)
            return True
        except (IOError, OSError):
            try:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
            except OSError:
                pass
            return False

    def note_mtime(self, username: str, note_id: str) -> float | None:
        try:
            return os.path.getmtime(self._note_path(username, note_id))
        except (IOError, OSError):
            return None

    def note_size(self, username: str, note_id: str) -> int | None:
        try:
            return os.path.getsize(self._note_path(username, note_id))
        except (IOError, OSError):
            return None

    def list_notes(self, username: str) -> list:
        user_dir = data_path("notes", username)
        if not os.path.isdir(user_dir):
            return []
        notes = []
        try:
            for fname in os.listdir(user_dir):
                if fname.endswith(".txt"):
                    notes.append(fname[:-4])
        except OSError:
            return []
        return notes

    def iter_all_notes(self):
        base = data_path("notes")
        if not os.path.isdir(base):
            return
        for username in os.listdir(base):
            user_dir = os.path.join(base, username)
            if not os.path.isdir(user_dir):
                continue
            for fname in os.listdir(user_dir):
                if fname.endswith(".txt"):
                    yield username, fname[:-4]

    # ---------- 锁：fcntl/msvcrt 跨进程文件锁 ----------
    @contextmanager
    def lock(self, name: str):
        lock_path = data_path(name.replace("/", "_").replace(":", "_") + ".lock")
        fh = open(lock_path, "a+b")
        try:
            if _HAS_FCNTL:
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            elif msvcrt is not None:
                fh.seek(0)
                if fh.read(1) == b"":
                    fh.write(b"\0")
                    fh.flush()
                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_LOCK, 1)
            yield
        finally:
            try:
                if _HAS_FCNTL:
                    fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
                elif msvcrt is not None:
                    fh.seek(0)
                    msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
            except Exception:
                pass
            fh.close()


# ======================================================================
# memory 后端：纯内存字典，任何平台可用（重启清空）
# ======================================================================
class MemoryBackend(StorageBackend):
    kind = "memory"
    persistent = False

    def __init__(self):
        self._data = {}
        self._guard = threading.Lock()
        self._locks: dict[str, threading.Lock] = {}

    def get(self, key: str):
        # 深拷贝：调用方（如 store._read_merge 的 clear/update）可能原地修改返回值，
        # 不能与内部存储共享同一对象引用
        with self._guard:
            value = self._data.get(key)
            return deepcopy(value) if value is not None else None

    def set(self, key: str, value) -> bool:
        with self._guard:
            self._data[key] = deepcopy(value)
        return True

    def delete(self, key: str) -> bool:
        with self._guard:
            return self._data.pop(key, None) is not None

    def list_keys(self, prefix: str) -> list:
        with self._guard:
            return [k for k in self._data if k.startswith(prefix)]

    # ---------- 笔记：note:<user>:<id> → {"content", "mtime"} ----------
    def read_note(self, username: str, note_id: str) -> str | None:
        val = self.get(_note_key(username, note_id))
        if isinstance(val, dict):
            content = val.get("content")
            return content if isinstance(content, str) else None
        return None

    def write_note(self, username: str, note_id: str, content: str) -> bool:
        key = _note_key(username, note_id)
        if content == "":
            return self.delete(key)
        return self.set(key, {"content": content, "mtime": time.time()})

    def note_mtime(self, username: str, note_id: str) -> float | None:
        val = self.get(_note_key(username, note_id))
        if isinstance(val, dict):
            mtime = val.get("mtime")
            return mtime if isinstance(mtime, (int, float)) else None
        return None

    def note_size(self, username: str, note_id: str) -> int | None:
        val = self.get(_note_key(username, note_id))
        if isinstance(val, dict):
            content = val.get("content")
            if isinstance(content, str):
                return len(content.encode("utf-8"))
        return None

    def list_notes(self, username: str) -> list:
        prefix = f"{NOTE_KEY_PREFIX}{username}:"
        return [key[len(prefix):] for key in self.list_keys(prefix)]

    def iter_all_notes(self):
        for key in self.list_keys(NOTE_KEY_PREFIX):
            parsed = parse_note_key(key)
            if parsed:
                yield parsed

    # ---------- 锁：进程内线程锁 ----------
    @contextmanager
    def lock(self, name: str):
        with self._guard:
            lock = self._locks.get(name)
            if lock is None:
                lock = threading.Lock()
                self._locks[name] = lock
        with lock:
            yield


# ======================================================================
# upstash 后端：Upstash Redis / Vercel KV REST API（纯 HTTPS + 标准库）
# 所有键统一加 "rusin:" 前缀，避免与共享 KV 中的其它应用冲突
# ======================================================================
class UpstashBackend(StorageBackend):
    kind = "upstash"
    persistent = True
    KEY_PREFIX = "rusin:"
    _LOCK_TTL = 10          # 锁自动过期秒数（防止崩溃后死锁）
    _LOCK_WAIT = 15         # 获取锁最长等待秒数

    def __init__(self, base_url: str, token: str):
        if not base_url or not token:
            raise StorageError("Upstash 后端需要 KV_REST_API_URL 与 KV_REST_API_TOKEN")
        self._base = base_url.rstrip("/")
        self._token = token
        self._headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    def _key(self, key: str) -> str:
        return self.KEY_PREFIX + key

    def _request(self, method: str, path: str, body=None, timeout: float = 10.0):
        """执行 Upstash REST 命令，返回响应中的 result 字段（可能为 None）"""
        url = f"{self._base}/{path}"
        data = None
        headers = self._headers
        if body is not None:
            data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError,
                OSError, ValueError) as e:
            raise StorageError(f"Upstash 请求失败: {e}")
        if isinstance(payload, dict) and payload.get("error"):
            raise StorageError(f"Upstash 错误: {payload['error']}")
        return payload.get("result") if isinstance(payload, dict) else payload

    def get(self, key: str):
        raw = self._request("GET", f"get/{urllib.parse.quote(self._key(key), safe='')}")
        if raw is None:
            return None
        return _json_loads(raw)

    def set(self, key: str, value) -> bool:
        result = self._request(
            "POST", f"set/{urllib.parse.quote(self._key(key), safe='')}",
            {"value": _json_dumps(value)},
        )
        return result == "OK" or result == 1 or result is not None

    def delete(self, key: str) -> bool:
        result = self._request("DELETE", f"del/{urllib.parse.quote(self._key(key), safe='')}")
        return result == 1

    def list_keys(self, prefix: str) -> list:
        pattern = urllib.parse.quote(self._key(prefix) + "*", safe="*")
        result = self._request("GET", f"keys/{pattern}")
        if not isinstance(result, list):
            return []
        full = self.KEY_PREFIX
        return [key[len(full):] for key in result if key.startswith(full)]

    # ---------- 笔记：note:<user>:<id> → {"content", "mtime"} ----------
    def read_note(self, username: str, note_id: str) -> str | None:
        val = self.get(_note_key(username, note_id))
        if isinstance(val, dict):
            content = val.get("content")
            return content if isinstance(content, str) else None
        return None

    def write_note(self, username: str, note_id: str, content: str) -> bool:
        key = _note_key(username, note_id)
        if content == "":
            return self.delete(key)
        return self.set(key, {"content": content, "mtime": time.time()})

    def note_mtime(self, username: str, note_id: str) -> float | None:
        val = self.get(_note_key(username, note_id))
        if isinstance(val, dict):
            mtime = val.get("mtime")
            return mtime if isinstance(mtime, (int, float)) else None
        return None

    def note_size(self, username: str, note_id: str) -> int | None:
        # STRLEN 命令：返回值的字节长度（含 JSON 编码开销，展示用足够）
        try:
            result = self._request(
                "GET", f"strlen/{urllib.parse.quote(self._key(_note_key(username, note_id)), safe='')}"
            )
            return result if isinstance(result, int) else None
        except StorageError:
            return None

    def list_notes(self, username: str) -> list:
        prefix = f"{NOTE_KEY_PREFIX}{username}:"
        return [key[len(prefix):] for key in self.list_keys(prefix)]

    def iter_all_notes(self):
        for key in self.list_keys(NOTE_KEY_PREFIX):
            parsed = parse_note_key(key)
            if parsed:
                yield parsed

    # ---------- 锁：SET NX EX（跨实例互斥，带自动过期防死锁） ----------
    @contextmanager
    def lock(self, name: str):
        key = f"lock:{name}"
        deadline = time.time() + self._LOCK_WAIT
        while True:
            try:
                acquired = self._request(
                    "POST", f"setnx/{urllib.parse.quote(self._key(key), safe='')}",
                    {"value": "1", "ex": self._LOCK_TTL},
                )
            except StorageError:
                acquired = None
            if acquired == 1:
                break
            if time.time() >= deadline:
                raise StorageError(f"获取存储锁超时: {name}")
            time.sleep(0.1)
        try:
            yield
        finally:
            try:
                self._request("DELETE", f"del/{urllib.parse.quote(self._key(key), safe='')}")
            except StorageError:
                pass


# ======================================================================
# postgres 后端：Neon / 任意 PostgreSQL（环境变量 DATABASE_URL）
# 建两张表：storage_kv（通用 KV，value 存 JSON 串或纯文本）与
# storage_notes（笔记，原生 mtime/大小/列举）；跨实例锁用 PG advisory lock
# ======================================================================
_SCHEMA_KV = """
CREATE TABLE IF NOT EXISTS storage_kv (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
)
"""
_SCHEMA_NOTES = """
CREATE TABLE IF NOT EXISTS storage_notes (
    username TEXT NOT NULL,
    note_id  TEXT NOT NULL,
    content  TEXT NOT NULL,
    mtime    DOUBLE PRECISION NOT NULL,
    PRIMARY KEY (username, note_id)
)
"""


class PostgresBackend(StorageBackend):
    kind = "postgres"
    persistent = True
    _LOCK_WAIT = 15  # 获取锁最长等待秒数

    def __init__(self, database_url: str):
        if not database_url:
            raise StorageError("Postgres 后端需要 DATABASE_URL")
        self._dsn = database_url
        self._schema_ready = False
        self._schema_guard = threading.Lock()

    def _connect(self):
        if psycopg is None:
            raise StorageError("需要安装 psycopg 才能使用 postgres 后端：pip install 'psycopg[binary]'")
        try:
            return psycopg.connect(self._dsn, connect_timeout=10)
        except Exception as e:
            raise StorageError(f"Postgres 连接失败: {e}")

    def _ensure_schema(self):
        if self._schema_ready:
            return
        with self._schema_guard:
            if self._schema_ready:
                return
            conn = self._connect()
            try:
                with conn.cursor() as cur:
                    cur.execute(_SCHEMA_KV)
                    cur.execute(_SCHEMA_NOTES)
                conn.commit()
                self._schema_ready = True
            except StorageError:
                raise
            except Exception as e:
                raise StorageError(f"Postgres 初始化表失败: {e}")
            finally:
                conn.close()

    def _execute(self, sql: str, params=(), fetch: str | None = None):
        """执行 SQL。fetch="one" 取单行首列、fetch="all" 取全部行，否则返回受影响行数。"""
        self._ensure_schema()
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                if fetch == "one":
                    row = cur.fetchone()
                    return row[0] if row is not None else None
                if fetch == "all":
                    return cur.fetchall()
                affected = cur.rowcount
            conn.commit()
            return affected
        except StorageError:
            raise
        except Exception as e:
            raise StorageError(f"Postgres 操作失败: {e}")
        finally:
            conn.close()

    def get(self, key: str):
        raw = self._execute(
            "SELECT value FROM storage_kv WHERE key = %s", (key,), fetch="one")
        if raw is None:
            return None
        if key in _RAW_TEXT_KEYS:
            return raw
        return _json_loads(raw)

    def set(self, key: str, value) -> bool:
        raw = value if key in _RAW_TEXT_KEYS else _json_dumps(value)
        self._execute(
            "INSERT INTO storage_kv (key, value) VALUES (%s, %s) "
            "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
            (key, raw),
        )
        return True

    def delete(self, key: str) -> bool:
        return bool(self._execute("DELETE FROM storage_kv WHERE key = %s", (key,)))

    def list_keys(self, prefix: str) -> list:
        rows = self._execute(
            "SELECT key FROM storage_kv WHERE key LIKE %s", (prefix + "%",), fetch="all")
        return [r[0] for r in rows]

    # ---------- 笔记：storage_notes 表 ----------
    def read_note(self, username: str, note_id: str) -> str | None:
        return self._execute(
            "SELECT content FROM storage_notes WHERE username = %s AND note_id = %s",
            (username, note_id), fetch="one")

    def write_note(self, username: str, note_id: str, content: str) -> bool:
        if content == "":
            self._execute(
                "DELETE FROM storage_notes WHERE username = %s AND note_id = %s",
                (username, note_id))
            return True
        self._execute(
            "INSERT INTO storage_notes (username, note_id, content, mtime) "
            "VALUES (%s, %s, %s, %s) "
            "ON CONFLICT (username, note_id) DO UPDATE SET "
            "content = EXCLUDED.content, mtime = EXCLUDED.mtime",
            (username, note_id, content, time.time()),
        )
        return True

    def note_mtime(self, username: str, note_id: str) -> float | None:
        return self._execute(
            "SELECT mtime FROM storage_notes WHERE username = %s AND note_id = %s",
            (username, note_id), fetch="one")

    def note_size(self, username: str, note_id: str) -> int | None:
        return self._execute(
            "SELECT octet_length(content) FROM storage_notes WHERE username = %s AND note_id = %s",
            (username, note_id), fetch="one")

    def list_notes(self, username: str) -> list:
        rows = self._execute(
            "SELECT note_id FROM storage_notes WHERE username = %s", (username,), fetch="all")
        return [r[0] for r in rows]

    def iter_all_notes(self):
        rows = self._execute(
            "SELECT username, note_id FROM storage_notes", fetch="all")
        for username, note_id in rows:
            yield username, note_id

    # ---------- 锁：PG advisory lock（跨实例互斥，事务结束自动释放） ----------
    @contextmanager
    def lock(self, name: str):
        self._ensure_schema()
        conn = self._connect()
        deadline = time.time() + self._LOCK_WAIT
        try:
            while True:
                try:
                    with conn.cursor() as cur:
                        cur.execute("SELECT pg_try_advisory_xact_lock(hashtextextended(%s, 0))", (name,))
                        acquired = cur.fetchone()[0]
                except StorageError:
                    raise
                except Exception as e:
                    raise StorageError(f"Postgres 锁失败: {e}")
                if acquired:
                    break
                if time.time() >= deadline:
                    raise StorageError(f"获取存储锁超时: {name}")
                time.sleep(0.1)
            try:
                yield
            finally:
                try:
                    conn.rollback()  # 释放 advisory xact lock
                except Exception:
                    pass
        finally:
            conn.close()


# ======================================================================
# 后端选择
# ======================================================================
def select_backend() -> StorageBackend:
    mode = os.environ.get("RUSIN_STORAGE", "").strip().lower()
    kv_url = os.environ.get("KV_REST_API_URL", "").strip()
    kv_token = os.environ.get("KV_REST_API_TOKEN", "").strip()
    database_url = os.environ.get("DATABASE_URL", "").strip()

    if mode == "postgres":
        return PostgresBackend(database_url)
    if mode == "upstash":
        return UpstashBackend(kv_url, kv_token)
    if mode == "memory":
        return MemoryBackend()
    if mode == "file":
        return FileBackend()
    # 自动识别：配置了 KV 环境变量 → upstash；DATABASE_URL → postgres；
    # 无服务器平台 → memory；否则 file
    if kv_url and kv_token:
        return UpstashBackend(kv_url, kv_token)
    if database_url:
        return PostgresBackend(database_url)
    if SERVERLESS:
        return MemoryBackend()
    return FileBackend()


storage = select_backend()