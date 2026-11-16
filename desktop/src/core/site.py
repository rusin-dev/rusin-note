"""站点地址规范化：桌面端只连用户自己的 rusin-note 网页版。

地址来自首次运行设置页的用户输入，属于外部输入，必须校验协议与主机，
避免把 file:// / javascript: 之类的地址交给 WebView 加载。
"""
from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit

DEFAULT_SITE_URL = "https://note.rusin7.com"

_ALLOWED_SCHEMES = ("http", "https")


def normalize_site_url(raw: str) -> str | None:
    """把用户输入规范化为站点根地址；非法输入返回 None。

    省略协议时按 https 补全；丢弃查询串与锚点（站点地址不该带它们），
    去掉末尾斜杠，协议与主机转小写。含账号密码的地址一律拒绝，避免把
    凭据写进配置文件。
    """
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    if not text or any(ch.isspace() for ch in text):
        return None
    if "://" not in text:
        text = "https://" + text
    try:
        parts = urlsplit(text)
        scheme = parts.scheme.lower()
        if scheme not in _ALLOWED_SCHEMES or not parts.netloc:
            return None
        if parts.username or parts.password:
            return None
        host = parts.hostname or ""
        if not host or any(ch.isspace() for ch in host):
            return None
        netloc = host.lower()
        if parts.port is not None:
            netloc = f"{netloc}:{parts.port}"
    except ValueError:
        return None
    path = parts.path.rstrip("/")
    return urlunsplit((scheme, netloc, path, "", ""))