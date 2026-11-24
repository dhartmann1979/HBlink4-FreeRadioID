#!/usr/bin/env python3
"""Initial setup's restore path. Requires only Python's standard library.

Validate and confirm first. A fresh target gets stopped bootstrap services;
the existing isolated restore worker performs the actual clone and rollback.
"""
from __future__ import annotations

import json
import contextlib
import os
import pwd
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dashboard import backup


class SetupError(Exception):
    pass


class RestoreInProgress(SetupError):
    pass


class SetupRestore:
    def __init__(self, root, archive, *, ask=input, say=print):
        self.root = Path(root).resolve()
        self.archive = Path(archive).resolve()
        self.ask, self.say = ask, say
        self.fresh = False
        self.queued = False

    def run(self, args, **kwargs):
        return backup.command([str(arg) for arg in args], **kwargs)

    def show(self, unit, prop):
        result = subprocess.run(["systemctl", "show", unit, "-p", prop, "--value"],
                                text=True, capture_output=True, timeout=10)
        if result.returncode and prop != "LoadState":
            raise SetupError(result.stderr.strip() or f"systemctl: {unit} {prop}")
        return result.stdout.strip() or ("not-found" if prop == "LoadState" else "")

    def preflight(self):
        if os.geteuid() != 0 or sys.platform != "linux":
            raise SetupError("Die Wiederherstellung benötigt Linux/systemd und root: sudo ./scripts/setup.sh")
        if os.environ.get("SKIP_SERVICES") == "1" or not shutil.which("systemctl"):
            raise SetupError("Wiederherstellen benötigt systemd-Dienste; SKIP_SERVICES=1 ist nicht möglich.")
        parent = self.root.parent.stat()
        if parent.st_uid != 0 or parent.st_mode & 0o022:
            raise SetupError("Das übergeordnete Installationsverzeichnis muss root gehören und geschützt sein, z. B. /opt/HBlink4.")
        if any(c.isspace() or c in '$%\\"' for c in str(self.root)):
            raise SetupError("Der Installationspfad darf keine Leerzeichen, $, %, Backslash oder Anführungszeichen enthalten.")
        if not self.archive.is_file() or self.archive.stat().st_size > backup.MAX_ENCRYPTED_UPLOAD:
            raise SetupError("Backup-Datei fehlt oder ist größer als 2 GiB.")
        if self.archive.is_relative_to(self.root) and backup.CONTROL not in self.archive.relative_to(self.root).parts:
            raise SetupError("Bitte die Backup-Datei außerhalb des Installationsverzeichnisses ablegen, z. B. unter /home.")
        if self.show("hblink4-restore.service", "ActiveState") in ("active", "activating", "deactivating"):
            raise SetupError("Eine Wiederherstellung läuft bereits. Bitte deren Abschluss abwarten.")

    def target_account(self):
        loaded = [self.show(unit, "LoadState") == "loaded" for unit in backup.UNITS]
        marker = self.root / "dashboard/data" / backup.CONTROL / "setup-bootstrap.json"
        configs = [self.root / "config/config.json", self.root / "dashboard/config.json"]
        self.fresh = not any(loaded) and not any(p.exists() for p in configs)
        if marker.is_file():
            self.fresh = True  # retry after a failed first installation
        if any(loaded) and not all(loaded):
            raise SetupError("Nur einer der beiden HBlink4-Dienste ist eingerichtet. Zuerst die Dienstinstallation vervollständigen.")
        if all(loaded):
            accounts = []
            for unit in backup.UNITS:
                if Path(self.show(unit, "WorkingDirectory")).resolve() != self.root:
                    raise SetupError(f"{unit} gehört zu einem anderen Installationsverzeichnis.")
                accounts.append(self.show(unit, "User") or "root")
            if len(set(accounts)) != 1:
                raise SetupError("Beide HBlink4-Dienste müssen dasselbe Dienstkonto verwenden.")
            account = accounts[0]
            self.say(f"Vorhandenes Dienstkonto bleibt erhalten: {account}")
            return pwd.getpwuid(int(account)).pw_name if account.isdigit() else account
        if not self.fresh:
            raise SetupError("Konfigurationen sind vorhanden, aber keine vollständigen Dienste. Zuerst die bestehende Installation reparieren.")
        owner = pwd.getpwuid(self.root.stat().st_uid).pw_name
        default = "hblink" if owner == "root" else owner
        account = self.ask(f"Dienst-Benutzer auf dem Zielserver [{default}]: ").strip() or default
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]*[$]?", account):
            raise SetupError("Ungültiger Dienst-Benutzername.")
        return account

    def preview(self, stage, manifest, account):
        cfg = json.loads((stage / "app/dashboard/config.json").read_text())
        admin = ((cfg.get("auth") or {}).get("superadmin") or {}).get("username", "")
        self.say("\nBackup geprüft – noch nicht eingespielt:")
        self.say(f"  Erstellt: {manifest['created_at']}")
        self.say(f"  Version: {manifest['version'].get('version') or manifest['version'].get('label') or 'unbekannt'}")
        self.say(f"  Python im Backup: {manifest['python']} · Ziel-Python: {sys.version_info.major}.{sys.version_info.minor} · Dateien: {len(manifest['files'])}")
        if backup.python_migration(manifest):
            self.say("  Python-Version weicht ab: Code und gespeicherte Paketversionen werden vor dem Stoppen der Dienste mit Ziel-Python geprüft.")
        self.say(f"  Ziel: {self.root} · Dienstkonto: {account}")
        self.say(f"  Anmeldung nachher mit dem Quellkonto: {admin or '(Konto aus dem Backup)'}")
        self.say("Programm, Einstellungen, Benutzer und Daten werden aus dem Backup übernommen.")
        self.say("Bestehende HBlink4-Dienste werden unterbrochen. Vor dem Ersetzen wird automatisch ein Ziel-Backup erstellt.")
        self.say("Firewall und DNS bleiben Aufgabe des Zielservers. Nur eigene, vertrauenswürdige Backups verwenden.")
        return self.ask("Zum Wiederherstellen RESTORE eingeben (Enter = abbrechen): ").strip() == "RESTORE"

    def prepare_fresh(self, account):
        try:
            user = pwd.getpwnam(account)
        except KeyError:
            self.run(["useradd", "--system", "--create-home", "--shell", "/usr/sbin/nologin", account])
            user = pwd.getpwnam(account)
        cfg = {"uid": user.pw_uid, "gid": user.pw_gid, "home": user.pw_dir}
        self.say("Zielumgebung und gestoppte Dienste werden vorbereitet …")
        for name in ("config/config.json", "dashboard/config.json"):
            target = self.root / name
            if not target.exists():
                sample = target.with_name("config_sample.json")
                value = json.loads(sample.read_text())
                if name.startswith("dashboard/"):
                    # Bootstrap never starts before the archive is installed.
                    # No temporary credentials are invented or shown.
                    value.setdefault("auth", {})["superadmin"] = {"username": "", "password": ""}
                    value["auth"]["public_dashboard"] = False
                backup.atomic_json(target, value)
        data = self.root / "dashboard/data"
        data.mkdir(parents=True, exist_ok=True)
        from dashboard.auth import AuthStore
        from hblink4.settings_db import SettingsDB
        auth = AuthStore(data / "dashboard.db")
        try:
            SettingsDB(auth._q, auth._x)
        finally:
            auth._db.close()
        backup.atomic_json(data / backup.CONTROL / "setup-bootstrap.json", {"fresh": True})
        backup._own_tree(self.root, cfg)
        if not (self.root / "venv/bin/python").is_file():
            backup._as_owner(cfg, [sys.executable, "-m", "venv", str(self.root / "venv")], timeout=120)
        backup._as_owner(cfg, [str(self.root / "venv/bin/python"), "-m", "pip", "install", "-r",
                              str(self.root / "requirements.txt"), "-r", str(self.root / "requirements-dashboard.txt")], timeout=1800)
        self.run([self.root / "scripts/install_services.sh"], cwd=self.root, timeout=180,
                 env={**os.environ, "ASSUME_YES": "1", "SVC_USER": account,
                      "SVC_GROUP": self.run(["id", "-gn", account]), "ENABLE_SERVICES": "0", "START_SERVICES": "0"})

    def system_extras(self, stage):
        cfg = json.loads((stage / "app/dashboard/config.json").read_text())
        with contextlib.closing(sqlite3.connect((stage / "data/dashboard.db").resolve().as_uri() + "?mode=ro", uri=True)) as db:
            stored = {key: json.loads(value) for key, value in db.execute(
                "SELECT key, value FROM settings WHERE key IN ('https.enabled','https.letsencrypt')")}
        https = cfg.get("https") or {}
        enabled = stored.get("https.enabled", https.get("enabled", False))
        automatic = stored.get("https.letsencrypt", https.get("letsencrypt", True))
        if enabled and automatic and not shutil.which("certbot"):
            if os.environ.get("SKIP_APT") == "1" or not shutil.which("apt-get"):
                raise SetupError("Dieses Backup benötigt certbot für Let's Encrypt. Zuerst certbot installieren oder SKIP_APT=1 aufheben.")
            self.say("certbot für die HTTPS-Einstellungen aus dem Backup wird installiert …")
            self.run(["apt-get", "install", "-y", "certbot"], timeout=600,
                     env={**os.environ, "DEBIAN_FRONTEND": "noninteractive"})

    def enqueue(self, cfg, snapshot, sha256):
        token = uuid.uuid4().hex
        # Copy and queue under the service account, including with the
        # dashboard's NoNewPrivileges hardening. The root-opened source fd is
        # the already validated, private snapshot, not an arbitrary path.
        code = r'''
import json, pathlib, runpy, shutil, sys
b = runpy.run_path('/usr/local/lib/hblink4-backup/backup.py')
folder = pathlib.Path(sys.argv[1]) / b['CONTROL']
folder.mkdir(parents=True, exist_ok=True, mode=0o700)
if folder.is_symlink() or folder.resolve() != folder:
    raise SystemExit('Unsafe backup directory')
token, sha = sys.argv[2:4]
with open(folder / (token + '.tar.gz'), 'xb') as out:
    shutil.copyfileobj(sys.stdin.buffer, out, 1024 * 1024)
    out.flush()
    import os
    os.fchmod(out.fileno(), 0o600)
b['atomic_json'](folder / 'restore-status.json', {'state':'queued','message':'Initial setup restore queued','updated_at':__import__('time').time()})
b['atomic_json'](folder / 'restore-request.json', {'token':token,'sha256':sha,'initial_setup':sys.argv[4] == 'fresh'})
'''
        with open(snapshot, "rb") as src:
            backup._as_owner(cfg, [sys.executable, "-I", "-c", code, cfg["data_dir"], token, sha256,
                                  "fresh" if self.fresh else "existing"], stdin=src, timeout=300)

    def wait(self, cfg, timeout=3600):
        status_file = Path(cfg["data_dir"]) / backup.CONTROL / "restore-status.json"
        started = time.monotonic()
        deadline, last = started + timeout, None
        while time.monotonic() < deadline:
            try:
                status = json.loads(status_file.read_text())
            except (OSError, ValueError):
                status = {}
            message = status.get("message", "Wiederherstellung wird gestartet …")
            if message != last:
                self.say(message)
                last = message
            if status.get("state") == "complete":
                return status
            if status.get("state") == "failed":
                raise SetupError(message)
            state = self.show("hblink4-restore.service", "ActiveState")
            if state == "failed" or (state in ("inactive", "not-found", "") and
                                     (status.get("state") != "queued" or time.monotonic() - started > 15)):
                raise SetupError("Der Wiederherstellungsdienst wurde beendet. Details: journalctl -u hblink4-restore.service")
            time.sleep(1)
        raise RestoreInProgress("Die Wartezeit ist abgelaufen. Der unabhängige Dienst kann weiterlaufen; Status mit systemctl status hblink4-restore.service prüfen.")

    def execute(self):
        self.preflight()
        # Keep the upload outside the installation that will be replaced. The
        # same immutable copy is checked, previewed and passed to the worker.
        with tempfile.TemporaryDirectory(prefix="hblink4-setup-restore-", dir=self.root.parent) as tmp:
            work = Path(tmp)
            snapshot = work / "backup.tar.gz"
            shutil.copyfile(self.archive, snapshot)
            if backup.encrypted(snapshot):
                key = Path(self.ask("Pfad zum separaten Wiederherstellungsschlüssel (.agekey): ").strip()).expanduser().resolve()
                plain = work / "decrypted.tar.gz"
                backup.plain_archive(snapshot, plain, key)
                snapshot = plain
            stage = work / "inspect"
            stage.mkdir()
            self.say("Backup wird vollständig geprüft …")
            manifest = backup.unpack_archive(snapshot, stage)
            account = self.target_account()
            if not self.preview(stage, manifest, account):
                self.say("Abgebrochen. Die Zielinstallation wurde nicht verändert.")
                return False
            try:
                self.system_extras(stage)
                if self.fresh:
                    self.prepare_fresh(account)
                self.run([self.root / "scripts/install_backup_helper.sh"], cwd=self.root, timeout=120)
                cfg = backup._host_config()
                if Path(cfg["root"]) != self.root:
                    raise SetupError("Der Diensthelfer gehört zu einer anderen Installation.")
                self.enqueue(cfg, snapshot, backup.digest(snapshot))
                self.queued = True
                self.say("Wiederherstellung gestartet. Python-Pakete können mehrere Minuten benötigen.")
                result = self.wait(cfg)
                marker = Path(cfg["data_dir"]) / backup.CONTROL / "setup-bootstrap.json"
                marker.unlink(missing_ok=True)
                self.say("\nBackup erfolgreich wiederhergestellt. Beide HBlink4-Dienste laufen.")
                self.say("Mit dem Superadmin-Konto aus dem Backup anmelden. Firewall und DNS des Zielservers prüfen.")
                self.say(f"Automatische Sicherung des vorherigen Zustands: {result.get('recovery', '')}")
                if (self.root / "dashboard/backup.py").is_file() and cfg.get("helper_sha256") != backup.digest(self.root / "dashboard/backup.py"):
                    self.say("Das Backup hat einen anderen Programmstand. Vor späteren Wiederherstellungen den Diensthelfer erneut installieren: sudo ./scripts/install_backup_helper.sh")
                return True
            except (RestoreInProgress, KeyboardInterrupt):
                # The systemd worker continues independently; never interrupt
                # an in-progress filesystem transaction on Ctrl-C or timeout.
                raise
            except Exception:
                if self.fresh and self.queued and self.show("hblink4-restore.service", "ActiveState") not in ("active", "activating", "deactivating"):
                    self.run(["systemctl", "stop", *backup.UNITS], timeout=120)
                raise


def main():
    """sudo python3 scripts/setup_restore.py INSTALLATIONSVERZEICHNIS BACKUP.tar.gz [--yes] [--account NAME]

    --yes:     ohne Rückfragen (Umzug durch den Web-Installer des HobbyRadioPortals): Vorschau wird nur angezeigt,
               die Bestätigung „RESTORE“ gilt als gegeben. Verschlüsselte AutoBackups (.age) gehen so nicht.
    --account: Dienst-Benutzer auf dem neuen Server (Vorgabe: Eigentümer des Verzeichnisses bzw. „hblink“)."""
    args = sys.argv[1:]
    yes = "--yes" in args
    account = None
    if "--account" in args:
        i = args.index("--account")
        account = args[i + 1] if i + 1 < len(args) else ""
        args = args[:i] + args[i + 2:]
    args = [a for a in args if a != "--yes"]
    if len(args) != 2:
        raise SetupError("Aufruf: sudo python3 scripts/setup_restore.py INSTALLATIONSVERZEICHNIS BACKUP.tar.gz [--yes] [--account NAME]")
    ask = input
    if yes:
        def ask(prompt):
            print(prompt, end="")
            if "RESTORE" in prompt:
                print("RESTORE")
                return "RESTORE"
            if "Dienst-Benutzer" in prompt:
                print(account or "")
                return account or ""
            raise SetupError("Rückfrage ohne Antwort im Modus --yes: " + prompt.strip())
    SetupRestore(args[0], args[1], ask=ask).execute()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nAnzeige abgebrochen. Ein bereits gestarteter Wiederherstellungsdienst läuft unabhängig weiter.", file=sys.stderr)
        sys.exit(130)
    except Exception as exc:
        print(f"Wiederherstellung fehlgeschlagen: {exc}", file=sys.stderr)
        sys.exit(1)
