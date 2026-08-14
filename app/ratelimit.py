"""IP 限流（POST / GET / 保存类 POST 独立限流）"""
import time
from collections import defaultdict
from threading import Lock

from . import config

# ---------- IP限流（POST） ----------
ip_requests = defaultdict(list)
ip_lock = Lock()
MAX_RECORDS_PER_IP = config.RATE_MAX * 2
IP_SWEEP_INTERVAL = 500  # 每 N 次请求清理一次已空的 IP 键，防止字典无限增长（BUG-011）


def cleanup_old_records(records, cutoff):
    i = 0
    while i < len(records):
        if records[i] <= cutoff:
            records.pop(i)
        else:
            i += 1


def _sweep_rate_limit_entries(records_dict, window_seconds):
    """清理所有 IP 的过期记录，并删除已无记录的键（调用方须已持有对应锁）"""
    cutoff = time.time() - window_seconds
    for key in list(records_dict.keys()):
        records = records_dict[key]
        cleanup_old_records(records, cutoff)
        if not records:
            del records_dict[key]


_ip_post_sweep_counter = 0


def is_rate_limited(ip: str) -> bool:
    global _ip_post_sweep_counter
    now = time.time()
    with ip_lock:
        records = ip_requests[ip]
        cutoff = now - config.RATE_WINDOW
        cleanup_old_records(records, cutoff)
        if len(records) >= config.RATE_MAX:
            return True
        records.append(now)
        if len(records) > MAX_RECORDS_PER_IP:
            del records[:len(records) - MAX_RECORDS_PER_IP]
        _ip_post_sweep_counter += 1
        if _ip_post_sweep_counter >= IP_SWEEP_INTERVAL:
            _ip_post_sweep_counter = 0
            _sweep_rate_limit_entries(ip_requests, config.RATE_WINDOW)
        return False


# ---------- IP限流（GET） ----------
ip_get_requests = defaultdict(list)
ip_get_lock = Lock()
MAX_GET_RECORDS_PER_IP = config.GET_RATE_MAX * 2
GET_SWEEP_INTERVAL = 500  # 每 N 次请求清理一次已空的 IP 键（BUG-011）

_ip_get_sweep_counter = 0


def is_get_rate_limited(ip: str) -> bool:
    global _ip_get_sweep_counter
    now = time.time()
    with ip_get_lock:
        records = ip_get_requests[ip]
        cutoff = now - config.GET_RATE_WINDOW
        cleanup_old_records(records, cutoff)  # 复用清理函数
        if len(records) >= config.GET_RATE_MAX:
            return True
        records.append(now)
        if len(records) > MAX_GET_RECORDS_PER_IP:
            del records[:len(records) - MAX_GET_RECORDS_PER_IP]
        _ip_get_sweep_counter += 1
        if _ip_get_sweep_counter >= GET_SWEEP_INTERVAL:
            _ip_get_sweep_counter = 0
            _sweep_rate_limit_entries(ip_get_requests, config.GET_RATE_WINDOW)
        return False


# ---------- IP限流（保存类 POST，独立于全局 POST 限流，BUG-14） ----------
ip_save_requests = defaultdict(list)
ip_save_lock = Lock()
MAX_SAVE_RECORDS_PER_IP = config.SAVE_RATE_MAX * 2
SAVE_SWEEP_INTERVAL = 500

_save_sweep_counter = 0


def is_save_rate_limited(ip: str) -> bool:
    global _save_sweep_counter
    now = time.time()
    with ip_save_lock:
        records = ip_save_requests[ip]
        cutoff = now - config.SAVE_RATE_WINDOW
        cleanup_old_records(records, cutoff)
        if len(records) >= config.SAVE_RATE_MAX:
            return True
        records.append(now)
        if len(records) > MAX_SAVE_RECORDS_PER_IP:
            del records[:len(records) - MAX_SAVE_RECORDS_PER_IP]
        _save_sweep_counter += 1
        if _save_sweep_counter >= SAVE_SWEEP_INTERVAL:
            _save_sweep_counter = 0
            _sweep_rate_limit_entries(ip_save_requests, config.SAVE_RATE_WINDOW)
        return False
