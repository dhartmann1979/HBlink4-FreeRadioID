"""
User management for the dashboard (SQLite).

Roles
-----
superadmin  set in dashboard/config.json (auth.superadmin); manages everyone,
            cannot be deleted or demoted from the web UI
admin       sees IP addresses, manages 'user' accounts and settings
user        logged-in viewer (needed when auth.public_dashboard is false)

Passwords are hashed with scrypt (stdlib). Sessions are random tokens; only
their SHA-256 is stored, so a leaked database does not leak live sessions.

HobbyRadioPortal (since 1.11.0: no API tokens)
----------------------------------------------
The portal on the same machine acts with the role ``admin`` (never superadmin) and only on the paths in
``server.PORTAL_PATHS`` – see ``server.portal_local()``. ``portal_user()`` is its pseudo user.

CLI:
    python -m dashboard.auth hash-password     # prints a hash for config.json
"""
from __future__ import annotations

import base64
import getpass
import hashlib
import hmac
import ipaddress
import logging
import re
import secrets
import sqlite3
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

ROLES = ("superadmin", "admin", "user")
ADMIN_ROLES = ("superadmin", "admin")
USERNAME_RE = re.compile(r"^[A-Za-z0-9._@-]{2,40}$")
MIN_PASSWORD_LEN = 8

_SCRYPT_N, _SCRYPT_R, _SCRYPT_P = 2 ** 14, 8, 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL CHECK (role IN ('superadmin','admin','user')),
    display_name  TEXT NOT NULL DEFAULT '',
    dmr_id        INTEGER,
    disabled      INTEGER NOT NULL DEFAULT 0,
    from_config   INTEGER NOT NULL DEFAULT 0,
    created_at    REAL NOT NULL,
    last_login    REAL
);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at REAL NOT NULL,
    expires_at REAL NOT NULL,
    last_seen  REAL NOT NULL,
    ip         TEXT NOT NULL DEFAULT '',
    user_agent TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS sessions_user ON sessions(user_id);
DROP TABLE IF EXISTS api_tokens;   -- until 1.10: tokens for the HobbyRadioPortal (now: same server, no token)
CREATE TABLE IF NOT EXISTS audit (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    ts       REAL NOT NULL,
    username TEXT NOT NULL DEFAULT '',
    action   TEXT NOT NULL,
    detail   TEXT NOT NULL DEFAULT '',
    ip       TEXT NOT NULL DEFAULT ''
);
"""


class AuthError(Exception):
    """A request the caller may not make, or invalid input. Message is user-facing."""


# ---------------------------------------------------------------- passwords

def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=32)
    return "scrypt${}${}${}${}${}".format(
        _SCRYPT_N, _SCRYPT_R, _SCRYPT_P,
        base64.b64encode(salt).decode(), base64.b64encode(dk).decode())


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt_b64, hash_b64 = stored.split("$")
        if algo != "scrypt":
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(hash_b64)
        dk = hashlib.scrypt(password.encode(), salt=salt, n=int(n), r=int(r), p=int(p),
                            dklen=len(expected), maxmem=128 * 1024 * 1024)
        return hmac.compare_digest(dk, expected)
    except Exception:
        return False


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


# ------------------------------------------------------------ IP redaction

# Addresses and ports of stations, links and trunks: admins only
IP_KEYS = frozenset({"address", "remote_address", "remote_port", "ip", "client_ip", "source_ip",
                     "local_address", "local_port", "target_address", "target_port", "port"})
_IPV4_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}(?::\d{1,5})?\b")
_IPV6_RE = re.compile(r"\[?\b(?:[0-9A-Fa-f]{0,4}:){2,7}[0-9A-Fa-f]{0,4}\b\]?(?::\d{1,5})?")


def _scrub_text(s: str) -> str:
    s = _IPV4_RE.sub("•••", s)
    if s.count(":") >= 2:
        def repl(m):
            txt = m.group(0).strip("[]")
            try:
                ipaddress.IPv6Address(txt.rsplit("]:", 1)[0] if "]:" in m.group(0) else txt)
                return "•••"
            except ValueError:
                return m.group(0)
        s = _IPV6_RE.sub(repl, s)
    return s


def redact_ips(obj: Any) -> Any:
    """Deep copy of obj without IP-address fields; IPs inside strings are masked."""
    if isinstance(obj, dict):
        return {k: redact_ips(v) for k, v in obj.items() if k not in IP_KEYS}
    if isinstance(obj, list):
        return [redact_ips(v) for v in obj]
    if isinstance(obj, tuple):
        return [redact_ips(v) for v in obj]
    if isinstance(obj, str):
        return _scrub_text(obj) if ("." in obj or ":" in obj) else obj
    return obj


# ------------------------------------------------------------------ store

class AuthStore:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._db = sqlite3.connect(str(self.db_path), check_same_thread=False, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA foreign_keys = ON")
        self._db.execute("PRAGMA journal_mode = WAL")
        self._db.executescript(_SCHEMA)
        self._failures: Dict[str, List[float]] = {}

    # -- helpers --------------------------------------------------------
    def _q(self, sql: str, args: tuple = ()) -> List[sqlite3.Row]:
        with self._lock:
            return self._db.execute(sql, args).fetchall()

    def _x(self, sql: str, args: tuple = ()) -> sqlite3.Cursor:
        with self._lock:
            return self._db.execute(sql, args)

    @staticmethod
    def public_user(row: sqlite3.Row) -> Dict[str, Any]:
        return {
            "id": row["id"], "username": row["username"], "role": row["role"],
            "display_name": row["display_name"], "dmr_id": row["dmr_id"],
            "disabled": bool(row["disabled"]), "from_config": bool(row["from_config"]),
            "created_at": row["created_at"], "last_login": row["last_login"],
        }

    def audit(self, action: str, username: str = "", detail: str = "", ip: str = "") -> None:
        self._x("INSERT INTO audit (ts, username, action, detail, ip) VALUES (?,?,?,?,?)",
                (time.time(), username, action, detail[:300], ip))
        # keep the log bounded
        self._x("DELETE FROM audit WHERE id <= (SELECT MAX(id) FROM audit) - 2000")

    # -- superadmin from config ----------------------------------------
    def sync_superadmin(self, cfg: Dict[str, Any]) -> Optional[str]:
        """
        Create/update the superadmin from auth.superadmin in config.json.
        Returns the username, or None if none is configured.
        """
        username = str((cfg or {}).get("username") or "").strip()
        password = str((cfg or {}).get("password") or "")
        pw_hash = str((cfg or {}).get("password_hash") or "")
        if not username or not (password or pw_hash):
            if not self._q("SELECT 1 FROM users WHERE role='superadmin' LIMIT 1"):
                logger.warning("🔐 No superadmin configured (dashboard/config.json → auth.superadmin): "
                               "admin login is not possible until you set one")
            return None
        if not USERNAME_RE.match(username):
            logger.error(f"🔐 auth.superadmin.username {username!r} is invalid (2-40 chars: letters, digits . _ @ -)")
            return None
        if password and not pw_hash:
            logger.warning("🔐 auth.superadmin.password is stored in plain text; consider "
                           "auth.superadmin.password_hash (python -m dashboard.auth hash-password)")
        existing = self._q("SELECT * FROM users WHERE username=?", (username,))
        if existing:
            row = existing[0]
            new_hash = row["password_hash"]
            if pw_hash:
                new_hash = pw_hash
            elif not verify_password(password, row["password_hash"]):
                new_hash = hash_password(password)
            self._x("UPDATE users SET role='superadmin', from_config=1, disabled=0, password_hash=? WHERE id=?",
                    (new_hash, row["id"]))
        else:
            self._x("INSERT INTO users (username, password_hash, role, display_name, from_config, created_at) "
                    "VALUES (?,?,?,?,1,?)",
                    (username, pw_hash or hash_password(password), "superadmin", "", time.time()))
            logger.info(f"🔐 Superadmin {username!r} created from config")
        # Only the configured account is superadmin; a renamed one becomes admin.
        self._x("UPDATE users SET role='admin', from_config=0 WHERE role='superadmin' AND username<>? COLLATE NOCASE",
                (username,))
        return username

    # -- login / sessions -------------------------------------------------
    def _throttled(self, key: str) -> bool:
        now = time.time()
        recent = [t for t in self._failures.get(key, []) if now - t < 900]
        self._failures[key] = recent
        return len(recent) >= 5

    def login(self, username: str, password: str, ip: str = "", user_agent: str = "",
              hours: float = 12) -> tuple:
        """Returns (token, user dict). Raises AuthError on failure."""
        key = f"{ip}|{username.lower()}"
        if self._throttled(ip) or self._throttled(key):
            raise AuthError("Too many failed logins. Try again in 15 minutes.")
        rows = self._q("SELECT * FROM users WHERE username=?", (username.strip(),))
        row = rows[0] if rows else None
        ok = row is not None and verify_password(password, row["password_hash"])
        if not row:
            verify_password(password, hash_password("timing-equaliser"))
        if not ok or row["disabled"]:
            now = time.time()
            self._failures.setdefault(ip, []).append(now)
            self._failures.setdefault(key, []).append(now)
            self.audit("login_failed", username.strip()[:40], "", ip)
            raise AuthError("Wrong username or password." if not (ok and row["disabled"]) else "Account disabled.")
        token = secrets.token_urlsafe(32)
        now = time.time()
        self._x("INSERT INTO sessions (token_hash, user_id, created_at, expires_at, last_seen, ip, user_agent) "
                "VALUES (?,?,?,?,?,?,?)",
                (_token_hash(token), row["id"], now, now + hours * 3600, now, ip, user_agent[:200]))
        self._x("UPDATE users SET last_login=? WHERE id=?", (now, row["id"]))
        self._x("DELETE FROM sessions WHERE expires_at < ?", (now,))
        self.audit("login", row["username"], "", ip)
        return token, self.public_user(row)

    def confirm_password(self, user: Dict[str, Any], password: str, ip: str = "") -> None:
        """Re-check the logged-in user's password before a dangerous action (same throttle as login)."""
        key = f"{ip}|{str(user.get('username', '')).lower()}"
        if self._throttled(ip) or self._throttled(key):
            raise AuthError("Too many wrong passwords. Try again in 15 minutes.")
        rows = self._q("SELECT password_hash, disabled FROM users WHERE id=?", (user.get("id"),))
        if not rows or rows[0]["disabled"] or not verify_password(password or "", rows[0]["password_hash"]):
            now = time.time()
            self._failures.setdefault(ip, []).append(now)
            self._failures.setdefault(key, []).append(now)
            self.audit("confirm_failed", str(user.get("username", ""))[:40], "", ip)
            raise AuthError("Wrong password.")

    def session_user(self, token: Optional[str]) -> Optional[Dict[str, Any]]:
        if not token:
            return None
        th = _token_hash(token)
        rows = self._q("SELECT u.*, s.expires_at, s.last_seen FROM sessions s JOIN users u ON u.id = s.user_id "
                       "WHERE s.token_hash=?", (th,))
        if not rows:
            return None
        row = rows[0]
        now = time.time()
        if row["expires_at"] < now or row["disabled"]:
            self._x("DELETE FROM sessions WHERE token_hash=?", (th,))
            return None
        if now - row["last_seen"] > 60:
            self._x("UPDATE sessions SET last_seen=? WHERE token_hash=?", (now, th))
        return self.public_user(row)

    def logout(self, token: Optional[str]) -> None:
        if token:
            self._x("DELETE FROM sessions WHERE token_hash=?", (_token_hash(token),))

    def list_sessions(self) -> List[Dict[str, Any]]:
        rows = self._q("SELECT s.token_hash, s.created_at, s.expires_at, s.last_seen, s.ip, s.user_agent, "
                       "u.username, u.role FROM sessions s JOIN users u ON u.id = s.user_id "
                       "WHERE s.expires_at > ? ORDER BY s.last_seen DESC", (time.time(),))
        return [{"id": r["token_hash"][:16], "username": r["username"], "role": r["role"],
                 "created_at": r["created_at"], "expires_at": r["expires_at"], "last_seen": r["last_seen"],
                 "ip": r["ip"], "user_agent": r["user_agent"]} for r in rows]

    def revoke_session(self, short_id: str) -> None:
        if not re.fullmatch(r"[0-9a-f]{16}", short_id or ""):
            raise AuthError("Invalid session.")
        self._x("DELETE FROM sessions WHERE substr(token_hash, 1, 16)=?", (short_id,))

    # -- user management --------------------------------------------------
    def get_user(self, user_id: int) -> Dict[str, Any]:
        rows = self._q("SELECT * FROM users WHERE id=?", (user_id,))
        if not rows:
            raise AuthError("User not found.")
        return self.public_user(rows[0])

    def list_users(self) -> List[Dict[str, Any]]:
        order = "CASE role WHEN 'superadmin' THEN 0 WHEN 'admin' THEN 1 ELSE 2 END, username COLLATE NOCASE"
        return [self.public_user(r) for r in self._q(f"SELECT * FROM users ORDER BY {order}")]

    @staticmethod
    def _check_manage(actor: Dict[str, Any], target_role: str) -> None:
        if actor["role"] not in ADMIN_ROLES:
            raise AuthError("Admins only.")
        if target_role == "superadmin":
            raise AuthError("The superadmin is managed in dashboard/config.json.")
        if target_role == "admin" and actor["role"] != "superadmin":
            raise AuthError("Only the superadmin can manage admins.")

    @staticmethod
    def _validate(username: Optional[str] = None, password: Optional[str] = None, role: Optional[str] = None,
                  dmr_id: Any = None) -> Optional[int]:
        if username is not None and not USERNAME_RE.match(username):
            raise AuthError("Username: 2–40 characters, letters, digits and . _ @ -")
        if password is not None and len(password) < MIN_PASSWORD_LEN:
            raise AuthError(f"Password must be at least {MIN_PASSWORD_LEN} characters.")
        if role is not None and role not in ("admin", "user"):
            raise AuthError("Role must be admin or user.")
        if dmr_id in (None, ""):
            return None
        try:
            v = int(dmr_id)
        except (TypeError, ValueError):
            raise AuthError("DMR-ID must be a number.")
        if not 1 <= v <= 16777215:
            raise AuthError("DMR-ID out of range.")
        return v

    def create_user(self, actor: Dict[str, Any], username: str, password: str, role: str = "user",
                    display_name: str = "", dmr_id: Any = None, ip: str = "") -> Dict[str, Any]:
        username = (username or "").strip()
        dmr = self._validate(username, password, role, dmr_id)
        self._check_manage(actor, role)
        if self._q("SELECT 1 FROM users WHERE username=?", (username,)):
            raise AuthError("Username already exists.")
        cur = self._x("INSERT INTO users (username, password_hash, role, display_name, dmr_id, created_at) "
                      "VALUES (?,?,?,?,?,?)",
                      (username, hash_password(password), role, (display_name or "").strip()[:60], dmr, time.time()))
        self.audit("user_created", actor["username"], f"{username} ({role})", ip)
        return self.get_user(cur.lastrowid)

    def update_user(self, actor: Dict[str, Any], user_id: int, changes: Dict[str, Any], ip: str = "") -> Dict[str, Any]:
        target = self.get_user(user_id)
        self._check_manage(actor, target["role"])
        if "role" in changes:
            self._validate(role=changes["role"])
            self._check_manage(actor, changes["role"])
        if target["id"] == actor["id"] and (changes.get("disabled") or changes.get("role") not in (None, actor["role"])):
            raise AuthError("You cannot disable or demote yourself.")
        sets, args, notes = [], [], []
        if "password" in changes and changes["password"]:
            self._validate(password=changes["password"])
            sets.append("password_hash=?"); args.append(hash_password(changes["password"])); notes.append("password")
        if "role" in changes:
            sets.append("role=?"); args.append(changes["role"]); notes.append(f"role={changes['role']}")
        if "display_name" in changes:
            sets.append("display_name=?"); args.append(str(changes["display_name"] or "").strip()[:60]); notes.append("name")
        if "dmr_id" in changes:
            sets.append("dmr_id=?"); args.append(self._validate(dmr_id=changes["dmr_id"])); notes.append("dmr_id")
        if "disabled" in changes:
            sets.append("disabled=?"); args.append(1 if changes["disabled"] else 0)
            notes.append("disabled" if changes["disabled"] else "enabled")
        if not sets:
            return target
        self._x(f"UPDATE users SET {', '.join(sets)} WHERE id=?", (*args, user_id))
        if changes.get("disabled") or changes.get("password") or "role" in changes:
            self._x("DELETE FROM sessions WHERE user_id=?", (user_id,))
        self.audit("user_updated", actor["username"], f"{target['username']}: {', '.join(notes)}", ip)
        return self.get_user(user_id)

    def delete_user(self, actor: Dict[str, Any], user_id: int, ip: str = "") -> None:
        target = self.get_user(user_id)
        self._check_manage(actor, target["role"])
        if target["id"] == actor["id"]:
            raise AuthError("You cannot delete yourself.")
        self._x("DELETE FROM users WHERE id=?", (user_id,))
        self.audit("user_deleted", actor["username"], target["username"], ip)

    def change_own_password(self, user: Dict[str, Any], old: str, new: str, ip: str = "") -> None:
        if user.get("from_config"):
            raise AuthError("The superadmin password is set in dashboard/config.json.")
        rows = self._q("SELECT password_hash FROM users WHERE id=?", (user["id"],))
        if not rows or not verify_password(old, rows[0]["password_hash"]):
            raise AuthError("Current password is wrong.")
        self._validate(password=new)
        self._x("UPDATE users SET password_hash=? WHERE id=?", (hash_password(new), user["id"]))
        self.audit("password_changed", user["username"], "", ip)

    # -- HobbyRadioPortal on this server -------------------------------
    @staticmethod
    def portal_user(on_behalf: str = "") -> Dict[str, Any]:
        """Pseudo user (role admin) of the HobbyRadioPortal on this server (see server.portal_local)."""
        who = re.sub(r"[^A-Za-z0-9._@-]", "", on_behalf or "")[:40]
        return {"id": 0, "username": "portal" + (f" ({who})" if who else ""), "role": "admin", "display_name": "HobbyRadioPortal",
                "dmr_id": None, "disabled": False, "from_config": False, "created_at": 0, "last_login": None, "api": True}

    def audit_log(self, limit: int = 200) -> List[Dict[str, Any]]:
        return [dict(r) for r in self._q("SELECT ts, username, action, detail, ip FROM audit "
                                          "ORDER BY id DESC LIMIT ?", (limit,))]


def sniff_image(data: bytes) -> Optional[str]:
    """MIME type of a PNG/JPEG/GIF/WebP image, or None. SVG is refused (script risk)."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def _cli(argv: List[str]) -> int:
    if len(argv) >= 2 and argv[1] == "hash-password":
        pw = getpass.getpass("Password: ")
        if len(pw) < MIN_PASSWORD_LEN:
            print(f"Password must be at least {MIN_PASSWORD_LEN} characters.", file=sys.stderr)
            return 1
        if pw != getpass.getpass("Repeat:   "):
            print("Passwords do not match.", file=sys.stderr)
            return 1
        print(hash_password(pw))
        return 0
    print("usage: python -m dashboard.auth hash-password", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(_cli(sys.argv))
