"""📰 Portal feed for the adn-frn-server: live summary, encrypted with the sync key (dashboard/n8feed.py)."""
import secrets
import time
import unittest

from dashboard import n8feed

KEY = "p" * 32


def request(key=KEY, path=n8feed.PATH, ts=None):
    return n8feed.seal({"path": path, "ts": ts or time.time(), "id": secrets.token_hex(8), "data": {}}, key)


class TestFeed(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient
        from dashboard import server
        cls.server = server
        cls.client = TestClient(server.app)

    def setUp(self):
        self.saved = dict(self.server.dashboard_config.get("portal_feed") or {})

    def tearDown(self):
        self.server.dashboard_config["portal_feed"] = self.saved

    def post(self, body):
        return self.client.post(n8feed.PATH, content=body, headers={"Content-Type": n8feed.CTYPE})

    def test_off_by_default_and_wrong_key(self):
        self.server.dashboard_config["portal_feed"] = {"enabled": False, "key": KEY}
        self.assertEqual(self.post(request()).status_code, 404)
        self.server.dashboard_config["portal_feed"] = {"enabled": True, "key": KEY}
        self.assertEqual(self.post(request("x" * 32)).status_code, 403)
        self.assertEqual(self.post(b"plain").status_code, 403)

    def test_summary(self):
        self.server.dashboard_config["portal_feed"] = {"enabled": True, "key": KEY}
        st = self.server.state
        st.last_heard.insert(0, {"radio_id": 2629999, "callsign": "DL1XYZ", "source_name": "DB0ABC (262123)", "talkgroup": 2623,
                                 "last_heard": time.time(), "address": "203.0.113.9"})
        body = request()
        r = self.post(body)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertNotIn(b"DL1XYZ", r.content)                     # encrypted
        out = n8feed.unseal(r.content, KEY)
        d = out["data"]
        self.assertEqual(d["system"], "hblink4")
        self.assertTrue(any(x["call"] == "DL1XYZ" and "TG 2623" in x["where"] for x in d["last_heard"]))
        self.assertNotIn("203.0.113.9", str(d))
        self.assertEqual(self.post(body).status_code, 403)          # a recorded request cannot be sent again
        st.last_heard.pop(0)

    def test_expired(self):
        self.server.dashboard_config["portal_feed"] = {"enabled": True, "key": KEY}
        self.assertEqual(self.post(request(ts=1)).status_code, 403)
