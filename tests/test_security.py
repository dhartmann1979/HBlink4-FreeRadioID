"""
Hardening of the web interface (N8 security, N8 update guard) and of the text fields a device sends.
"""
import asyncio
import json
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

from dashboard import n8_security
from dashboard.auth import AuthStore
from hblink4.hblink import _clean_text_field

ROOT = Path(__file__).resolve().parent.parent


class TestHeadersAndDocs(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient
        from dashboard import server
        cls.server = server
        server.dashboard_config["auth"] = {"superadmin": {"username": "boss", "password": "SuperSecret1"},
                                           "public_dashboard": True}
        server.state.auth = AuthStore(Path(tempfile.mkdtemp()) / "sec.db")
        cls.client = TestClient(server.app)

    def test_api_docs_are_off(self):
        for path in ("/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect"):
            r = self.client.get(path)
            self.assertNotEqual(r.status_code, 200, path)
            self.assertNotIn("swagger", r.text.lower())
            self.assertNotIn('"paths"', r.text)

    def test_security_headers(self):
        r = self.client.get("/api/version")
        h = r.headers
        csp = h["content-security-policy"]
        for part in ("default-src 'self'", "object-src 'none'", "base-uri 'self'", "frame-ancestors 'self'", "form-action 'self'"):
            self.assertIn(part, csp)
        self.assertNotIn("http:", csp.replace("https:", ""))          # no plain-HTTP sources
        self.assertIn("camera=()", h["permissions-policy"])
        self.assertEqual(h["x-content-type-options"], "nosniff")
        self.assertEqual(h["x-frame-options"], "SAMEORIGIN")
        self.assertNotIn("strict-transport-security", h)                 # plain HTTP: no HSTS
        self.assertNotIn("server", h)

    def test_hsts_behind_https_proxy(self):
        r = self.client.get("/api/version", headers={"X-Forwarded-Proto": "https"})
        self.assertIn("max-age=", r.headers["strict-transport-security"])

    def test_uvicorn_without_server_header(self):
        self.assertFalse(n8_security.UVICORN_KWARGS["server_header"])
        srv = self.server._Server.make(self.server.app, host="127.0.0.1", port=1)
        self.assertFalse(srv.config.server_header)


class TestCleanTextField(unittest.TestCase):
    def test_markup_dropped_length_kept(self):
        raw = b'DL1<img src=x onerror=alert(1)>'
        out = _clean_text_field(raw)
        self.assertEqual(len(out), len(raw))
        for ch in b'<>"\'`':
            self.assertNotIn(ch, out)

    def test_url_keeps_ampersand(self):
        self.assertEqual(_clean_text_field(b"https://x.de/?a=1&b=2", keep_amp=True), b"https://x.de/?a=1&b=2")
        self.assertNotIn(b"&", _clean_text_field(b"A&B"))

    def test_control_codes(self):
        self.assertEqual(_clean_text_field(b"A\x1bB\x7f\x00").rstrip(b" "), b"AB\x00")


class TestN8Admin(unittest.TestCase):
    """Update, Rechte-Check, sudo und Dienste über scripts/n8-admin.sh (wie N8 Crosslink) – ohne den alten update guard."""

    def test_wired(self):
        import subprocess
        unit = (ROOT / "hblink4-dash.service").read_text()
        self.assertNotIn("n8-update-guard", unit)
        self.assertIn("NoNewPrivileges=no", unit)
        self.assertNotIn("CapabilityBoundingSet=CAP_NET_BIND_SERVICE", unit)
        self.assertIn('n8-admin.sh" update', (ROOT / "scripts" / "update.sh").read_text())
        conf = (ROOT / "scripts" / "n8-admin.conf").read_text()
        self.assertIn("N8_ID=hblink4", conf)
        for f in ("n8-admin.sh", "n8-admin.conf", "update.sh", "install_services.sh"):
            self.assertEqual(subprocess.run(["bash", "-n", str(ROOT / "scripts" / f)]).returncode, 0, f)
        self.assertIn("n8-admin.sh\" fix-perms", (ROOT / "scripts" / "install_services.sh").read_text())


class TestKitFiles(unittest.TestCase):
    """The N8 Kit is shared with N8 Crosslink, adn-frn-server and N8-HotSpot: it must be complete."""

    def test_pages_load_kit_and_dictionary(self):
        for page in ("dashboard.html", "aprs.html"):
            html = (ROOT / "dashboard" / "static" / page).read_text()
            for f in ("/static/n8-kit.css", "/static/n8-kit.js", "/static/i18n-dashboard.js"):
                self.assertIn(f, html, (page, f))

    def test_dictionary_parses(self):
        js = (ROOT / "dashboard" / "static" / "i18n-dashboard.js").read_text()
        self.assertIn("base: 'en'", js)
        self.assertIn("'Last heard': 'Zuletzt gehört'", js)


if __name__ == "__main__":
    unittest.main()


class TestBackupAndGuard(unittest.TestCase):
    """Backups (PR #2) and the N8 update guard must not get in each other's way."""

    def test_guard_state_not_in_backups(self):
        from dashboard import backup
        for name in ("update.pending", "update.pending.tmp", "update.result"):
            self.assertIn(name, backup.EXCLUDED)

    def test_update_and_backup_exclude_each_other(self):
        src = (ROOT / "dashboard" / "server.py").read_text()
        install = src[src.index("async def api_admin_update_install"):src.index("@app.get(\"/api/admin/system\")")]
        self.assertIn("_backup_idle()", install)
        idle = src[src.index("def _backup_idle():"):src.index("@app.exception_handler(_backup.BackupError)")]
        self.assertIn("_update_lock.locked()", idle)

    def test_backup_routes_hidden_from_docs(self):
        from fastapi.testclient import TestClient
        from dashboard import server
        c = TestClient(server.app)
        self.assertNotEqual(c.get("/openapi.json").status_code, 200)
        r = c.get("/api/admin/backup")
        self.assertIn(r.status_code, (401, 403))
        self.assertIn("default-src 'self'", r.headers["content-security-policy"])


class TestConnectedSystemsCards:
    """1.6.1: one grid, one card renderer; no raw fmtAddr HTML escaped into text."""
    html = (Path(__file__).resolve().parents[1] / "dashboard" / "static" / "dashboard.html").read_text(encoding="utf-8")

    def test_single_grid_replaces_masonry(self):
        assert 'id="connAll"' in self.html and 'class="conn-columns"' not in self.html
        assert "column-count" not in self.html.split("/* ---- Connected systems")[1].split("</style>")[0]

    def test_all_kinds_use_conn_card(self):
        for kind in ("openbridge", "outbound"):
            assert f"kind: '{kind}'" in self.html
        assert "kind: sectionName" in self.html

    def test_outbound_status_not_double_escaped(self):
        assert "escapeHtml(statusText)}</span>` : ''" not in self.html
        assert "fmtAddr(o.remote_address, o.remote_port)\n                    : `<span class=" in self.html

    def test_obp_click_uses_data_attribute(self):
        assert "obpOpen(this.closest(\\'.conn-card\\').dataset.obp)" in self.html


class TestLastHeardEndpoint:
    def test_route_exists_and_is_redacted(self):
        src = (Path(__file__).resolve().parents[1] / "dashboard" / "server.py").read_text(encoding="utf-8")
        i = src.index('@app.get("/api/last-heard")')
        assert "view_for(current_user(request)" in src[i:i + 400]
