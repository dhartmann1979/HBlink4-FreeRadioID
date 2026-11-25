"""HobbyRadioPortal on the same server (since 1.11.0): no API token – a direct call from this machine is the portal."""
import tempfile
import unittest
from pathlib import Path

from dashboard.auth import AuthStore

P = {"X-HobbyRadioPortal": "1", "X-Dashboard": "1", "X-Portal-User": "dirk<x>"}


class TestPortalLocal(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient
        from dashboard import server
        cls.server = server
        server.dashboard_config["auth"] = {"superadmin": {"username": "boss", "password": "SuperSecret1"},
                                           "public_dashboard": False}
        server.state.auth = AuthStore(Path(tempfile.mkdtemp()) / "http.db")
        server.state.auth.sync_superadmin(server.dashboard_config)
        # wie das Portal: von 127.0.0.1 an http://127.0.0.1:8080/
        cls.local = TestClient(server.app, base_url="http://127.0.0.1:8080", client=("127.0.0.1", 50000))
        cls.remote = TestClient(server.app)

    @classmethod
    def tearDownClass(cls):
        cls.server.dashboard_config["auth"]["public_dashboard"] = True

    def test_allowed_paths(self):
        r = self.local.get("/api/admin/settings", headers=P)
        self.assertEqual(r.status_code, 200)
        self.assertIn("aprs_daprs", [s["id"] for s in r.json()["sections"]])
        self.assertEqual(self.local.get("/api/admin/aprs", headers=P).status_code, 200)

    def test_not_the_portal(self):
        self.assertEqual(self.local.get("/api/admin/settings", headers={"X-Dashboard": "1"}).status_code, 401)   # ohne Kennung
        self.assertEqual(self.remote.get("/api/admin/settings", headers=P).status_code, 401)                     # anderer Rechner
        for extra in ({"X-Forwarded-For": "203.0.113.9"}, {"X-Real-IP": "203.0.113.9"}, {"Forwarded": "for=1.2.3.4"},
                      {"Via": "1.1 caddy"}, {"Host": "dmr.example.org"}):
            self.assertEqual(self.local.get("/api/admin/settings", headers={**P, **extra}).status_code, 401, extra)

    def test_forbidden_paths(self):
        for path in ("/api/admin/users", "/api/admin/sessions", "/api/admin/backup"):
            self.assertIn(self.local.get(path, headers=P).status_code, (401, 403), path)
        self.assertEqual(self.local.get("/api/admin/api-tokens", headers=P).status_code, 401)   # gibt es nicht mehr
        r = self.local.post("/api/auth/password", json={"old": "x", "new": "yyyyyyyyyy"}, headers=P)
        self.assertEqual(r.status_code, 401)

    def test_locked_settings(self):
        r = self.local.put("/api/admin/settings", json={"changes": {"auth.public_dashboard": True}}, headers=P)
        self.assertEqual(r.status_code, 403)
        r = self.local.post("/api/admin/settings/reset", json={"section": "https"}, headers=P)
        self.assertEqual(r.status_code, 403)

    def test_change_daprs_setting_is_audited(self):
        r = self.local.put("/api/admin/settings", json={"changes": {"daprs.ssid": 9}}, headers=P)
        self.assertEqual(r.status_code, 200, r.text)
        log = self.server.state.auth.audit_log(20)
        self.assertTrue(any(e["username"] == "portal (dirkx)" and e["action"] == "settings_changed" for e in log))
        self.local.put("/api/admin/settings", json={"changes": {"daprs.ssid": 7}}, headers=P)

    def test_csrf_header_still_required(self):
        h = dict(P)
        h.pop("X-Dashboard")
        self.assertEqual(self.local.put("/api/admin/settings", json={"changes": {}}, headers=h).status_code, 403)

    def test_switch_off(self):
        self.server.PORTAL_LOCAL = False
        try:
            self.assertEqual(self.local.get("/api/admin/settings", headers=P).status_code, 401)
        finally:
            self.server.PORTAL_LOCAL = True


if __name__ == "__main__":
    unittest.main()
