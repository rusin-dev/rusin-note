"""程序入口：uv run python main.py"""
import sys

# 必须在导入 webview 之前解除下载标记：带 Zone.Identifier 的 Python.Runtime.dll
# 会让 pythonnet 初始化失败，pywebview 直接起不来（见 src/core/motw.py）
from src.core.motw import clear_mark_of_the_web

clear_mark_of_the_web()

from src.app import main  # noqa: E402  必须在解除锁定之后再导入

if __name__ == "__main__":
    sys.exit(main())
