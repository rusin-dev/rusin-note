"""Gitee 双向同步核心行为测试。"""
from __future__ import annotations

import logging
import urllib.parse

from app.core import config
from app.core.feature_flags import FEATURE_KEYS, set_flags
from app.core.notes import read_note, write_note
from support import create_note, csrf_of, expect, register_and_login

logger = logging.getLogger("rusin.tests.gitee_sync")


class TestGiteeMerge:
    def test_non_overlapping_edits_merge(self):
        base = "a\nb\nc\nd\n"
        local = "A\nb\nc\nd\n"
        remote = "a\nb\nc\nD\n"
        from app.apps.gitee_sync.merge import three_way_merge
        expect(three_way_merge(base, local, remote) == "A\nb\nc\nD\n",
               "两侧修改不同行时自动合并")

    def test_overlapping_edits_conflict(self):
        base = "a\nb\nc\n"
        local = "a\nLOCAL\nc\n"
        remote = "a\nREMOTE\nc\n"
        from app.apps.gitee_sync.merge import three_way_merge
        expect(three_way_merge(base, local, remote) is None,
               "两侧修改同一行时返回冲突")


class TestGiteeDecision:
    def test_local_change_pushes(self):
        from app.apps.gitee_sync.merge import decide
        expect(decide("base", "local", "base") == ("push", None),
               "仅站内修改 -> 推送仓库")

    def test_remote_change_pulls(self):
        from app.apps.gitee_sync.merge import decide
        expect(decide("base", "base", "remote") == ("pull", None),
               "仅仓库修改 -> 拉回站内")

    def test_both_same_is_noop(self):
        from app.apps.gitee_sync.merge import decide
        expect(decide("base", "same", "same") == ("noop", None),
               "两侧一致 -> 无需操作")

    def test_safe_delete_propagates(self):
        from app.apps.gitee_sync.merge import decide
        expect(decide("base", None, "base") == ("delete_remote", None),
               "站内删除且仓库未改 -> 删除仓库文件")
        expect(decide("base", "base", None) == ("delete_local", None),
               "仓库删除且站内未改 -> 删除站内笔记")

    def test_delete_edit_conflicts(self):
        from app.apps.gitee_sync.merge import decide
        expect(decide("base", None, "remote")[0] == "conflict",
               "删除与修改并发时进入冲突")


class TestNotifications:
    def test_store_and_mark_read(self, ctx):
        from app.apps.notifications import service
        logger.info("=== 通知持久化与未读状态 ===")
        register_and_login(ctx.client, "notify_user")
        first = service.add("notify_user", "gitee_sync", "同步失败", "存在冲突",
                            url="/user/notify_user/gitee")
        service.add("notify_user", "gitee_sync", "同步失败", "重复提醒",
                    dedupe="same-conflict")
        service.add("notify_user", "gitee_sync", "同步失败", "重复提醒",
                    dedupe="same-conflict")
        expect(service.unread_count("notify_user") == 2, "相同去重键只保留一条未读通知")
        expect(service.mark_read("notify_user", first["id"]), "单条通知可标记已读")
        expect(service.unread_count("notify_user") == 1, "已读后未读数下降")

    def test_notification_page_and_route(self, ctx):
        from app.apps.notifications import service
        logger.info("=== 通知页面与导航入口 ===")
        register_and_login(ctx.client, "notify_route")
        service.add("notify_route", "gitee_sync", "同步失败", "请处理 PR",
                    url="/user/notify_route/gitee")
        html = ctx.client.get("/user/notify_route/notifications").get_data(as_text=True)
        expect("同步失败" in html and "请处理 PR" in html, "通知页展示系统通知")
        expect('href="/user/notify_route/notifications"' in html,
               "导航栏提供通知入口")
        csrf = csrf_of(html)
        response = ctx.client.post("/user/notify_route/notifications/read",
                                   data={"csrf_token": csrf, "all": "1"})
        expect(response.status_code == 302, "全部已读操作成功")
        expect(service.unread_count("notify_route") == 0, "全部已读后未读归零")


class TestGiteeApi:
    def test_authorize_url_contract(self):
        from app.apps.gitee_sync import api
        url = api.build_authorize_url(
            "client-1", "https://note.example/gitee/callback", "state-1",
            "user_info projects pull_requests")
        expect(url.startswith("https://gitee.com/oauth/authorize?"), "Gitee 授权端点")
        expect("client_id=client-1" in url and "state=state-1" in url, "授权 URL 携带客户端与 state")
        expect("scope=user_info" in url, "授权 URL 携带仓库与 PR 所需 scope")

    def test_token_and_profile_mapping(self, monkeypatch):
        from app.apps.gitee_sync import api
        calls = []
        monkeypatch.setattr(api, "_post_form", lambda url, fields: (
            calls.append(("token", url, fields)) or {
                "access_token": "at", "refresh_token": "rt", "expires_in": 3600}))
        tokens = api.exchange_code("cid", "secret", "code", "https://cb")
        expect(tokens["access_token"] == "at", "解析 access_token")
        expect(calls[0][2]["grant_type"] == "authorization_code", "使用授权码模式")
        monkeypatch.setattr(api, "_request_json", lambda *a, **k: {
            "id": 7, "login": "octo", "name": "Octo Cat",
            "email": "octo@example.com", "avatar_url": "https://avatar"})
        profile = api.fetch_profile("at")
        expect(profile == {
            "uid": "7", "login": "octo", "display": "Octo Cat",
            "email": "octo@example.com", "avatar": "https://avatar",
        }, "Gitee 用户资料归一化")

    def test_create_pull_request_payload(self, monkeypatch):
        from app.apps.gitee_sync import api
        captured = {}
        monkeypatch.setattr(api, "_request_json", lambda *a, **k: (
            captured.update(k) or {"html_url": "https://gitee.com/p/1"}))
        result = api.create_pull_request(
            "at", "owner", "repo", "rusin-sync/conflict/demo",
            "main", "冲突", "正文")
        expect(result["html_url"].endswith("/1"), "返回 PR 地址")
        body = captured["payload"]
        expect(body["head"] == "rusin-sync/conflict/demo" and body["base"] == "main",
               "PR 指定冲突分支和目标分支")

    def test_list_notes_skips_unchanged_files(self, monkeypatch):
        from app.apps.gitee_sync import api
        client = api.GiteeClient({
            "token": "at",
            "repo": {"owner": "o", "name": "r", "branch": "main",
                     "directory": "rusin-note"},
        })
        monkeypatch.setattr(client, "_list_directory", lambda relative: [{
            "type": "file", "name": "abc.md",
            "path": "rusin-note/notes/abc.md", "sha": "blob-sha",
        }])
        monkeypatch.setattr(client, "_read_text", lambda path: (
            _ for _ in ()).throw(AssertionError("未变化文件不应下载正文")))
        notes = client.list_notes(
            "rusin-note", "main", known_shas={"abc": "blob-sha"})
        expect(notes["abc"]["unchanged"] is True, "列表 SHA 未变时标记为 unchanged")

    def test_create_branch_uses_git_ref_and_base_sha(self, monkeypatch):
        from app.apps.gitee_sync import api
        calls = []

        def fake(method, path, access_token="", payload=None, params=None):
            calls.append((method, path, payload))
            if method == "GET":
                return {"commit": {"sha": "base-sha"}}
            return {"ref": "refs/heads/feature"}

        monkeypatch.setattr(api, "_request_json", fake)
        api.create_branch("at", "owner", "repo", "rusin-sync/conflict/x", "main")
        payload = calls[-1][2]
        expect(calls[-1][0] == "POST" and calls[-1][1].endswith("/git/refs"),
               "使用 Gitee git/refs 创建分支")
        expect(payload == {"ref": "refs/heads/rusin-sync/conflict/x", "sha": "base-sha"},
               "分支请求包含完整 ref 与基础 commit SHA")


class _FakeClient:
    def __init__(self, remote=None, manifest=None):
        self.remote = remote or {}
        self.manifest = manifest
        self.manifest_sha = "m1" if manifest is not None else None
        self.puts = []
        self.deletes = []
        self.conflicts = []

    def list_notes(self, directory, branch, known_shas=None):
        return {key: dict(value) for key, value in self.remote.items()}

    def read_manifest(self, directory, branch):
        return (dict(self.manifest) if self.manifest is not None else None,
                self.manifest_sha)

    def put_manifest(self, directory, content, sha, branch):
        self.manifest = dict(content)
        self.manifest_sha = "m2"
        return self.manifest_sha

    def put_note(self, path, content, sha, branch):
        note_id = path.rsplit("/", 1)[-1][:-3]
        self.remote[note_id] = {"content": content, "sha": "new-" + note_id, "path": path}
        self.puts.append((path, content, sha, branch))
        return "new-" + note_id

    def delete_note(self, path, sha, branch):
        note_id = path.rsplit("/", 1)[-1][:-3]
        self.remote.pop(note_id, None)
        self.deletes.append((path, sha, branch))
        return True

    def create_conflict_pr(self, note_id, conflict_text, local_content, base_branch):
        self.conflicts.append((note_id, conflict_text, local_content, base_branch))
        return {"branch": "rusin-sync/conflict/" + note_id,
                "pr_url": "https://gitee.com/o/r/pulls/9"}


class TestGiteeSyncEngine:
    def _connection(self):
        return {
            "repo": {"owner": "owner", "name": "repo", "branch": "main",
                     "directory": "rusin-note"},
            "token": "at", "enabled": True,
        }

    def test_initial_remote_import(self, data_dir):
        from app.apps.gitee_sync import engine
        remote = {"abc": {"content": "# 远端\n", "sha": "s1",
                          "path": "rusin-note/notes/abc.md"}}
        manifest = {"notes": {"abc": {"tags": ["remote"], "folder": "inbox"}}}
        client = _FakeClient(remote, manifest)
        summary = engine.sync_user("sync_import", client, self._connection(),
                                   notify=False)
        expect(summary["pulled"] == 1, "首次同步导入远端笔记")
        expect(read_note("sync_import", "abc") == "# 远端\n", "远端内容写入站内")
        from app.core.tags import get_note_tags
        from app.core.folders import get_note_folder
        expect(get_note_tags("sync_import", "abc") == ["remote"], "导入仓库标签")
        expect(get_note_folder("sync_import", "abc") == "inbox", "导入仓库文件夹")

    def test_local_push_updates_base(self, data_dir):
        from app.apps.gitee_sync import engine, store
        write_note("sync_push", "local1", "# 本地\n")
        store.save_connection("sync_push", self._connection())
        client = _FakeClient()
        summary = engine.sync_user("sync_push", client, self._connection(),
                                   notify=False)
        expect(summary["pushed"] == 1, "站内笔记推送到仓库")
        state = store.get_sync_state("sync_push")
        expect(state["notes"]["local1"]["base_content"] == "# 本地\n",
               "推送后记录新的同步基线")

    def test_remote_change_pulls(self, data_dir):
        from app.apps.gitee_sync import engine, store
        write_note("sync_pull", "n1", "base\n")
        store.save_connection("sync_pull", self._connection())
        store.save_sync_state("sync_pull", {
            "notes": {"n1": {
                "base_content": "base\n", "remote_sha": "s0",
                "path": "rusin-note/notes/n1.md",
            }},
            "manifest": {},
        })
        remote = {"n1": {"content": "base\nremote\n", "sha": "s1",
                         "path": "rusin-note/notes/n1.md"}}
        summary = engine.sync_user("sync_pull", _FakeClient(remote),
                                   self._connection(), notify=False)
        expect(summary["pulled"] == 1, "远端修改拉回站内")
        expect(read_note("sync_pull", "n1") == "base\nremote\n", "站内内容已更新")

    def test_conflict_creates_copy_pr_and_notification(self, data_dir):
        from app.apps.gitee_sync import engine, store
        from app.apps.notifications import service as notifications
        write_note("sync_conflict", "n1", "local\n")
        store.save_connection("sync_conflict", self._connection())
        store.save_sync_state("sync_conflict", {
            "notes": {"n1": {
                "base_content": "base\n", "remote_sha": "s0",
                "path": "rusin-note/notes/n1.md",
            }},
            "manifest": {},
        })
        remote = {"n1": {"content": "remote\n", "sha": "s1",
                         "path": "rusin-note/notes/n1.md"}}
        client = _FakeClient(remote)
        summary = engine.sync_user("sync_conflict", client,
                                   self._connection(), notify=True)
        expect(summary["conflicts"] == 1, "并发修改进入冲突")
        expect(len(client.conflicts) == 1, "创建冲突分支与 PR")
        expect(notifications.unread_count("sync_conflict") == 1, "同步失败写入站内通知")
        state = store.get_sync_state("sync_conflict")
        expect("n1" in state["conflicts"], "冲突笔记暂停自动同步")

    def test_safe_remote_delete_propagates(self, data_dir):
        from app.apps.gitee_sync import engine, store
        write_note("sync_delete", "n1", "base\n")
        store.save_connection("sync_delete", self._connection())
        store.save_sync_state("sync_delete", {
            "notes": {"n1": {
                "base_content": "base\n", "remote_sha": "s0",
                "path": "rusin-note/notes/n1.md",
            }},
            "manifest": {},
        })
        summary = engine.sync_user("sync_delete", _FakeClient({}),
                                   self._connection(), notify=False)
        expect(summary["deleted_local"] == 1, "仓库安全删除传播到站内")
        expect(read_note("sync_delete", "n1") == "", "站内笔记已删除")


def _enable_gitee():
    set_flags({**{key: True for key in FEATURE_KEYS}, "gitee_sync": True})


def _configure_gitee(monkeypatch):
    monkeypatch.setattr(config, "GITEE_SYNC_CLIENT_ID", "client-id")
    monkeypatch.setattr(config, "GITEE_SYNC_CLIENT_SECRET", "client-secret")
    monkeypatch.setattr(config, "GITEE_SYNC_SCOPE", "user_info projects pull_requests hook")


class TestGiteeRoutes:
    def test_oauth_connect_callback_and_redaction(self, ctx, monkeypatch):
        from app.apps.gitee_sync import api, service, store
        logger.info("=== Gitee OAuth 连接 ===")
        _enable_gitee()
        _configure_gitee(monkeypatch)
        register_and_login(ctx.client, "gitee_conn")
        start = ctx.client.get("/user/gitee_conn/gitee/connect")
        expect(start.status_code == 302 and "gitee.com/oauth/authorize" in start.headers["Location"],
               "连接请求跳转 Gitee 授权")
        state = urllib.parse.parse_qs(
            urllib.parse.urlparse(start.headers["Location"]).query).get("state", [""])[0]
        monkeypatch.setattr(api, "exchange_code", lambda *a, **k: {
            "access_token": "secret-token", "refresh_token": "refresh",
            "expires_in": 3600})
        monkeypatch.setattr(api, "fetch_profile", lambda token: {
            "uid": "1", "login": "gitee_user", "display": "Gitee User",
            "email": "", "avatar": ""})
        callback = ctx.client.get(f"/gitee/callback?code=code1&state={state}")
        expect(callback.status_code == 302, "OAuth 回调成功")
        connection = store.get_connection("gitee_conn")
        expect(connection and connection["token"] == "secret-token", "Token 保存在服务端")
        page = ctx.client.get("/user/gitee_conn/gitee").get_data(as_text=True)
        expect("secret-token" not in page and "refresh" not in page, "页面不泄露 Token")

    def test_repository_setup(self, ctx, monkeypatch):
        from app.apps.gitee_sync import api, service, store
        logger.info("=== 绑定仓库 ===")
        _enable_gitee()
        _configure_gitee(monkeypatch)
        register_and_login(ctx.client, "gitee_repo")
        store.save_connection("gitee_repo", {
            "token": "at", "refresh_token": "", "expires_at": 0,
            "profile": {"login": "octo"}, "repo": {},
            "webhook_token": "wh-token", "webhook_secret": "wh-secret",
        })
        monkeypatch.setattr(api, "get_repository", lambda *a, **k: {
            "full_name": "octo/repo", "default_branch": "main"})
        monkeypatch.setattr(api, "create_webhook", lambda *a, **k: {"id": 11})
        csrf = csrf_of(ctx.client.get("/user/gitee_repo/gitee").get_data(as_text=True))
        response = ctx.client.post("/user/gitee_repo/gitee/setup", data={
            "csrf_token": csrf, "owner": "octo", "repo": "repo",
            "branch": "main", "directory": "rusin-note",
        })
        expect(response.status_code == 302, "绑定仓库成功")
        connection = store.get_connection("gitee_repo")
        expect(connection["repo"]["name"] == "repo", "仓库配置持久化")
        expect(connection.get("webhook_state") == "active", "自动创建 Webhook")

    def test_webhook_authentication_and_queue(self, ctx):
        from app.apps.gitee_sync import store
        logger.info("=== Webhook 校验与远程事件入队 ===")
        _enable_gitee()
        store.save_connection("hook_user", {
            "repo": {"owner": "o", "name": "r", "branch": "main",
                     "directory": "rusin-note"},
            "webhook_token": "hook-id", "webhook_secret": "hook-secret",
        })
        denied = ctx.anon.post("/gitee/webhook/hook-id", json={"after": "abc"})
        expect(denied.status_code in (401, 403), "错误 Webhook Token 被拒绝")
        accepted = ctx.anon.post(
            "/gitee/webhook/hook-id", json={"after": "abc"},
            headers={"X-Gitee-Token": "hook-secret", "X-Gitee-Event": "Push Hook"})
        expect(accepted.status_code == 202, "合法 Webhook 返回 202")
        expect("__remote__" in store.get_outbox("hook_user"), "远程变更进入待同步队列")

    def test_note_save_enqueues_sync(self, ctx):
        from app.apps.gitee_sync import store
        logger.info("=== 站内保存自动入队 ===")
        _enable_gitee()
        register_and_login(ctx.client, "queue_user")
        store.save_connection("queue_user", {
            "repo": {"owner": "o", "name": "r", "branch": "main",
                     "directory": "rusin-note"},
            "token": "at",
        })
        note_id = create_note(ctx.client, "queue_user", "# queued")
        expect(note_id in store.get_outbox("queue_user"), "保存笔记后自动加入同步队列")

    def test_feature_switch_gates_routes(self, ctx):
        logger.info("=== Gitee 同步功能开关 ===")
        register_and_login(ctx.client, "gitee_gate")
        set_flags({**{key: True for key in FEATURE_KEYS}, "gitee_sync": False})
        expect(ctx.client.get("/user/gitee_gate/gitee").status_code == 404,
               "功能关闭后同步页 404")

    def test_username_migration(self, ctx):
        from app.apps.gitee_sync import store
        from app.apps.notifications import service as notifications
        from app.apps.user.service import rename_user
        logger.info("=== 改名迁移 Gitee 连接与通知 ===")
        _enable_gitee()
        register_and_login(ctx.client, "gitee_old")
        store.save_connection("gitee_old", {
            "repo": {"owner": "o", "name": "r", "branch": "main",
                     "directory": "rusin-note"},
            "token": "at",
        })
        notifications.add("gitee_old", "gitee_sync", "同步失败")
        expect(rename_user("gitee_old", "gitee_new", "TestPass1!") is None,
               "改名成功")
        expect((store.get_connection("gitee_new") or {}).get("token") == "at",
               "Gitee 连接迁移到新用户名")
        expect(notifications.unread_count("gitee_new") == 1, "通知迁移到新用户名")

