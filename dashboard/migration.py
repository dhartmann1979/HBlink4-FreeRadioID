"""Umzug ins HobbyRadioPortal: Umzugscodes und das Umzugspaket.

Ein Superadmin legt im Adminbereich (💾 Backup → 📦 Umzug ins HobbyRadioPortal) einen Umzugscode an. Damit holt der
Web-Installer des Portals auf dem neuen Server

  POST /api/migration/info     – was übernommen wird (Version, Titel, Domains, Ports, Zahlen), verbraucht nichts
  POST /api/migration/export   – das komplette HBlink4 (Klon-Backup wie unter 💾 Backup), verschlüsselt (n8mig)

Der Code gilt 2 Stunden und für höchstens 3 Abrufe des Pakets; gespeichert wird nur der SHA-256 des Geheimteils.
Zu viele falsche Codes von einer Adresse sperren sie 15 Minuten.

Das Paket ist ein „portalfertiger“ Klon: das eigene HTTPS von HBlink4 (Dashboard und APRS-Domains) ist darin
ausgeschaltet, weil auf dem neuen Server nginx des Portals Port 80/443 übernimmt und die Domains weiterleitet.
Auf dem alten Server ändert sich nichts.
"""
import contextlib
import json
import socket
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import n8mig

PREFIX = "hb4m"
TTL = 2 * 3600
MAX_USES = 3
FAIL_LIMIT, FAIL_WINDOW = 8, 15 * 60

# Was im Umzugspaket anders ist als auf dem alten Server (das Portal übernimmt HTTPS und Domains)
PORTAL_OVERRIDES = {"https.enabled": False, "aprs.site1.https": False, "aprs.site2.https": False, "aprs.site3.https": False}


class Codes:
    def __init__(self, folder: Path):
        self.path = Path(folder) / "migration-codes.json"
        self._lock = threading.Lock()
        self._fails: Dict[str, List[float]] = {}

    def _load(self) -> List[Dict[str, Any]]:
        try:
            return json.loads(self.path.read_text())
        except (OSError, ValueError):
            return []

    def _save(self, items) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(items, indent=1))
        tmp.chmod(0o600)
        tmp.replace(self.path)

    def list(self) -> List[Dict[str, Any]]:
        now = time.time()
        out = []
        for c in self._load():
            state = "revoked" if c.get("revoked") else "expired" if c["expires_at"] < now else "used" if c["uses"] >= MAX_USES else "active"
            out.append({k: c.get(k) for k in ("id", "created_at", "expires_at", "created_by", "uses", "last_used", "last_ip")}
                       | {"state": state, "max_uses": MAX_USES})
        return sorted(out, key=lambda c: c["created_at"], reverse=True)

    def create(self, actor: str) -> Dict[str, Any]:
        code, cid, sha = n8mig.new_code(PREFIX)
        now = time.time()
        with self._lock:
            items = [c for c in self._load() if c["expires_at"] > now - 7 * 86400]   # alte Einträge nach einer Woche weg
            items.append({"id": cid, "sha256": sha, "created_at": now, "expires_at": now + TTL, "created_by": actor,
                          "uses": 0, "last_used": None, "last_ip": "", "revoked": False})
            self._save(items)
        return {"code": code, "id": cid, "expires_at": now + TTL, "max_uses": MAX_USES}

    def revoke(self, cid: str) -> bool:
        with self._lock:
            items = self._load()
            hit = False
            for c in items:
                if c["id"] == cid and not c.get("revoked"):
                    c["revoked"] = hit = True
            self._save(items)
        return hit

    def blocked(self, ip: str) -> bool:
        now = time.time()
        f = [t for t in self._fails.get(ip, []) if t > now - FAIL_WINDOW]
        self._fails[ip] = f
        return len(f) >= FAIL_LIMIT

    def check(self, code: str, ip: str, use: bool = False) -> Dict[str, Any]:
        """Prüft den Code (und zählt einen Abruf, wenn use=True). Fehler: MigrationError mit verständlichem Text."""
        if self.blocked(ip):
            raise n8mig.MigrationError("Zu viele falsche Umzugscodes – bitte 15 Minuten warten.")
        try:
            prefix, cid, secret = n8mig.parse_code(code)
            if prefix != PREFIX:
                raise n8mig.MigrationError("Das ist kein Umzugscode von HBlink4 (beginnt mit hb4m_).")
        except n8mig.MigrationError:
            self._fails.setdefault(ip, []).append(time.time())
            raise
        sha = n8mig.secret_hash(secret)
        now = time.time()
        with self._lock:
            items = self._load()
            c = next((x for x in items if x["id"] == cid and n8mig.hmac.compare_digest(x["sha256"], sha)), None)
            if not c:
                self._fails.setdefault(ip, []).append(now)
                raise n8mig.MigrationError("Umzugscode unbekannt.")
            if c.get("revoked"):
                raise n8mig.MigrationError("Umzugscode wurde widerrufen.")
            if c["expires_at"] < now:
                raise n8mig.MigrationError("Umzugscode ist abgelaufen – bitte im alten Dashboard einen neuen anlegen.")
            if c["uses"] >= MAX_USES:
                raise n8mig.MigrationError("Umzugscode ist aufgebraucht – bitte einen neuen anlegen.")
            if use:
                c["uses"] += 1
                c["last_used"], c["last_ip"] = now, ip
                self._save(items)
        return {"id": cid, "secret": secret}


def apply_overrides(stage: Path, overrides: Dict[str, Any]) -> None:
    """Ändert die Einstellungen in der KOPIE (Stage) eines Klon-Backups, bevor Prüfsummen gebildet werden."""
    db = stage / "data" / "dashboard.db"
    if db.is_file() and overrides:
        with contextlib.closing(sqlite3.connect(str(db))) as conn:
            for k, v in overrides.items():
                conn.execute("INSERT OR REPLACE INTO settings (key, value, updated_at, updated_by) VALUES (?,?,?,?)",
                             (k, json.dumps(v), time.time(), "migration"))
            conn.commit()
            conn.execute("PRAGMA journal_mode = DELETE")
        for suffix in ("-wal", "-shm"):
            Path(str(db) + suffix).unlink(missing_ok=True)
    cfg_path = stage / "app" / "dashboard" / "config.json"
    if cfg_path.is_file() and overrides.get("https.enabled") is False:
        cfg = json.loads(cfg_path.read_text())
        if isinstance(cfg.get("https"), dict):
            cfg["https"]["enabled"] = False
            cfg_path.write_text(json.dumps(cfg, indent=2) + "\n")


def info(values: Dict[str, Any], *, version: str, users: int, repeaters: int, size_hint: int = 0) -> Dict[str, Any]:
    """Vorschau für den Web-Installer: was kommt mit, welche Domains und Ports braucht der neue Server."""
    domains = []
    if values.get("https.domain"):
        domains.append({"domain": values["https.domain"], "kind": "dmr", "https": bool(values.get("https.enabled"))})
    for i in (1, 2, 3):
        d = values.get(f"aprs.site{i}.domain")
        if d:
            domains.append({"domain": d, "kind": "aprs", "https": bool(values.get(f"aprs.site{i}.https", True))})
    ports = [{"port": int(values.get("dmr.global.port_ipv4") or 62031), "proto": "udp", "what": "DMR (Repeater, Hotspots)"}]
    for o in values.get("dmr.openbridge_connections") or []:
        if isinstance(o, dict) and o.get("port"):
            ports.append({"port": int(o["port"]), "proto": "udp", "what": f"OpenBridge {o.get('name') or ''}".strip()})
    if values.get("aprs.enabled") and values.get("aprs.server.enabled"):
        ports.append({"port": int(values.get("aprs.server.port_filter") or 14580), "proto": "tcp", "what": "APRS-IS (Filter)"})
        ports.append({"port": int(values.get("aprs.server.port_full") or 10152), "proto": "tcp", "what": "APRS-IS (Full Feed)"})
    return {"app": "HBlink4-FreeRadioID", "kind": "dmr", "version": version, "host": socket.gethostname(),
            "title": values.get("dashboard_title") or "", "web_port": int(values.get("web.port") or 8080),
            "https_before": bool(values.get("https.enabled")), "aprs": bool(values.get("aprs.enabled")),
            "users": users, "repeaters": repeaters, "rules": len(values.get("dmr.repeater_configurations.patterns") or []),
            "obp": len(values.get("dmr.openbridge_connections") or []), "domains": domains, "ports": ports, "size_hint": size_hint,
            "changes": ["Eigenes HTTPS und Let's Encrypt von HBlink4 werden ausgeschaltet – das übernimmt das Portal (nginx)."]}
