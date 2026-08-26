"""组织/团队协作：/org/<org_name>/*"""
import re

from flask import Blueprint, abort, g, redirect, render_template, request, url_for

from .. import config
from ..extensions import cache, limiter
from ..i18n import t
from ..feature_flags import feature_enabled, require_feature
from ..middleware import get_current_user
from ..notes import (
    generate_random_id,
    get_note_mtime,
    get_note_size,
    list_user_notes,
    note_exists,
    read_note,
    validate_note_id,
    write_note,
)
from ..store import (
    can_org_do,
    create_org,
    create_org_invite,
    create_join_request,
    delete_org,
    delete_org_invite,
    approve_join_request,
    reject_join_request,
    get_org,
    get_org_invites,
    get_org_join_requests,
    get_org_members,
    get_org_member_role,
    get_user_orgs,
    org_invite_join,
    org_public_join,
    remove_org_member,
    update_org,
    update_org_member_role,
    validate_org_invite,
)
from ..utils import format_note_time, format_size, render_markdown_html

bp = Blueprint("org", __name__)

# 组织笔记的虚拟用户名前缀
ORG_USERNAME_PREFIX = "_orgs/"

# 保留的组织名（不能创建）
RESERVED_ORG_NAMES = {"create", "join", "new", "settings", "members", "invites", "requests", "leave"}


def _org_username(org_name: str) -> str:
    """将 org_name 转换为存储用的虚拟用户名"""
    return f"{ORG_USERNAME_PREFIX}{org_name}"


def _validate_org_name(org_name: str) -> bool:
    """校验组织名格式"""
    if org_name.lower() in RESERVED_ORG_NAMES:
        return False
    return bool(re.match(r'^[a-zA-Z0-9_\-]+$', org_name))


def _require_org_member(org_name: str, min_role: str = "member"):
    """检查当前用户是否为组织成员且角色 >= min_role"""
    user = get_current_user()
    if not user:
        abort(401)
    if not can_org_do(org_name, user, min_role):
        abort(403)


def _require_org_admin(org_name: str):
    """检查当前用户是否为组织 admin 或 owner"""
    _require_org_member(org_name, "admin")


def _require_org_owner(org_name: str):
    """检查当前用户是否为组织 owner"""
    _require_org_member(org_name, "owner")


# ---------- 组织主页 ----------
@bp.route("/org/<org_name>", methods=["GET"])
@bp.route("/org/<org_name>/", methods=["GET"])
@require_feature("orgs")
@limiter.limit(lambda: f"{config.GET_RATE_MAX} per {config.GET_RATE_WINDOW} second")
def org_home(org_name):
    if not _validate_org_name(org_name):
        abort(400)
    org = get_org(org_name)
    if not org:
        abort(404)
    user = get_current_user()
    is_member = user and can_org_do(org_name, user, "member")
    members = get_org_members(org_name) if is_member else {}
    return render_template(
        "org/org.html",
        org_name=org_name,
        org=org,
        is_member=is_member,
        members=members if is_member else None,
    )


# ---------- 组织笔记列表 ----------
@bp.route("/org/<org_name>/notes", methods=["GET"])
@require_feature("orgs")
@limiter.limit(lambda: f"{config.GET_RATE_MAX} per {config.GET_RATE_WINDOW} second")
def org_notes(org_name):
    if not _validate_org_name(org_name):
        abort(400)
    org = get_org(org_name)
    if not org:
        abort(404)
    _require_org_member(org_name)
    username = _org_username(org_name)
    notes = list_user_notes(username)
    note_list = []
    for nid in notes:
        mtime = get_note_mtime(username, nid)
        size = get_note_size(username, nid)
        note_list.append({
            "id": nid,
            "mtime": format_note_time(mtime) if mtime else "",
            "size": format_size(size) if size is not None else "",
        })
    return render_template(
        "org/org_notes.html",
        org_name=org_name,
        org=org,
        notes=note_list,
    )


# ---------- 查看组织笔记 ----------
@bp.route("/org/<org_name>/notes/<note_id>", methods=["GET"])
@require_feature("orgs")
@limiter.limit(lambda: f"{config.GET_RATE_MAX} per {config.GET_RATE_WINDOW} second")
def org_note_view(org_name, note_id):
    if not _validate_org_name(org_name) or not validate_note_id(note_id):
        abort(400)
    org = get_org(org_name)
    if not org:
        abort(404)
    _require_org_member(org_name)
    username = _org_username(org_name)
    content = read_note(username, note_id)
    if content is None:
        abort(404)
    mtime = get_note_mtime(username, note_id)
    html = render_markdown_html(content)
    return render_template(
        "org/org_note_view.html",
        org_name=org_name,
        org=org,
        note_id=note_id,
        content=html,
        mtime=format_note_time(mtime) if mtime else "",
    )


# ---------- 新建组织笔记 ----------
@bp.route("/org/<org_name>/notes/new", methods=["GET", "POST"])
@require_feature("orgs")
@limiter.limit(lambda: f"{config.SAVE_RATE_MAX} per {config.SAVE_RATE_WINDOW} second")
def org_note_new(org_name):
    if not _validate_org_name(org_name):
        abort(400)
    org = get_org(org_name)
    if not org:
        abort(404)
    _require_org_member(org_name, "member")  # 所有成员都可创建笔记
    username = _org_username(org_name)

    if request.method == "GET":
        return render_template(
            "org/org_note_edit.html",
            org_name=org_name,
            org=org,
            note_id=None,
            content="",
            is_new=True,
        )

    # POST: 保存笔记
    content = request.form.get("content", "")
    note_id = generate_random_id()
    if write_note(username, note_id, content):
        return redirect(url_for("org.org_note_view", org_name=org_name, note_id=note_id))
    abort(500)


# ---------- 编辑组织笔记 ----------
@bp.route("/org/<org_name>/notes/<note_id>/edit", methods=["GET", "POST"])
@require_feature("orgs")
@limiter.limit(lambda: f"{config.SAVE_RATE_MAX} per {config.SAVE_RATE_WINDOW} second")
def org_note_edit(org_name, note_id):
    if not _validate_org_name(org_name) or not validate_note_id(note_id):
        abort(400)
    org = get_org(org_name)
    if not org:
        abort(404)
    _require_org_member(org_name, "member")
    username = _org_username(org_name)
    content = read_note(username, note_id)
    if content is None:
        abort(404)

    if request.method == "GET":
        return render_template(
            "org/org_note_edit.html",
            org_name=org_name,
            org=org,
            note_id=note_id,
            content=content,
            is_new=False,
        )

    # POST: 更新笔记
    new_content = request.form.get("content", "")
    if write_note(username, note_id, new_content):
        return redirect(url_for("org.org_note_view", org_name=org_name, note_id=note_id))
    abort(500)


# ---------- 删除组织笔记 ----------
@bp.route("/org/<org_name>/notes/<note_id>/delete", methods=["POST"])
@require_feature("orgs")
@limiter.limit(lambda: f"{config.SAVE_RATE_MAX} per {config.SAVE_RATE_WINDOW} second")
def org_note_delete(org_name, note_id):
    if not _validate_org_name(org_name) or not validate_note_id(note_id):
        abort(400)
    org = get_org(org_name)
    if not org:
        abort(404)
    _require_org_member(org_name, "member")
    username = _org_username(org_name)
    if write_note(username, note_id, ""):  # 空内容表示删除
        return redirect(url_for("org.org_notes", org_name=org_name))
    abort(500)


# ---------- 组织成员列表 ----------
@bp.route("/org/<org_name>/members", methods=["GET"])
@require_feature("orgs")
@limiter.limit(lambda: f"{config.GET_RATE_MAX} per {config.GET_RATE_WINDOW} second")
def org_members(org_name):
    if not _validate_org_name(org_name):
        abort(400)
    org = get_org(org_name)
    if not org:
        abort(404)
    _require_org_member(org_name)
    members = get_org_members(org_name)
    return render_template(
        "org/org_members.html",
        org_name=org_name,
        org=org,
        members=members,
    )


# ---------- 组织设置 ----------
@bp.route("/org/<org_name>/settings", methods=["GET", "POST"])
@require_feature("orgs")
@limiter.limit(lambda: f"{config.SAVE_RATE_MAX} per {config.SAVE_RATE_WINDOW} second")
def org_settings(org_name):
    if not _validate_org_name(org_name):
        abort(400)
    org = get_org(org_name)
    if not org:
        abort(404)
    _require_org_admin(org_name)  # 需要 admin 或 owner
    members = get_org_members(org_name)

    if request.method == "GET":
        return render_template(
            "org/org_settings.html",
            org_name=org_name,
            org=org,
            members=members,
        )

    # POST: 更新设置
    action = request.form.get("action")
    if action == "update_info":
        name = request.form.get("name", "")[:100]
        description = request.form.get("description", "")[:500]
        join_policy = request.form.get("join_policy", "invite")
        if join_policy not in ("invite", "public", "approve"):
            join_policy = "invite"
        update_org(org_name, {
            "name": name,
            "description": description,
            "join_policy": join_policy,
        })
        return redirect(url_for("org.org_settings", org_name=org_name))
    elif action == "delete_org":
        _require_org_owner(org_name)
        if delete_org(org_name):
            return redirect(url_for("home.index"))
        abort(500)
    elif action == "remove_member":
        _require_org_admin(org_name)
        target_user = request.form.get("username", "")
        if remove_org_member(org_name, target_user):
            return redirect(url_for("org.org_settings", org_name=org_name))
        abort(400)
    elif action == "update_role":
        _require_org_owner(org_name)
        target_user = request.form.get("username", "")
        new_role = request.form.get("role", "")
        if new_role in ("admin", "member") and update_org_member_role(org_name, target_user, new_role):
            return redirect(url_for("org.org_settings", org_name=org_name))
        abort(400)

    return redirect(url_for("org.org_settings", org_name=org_name))


# ---------- 邀请管理 ----------
@bp.route("/org/<org_name>/invites", methods=["GET", "POST"])
@require_feature("orgs")
@limiter.limit(lambda: f"{config.SAVE_RATE_MAX} per {config.SAVE_RATE_WINDOW} second")
def org_invites(org_name):
    if not _validate_org_name(org_name):
        abort(400)
    org = get_org(org_name)
    if not org:
        abort(404)
    _require_org_admin(org_name)

    if request.method == "POST":
        action = request.form.get("action")
        if action == "create_invite":
            invite_type = request.form.get("type", "invite")
            expires_days = int(request.form.get("expires_days", 7))
            code = create_org_invite(org_name, get_current_user(), invite_type, expires_days)
            if code:
                return render_template(
                    "org/org_invites.html",
                    org_name=org_name,
                    org=org,
                    invites=get_org_invites(org_name),
                    new_code=code,
                )
            abort(500)
        elif action == "delete_invite":
            code = request.form.get("code", "")
            delete_org_invite(code)
            return redirect(url_for("org.org_invites", org_name=org_name))

    return render_template(
        "org/org_invites.html",
        org_name=org_name,
        org=org,
        invites=get_org_invites(org_name),
        new_code=None,
    )


# ---------- 申请审批 ----------
@bp.route("/org/<org_name>/requests", methods=["GET", "POST"])
@require_feature("orgs")
@limiter.limit(lambda: f"{config.SAVE_RATE_MAX} per {config.SAVE_RATE_WINDOW} second")
def org_requests(org_name):
    if not _validate_org_name(org_name):
        abort(400)
    org = get_org(org_name)
    if not org:
        abort(404)
    _require_org_admin(org_name)

    if request.method == "POST":
        action = request.form.get("action")
        username = request.form.get("username", "")
        if action == "approve":
            approve_join_request(org_name, username)
        elif action == "reject":
            reject_join_request(org_name, username)
        return redirect(url_for("org.org_requests", org_name=org_name))

    requests = get_org_join_requests(org_name)
    return render_template(
        "org/org_requests.html",
        org_name=org_name,
        org=org,
        requests=requests,
    )


# ---------- 创建组织 ----------
@bp.route("/org/create", methods=["GET", "POST"])
@require_feature("orgs")
@limiter.limit(lambda: f"{config.SAVE_RATE_MAX} per {config.SAVE_RATE_WINDOW} second")
def org_create():
    user = get_current_user()
    if not user:
        abort(401)

    if request.method == "GET":
        return render_template("org/org_create.html")

    # POST: 创建组织
    org_name = request.form.get("org_name", "")[:50]
    name = request.form.get("name", "")[:100]
    description = request.form.get("description", "")[:500]
    join_policy = request.form.get("join_policy", "invite")

    if not _validate_org_name(org_name):
        return render_template("org/org_create.html", error="Invalid organization name")
    if get_org(org_name):
        return render_template("org/org_create.html", error="Organization already exists")

    if join_policy not in ("invite", "public", "approve"):
        join_policy = "invite"

    if create_org(org_name, name, user, description, join_policy):
        return redirect(url_for("org.org_home", org_name=org_name))
    abort(500)


# ---------- 通过邀请码加入 ----------
@bp.route("/org/join/<invite_code>", methods=["POST"])
@require_feature("orgs")
@limiter.limit(lambda: f"{config.SAVE_RATE_MAX} per {config.SAVE_RATE_WINDOW} second")
def org_join_by_invite(invite_code):
    user = get_current_user()
    if not user:
        abort(401)

    invite = validate_org_invite(invite_code)
    if not invite:
        abort(400)

    org_name = invite.get("org_name")
    if org_invite_join(invite_code, user):
        return redirect(url_for("org.org_home", org_name=org_name))
    abort(400)


# ---------- 申请加入（审批制） ----------
@bp.route("/org/join-approve/<org_name>", methods=["POST"])
@require_feature("orgs")
@limiter.limit(lambda: f"{config.SAVE_RATE_MAX} per {config.SAVE_RATE_WINDOW} second")
def org_join_approve(org_name):
    if not _validate_org_name(org_name):
        abort(400)
    user = get_current_user()
    if not user:
        abort(401)

    org = get_org(org_name)
    if not org:
        abort(404)
    if org.get("join_policy") != "approve":
        abort(400)

    message = request.form.get("message", "")[:200]
    if create_join_request(org_name, user, message):
        return redirect(url_for("org.org_home", org_name=org_name))
    abort(400)


# ---------- 公开加入 ----------
@bp.route("/org/join-public/<org_name>", methods=["POST"])
@require_feature("orgs")
@limiter.limit(lambda: f"{config.SAVE_RATE_MAX} per {config.SAVE_RATE_WINDOW} second")
def org_join_public(org_name):
    if not _validate_org_name(org_name):
        abort(400)
    user = get_current_user()
    if not user:
        abort(401)

    if org_public_join(org_name, user):
        return redirect(url_for("org.org_home", org_name=org_name))
    abort(400)


# ---------- 退出组织 ----------
@bp.route("/org/<org_name>/leave", methods=["POST"])
@require_feature("orgs")
@limiter.limit(lambda: f"{config.SAVE_RATE_MAX} per {config.SAVE_RATE_WINDOW} second")
def org_leave(org_name):
    if not _validate_org_name(org_name):
        abort(400)
    user = get_current_user()
    if not user:
        abort(401)

    role = get_org_member_role(org_name, user)
    if role == "owner":
        abort(400)  # owner 不能退出，需转移或删除组织

    if remove_org_member(org_name, user):
        return redirect(url_for("home.index"))
    abort(400)


# ---------- 我的组织列表 ----------
@bp.route("/org/mine", methods=["GET"])
@require_feature("orgs")
@limiter.limit(lambda: f"{config.GET_RATE_MAX} per {config.GET_RATE_WINDOW} second")
def org_mine():
    user = get_current_user()
    if not user:
        abort(401)
    org_names = get_user_orgs(user)
    orgs_list = []
    for name in org_names:
        org = get_org(name)
        if org:
            role = get_org_member_role(name, user)
            orgs_list.append({"name": name, "info": org, "role": role})
    return render_template("org/org_mine.html", orgs=orgs_list)


# ---------- 模板上下文处理器 ----------
@bp.context_processor
def org_context():
    """在所有 org 模板中注入 can_org_do 函数"""
    return dict(can_org_do=can_org_do)
