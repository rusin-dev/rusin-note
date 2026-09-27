"""用户界面偏好：简洁模式。

跨 App 共享（middleware 注入 g.simple_mode，页面缓存键与各视图读取），
因此放在共享内核而不是某个功能 App 内。数据寄存在 users.json 的用户记录上。
"""
from app.core.store import get_user, update_user


def get_simple_mode(username: str) -> bool:
    """用户是否启用简洁模式（未登录/记录缺失时为 False）"""
    if not username:
        return False
    user = get_user(username)
    return bool(user.get("simple_mode")) if isinstance(user, dict) else False


def set_simple_mode(username: str, enabled: bool) -> bool:
    return update_user(username, {"simple_mode": bool(enabled)})
