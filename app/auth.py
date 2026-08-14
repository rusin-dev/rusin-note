"""密码哈希、会话管理、密码复杂度检查与会话清理"""
import re
import time
import hashlib
import hmac
import secrets
from threading import Thread

from . import config
from .store import sessions, sessions_lock, save_sessions

# BUG-9: 使用 PBKDF2-HMAC-SHA256 慢哈希（≥10 万次迭代），并加大盐长度。
# 旧版单轮 SHA-256 哈希通过 verify_password 的向后兼容逻辑继续可验证（登录成功后自然升级）。
PBKDF2_ITERATIONS = 100000
PBKDF2_PREFIX = "pbkdf2_sha256"


# ---------- 密码哈希 ----------
def generate_salt():
    return secrets.token_hex(16)


def hash_password(password: str, salt: str) -> str:
    """生成 PBKDF2 格式哈希：pbkdf2_sha256$<迭代次数>$<十六进制摘要>"""
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt), PBKDF2_ITERATIONS
    ).hex()
    return f"{PBKDF2_PREFIX}${PBKDF2_ITERATIONS}${digest}"


def verify_password(password: str, salt: str, hashed: str) -> bool:
    """常量时间比较。兼容旧版单轮 SHA-256 哈希（64 位十六进制串）。"""
    try:
        if isinstance(hashed, str) and hashed.startswith(PBKDF2_PREFIX + "$"):
            try:
                _, iterations_str, digest = hashed.split("$")
                iterations = int(iterations_str)
                computed = hashlib.pbkdf2_hmac(
                    "sha256", password.encode("utf-8"), bytes.fromhex(salt), iterations
                ).hex()
                return hmac.compare_digest(computed, digest)
            except (ValueError, TypeError):
                return False
        # 旧版格式（单轮 SHA-256）
        if isinstance(hashed, str) and isinstance(salt, str):
            legacy = hashlib.sha256((salt + password).encode("utf-8")).hexdigest()
            return hmac.compare_digest(legacy, hashed)
    except Exception:
        return False
    return False


# ---------- 会话管理 ----------
def generate_session_token():
    return secrets.token_hex(32)


def hash_token(token: str) -> str:
    """对token进行SHA-256哈希"""
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(username: str) -> str:
    """创建会话，返回原始token，存储时使用哈希作为键"""
    token = generate_session_token()
    token_hash = hash_token(token)
    with sessions_lock:
        sessions[token_hash] = {
            "username": username,
            "created_at": time.time()
        }
    save_sessions()
    return token


def delete_session(token: str):
    token_hash = hash_token(token)
    with sessions_lock:
        if token_hash in sessions:
            del sessions[token_hash]
    save_sessions()


def get_session_user(token: str) -> str | None:
    """验证token，返回用户名，若超时或不存在则返回None"""
    token_hash = hash_token(token)
    expired = False
    with sessions_lock:
        session = sessions.get(token_hash)
        if not session or not isinstance(session, dict):
            return None
        username = session.get("username")
        if not username:
            return None
        # 检查超时
        created_at = session.get("created_at")
        if config.SESSION_TIMEOUT_ENABLED and isinstance(created_at, (int, float)):
            elapsed = time.time() - created_at
            if elapsed > config.SESSION_TIMEOUT_SECONDS:
                # 删除过期会话
                del sessions[token_hash]
                # BUG-01: save_sessions 会再次获取 sessions_lock（threading.Lock 不可重入），
                # 必须在持锁块外调用，否则死锁导致处理线程永久挂起
                expired = True
    if expired:
        save_sessions()
        return None
    return username


# ---------- 过期会话清理（BUG-013） ----------
def purge_expired_sessions() -> int:
    """删除已过期的会话，返回删除数量（仅在启用会话超时时生效）"""
    if not config.SESSION_TIMEOUT_ENABLED:
        return 0
    now = time.time()
    cutoff = now - config.SESSION_TIMEOUT_SECONDS
    expired = []
    with sessions_lock:
        for token_hash, sess in sessions.items():
            if not isinstance(sess, dict):
                continue
            created_at = sess.get("created_at")
            if not isinstance(created_at, (int, float)):
                continue  # 损坏/旧版数据，跳过（BUG-7）
            if created_at < cutoff:
                expired.append(token_hash)
        for token_hash in expired:
            del sessions[token_hash]
    if expired:
        save_sessions()
        print(f"[清理] 已清除 {len(expired)} 个过期会话")
    return len(expired)


def session_cleanup_loop():
    """后台线程：定时清除过期会话"""
    while True:
        time.sleep(config.SESSION_CLEANUP_INTERVAL)
        try:
            purge_expired_sessions()
        except Exception as e:
            print(f"[错误] 会话清理失败: {e}")


# ---------- 密码复杂度检查（根据配置） ----------
def check_password_complexity(password: str) -> bool:
    if len(password) < config.PW_MIN_LENGTH:
        return False
    if config.PW_REQUIRE_UPPER and not re.search(r'[A-Z]', password):
        return False
    if config.PW_REQUIRE_LOWER and not re.search(r'[a-z]', password):
        return False
    if config.PW_REQUIRE_DIGIT and not re.search(r'[0-9]', password):
        return False
    if config.PW_REQUIRE_SPECIAL:
        # 特殊字符：排除 / \ ( ) " '
        excluded = r'\/\(\)"\''
        special_pattern = r'[^A-Za-z0-9' + re.escape(excluded) + r']'
        if not re.search(special_pattern, password):
            return False
    return True
