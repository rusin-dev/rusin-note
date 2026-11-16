"""首次运行设置页：让用户填写自己的 rusin-note 站点地址。

自包含 HTML（不引用任何外部资源），首次运行可能还没联网也能正常显示。
站点地址会写入 value 属性，必须转义后再拼接。
"""
from __future__ import annotations

import html
import json
import locale


def ui_lang() -> str:
    """界面语言：跟随系统区域设置，中文之外一律英文。"""
    try:
        value = (locale.getlocale()[0] or "").lower()
    except (ValueError, TypeError):
        value = ""
    return "zh" if value.startswith(("zh", "chinese")) else "en"

_TEXTS = {
    "zh": {
        "title": "连接到你的站点",
        "sub": "桌面端只是 rusin-note 网页版的原生窗口，笔记数据全部保存在你的站点，本机不存笔记。",
        "label": "站点地址",
        "placeholder": "https://note.example.com",
        "submit": "连接",
        "hint": "填写你部署的 rusin-note 地址，留空则使用官方演示站。",
        "invalid": "地址无效，请输入 http(s):// 开头的站点地址",
        "failed": "连接失败，请重试",
    },
    "en": {
        "title": "Connect to your site",
        "sub": "The desktop app is a native window onto the rusin-note web app. Your notes live on your site, never on this machine.",
        "label": "Site address",
        "placeholder": "https://note.example.com",
        "submit": "Connect",
        "hint": "Enter your own rusin-note deployment, or leave blank to use the official demo.",
        "invalid": "Invalid address. Please enter a site URL starting with http(s)://",
        "failed": "Connection failed, please retry",
    },
}


def render_setup_html(default_url: str, error: str | None = None) -> str:
    """渲染设置页；default_url 为预填地址，error 为上一次提交的错误提示。"""
    texts = {"zh": _TEXTS["zh"], "en": _TEXTS["en"]}
    payload = json.dumps(texts, ensure_ascii=False)
    return f"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>rusin-note</title>
<style>
    * {{ box-sizing: border-box; }}
    body {{
        margin: 0; min-height: 100vh; display: flex; align-items: center; justify-content: center;
        background: #ffffff; color: #0d0d0d; padding: 24px;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans SC", Roboto, Helvetica, Arial, sans-serif;
    }}
    .setup {{ width: 100%; max-width: 460px; text-align: center; }}
    .setup-mark {{
        width: 52px; height: 52px; margin: 0 auto 18px; border-radius: 14px;
        background: linear-gradient(135deg, #0d0d0d, #10a37f);
        display: flex; align-items: center; justify-content: center;
        color: #ffffff; font-size: 24px; font-weight: 700;
    }}
    h1 {{
        margin: 0; font-size: 26px; font-weight: 700;
        background: linear-gradient(135deg, #0d0d0d, #10a37f);
        -webkit-background-clip: text; background-clip: text;
        -webkit-text-fill-color: transparent; color: transparent;
    }}
    .setup-sub {{ margin: 12px 0 26px; font-size: 14px; line-height: 1.7; color: #6e6e80; }}
    form {{ text-align: left; }}
    label {{ display: block; font-size: 13px; font-weight: 600; margin-bottom: 8px; }}
    input {{
        width: 100%; height: 46px; padding: 0 14px; font-size: 15px;
        border: 1px solid #e5e5e5; border-radius: 10px; background: #f7f7f8; color: #0d0d0d;
        outline: none;
    }}
    input:focus {{ border-color: #0e8a6d; background: #ffffff; }}
    button {{
        width: 100%; height: 46px; margin-top: 14px; border: none; border-radius: 10px;
        background: #0e8a6d; color: #ffffff; font-size: 15px; font-weight: 600; cursor: pointer;
    }}
    button:hover {{ filter: brightness(0.94); }}
    button:disabled {{ opacity: 0.6; cursor: default; }}
    .setup-error {{ margin-top: 12px; font-size: 13px; color: #b42318; min-height: 18px; }}
    .setup-hint {{ margin-top: 18px; font-size: 12px; line-height: 1.7; color: #6e6e80; }}
</style>
</head>
<body>
<div class="setup">
    <div class="setup-mark" aria-hidden="true">R</div>
    <h1 id="setupTitle"></h1>
    <p class="setup-sub" id="setupSub"></p>
    <form id="setupForm" novalidate>
        <label for="siteUrl" id="setupLabel"></label>
        <input id="siteUrl" name="siteUrl" type="text" autocomplete="off" spellcheck="false"
               value="{html.escape(default_url, quote=True)}" placeholder="{html.escape(_TEXTS['zh']['placeholder'], quote=True)}">
        <div class="setup-error" id="setupError" role="alert">{html.escape(error or '')}</div>
        <button type="submit" id="setupBtn"></button>
    </form>
    <p class="setup-hint" id="setupHint"></p>
</div>
<script>
    const TEXTS = {payload};
    const lang = (navigator.language || 'en').toLowerCase().startsWith('zh') ? 'zh' : 'en';
    const text = TEXTS[lang];
    document.documentElement.lang = lang;
    document.getElementById('setupTitle').textContent = text.title;
    document.getElementById('setupSub').textContent = text.sub;
    document.getElementById('setupLabel').textContent = text.label;
    document.getElementById('setupHint').textContent = text.hint;
    document.getElementById('setupBtn').textContent = text.submit;
    const input = document.getElementById('siteUrl');
    input.placeholder = text.placeholder;

    const form = document.getElementById('setupForm');
    const error = document.getElementById('setupError');
    const button = document.getElementById('setupBtn');
    form.addEventListener('submit', async (event) => {{
        event.preventDefault();
        error.textContent = '';
        button.disabled = true;
        try {{
            const result = await pywebview.api.connect(input.value);
            if (!result || !result.ok) {{
                error.textContent = result && result.reason === 'invalid' ? text.invalid : text.failed;
                button.disabled = false;
            }}
        }} catch (err) {{
            error.textContent = text.failed;
            button.disabled = false;
        }}
    }});
    input.focus();
    input.select();
</script>
</body>
</html>
"""