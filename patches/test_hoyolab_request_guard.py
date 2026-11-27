import importlib
import os
import sys
import types
import unittest


class FakeResponse:
    def __init__(self, payload, status=200):
        self.payload = payload
        self.status_code = status

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append(("GET", url))
        return self.responses.pop(0)

    def post(self, url, **kwargs):
        self.calls.append(("POST", url))
        return self.responses.pop(0)


class RequestGuardTests(unittest.TestCase):
    def setUp(self):
        self.old_modules = {name: sys.modules.get(name) for name in ("setting", "config", "request", "loghelper")}
        setting = types.ModuleType("setting")
        setting.os_referer_url = "https://example.invalid/"
        setting.os_zzz_act_id = "zzz"
        setting.os_genshin_act_id = "genshin"
        setting.os_honkai_sr_act_id = "sr"
        setting.os_honkai3rd_act_id = "bh3"
        setting.os_tearsofthemis_act_id = "themis"
        self.config = types.ModuleType("config")
        self.config.config = {"games": {"os": {"enable": True, "cookie": "uid=123; token=abc", "lang": "zh-cn",
            "genshin": {"checkin": True}, "zzz": {"checkin": True}}}}
        request = types.ModuleType("request")
        request.get_new_session = lambda: None
        loghelper = types.ModuleType("loghelper")
        loghelper.log = types.SimpleNamespace(info=lambda *a, **k: None, warning=lambda *a, **k: None,
            error=lambda *a, **k: None, debug=lambda *a, **k: None, exception=lambda *a, **k: None)
        for name, module in (("setting", setting), ("config", self.config), ("request", request), ("loghelper", loghelper)):
            sys.modules[name] = module
        sys.path.insert(0, os.environ["HOYOLAB_TEST_PACKAGE"])
        sys.modules.pop("hoyo_checkin", None)
        self.module = importlib.import_module("hoyo_checkin")

    def tearDown(self):
        sys.modules.pop("hoyo_checkin", None)
        if os.environ["HOYOLAB_TEST_PACKAGE"] in sys.path:
            sys.path.remove(os.environ["HOYOLAB_TEST_PACKAGE"])
        for name, module in self.old_modules.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module
        os.environ.pop(self.module.COOKIE_INVALID_ENV, None)

    def test_already_signed_uses_one_status_request_only(self):
        session = FakeSession([FakeResponse({"retcode": 0, "data": {"is_sign": True}})])
        self.module.get_new_session = lambda: session
        result = self.module.hoyo_checkin("https://api.invalid/event", "act")
        self.assertEqual(result, "今天已经签到过")
        self.assertEqual(len(session.calls), 1)
        self.assertEqual(session.calls[0][0], "GET")

    def test_expired_cookie_stops_before_rewards_and_sign(self):
        session = FakeSession([FakeResponse({"retcode": -100, "message": "login expired"})])
        self.module.get_new_session = lambda: session
        with self.assertRaises(self.module.HoyoCookieExpired):
            self.module.hoyo_checkin("https://api.invalid/event", "act")
        self.assertEqual(len(session.calls), 1)

    def test_reward_auth_failure_never_posts_sign(self):
        session = FakeSession([
            FakeResponse({"retcode": 0, "data": {"is_sign": False, "first_bind": False, "total_sign_day": 1}}),
            FakeResponse({"retcode": -100, "message": "login expired"}),
        ])
        self.module.get_new_session = lambda: session
        with self.assertRaises(self.module.HoyoCookieExpired):
            self.module.hoyo_checkin("https://api.invalid/event", "act")
        self.assertEqual([call[0] for call in session.calls], ["GET", "GET"])

    def test_success_posts_once_without_retry(self):
        session = FakeSession([
            FakeResponse({"retcode": 0, "data": {"is_sign": False, "first_bind": False, "total_sign_day": 1, "today": "2026-11-27"}}),
            FakeResponse({"retcode": 0, "data": {"awards": [{"cnt": 1, "name": "reward"}]}}),
            FakeResponse({"retcode": 0, "message": "OK"}),
        ])
        self.module.get_new_session = lambda: session
        result = self.module.hoyo_checkin("https://api.invalid/event", "act")
        self.assertIn("reward", result)
        self.assertEqual([call[0] for call in session.calls], ["GET", "GET", "POST"])

    def test_persisted_invalid_fingerprint_blocks_all_requests(self):
        cookie = self.config.config["games"]["os"]["cookie"]
        os.environ[self.module.COOKIE_INVALID_ENV] = self.module.cookie_fingerprint(cookie)
        self.module.get_new_session = lambda: self.fail("must not create an HTTP session")
        result = self.module.run_task()
        self.assertIn("永久标记作废", result)

    def test_expiry_stops_other_enabled_games_in_same_invocation(self):
        session = FakeSession([FakeResponse({"retcode": -100, "message": "login expired"})])
        self.module.get_new_session = lambda: session
        result = self.module.run_task()
        self.assertIn("已停止", result)
        self.assertEqual(len(session.calls), 1)
        self.assertEqual(self.config.config["games"]["os"]["cookie"], "CookieError")
        self.assertFalse(self.config.config["games"]["os"]["enable"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
