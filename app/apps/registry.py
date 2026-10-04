"""功能 App 注册入口：共享内核 → 各功能 App → 插件蓝图 → world_short（catch-all 必须最后）

插件蓝图须先于 world_short，否则插件单段路由（/myplug）会被 /<id> 短链抢匹配。
"""
from flask import Flask

from app.apps.admin.views import bp as admin_bp
from app.apps.attachments.views import bp as attachments_bp
from app.apps.auth.views import bp as auth_bp
from app.apps.benben.views import bp as benben_bp
from app.apps.comments.views import bp as comments_bp
from app.apps.email.views import bp as email_bp
from app.apps.home.views import bp as home_bp
from app.apps.images.views import bp as images_bp
from app.apps.notes.views import bp as notes_bp
from app.apps.oauth.views import bp as oauth_bp
from app.apps.org.views import bp as org_bp
from app.apps.share.views import bp as share_bp
from app.apps.static.views import bp as static_bp
from app.apps.todos.views import bp as todos_bp
from app.apps.twofa.views import bp as twofa_bp
from app.apps.user.views import bp as user_bp
from app.apps.world.views import bp as world_bp


def register_blueprints(app: Flask) -> None:
    app.register_blueprint(home_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(benben_bp)
    app.register_blueprint(static_bp)
    app.register_blueprint(notes_bp)
    app.register_blueprint(images_bp)
    app.register_blueprint(attachments_bp)
    app.register_blueprint(user_bp)
    app.register_blueprint(share_bp)
    app.register_blueprint(world_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(comments_bp)
    app.register_blueprint(org_bp)
    app.register_blueprint(todos_bp)
    # 验证 / 认证：第三方登录、双因素、邮箱手机验证（各自独立 App）
    app.register_blueprint(oauth_bp)
    app.register_blueprint(twofa_bp)
    app.register_blueprint(email_bp)
    # 插件蓝图（Phase 1 安装 + 注册）：必须在 world_short 之前，
    # 否则插件的单段路由（如 /myplug）会被 /<id> 短链抢匹配
    from app.core import plugins
    plugins.register_plugin_blueprints(app)
    # world_short 包含 /<id> 与 /<id>.md 的 catch-all 路由，必须最后
    from app.apps.world import short as world_short
    app.register_blueprint(world_short.bp)
