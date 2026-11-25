"""'Update now': fast-forward only, exact commit, no local changes – tested with real git repos."""
import subprocess
import tempfile
import unittest
from pathlib import Path

from dashboard import version as v


def git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True).stdout.strip()


class TestInstall(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.origin = root / "origin.git"
        self.up = root / "upstream"
        self.local = root / "local"
        git(root, "init", "-q", "--bare", "-b", "main", str(self.origin))
        git(root, "init", "-q", "-b", "main", str(self.up))
        for repo in (self.up,):
            git(repo, "config", "user.email", "t@example.org"); git(repo, "config", "user.name", "t")
        (self.up / "a.txt").write_text("1\n")
        git(self.up, "add", "."); git(self.up, "commit", "-qm", "one")
        git(self.up, "remote", "add", "origin", str(self.origin)); git(self.up, "push", "-q", "origin", "main")
        git(root, "clone", "-q", str(self.origin), str(self.local))
        git(self.local, "config", "user.email", "t@example.org"); git(self.local, "config", "user.name", "t")
        self._root = v.REPO_ROOT
        v.REPO_ROOT = self.local
        # the test repos use the file transport, which install() switches off on purpose
        self._safe = v._GIT_SAFE
        v._GIT_SAFE = ["-c", "core.hooksPath=/dev/null"]

    def tearDown(self):
        v.REPO_ROOT = self._root
        v._GIT_SAFE = self._safe
        v._local = None
        self.tmp.cleanup()

    def push_new(self, name="b.txt"):
        (self.up / name).write_text("2\n")
        git(self.up, "add", "."); git(self.up, "commit", "-qm", "two"); git(self.up, "push", "-q", "origin", "main")
        return git(self.up, "rev-parse", "HEAD")

    def test_fast_forward(self):
        new = self.push_new()
        r = v.install("main", new)
        self.assertTrue(r["changed"]); self.assertEqual(r["files"], ["b.txt"])
        self.assertEqual(git(self.local, "rev-parse", "HEAD"), new)
        self.assertFalse(r["requirements_changed"])

    def test_requirements_change_is_reported(self):
        new = self.push_new("requirements.txt")
        self.assertTrue(v.install("main", new)["requirements_changed"])

    def test_wrong_expected_commit(self):
        self.push_new()
        with self.assertRaises(v.UpdateError):
            v.install("main", "f" * 40)

    def test_local_changes_block(self):
        new = self.push_new()
        (self.local / "a.txt").write_text("changed\n")
        with self.assertRaises(v.UpdateError) as cm:
            v.install("main", new)
        self.assertIn("a.txt", str(cm.exception))

    def test_own_commits_block(self):
        new = self.push_new()
        (self.local / "c.txt").write_text("x\n")
        git(self.local, "add", "."); git(self.local, "commit", "-qm", "local")
        with self.assertRaises(v.UpdateError):
            v.install("main", new)

    def test_bad_inputs(self):
        for branch, sha in (("--upload-pack=x", "a" * 40), ("main", "HEAD"), ("main", ""), ("a..b", "a" * 40)):
            with self.assertRaises(v.UpdateError):
                v.install(branch, sha)

    def test_file_transport_is_blocked_by_default(self):
        v._GIT_SAFE = self._safe
        new = self.push_new()
        with self.assertRaises(v.UpdateError):
            v.install("main", new)

    def test_sudo_argv_is_fixed(self):
        self.assertEqual(v.sudo_restart_argv(), ["sudo", "-n", "/usr/bin/systemctl", "--no-block", "restart",
                                                 "hblink4.service", "hblink4-dash.service"])


if __name__ == "__main__":
    unittest.main()


class TestInstallApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient
        from dashboard import server
        from dashboard.auth import AuthStore
        cls.server = server
        server.dashboard_config.setdefault("auth", {})["superadmin"] = {"username": "boss", "password": "SuperSecret1"}
        server.state.auth = AuthStore(Path(tempfile.mkdtemp()) / "upd.db")
        server.state.auth.sync_superadmin(server.dashboard_config["auth"]["superadmin"])
        boss = next(u for u in server.state.auth.list_users() if u["username"] == "boss")
        server.state.auth.create_user(boss, "helper", "HelperPass1", "admin")
        cls.client = TestClient(server.app)

    def setUp(self):
        self.calls = []
        test = self

        class FakeN8:        # „Update jetzt“ legt nur den Auftrag für scripts/n8-admin.sh an
            def request_update(self):
                test.calls.append("request")
                return True, "Update angefordert"

            def update_state(self):
                return {"ready": True, "result": None}
        self._n8 = self.server._n8
        self.server._n8 = lambda: FakeN8()
        self.server._update_last_try = 0.0
        self.server.dashboard_config["update"] = {"install_role": "superadmin"}
        self.client.cookies.clear()

    def tearDown(self):
        self.server._n8 = self._n8
        self.client.post("/api/auth/logout", headers={"X-Dashboard": "1"})
        self.client.cookies.clear()

    def login(self, user, pw):
        self.client.post("/api/auth/login", json={"username": user, "password": pw}, headers={"X-Dashboard": "1"})

    def post(self, body, header=True):
        return self.client.post("/api/admin/update/install", json=body, headers={"X-Dashboard": "1"} if header else {})

    def test_needs_login_header_and_password(self):
        self.assertEqual(self.post({"password": "SuperSecret1", "expected": "b" * 40}).status_code, 401)
        self.login("boss", "SuperSecret1")
        self.assertEqual(self.post({"password": "SuperSecret1", "expected": "b" * 40}, header=False).status_code, 403)
        self.assertEqual(self.post({"password": "wrong", "expected": "b" * 40}).status_code, 403)
        self.assertEqual(self.calls, [])
        r = self.post({"password": "SuperSecret1", "expected": "b" * 40})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self.calls, ["request"])
        self.assertTrue(r.json()["requested"])

    def test_admin_only_when_allowed(self):
        self.login("helper", "HelperPass1")
        self.assertEqual(self.post({"password": "HelperPass1", "expected": "b" * 40}).status_code, 403)
        self.server.dashboard_config["update"] = {"install_role": "admin"}
        self.assertEqual(self.post({"password": "HelperPass1", "expected": "b" * 40, "restart": False}).status_code, 200)

    def test_switched_off(self):
        self.server.dashboard_config["update"] = {"install_role": "nobody"}
        self.login("boss", "SuperSecret1")
        self.assertEqual(self.post({"password": "SuperSecret1", "expected": "b" * 40}).status_code, 403)
        self.assertEqual(self.calls, [])
