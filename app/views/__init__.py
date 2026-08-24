"""蓝图注册入口：固定路由 → 插件蓝图 → 短链（必须最后注册）

短链 /<id> 与 /<id>.md 是 catch-all，会匹配任何未注册的根级路径，
因此必须最后注册以避免抢匹配。
"""
from flask import Flask

from . import home, auth, world, user, share, benben, static_routes, admin, comments


def register_blueprints(app: Flask) -> None:
    app.register_blueprint(home.bp)
    app.register_blueprint(auth.bp)
    app.register_blueprint(benben.bp)
    app.register_blueprint(static_routes.bp)
    app.register_blueprint(world.bp)
    app.register_blueprint(user.bp)
    app.register_blueprint(share.bp)
    app.register_blueprint(admin.bp)
    app.register_blueprint(comments.bp)
    # 插件蓝图（Phase 1 安装 + 注册）：必须在 world_short 之前，
    # 否则插件的单段路由（如 /myplug）会被 /<id> 短链抢匹配
    from .. import plugins
    plugins.register_plugin_blueprints(app)
    # world_short 包含 /<id> 与 /<id>.md 的 catch-all 路由，必须最后
    from . import world_short
    app.register_blueprint(world_short.bp)