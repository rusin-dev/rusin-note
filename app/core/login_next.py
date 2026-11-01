"""登录后站内回跳（防止开放重定向）。"""
from flask import session

LOGIN_NEXT_KEY = "login_next"


def safe_path(value: str | None) -> str:
    path = (value or "").strip()
    if not path.startswith("/") or path[1:2] in ("/", "\\"):
        return "/"
    if any(ch in path for ch in ("\r", "\n", "\x00")):
        return "/"
    return path


def remember(path: str | None) -> None:
    session[LOGIN_NEXT_KEY] = safe_path(path)


def consume() -> str:
    return safe_path(session.pop(LOGIN_NEXT_KEY, "/"))


def clear() -> None:
    session.pop(LOGIN_NEXT_KEY, None)
