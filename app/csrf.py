"""CSRF 防护（Cookie + 表单双重验证）"""
import secrets

CSRF_COOKIE_NAME = "_csrf_token"
CSRF_FIELD_NAME = "_csrf_token"
TOKEN_LENGTH = 32
COOKIE_MAX_AGE = 2592000  # 30 天


def generate_token() -> str:
    return secrets.token_urlsafe(TOKEN_LENGTH)


def read_csrf_cookie(handler) -> str | None:
    cookie = handler.headers.get("Cookie")
    if cookie:
        for pair in cookie.split(";"):
            pair = pair.strip()
            if pair.startswith(f"{CSRF_COOKIE_NAME}="):
                return pair[len(CSRF_COOKIE_NAME) + 1:]
    return None


def validate_csrf(handler, form_data: dict) -> bool:
    cookie_token = read_csrf_cookie(handler)
    form_tokens = form_data.get(CSRF_FIELD_NAME, [])
    if not cookie_token or not form_tokens:
        return False
    return secrets.compare_digest(cookie_token, form_tokens[0])
