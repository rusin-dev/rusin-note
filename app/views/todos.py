"""工作台待办（TODO LIST）路由：新增 / 切换完成 / 删除 / 清理已完成

待办在首页工作台内联展示，均为表单 POST（带 CSRF），操作后重定向回工作台。
"""
from flask import Blueprint, abort, redirect, request

from .. import config
from ..extensions import limiter
from ..middleware import get_current_user
from ..notes import validate_username
from ..todos import add_user_todo, clear_done_user_todos, delete_user_todo, toggle_user_todo

bp = Blueprint("todos", __name__)


def _require_auth(username: str):
    if get_current_user() != username:
        abort(401)


def _guard(username: str):
    if not validate_username(username):
        abort(400)
    _require_auth(username)


@bp.route("/user/<username>/todos/add", methods=["POST"])
@limiter.limit(lambda: f"{config.RATE_MAX} per {config.RATE_WINDOW} second")
def todo_add(username):
    _guard(username)
    ok, err = add_user_todo(username, request.form.get("text", ""))
    if ok:
        return redirect("/")
    return redirect(f"/?todo_err={err}")


@bp.route("/user/<username>/todos/<todo_id>/toggle", methods=["POST"])
@limiter.limit(lambda: f"{config.RATE_MAX} per {config.RATE_WINDOW} second")
def todo_toggle(username, todo_id):
    _guard(username)
    toggle_user_todo(username, todo_id)
    return redirect("/")


@bp.route("/user/<username>/todos/<todo_id>/delete", methods=["POST"])
@limiter.limit(lambda: f"{config.RATE_MAX} per {config.RATE_WINDOW} second")
def todo_delete(username, todo_id):
    _guard(username)
    delete_user_todo(username, todo_id)
    return redirect("/")


@bp.route("/user/<username>/todos/clear-done", methods=["POST"])
@limiter.limit(lambda: f"{config.RATE_MAX} per {config.RATE_WINDOW} second")
def todo_clear_done(username):
    _guard(username)
    clear_done_user_todos(username)
    return redirect("/")
