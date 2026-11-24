"""Umzug ins HobbyRadioPortal: Umzugscode, verschlüsseltes Paket (n8mig) und der „portalfertige“ Klon."""
import contextlib
import json
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from dashboard import backup, migration, n8mig
from tests.test_backup import BackupFixture


class TestN8Mig(unittest.TestCase):
    def test_roundtrip_tamper_and_wrong_code(self):
        d = Path(tempfile.mkdtemp())
        src = d / "plain.bin"
        src.write_bytes(bytes(range(256)) * 9000 + b"end")          # > 2 MiB → mehrere Blöcke
        code, cid, sha = n8mig.new_code("hb4m")
        prefix, cid2, secret = n8mig.parse_code(code)
        self.assertEqual((prefix, cid2, n8mig.secret_hash(secret)), ("hb4m", cid, sha))
        n8mig.encrypt_file(src, d / "pkg", secret)
        self.assertTrue((d / "pkg").read_bytes().startswith(n8mig.MAGIC))
        self.assertNotIn(b"end", (d / "pkg").read_bytes()[-40:])
        n8mig.decrypt_file(d / "pkg", d / "out", secret)
        self.assertEqual((d / "out").read_bytes(), src.read_bytes())
        with self.assertRaises(n8mig.MigrationError):
            n8mig.decrypt_file(d / "pkg", d / "bad", "x" * 32)
        self.assertFalse((d / "bad").exists())                      # nichts Ungeprüftes bleibt liegen
        blob = bytearray((d / "pkg").read_bytes())
        blob[5000] ^= 1
        (d / "pkg2").write_bytes(bytes(blob))
        with self.assertRaises(n8mig.MigrationError):
            n8mig.decrypt_file(d / "pkg2", d / "bad2", secret)
        self.assertFalse((d / "bad2").exists())
        for bad in ("", "hb4m_123.x", "hb4m_zzzzzzzz." + "a" * 32, code + "x"):
            with self.assertRaises(n8mig.MigrationError):
                n8mig.parse_code(bad)


class TestCodes(unittest.TestCase):
    def setUp(self):
        self.codes = migration.Codes(Path(tempfile.mkdtemp()))

    def test_uses_expiry_revoke_and_lockout(self):
        c = self.codes.create("boss")
        self.assertTrue(c["code"].startswith("hb4m_"))
        self.assertNotIn(c["code"].split(".")[1], self.codes.path.read_text())   # nur der Hash ist gespeichert
        self.assertEqual(self.codes.check(c["code"], "1.2.3.4")["id"], c["id"])
        for _ in range(migration.MAX_USES):
            self.codes.check(c["code"], "1.2.3.4", use=True)
        with self.assertRaisesRegex(n8mig.MigrationError, "aufgebraucht"):
            self.codes.check(c["code"], "1.2.3.4")
        c2 = self.codes.create("boss")
        self.assertTrue(self.codes.revoke(c2["id"]))
        with self.assertRaisesRegex(n8mig.MigrationError, "widerrufen"):
            self.codes.check(c2["code"], "1.2.3.4")
        c3 = self.codes.create("boss")
        with patch("time.time", return_value=time.time() + migration.TTL + 5):
            with self.assertRaisesRegex(n8mig.MigrationError, "abgelaufen"):
                self.codes.check(c3["code"], "1.2.3.4")
        self.assertEqual({x["state"] for x in self.codes.list()}, {"used", "revoked", "active"})
        for _ in range(migration.FAIL_LIMIT):
            with self.assertRaises(n8mig.MigrationError):
                self.codes.check("hb4m_00000000." + "a" * 32, "6.6.6.6")
        with self.assertRaisesRegex(n8mig.MigrationError, "15 Minuten"):
            self.codes.check(c3["code"], "6.6.6.6")
        with self.assertRaisesRegex(n8mig.MigrationError, "hb4m_"):
            self.codes.check("n8xm_00000000." + "a" * 32, "1.1.1.1")

    def test_info_lists_domains_and_ports(self):
        i = migration.info({"https.enabled": True, "https.domain": "dmr.example.org", "aprs.site1.domain": "aprs.example.org",
                            "aprs.enabled": True, "aprs.server.enabled": True, "dmr.global.port_ipv4": 62031,
                            "dmr.openbridge_connections": [{"name": "OBP-X", "port": 62044}]}, version="1.8.0", users=3, repeaters=2)
        self.assertEqual([d["domain"] for d in i["domains"]], ["dmr.example.org", "aprs.example.org"])
        self.assertEqual([(p["port"], p["proto"]) for p in i["ports"]], [(62031, "udp"), (62044, "udp"), (14580, "tcp"), (10152, "tcp")])
        self.assertTrue(i["https_before"])


class TestMigrationApi(BackupFixture):
    def setUp(self):
        super().setUp()
        from dashboard import server
        from fastapi.testclient import TestClient
        self.server = server
        saved = (server.state.auth, server.state._data_dir)
        server.state.auth, server.state._data_dir = self.auth, self.data
        self.addCleanup(lambda: (setattr(server.state, "auth", saved[0]), setattr(server.state, "_data_dir", saved[1])))
        self.auth._db.execute("INSERT OR REPLACE INTO settings(key,value,updated_at,updated_by) VALUES(?,?,?,?)",
                              ("https.enabled", "true", time.time(), "test"))
        self.client = TestClient(server.app)
        self.addCleanup(self.client.close)
        self.headers = {"X-Dashboard": "1"}

    def test_code_info_export_and_portal_ready_clone(self):
        self.assertEqual(self.client.post("/api/admin/migration/code", json={}, headers=self.headers).status_code, 401)
        self.client.post("/api/auth/login", json={"username": "source", "password": "source-secret"}, headers=self.headers)
        overview = self.client.get("/api/admin/migration").json()
        self.assertEqual(overview["codes"], [])
        code = self.client.post("/api/admin/migration/code", json={}, headers=self.headers).json()["code"]
        self.client.cookies.clear()                                    # der neue Server hat keine Sitzung
        bearer = {"X-Dashboard": "1", "Authorization": "Bearer " + code}
        self.assertEqual(self.client.post("/api/migration/info", headers={"X-Dashboard": "1"}).status_code, 401)
        wrong = {"X-Dashboard": "1", "Authorization": "Bearer hb4m_00000000." + "a" * 32}
        self.assertEqual(self.client.post("/api/migration/info", headers=wrong).status_code, 403)
        info = self.client.post("/api/migration/info", headers=bearer)
        self.assertEqual(info.status_code, 200, info.text)
        self.assertEqual(info.json()["kind"], "dmr")
        with patch.object(self.server._version, "REPO_ROOT", self.root), \
             patch.object(self.server.state, "save_all_data"), patch.object(self.server.state.aprs.store, "flush"):
            r = self.client.post("/api/migration/export", headers=bearer)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.headers["cache-control"], "no-store")
        self.assertFalse(list(self.control.glob("migration-*.n8mig")) + list(self.control.glob("migration-*.tar.gz")))     # nichts bleibt auf dem alten Server liegen
        pkg = self.base / "pkg.n8mig"
        pkg.write_bytes(r.content)
        plain = self.base / "clone.tar.gz"
        n8mig.decrypt_file(pkg, plain, n8mig.parse_code(code)[2])
        dest = self.base / "unpacked"
        dest.mkdir()
        manifest = backup.unpack_archive(plain, dest)                  # vollständige Prüfung wie bei jedem Backup
        self.assertEqual(manifest["format"], backup.FORMAT)
        with contextlib.closing(sqlite3.connect(str(dest / "data/dashboard.db"))) as db:
            vals = dict(db.execute("SELECT key, value FROM settings").fetchall())
        self.assertEqual(json.loads(vals["https.enabled"]), False)     # im Paket: eigenes HTTPS aus
        self.assertEqual(json.loads(self.auth._q("SELECT value FROM settings WHERE key='https.enabled'")[0]["value"]), True)  # alter Server unverändert
        self.assertEqual(self.client.post("/api/admin/migration/code", json={}, headers=self.headers).status_code, 401)
        self.client.post("/api/auth/login", json={"username": "source", "password": "source-secret"}, headers=self.headers)
        codes = self.client.get("/api/admin/migration").json()["codes"]
        self.assertEqual(codes[0]["uses"], 1)
        self.assertEqual(self.client.delete(f"/api/admin/migration/code/{codes[0]['id']}", headers=self.headers).json(), {"ok": True})
        self.client.cookies.clear()
        self.assertEqual(self.client.post("/api/migration/info", headers=bearer).status_code, 403)


if __name__ == "__main__":
    unittest.main()
