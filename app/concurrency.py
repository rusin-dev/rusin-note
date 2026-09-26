"""进程内并发闸门：限制「同一个 key」同时占用的请求数

用途：附件下载 / 上传这类长连接请求的单用户并发上限。

为什么需要单独一层
------------------
IP 限流（Flask-Limiter，见 ``extensions.py``）限制的是**单位时间内的请求数**，
挡不住「少量请求、超长时间占用」的攻击：攻击者可以发起上千个并发连接，
每个以 1KB/s 的速度慢慢传，请求数没超限，却把 worker 线程/连接池全部占满。
因此这里对**同时在途**的请求数单独设闸，按用户（未登录时按 IP）计数。

实现说明
--------
- 计数在**进程内**（``threading.Lock`` + 字典），每个 worker 进程各自计数：
  gunicorn 起 N 个 worker 时，实际上限约为 ``N × limit``。要做到跨实例严格
  计数需要外部存储的原子自增，代价是每个请求都要多次远程读写，本项目未采用。
- 槽位用 :class:`Slot` 表示，**释放是幂等的**：同一个 Slot 可以同时挂在生成器
  ``finally`` 与 ``Response.call_on_close`` 上，重复释放不会把计数减成负数。
- ``limit <= 0`` 表示不限（返回不计数的一次性 Slot，调用方代码无需分支）。

用法::

    slot = guard.try_acquire(f"user:{username}", limit)
    if slot is None:
        return too_many_requests()
    try:
        ...
    finally:
        slot.release()
"""
from __future__ import annotations

import threading

# 全部闸门实例（供测试/运维一键重置与观察）
_INSTANCES: list["ConcurrencyLimiter"] = []


class Slot:
    """一次并发占位；``release()`` 幂等，可安全地在多处调用。"""

    __slots__ = ("_limiter", "_key", "_counted", "_released", "_lock")

    def __init__(self, limiter: "ConcurrencyLimiter", key: str, counted: bool):
        self._limiter = limiter
        self._key = key
        self._counted = counted
        self._released = False
        self._lock = threading.Lock()

    @property
    def key(self) -> str:
        return self._key

    @property
    def counted(self) -> bool:
        """是否真正占用了一个名额（``limit <= 0`` 时为 False）。"""
        return self._counted

    @property
    def released(self) -> bool:
        return self._released

    def release(self) -> None:
        with self._lock:
            if self._released:
                return
            self._released = True
        if self._counted:
            self._limiter._release(self._key)

    # 便于 ``with guard.try_acquire(...) as slot`` 的写法（None 不可用，需自行判空）
    def __enter__(self) -> "Slot":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.release()
        return False


class ConcurrencyLimiter:
    """按 key 计数的并发闸门（进程内）。"""

    def __init__(self, name: str):
        self.name = name
        self._lock = threading.Lock()
        self._active: dict[str, int] = {}
        self._peak = 0
        self._rejected = 0
        _INSTANCES.append(self)

    # ---------- 采集 ----------
    def try_acquire(self, key: str, limit: int) -> Slot | None:
        """占用一个槽位；已满时返回 ``None``（调用方据此返回 429）。

        ``limit <= 0`` 表示不限并发，返回一个不计数的一次性 Slot。
        """
        try:
            limit = int(limit)
        except (TypeError, ValueError):
            limit = 0
        if limit <= 0:
            return Slot(self, key, counted=False)
        with self._lock:
            current = self._active.get(key, 0)
            if current >= limit:
                self._rejected += 1
                return None
            current += 1
            self._active[key] = current
            if current > self._peak:
                self._peak = current
        return Slot(self, key, counted=True)

    def _release(self, key: str) -> None:
        with self._lock:
            current = self._active.get(key, 0)
            if current <= 1:
                self._active.pop(key, None)
            else:
                self._active[key] = current - 1

    # ---------- 观察 / 测试 ----------
    def active(self, key: str) -> int:
        """该 key 当前在途的请求数。"""
        with self._lock:
            return self._active.get(key, 0)

    def total_active(self) -> int:
        with self._lock:
            return sum(self._active.values())

    @property
    def peak(self) -> int:
        with self._lock:
            return self._peak

    @property
    def rejected(self) -> int:
        """累计被拒绝（触发 429）的次数。"""
        with self._lock:
            return self._rejected

    def reset(self) -> None:
        with self._lock:
            self._active.clear()
            self._peak = 0
            self._rejected = 0

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"<ConcurrencyLimiter {self.name} active={self.total_active()}>"


def reset_all() -> None:
    """重置所有闸门（测试隔离用）。"""
    for instance in _INSTANCES:
        instance.reset()


def stats() -> dict:
    """各闸门当前状态（日志 / 统计页可选展示）。"""
    return {
        instance.name: {
            "active": instance.total_active(),
            "peak": instance.peak,
            "rejected": instance.rejected,
        }
        for instance in _INSTANCES
    }
