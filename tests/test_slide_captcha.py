"""滑动拼图验证码端到端 + 单元测试（pytest + logging）。

覆盖：阻尼曲线可达/单调/随机、SVG 不泄露文本、页面与刷新端点渲染、
位置对齐校验、一次性/过期/缺失拒绝、类人轨迹登录注册成功；
IP 风险体系：机器轨迹静默放行但累计风险、升级后更难通过、第二次注册标记风控、
风险分时间衰减；以及 type=image 切回原图形码。

运行：``pytest tests/test_slide_captcha.py``
"""
from __future__ import annotations

import json
import logging
import re
import time

import pytest

from app.core import captcha_risk as cr
from app.core import config
from app.core import slide_captcha as sc
from app.core.storage import storage
from app.core.store import get_user
from support import (
    DEFAULT_PASSWORD, _human_traj, _solve_slide, csrf_of, expect, logout,
)

logger = logging.getLogger("rusin.tests.slide")

_TOKEN_RE = re.compile(r'name="captcha_token"[^>]*value="([^"]+)"')


def _token_of(html: str) -> str:
    m = _TOKEN_RE.search(html)
    expect(bool(m), "页面含验证码 token")
    return m.group(1)


def _bot_traj(d: float) -> list:
    """瞬移轨迹：两步覆盖全程、完全水平 → suspicion 极高。"""
    return [{"x": 0, "y": 0, "t": 0}, {"x": round(d, 2), "y": 0, "t": 30}]


def _register_slide(client, username, bot=False):
    page = client.get("/register")
    html = page.get_data(as_text=True)
    fields = _solve_slide(_token_of(html))
    if bot:
        fields["captcha_traj"] = json.dumps(_bot_traj(float(fields["captcha_x"])))
    data = {
        "username": username, "password": DEFAULT_PASSWORD, "confirm": DEFAULT_PASSWORD,
        "csrf_token": csrf_of(html), "agree_terms": "1", **fields,
    }
    return client.post("/register", data=data)


def _login_slide(client, username, bot=False, token=None, x=None, traj=None):
    html = client.get("/login").get_data(as_text=True)
    fields = _solve_slide(token or _token_of(html))
    if bot:
        fields["captcha_traj"] = json.dumps(_bot_traj(float(fields["captcha_x"])))
    if x is not None:
        fields["captcha_x"] = str(x)
    if traj is not None:
        fields["captcha_traj"] = json.dumps(traj)
    data = {
        "username": username, "password": DEFAULT_PASSWORD,
        "csrf_token": csrf_of(html), **fields,
    }
    return client.post("/login", data=data), fields


class TestSlideCurve:
    """阻尼曲线与 SVG 生成的单元性质（每次随机，重复采样验证不变量）。"""

    def test_curve_reachable_and_monotonic(self, data_dir):
        logger.info("=== [A] 曲线可达且单调 ===")
        for _ in range(40):
            tok, ch = sc.generate()
            curve, S, tm = ch["curve"], ch["S"], ch["tm"]
            expect(abs(sc.curve_value(curve, S) - tm) < 1e-6, "滑块到底拼图达最远端")
            expect(all(curve[i + 1][1] >= curve[i][1] for i in range(len(curve) - 1)),
                   "曲线单调不减")
            expect(curve[0] == [0.0, 0.0], "起点为零")

    def test_damping_varies(self, data_dir):
        logger.info("=== [B] 随机阻尼：局部斜率有差异 ===")
        varied = 0
        for _ in range(30):
            tok, ch = sc.generate()
            curve = ch["curve"]
            slopes = [(curve[i + 1][1] - curve[i][1]) / ((curve[i + 1][0] - curve[i][0]) or 1)
                      for i in range(len(curve) - 1)]
            if max(slopes) - min(slopes) > 0.15:
                varied += 1
        expect(varied >= 25, "绝大多数挑战的局部斜率明显不同（过滑/阻滞手感）")

    def test_target_reachable_before_end(self, data_dir):
        logger.info("=== [C] 缺口在滑块到底前可达 ===")
        for _ in range(40):
            tok, ch = sc.generate()
            sec = sc.peek(tok)
            target, curve, S = sec["t"], sec["curve"], sec["S"]
            lo, hi = 0.0, S
            for _ in range(60):
                mid = (lo + hi) / 2
                if sc.curve_value(curve, mid) < target:
                    lo = mid
                else:
                    hi = mid
            d = (lo + hi) / 2
            expect(d < S, "对齐缺口所需滑块位移 < 满量程")
            expect(abs(sc.curve_value(curve, d) - target) < 0.5, "反解位置命中缺口")

    def test_svg_no_plaintext(self, data_dir):
        logger.info("=== [D] SVG 不含可读文本节点 ===")
        tok, ch = sc.generate()
        expect("<text" not in ch["bg"] and "<text" not in ch["piece"], "背景/拼图均无 text 元素")
        expect("<svg" in ch["bg"] and "<svg" in ch["piece"], "返回内联 SVG")


class TestSlideFlow:
    def test_page_render(self, ctx):
        logger.info("=== [E] 登录/注册页渲染滑动拼图 ===")
        for path in ("/login", "/register"):
            html = ctx.client.get(path).get_data(as_text=True)
            expect("slideCaptcha" in html, f"{path} 含滑动容器")
            expect('name="captcha_x"' in html and 'name="captcha_traj"' in html,
                   f"{path} 含位移/轨迹隐藏字段")
            expect("slide-thumb" in html and "<svg" in html, f"{path} 含滑块与 SVG")
            expect("/login/captcha" in html, f"{path} 刷新脚本就位")

    def test_refresh_endpoint(self, ctx):
        logger.info("=== [F] 刷新端点返回滑动挑战 ===")
        resp = ctx.client.get("/login/captcha")
        expect(resp.status_code == 200, "刷新端点 200")
        d = json.loads(resp.data)
        expect(d.get("type") == "slide", "类型为 slide")
        expect(d.get("token") and "<svg" in d.get("bg", "") and "curve" in d,
               "返回 token/背景/曲线")
        expect(bool(sc.peek(d["token"])), "新 token 可校验")

    def test_correct_registers(self, ctx):
        logger.info("=== [G] 类人轨迹注册成功 ===")
        resp = _register_slide(ctx.client, "slideok")
        expect(resp.status_code == 302, "对齐 + 类人轨迹注册 -> 302")
        expect(bool((get_user("slideok") or {}).get("salt")), "用户已创建")

    def test_wrong_position_rejected(self, ctx):
        logger.info("=== [H] 位置未对齐拒绝 ===")
        resp = _register_slide(ctx.client, "slidebad")
        # 重新取一个挑战，提交错误位移
        html = ctx.client.get("/register").get_data(as_text=True)
        fields = _solve_slide(_token_of(html))
        fields["captcha_x"] = "3"
        data = {"username": "slidebad2", "password": DEFAULT_PASSWORD, "confirm": DEFAULT_PASSWORD,
                "csrf_token": csrf_of(html), "agree_terms": "1", **fields}
        resp = ctx.client.post("/register", data=data)
        expect(resp.status_code == 400, "错位返回 400")
        expect(not (get_user("slidebad2") or {}).get("salt"), "用户未被创建")

    def test_missing_captcha_rejected(self, ctx):
        logger.info("=== [I] 缺失验证码拒绝 ===")
        html = ctx.client.get("/register").get_data(as_text=True)
        resp = ctx.client.post("/register", data={
            "username": "slide_missing", "password": DEFAULT_PASSWORD, "confirm": DEFAULT_PASSWORD,
            "csrf_token": csrf_of(html), "agree_terms": "1",
        })
        expect(resp.status_code == 400, "缺失验证码返回 400")

    def test_replay_rejected(self, ctx):
        logger.info("=== [J] 一次性：重放失效 ===")
        _register_slide(ctx.client, "slidereplay")
        logout(ctx.client)
        resp, fields = _login_slide(ctx.client, "slidereplay")
        expect(resp.status_code in (200, 302), "首次登录成功")
        logout(ctx.client)
        html = ctx.client.get("/login").get_data(as_text=True)
        resp2 = ctx.client.post("/login", data={
            "username": "slidereplay", "password": DEFAULT_PASSWORD,
            "csrf_token": csrf_of(html), **fields,
        })
        expect(resp2.status_code == 400, "同一 token 重放被拒")

    def test_expired_rejected(self, ctx):
        logger.info("=== [K] 过期挑战拒绝 ===")
        tok, ch = sc.generate(ttl=-1)
        html = ctx.client.get("/login").get_data(as_text=True)
        resp = ctx.client.post("/login", data={
            "username": "x", "password": DEFAULT_PASSWORD, "csrf_token": csrf_of(html),
            "captcha_token": tok, "captcha_x": "50", "captcha_traj": "[]",
        })
        expect(resp.status_code == 400, "过期 token 返回 400")

    def test_correct_login(self, ctx):
        logger.info("=== [L] 类人轨迹登录成功 ===")
        _register_slide(ctx.client, "slidelogin")
        logout(ctx.client)
        resp, _ = _login_slide(ctx.client, "slidelogin")
        expect(resp.status_code in (200, 302), "登录成功")
        expect(ctx.client.get("/user/slidelogin").status_code == 200, "会话已建立")


class TestSlideRisk:
    def test_silent_pass_accumulates(self, ctx):
        logger.info("=== [M] 机器轨迹静默放行但累计风险 ===")
        ctx.client.environ_base["REMOTE_ADDR"] = "203.0.113.11"
        _register_slide(ctx.client, "riskuser")
        logout(ctx.client)
        before = cr.get_state("203.0.113.11")["score"]
        resp, _ = _login_slide(ctx.client, "riskuser", bot=True)
        expect(resp.status_code in (200, 302), "位置对齐 → 机器轨迹仍静默放行")
        after = cr.get_state("203.0.113.11")
        expect(after["score"] > before, "风险分上升")
        expect(after["suspicious"] >= 1, "可疑放行计数增加")

    def test_escalation_blocks_bot(self, ctx):
        logger.info("=== [N] 风险升级后机器轨迹更难通过 ===")
        ip = "203.0.113.22"
        ctx.client.environ_base["REMOTE_ADDR"] = ip
        _register_slide(ctx.client, "escuser")
        logout(ctx.client)
        for i in range(3):
            resp, _ = _login_slide(ctx.client, "escuser", bot=True)
            expect(resp.status_code in (200, 302), f"第 {i+1} 次机器放行（tier0 静默）")
            logout(ctx.client)
        expect(cr.get_state(ip)["tier"] >= 1, "累计后进入升级档")
        tol, require_human = cr.difficulty(ip)
        expect(require_human and tol < 6, "升级档收紧容差并要求类人轨迹")
        resp, _ = _login_slide(ctx.client, "escuser", bot=True)
        expect(resp.status_code == 400, "升级后机器轨迹被拒")

    def test_second_registration_flagged(self, ctx):
        logger.info("=== [O] 可疑 IP 第二次注册标记风控 ===")
        ip = "203.0.113.33"
        ctx.client.environ_base["REMOTE_ADDR"] = ip
        r1 = _register_slide(ctx.client, "flagone", bot=True)
        expect(r1.status_code == 302, "第一次注册成功（静默）")
        expect(not cr.is_flagged("flagone"), "首次注册暂不标记")
        logout(ctx.client)
        r2 = _register_slide(ctx.client, "flagtwo", bot=True)
        expect(r2.status_code == 302, "第二次注册仍成功（不打草惊蛇）")
        expect(cr.is_flagged("flagtwo"), "第二次注册被标记风控")
        expect(bool((get_user("flagtwo") or {}).get("risk_flagged")), "账号已打风控标")

    def test_decay(self, ctx):
        logger.info("=== [P] 风险分随时间衰减 ===")
        ip = "203.0.113.44"
        cr.record(ip, True, 100.0)
        s0 = cr.get_state(ip)["score"]
        expect(s0 > 0, "记录后有风险分")
        data = storage.get(cr.K_RISK)
        data[ip]["updated"] = time.time() - cr._float("decay_hours", 12) * 3600
        storage.set(cr.K_RISK, data)
        s1 = cr.get_state(ip)["score"]
        expect(abs(s1 - s0 / 2) < 0.6, "经过一个半衰期分数约减半")

    def test_human_pass_no_risk(self, ctx):
        logger.info("=== [Q] 类人放行不累积风险 ===")
        ip = "203.0.113.55"
        ctx.client.environ_base["REMOTE_ADDR"] = ip
        _register_slide(ctx.client, "cleanuser")
        expect(cr.get_state(ip)["score"] == 0, "类人注册零风险分")
        expect(cr.get_state(ip)["tier"] == 0, "保持正常档")


class TestCaptchaType:
    def test_image_switch(self, ctx):
        logger.info("=== [R] 配置切回原图形验证码 ===")
        old = config.CAPTCHA_TYPE
        config.CAPTCHA_TYPE = "image"
        try:
            html = ctx.client.get("/login").get_data(as_text=True)
            expect('name="captcha"' in html and "slideCaptcha" not in html,
                   "image 类型渲染文本验证码而非滑动")
            d = json.loads(ctx.client.get("/login/captcha").data)
            expect(d.get("type") == "image" and "<svg" in d.get("svg", ""), "刷新端点返回图形码")
        finally:
            config.CAPTCHA_TYPE = old