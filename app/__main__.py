"""入口：python -m app（兼容 python app/__main__.py 直接运行）"""
try:
    from .server import run_server
except ImportError:
    from server import run_server

if __name__ == "__main__":
    run_server()
