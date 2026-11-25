"""Portable HBlink4 archives and the isolated systemd restore helper (stdlib only).

Never extract an uploaded tar with extractall. Every byte is checked before any
live file is changed; SQLite files are copied through SQLite's backup API.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import platform
import re
import shutil
import sqlite3
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

FORMAT = "hblink4-clone"
SCHEMA = 1
MAX_UPLOAD = 2 * 1024**3
MAX_ENCRYPTED_UPLOAD = MAX_UPLOAD + 1024**2
MAX_UNPACKED = 8 * 1024**3
MAX_FILES = 100000
CONTROL = ".hblink4-backup"
HELPER = "/usr/local/sbin/hblink4-restore"
HELPER_CONFIG = "/etc/hblink4-backup.json"
LOCK_PATH = "/run/hblink4-restore.lock"
UNITS = ("hblink4.service", "hblink4-dash.service")
EXCLUDED = {".git", "venv", ".venv", "env", "ENV", "__pycache__", ".pytest_cache",
            ".mypy_cache", ".ruff_cache", ".coverage", ".DS_Store", CONTROL,
            # N8 update guard: state of an update on THIS server – a clone must not inherit it
            "update.pending", "update.pending.tmp", "update.result", "update.request", "update.log", "n8-admin.json"}
REQUIRED = {"app/hblink4/hblink.py", "app/dashboard/server.py", "app/config/config.json",
            "app/dashboard/config.json", "data/dashboard.db"}


class BackupError(Exception):
    pass


def encrypted(path):
    with open(path, "rb") as src:
        return src.read(22).startswith(b"age-encryption.org/v1\n")


def identity_recipient(path):
    if not shutil.which("age-keygen"):
        raise BackupError("age-keygen fehlt. Bitte das Paket age installieren.")
    try:
        if not Path(path).is_file() or Path(path).stat().st_size > 4096:
            raise ValueError()
        raw = Path(path).read_text()
        keys = [line.strip() for line in raw.splitlines() if line.strip() and not line.lstrip().startswith("#")]
        if len(raw) > 4096 or len(keys) != 1 or not re.fullmatch(r"AGE-SECRET-KEY-1[0-9A-Z]+", keys[0]):
            raise ValueError()
    except (OSError, UnicodeError, ValueError):
        raise BackupError("Ein einzelner nativer age-Wiederherstellungsschlüssel wird benötigt.") from None
    try:
        value = command(["age-keygen", "-y", str(path)], timeout=15)
    except Exception:
        raise BackupError("Der Wiederherstellungsschlüssel ist ungültig oder nicht lesbar.") from None
    if not re.fullmatch(r"age1[0-9a-z]{58}", value):
        raise BackupError("Ein einzelner nativer age-Wiederherstellungsschlüssel wird benötigt.")
    return value


def encrypt_archive(source, target, recipient):
    if not shutil.which("age"):
        raise BackupError("age fehlt. Bitte das Paket age installieren.")
    try:
        command(["age", "--encrypt", "--recipient", recipient, "--output", str(target), str(source)], timeout=900)
        os.chmod(target, 0o600)
    except Exception:
        Path(target).unlink(missing_ok=True)
        raise BackupError("Die Verschlüsselung ist fehlgeschlagen.") from None


def plain_archive(source, target, identity=None):
    """Decrypt an age archive to a private file, or copy a legacy plaintext one."""
    if not encrypted(source):
        if Path(source).stat().st_size > MAX_UPLOAD:
            raise BackupError("Backup exceeds 2 GiB.")
        shutil.copyfile(source, target)
        os.chmod(target, 0o600)
        return False
    if Path(source).stat().st_size > MAX_ENCRYPTED_UPLOAD:
        raise BackupError("Encrypted backup exceeds the upload limit.")
    if identity is None:
        raise BackupError("Verschlüsseltes Backup: bitte den separaten Wiederherstellungsschlüssel auswählen.")
    identity_recipient(identity)
    if not shutil.which("age"):
        raise BackupError("age fehlt. Bitte das Paket age installieren.")
    try:
        command(["age", "--decrypt", "--identity", str(identity), "--output", str(target), str(source)], timeout=900)
        os.chmod(target, 0o600)
        if Path(target).stat().st_size > MAX_UPLOAD:
            raise BackupError("Decrypted backup exceeds 2 GiB.")
    except Exception:
        Path(target).unlink(missing_ok=True)
        raise BackupError("Entschlüsseln fehlgeschlagen: Schlüssel passt nicht oder das Backup ist beschädigt.") from None
    return True


def digest(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp-" + uuid.uuid4().hex)
    try:
        with open(temporary, "x", encoding="utf-8") as f:
            os.chmod(temporary, 0o600)
            json.dump(value, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def command(args, **kw):
    p = subprocess.run(args, capture_output=True, text=True, timeout=kw.pop("timeout", 30), **kw)
    if p.returncode:
        raise BackupError((p.stderr.strip() or p.stdout.strip() or "Command failed")[-1500:])
    return p.stdout.strip()


def snapshot_file(source, dest):
    """Include committed WAL contents rather than copying a live .db file."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    with open(source, "rb") as f:
        is_sqlite = f.read(16) == b"SQLite format 3\x00"
    if is_sqlite:
        with contextlib.closing(sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True)) as src:
            with contextlib.closing(sqlite3.connect(str(dest))) as dst:
                src.backup(dst, pages=256, sleep=0.01)
                if dst.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                    raise BackupError(f"Database check failed: {source.name}")
        shutil.copymode(source, dest)
    else:
        shutil.copy2(source, dest)


def copy_tree(source, dest, skip=()):
    """Materialise internal certificate symlinks; reject external links/cycles."""
    source, dest = Path(source).resolve(), Path(dest)
    skipped = {Path(p).resolve() for p in skip}

    def walk(folder, target, parents):
        real = folder.resolve()
        if real in skipped:
            return
        if not real.is_relative_to(source) or real in parents:
            raise BackupError(f"External or recursive symlink: {folder}. Move this data into the installation first.")
        target.mkdir(parents=True, exist_ok=True)
        for item in sorted(folder.iterdir()):
            if item.name in EXCLUDED or item.name.endswith(("-wal", "-shm", ".pyc", ".sock")):
                continue
            resolved = item.resolve()
            if resolved in skipped:
                continue
            if not resolved.is_relative_to(source):
                raise BackupError(f"External symlink cannot be backed up: {item}")
            if item.is_dir():
                walk(item, target / item.name, parents | {real})
            elif item.is_file():
                snapshot_file(item, target / item.name)
            elif not stat.S_ISSOCK(item.lstat().st_mode):
                raise BackupError(f"Unsupported file in installation: {item}")
    walk(source, dest, set())


def create_archive(root, data_dir, output, *, version=None, system_units=None, python=None, stage_hook=None):
    root, data_dir, output = Path(root).resolve(), Path(data_dir).resolve(), Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="hblink4-snapshot-", dir=output.parent) as tmp:
        stage = Path(tmp)
        copy_tree(root, stage / "app", skip=[data_dir, output.parent])
        copy_tree(data_dir, stage / "data")
        core_path = stage / "app/config/config.json"
        core = json.loads(core_path.read_text()) if core_path.exists() else {}
        configured_db = (core.get("global") or {}).get("settings_db", "dashboard/data/dashboard.db")
        core_db = Path(configured_db)
        if not core_db.is_absolute():
            core_db = root / core_db
        if core_db.resolve() == data_dir / "dashboard.db":
            core.setdefault("global", {})["settings_db"] = str(data_dir / "dashboard.db")
        elif not core_db.resolve().is_relative_to(root):
            if not core_db.is_file():
                raise BackupError("Configured DMR settings database is missing.")
            snapshot_file(core_db, stage / "data/backup-core-settings.db")
            core.setdefault("global", {})["settings_db"] = str(data_dir / "backup-core-settings.db")
        if core_path.exists():
            core_path.write_text(json.dumps(core, indent=2) + "\n")
        # Custom TLS files outside the installation are made portable too.
        cfg_path = stage / "app/dashboard/config.json"
        cfg = json.loads(cfg_path.read_text()) if cfg_path.exists() else {}
        tls = cfg.get("https") or {}
        for key in ("cert_file", "key_file"):
            if tls.get(key):
                src = Path(tls[key])
                if not src.is_absolute():
                    src = root / src
                if not src.is_file():
                    raise BackupError(f"Configured TLS file is missing: {key}")
                snapshot_file(src, stage / "data/backup-tls" / (key + ".pem"))
                tls[key] = str(data_dir / "backup-tls" / (key + ".pem"))
        if cfg_path.exists():
            cfg_path.write_text(json.dumps(cfg, indent=2) + "\n")
        if stage_hook:
            stage_hook(stage)   # e.g. the migration package: change the COPY before checksums are taken
        meta = stage / "metadata"
        meta.mkdir()
        (meta / "services.json").write_text(json.dumps(system_units or {}, indent=2))
        installed = json.loads(command([str(python or sys.executable), "-c",
            "import importlib.metadata as m,json; print(json.dumps([{'name': d.metadata['Name'], 'version': d.version, "
            "'direct': d.read_text('direct_url.json')} for d in m.distributions()]))"], timeout=60))
        pins = []
        for package in installed:
            name, package_version = package["name"], package["version"]
            if str(name).lower() == "hblink4":
                continue  # the program is restored from the archive, not PyPI
            if package.get("direct") or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", name or "") or not re.fullmatch(r"[A-Za-z0-9.!+_-]+", package_version or ""):
                raise BackupError("Python has non-portable dependencies. Install published package versions before creating a clone.")
            pins.append(f"{name}=={package_version}")
        freeze = "\n".join(sorted(set(pins), key=str.lower))
        (meta / "requirements-frozen.txt").write_text(freeze + "\n")
        if (root / ".git").exists():
            command(["git", "-c", f"safe.directory={root}", "-C", str(root), "bundle", "create",
                     str(meta / "repository.bundle"), "HEAD"], timeout=120)
        origin = ""
        if (root / ".git").exists():
            p = subprocess.run(["git", "-c", f"safe.directory={root}", "-C", str(root), "remote", "get-url", "origin"],
                               capture_output=True, text=True, timeout=10)
            candidate = p.stdout.strip() if p.returncode == 0 else ""
            if re.fullmatch(r"https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:\.git)?", candidate):
                origin = candidate
        files = {}
        total = 0
        for p in sorted(stage.rglob("*")):
            if p.is_file():
                name = p.relative_to(stage).as_posix()
                total += p.stat().st_size
                if total > MAX_UNPACKED or len(files) >= MAX_FILES:
                    raise BackupError("Backup exceeds the archive size/file limit.")
                files[name] = {"size": p.stat().st_size, "sha256": digest(p),
                               "mode": stat.S_IMODE(p.stat().st_mode) & 0o777}
        missing = REQUIRED - files.keys()
        if missing:
            raise BackupError("Incomplete installation: missing " + ", ".join(sorted(missing)))
        manifest = {"format": FORMAT, "schema": SCHEMA, "created_at": datetime.now(timezone.utc).isoformat(),
                    "version": version or {}, "source_root": str(root), "source_data": str(data_dir),
                    "python": platform.python_version(), "platform": platform.platform(),
                    "origin": origin, "files": files, "unpacked_bytes": total}
        (stage / "manifest.json").write_text(json.dumps(manifest, indent=2))
        try:
            with tarfile.open(output, "w:gz", compresslevel=5) as archive:
                for name in ["manifest.json", *files]:
                    archive.add(stage / name, arcname=name, recursive=False)
            os.chmod(output, 0o600)
            if output.stat().st_size > MAX_UPLOAD:
                raise BackupError("Compressed backup exceeds the 2 GiB upload limit.")
        except Exception:
            output.unlink(missing_ok=True)
            raise
    return manifest


def unpack_archive(archive_path, destination):
    """Validate names, types, sizes, checksums and SQLite; return only on success."""
    destination = Path(destination)
    if Path(archive_path).stat().st_size > MAX_UPLOAD:
        raise BackupError("Archive exceeds 2 GiB.")
    try:
        with tarfile.open(archive_path, "r:gz") as tar:
            seen, total, manifest = set(), 0, None
            for member in tar:
                name = member.name
                path = PurePosixPath(name)
                if (not member.isfile() or path.is_absolute() or ".." in path.parts or
                        "\\" in name or "\x00" in name or path.as_posix() != name or name in seen or
                        len(name) > 1000 or member.size < 0):
                    raise BackupError("Archive contains an unsafe path, duplicate or non-regular file.")
                if name != "manifest.json" and (len(path.parts) < 2 or path.parts[0] not in ("app", "data", "metadata") or
                        any(part in EXCLUDED for part in path.parts[1:]) or name.endswith(("-wal", "-shm"))):
                    raise BackupError(f"Unsupported archive entry: {name}")
                seen.add(name)
                total += member.size
                if total > MAX_UNPACKED or len(seen) > MAX_FILES + 1:
                    raise BackupError("Archive exceeds the unpacked size/file limit.")
                if name == "manifest.json":
                    if manifest is not None or member.size > 32 * 1024**2:
                        raise BackupError("Invalid manifest.")
                    manifest = json.load(tar.extractfile(member))
                    continue
                target = destination / name
                target.parent.mkdir(parents=True, exist_ok=True)
                with open(target, "xb") as out:
                    shutil.copyfileobj(tar.extractfile(member), out, 1024 * 1024)
                os.chmod(target, 0o600)
        if not isinstance(manifest, dict) or manifest.get("format") != FORMAT or manifest.get("schema") != SCHEMA:
            raise BackupError("Not a supported HBlink4 clone backup.")
        for key, kind in (("created_at", str), ("version", dict), ("platform", str),
                          ("source_root", str), ("source_data", str)):
            if not isinstance(manifest.get(key), kind):
                raise BackupError(f"Invalid manifest field: {key}")
        datetime.fromisoformat(manifest["created_at"])
        for key in ("source_root", "source_data"):
            if not manifest[key].startswith("/") or manifest[key] == "/":
                raise BackupError("Invalid source installation path.")
        files = manifest.get("files")
        if not isinstance(files, dict) or set(files) != seen - {"manifest.json"} or not REQUIRED <= files.keys():
            raise BackupError("The backup is incomplete or has undeclared files.")
        if not {"metadata/requirements-frozen.txt", "metadata/services.json"} <= files.keys():
            raise BackupError("Dependency or service metadata is missing.")
        if manifest.get("unpacked_bytes") != sum(v.get("size", -1) for v in files.values() if isinstance(v, dict)):
            raise BackupError("Invalid unpacked size.")
        if not isinstance(manifest.get("python"), str) or not re.fullmatch(r"3\.\d+\.\d+", manifest["python"]):
            raise BackupError("Invalid Python version metadata.")
        if tuple(map(int, manifest["python"].split(".")[:2])) < (3, 9) or sys.version_info[:2] < (3, 9):
            raise BackupError("HBlink4 restore requires Python 3.9 or newer.")
        for name, info in files.items():
            p = destination / name
            if not isinstance(info, dict) or p.stat().st_size != info.get("size") or digest(p) != info.get("sha256"):
                raise BackupError(f"Checksum failed: {name}")
            mode = info.get("mode", 0o600)
            if not isinstance(mode, int) or mode < 0 or mode > 0o777:
                raise BackupError("Invalid file permissions.")
            os.chmod(p, mode)
            with open(p, "rb") as f:
                sqlite = f.read(16) == b"SQLite format 3\x00"
            if sqlite:
                with contextlib.closing(sqlite3.connect(p.resolve().as_uri() + "?mode=ro", uri=True)) as db:
                    if db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                        raise BackupError(f"Invalid database: {name}")
        for name in ("app/config/config.json", "app/dashboard/config.json", "metadata/services.json"):
            if name in files and not isinstance(json.loads((destination / name).read_text()), dict):
                raise BackupError(f"Invalid JSON configuration: {name}")
        return manifest
    except (OSError, tarfile.TarError, ValueError, KeyError, TypeError, sqlite3.Error) as e:
        raise BackupError(f"Invalid backup: {e}") from e


def summary(manifest):
    return {k: manifest[k] for k in ("format", "schema", "created_at", "version", "python", "platform", "unpacked_bytes")} | {
        "files": len(manifest["files"]), "contains_secrets": True,
        "target_python": platform.python_version(), "python_migration": python_migration(manifest)}


def python_migration(manifest):
    return tuple(map(int, manifest["python"].split(".")[:2])) != sys.version_info[:2]


def helper_available(root, data_dir):
    try:
        cfg = json.loads(Path(HELPER_CONFIG).read_text())
        if cfg["root"] != str(Path(root).resolve()) or cfg["data_dir"] != str(Path(data_dir).resolve()):
            return False
        if cfg.get("helper_sha256") != digest(Path(__file__)):
            return False
        return Path(HELPER).is_file() and subprocess.run(
            ["systemctl", "is-active", "--quiet", "hblink4-restore.path"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5).returncode == 0
    except (OSError, ValueError, KeyError, subprocess.SubprocessError):
        return False


def adapt_paths(stage, manifest, root, data_dir):
    replacements = [(manifest["source_data"], str(data_dir)), (manifest["source_root"], str(root))]
    if not all(isinstance(old, str) and old.startswith("/") and old != "/" for old, _ in replacements):
        raise BackupError("Invalid source paths.")

    def remap(v, key=""):
        if isinstance(v, dict):
            return {k: remap(val, k) for k, val in v.items()}
        if isinstance(v, list):
            return [remap(val, key) for val in v]
        if isinstance(v, str) and key in ("cert_file", "key_file", "settings_db", "unix_socket", "log_file"):
            for old, new in replacements:
                if v == old or v.startswith(old + "/"):
                    return new + v[len(old):]
        return v
    for name in ("app/config/config.json", "app/dashboard/config.json"):
        path = stage / name
        path.write_text(json.dumps(remap(json.loads(path.read_text())), indent=2) + "\n")
    # Settings are authoritative after initial seeding. Preserve passwords,
    # callsigns, subscriptions etc.; adapt only installation-local paths.
    db_path = stage / "data/dashboard.db"
    with sqlite3.connect(db_path) as db:
        for key, value in db.execute("SELECT key, value FROM settings").fetchall():
            old = json.loads(value)
            new = remap(old, key.rsplit(".", 1)[-1])
            if old != new:
                db.execute("UPDATE settings SET value=? WHERE key=?", (json.dumps(new), key))
        # Imported session cookies must never silently authenticate on a clone.
        db.execute("DELETE FROM sessions")


def collect_units():
    units = {}
    if shutil.which("systemctl"):
        for unit in UNITS:
            p = subprocess.run(["systemctl", "cat", unit], capture_output=True, text=True, timeout=10)
            if p.returncode == 0:
                units[unit] = p.stdout
    return units


def _host_config():
    p = Path(HELPER_CONFIG)
    if p.is_symlink() or p.stat().st_uid != 0 or p.stat().st_mode & 0o022:
        raise BackupError("Restore helper configuration must be owned and writable only by root.")
    cfg = json.loads(p.read_text())
    for k in ("root", "data_dir"):
        value = Path(cfg[k])
        if not value.is_absolute() or value.resolve() != value or value.resolve() == Path("/"):
            raise BackupError("Invalid helper installation path.")
    parent = Path(cfg["root"]).parent.stat()
    if parent.st_uid != 0 or parent.st_mode & 0o022:
        raise BackupError("The installation's parent directory must be owned and writable only by root.")
    data = Path(cfg["data_dir"])
    if not data.is_relative_to(Path(cfg["root"])):
        parent = data.parent.stat()
        if parent.st_uid != 0 or parent.st_mode & 0o022:
            raise BackupError("External data needs a root-protected parent directory.")
    return cfg


def _as_owner(cfg, args, **kw):
    return command(args, user=int(cfg["uid"]), group=int(cfg["gid"]), extra_groups=[],
                   env={"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": cfg["home"], "LANG": "C.UTF-8",
                        "PYTHONNOUSERSITE": "1", "PIP_CONFIG_FILE": "/dev/null"}, **kw)


def _own_tree(path, cfg):
    for item in [path, *path.rglob("*")]:
        os.chown(item, int(cfg["uid"]), int(cfg["gid"]), follow_symlinks=False)


def check_python_sources(stage):
    """Compile, never execute, restored program sources with the target Python."""
    for directory in ("hblink4", "dashboard", "scripts"):
        for path in (Path(stage) / "app" / directory).rglob("*.py"):
            try:
                compile(path.read_bytes(), str(path.relative_to(stage)), "exec", dont_inherit=True)
            except (SyntaxError, ValueError) as error:
                target = f"{sys.version_info.major}.{sys.version_info.minor}"
                raise BackupError(f"Programmdatei {path.relative_to(stage)} ist mit Ziel-Python {target} nicht kompatibel: {error}") from None


def migration_requirements(text):
    """Keep application pins; bootstrap tools must belong to the target Python."""
    lines = []
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        match = re.fullmatch(r"([A-Za-z0-9][A-Za-z0-9._-]*)==([A-Za-z0-9.!+_-]+)", line.strip())
        if not match:
            raise BackupError("Ungültige gespeicherte Python-Paketversion. Nur veröffentlichte Name==Version-Einträge sind übertragbar.")
        if match[1].lower() not in ("pip", "setuptools", "wheel"):
            lines.append(line.strip())
    return "\n".join(lines) + "\n"


def prepare_python_packages(cfg, stage, prepared):
    """Build and test saved pins before stopping services, as the service user.

    Keep a wheelhouse at its final control-directory path across the swap. The
    final venv is created at root/venv, since virtualenvs cannot be relocated.
    """
    check_python_sources(stage)
    code = r'''
import pathlib, shutil, subprocess, sys
folder = pathlib.Path(sys.argv[1])
folder.mkdir(mode=0o700)
requirements = folder / 'requirements.txt'
requirements.write_text(sys.stdin.read())
def run(args):
    result = subprocess.run(list(map(str, args)), stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, errors='replace')
    if result.returncode:
        raise SystemExit(result.stdout[-2000:])
run([sys.executable, '-m', 'venv', folder / 'probe'])
python = folder / 'probe/bin/python'
wheels = folder / 'wheels'
wheels.mkdir()
if requirements.read_text().strip():
    run([python, '-m', 'pip', 'wheel', '--wheel-dir', wheels, '-r', requirements])
    run([python, '-m', 'pip', 'install', '--no-index', '--find-links', wheels, '-r', requirements])
run([python, '-m', 'pip', 'check'])
shutil.rmtree(folder / 'probe')
'''
    try:
        _as_owner(cfg, [sys.executable, "-I", "-c", code, str(prepared)],
                  input=migration_requirements((Path(stage) / "metadata/requirements-frozen.txt").read_text()), timeout=1800)
    except (BackupError, subprocess.SubprocessError) as error:
        target = f"{sys.version_info.major}.{sys.version_info.minor}"
        raise BackupError(f"Paketprüfung für Ziel-Python {target} fehlgeschlagen. Die gesicherten Paketversionen müssen auf dem Ziel installierbar sein. {error}") from None


def cleanup_prepared_python(cfg, prepared):
    # This directory is writable by the service user. Never follow/remove its
    # contents as root, including on the failure/rollback path.
    with contextlib.suppress(Exception):
        _as_owner(cfg, [sys.executable, "-I", "-c",
                       "import shutil,sys; shutil.rmtree(sys.argv[1])", str(prepared)], timeout=60)


class InstallationSwap:
    """Directory-level transaction. The untouched old venv also rolls back."""

    def __init__(self, root, data, stage, work):
        self.root, self.data, self.stage, self.work = map(Path, (root, data, stage, work))
        self.old_root = self.work / "previous-installation"
        self.old_data = self.work / "previous-data"
        self.relative_data = self.data.relative_to(self.root) if self.data.is_relative_to(self.root) else None
        if self.data == self.root or self.root.is_relative_to(self.data):
            raise BackupError("The data directory must be a child of the installation or a separate directory.")
        self.root_moved = self.data_moved = False
        self.new_data = self.stage / "app" / self.relative_data if self.relative_data else self.stage / "data"
        self.saved_control = self.work / "control"

    def apply(self):
        if self.relative_data:
            self.new_data.parent.mkdir(parents=True, exist_ok=True)
            if self.new_data.exists():
                raise BackupError("The archive contains duplicate application/data directories.")
            os.replace(self.stage / "data", self.new_data)
        elif self.data.stat().st_dev != self.work.stat().st_dev:
            raise BackupError("External data must be on the same filesystem for an atomic restore.")
        # Control files survive success and rollback, but are never restored from
        # an uploaded archive. No uploaded path can replace a recovery archive.
        control = self.data / CONTROL
        if control.is_symlink():
            raise BackupError("Backup control directory must not be a symlink.")
        if control.exists():
            os.replace(control, self.saved_control)
        try:
            os.replace(self.root, self.old_root)
            self.root_moved = True
            os.replace(self.stage / "app", self.root)
            if not self.relative_data:
                os.replace(self.data, self.old_data)
                self.data_moved = True
                os.replace(self.new_data, self.data)
            if self.saved_control.exists():
                os.replace(self.saved_control, self.data / CONTROL)
        except Exception:
            self.rollback()
            raise

    def rollback(self):
        control = self.data / CONTROL
        if control.exists() and not self.saved_control.exists():
            os.replace(control, self.saved_control)
        if self.data_moved:
            if self.data.exists():
                shutil.rmtree(self.data)
            os.replace(self.old_data, self.data)
            self.data_moved = False
        if self.root_moved:
            if self.root.exists():
                shutil.rmtree(self.root)
            os.replace(self.old_root, self.root)
            self.root_moved = False
        if self.saved_control.exists():
            os.replace(self.saved_control, self.data / CONTROL)


def restore_worker(cfg):
    """Runs in a dedicated systemd unit; never run uploaded code as root."""
    import fcntl
    root, data = Path(cfg["root"]), Path(cfg["data_dir"])
    control = data / CONTROL
    if control.is_symlink() or control.resolve() != control:
        raise BackupError("Unsafe backup control directory.")
    with open(LOCK_PATH, "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        request_path = control / "restore-request.json"
        fd = os.open(request_path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, "r") as request_file:
            info = os.fstat(request_file.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid != int(cfg["uid"]) or info.st_size > 16384:
                raise BackupError("Invalid restore request file.")
            request = json.load(request_file)
        initial_setup = request.get("initial_setup") is True
        token = request.get("token", "")
        if not re.fullmatch(r"[a-f0-9]{32}", token):
            raise BackupError("Invalid restore request.")
        archive = control / (token + ".tar.gz")
        request_path.unlink()
        result_path = control / "restore-status.json"

        def status(state, message, **extra):
            value = {"state": state, "message": message, "updated_at": time.time(), **extra}
            # This directory belongs to the service account. All writes there
            # must use that account's privileges, even if it swaps symlinks.
            _as_owner(cfg, [sys.executable, "-I", str(Path(__file__).resolve()), "--write-status"],
                      input=json.dumps(value))

        status("running", "Checking backup before stopping services")
        stopped = False
        prepared = None
        rollback_archive = control / ("before-restore-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S") + ".tar.gz")
        with tempfile.TemporaryDirectory(prefix="hblink4-restore-", dir=root.parent) as tmp:
            work, stage = Path(tmp), Path(tmp) / "stage"
            stage.mkdir()
            swap = InstallationSwap(root, data, stage, work)
            try:
                fd = os.open(archive, os.O_RDONLY | os.O_NOFOLLOW)
                with os.fdopen(fd, "rb") as src, open(work / "upload.tar.gz", "xb") as dst:
                    if (not stat.S_ISREG(os.fstat(src.fileno()).st_mode) or os.fstat(src.fileno()).st_size > MAX_UPLOAD
                            or os.fstat(src.fileno()).st_uid != int(cfg["uid"])):
                        raise BackupError("Invalid upload file.")
                    shutil.copyfileobj(src, dst, 1024 * 1024)
                if digest(work / "upload.tar.gz") != request.get("sha256"):
                    raise BackupError("Backup changed after preview. Upload and inspect it again.")
                manifest = unpack_archive(work / "upload.tar.gz", stage)
                adapt_paths(stage, manifest, root, data)
                if shutil.disk_usage(root).free < manifest["unpacked_bytes"] + 1024**3:
                    raise BackupError("Not enough free disk space for a safe restore.")
                if python_migration(manifest):
                    target = f"{sys.version_info.major}.{sys.version_info.minor}"
                    status("running", f"Python {manifest['python']} → {target}: Paket- und Codeprüfung vor dem Stoppen der Dienste")
                    prepared = control / ("restore-python-" + uuid.uuid4().hex)
                    prepare_python_packages(cfg, stage, prepared)
                    if shutil.disk_usage(root).free < manifest["unpacked_bytes"] + 1024**3:
                        raise BackupError("Not enough free disk space after preparing Python packages.")
                # Stopping both services flushes in-memory state before making
                # the independent, downloadable recovery archive.
                status("running", "Stopping services and creating the automatic recovery backup")
                stopped = True
                command(["systemctl", "stop", *UNITS], timeout=120)
                _as_owner(cfg, [sys.executable, "-I", str(Path(__file__).resolve()),
                                "--snapshot", str(rollback_archive)], timeout=900)
                # Transfer ownership while staging is still behind the
                # root-only work directory, before exposing it to the account.
                _own_tree(stage / "app", cfg)
                _own_tree(stage / "data", cfg)
                swap.apply()
                status("running", "Rebuilding the Python environment with saved package versions")
                _as_owner(cfg, [sys.executable, "-m", "venv", str(root / "venv")], timeout=120)
                frozen = stage / "metadata/requirements-frozen.txt"
                if prepared:
                    target_requirements = work / "requirements-target.txt"
                    target_requirements.write_text(migration_requirements(frozen.read_text()))
                    frozen = target_requirements
                requirements = control / "restore-requirements.txt"
                with open(frozen, "rb") as src:
                    _as_owner(cfg, [sys.executable, "-I", str(Path(__file__).resolve()),
                                    "--write-file", requirements.name], stdin=src)
                try:
                    options = ["--no-index", "--find-links", str(prepared / "wheels")] if prepared else []
                    _as_owner(cfg, [str(root / "venv/bin/python"), "-m", "pip", "install", *options,
                                    "-r", str(requirements)], timeout=1800)
                    _as_owner(cfg, [str(root / "venv/bin/python"), "-m", "pip", "check"], timeout=60)
                finally:
                    requirements.unlink(missing_ok=True)
                bundle = stage / "metadata/repository.bundle"
                if bundle.exists():
                    safe_bundle = control / "restore-repository.bundle"
                    with open(bundle, "rb") as src:
                        _as_owner(cfg, [sys.executable, "-I", str(Path(__file__).resolve()),
                                        "--write-file", safe_bundle.name], stdin=src)
                    try:
                        _as_owner(cfg, ["git", "init", "--template=", str(root)])
                        _as_owner(cfg, ["git", "-C", str(root), "fetch", str(safe_bundle), "HEAD"])
                        _as_owner(cfg, ["git", "-C", str(root), "symbolic-ref", "HEAD", "refs/heads/main"])
                        # --mixed builds the index without touching files,
                        # retaining every uncommitted change in the snapshot.
                        _as_owner(cfg, ["git", "-C", str(root), "reset", "--mixed", "FETCH_HEAD"], timeout=60)
                        origin = manifest.get("origin", "")
                        if re.fullmatch(r"https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:\.git)?", origin):
                            _as_owner(cfg, ["git", "-C", str(root), "remote", "add", "origin", origin])
                    finally:
                        safe_bundle.unlink(missing_ok=True)
                # Destination systemd units stay in place: its users, paths,
                # privileges and environment belong to this host. Source units
                # are included for reference, never executed as root on upload.
                command(["systemctl", "start", *UNITS], timeout=120)
                # Watch for a crash/restart cycle as well as an immediate
                # startup error; Type=simple alone reports success too early.
                for _ in range(10):
                    time.sleep(1)
                    for unit in UNITS:
                        command(["systemctl", "is-active", "--quiet", unit])
                        restarts = command(["systemctl", "show", unit, "-p", "NRestarts", "--value"])
                        if int(restarts or "0"):
                            raise BackupError(f"{unit} restarted unexpectedly after restore.")
                if initial_setup:
                    command(["systemctl", "enable", *UNITS])
                    _as_owner(cfg, [sys.executable, "-I", "-c",
                                    "from pathlib import Path; import sys; Path(sys.argv[1]).unlink(missing_ok=True)",
                                    str(control / "setup-bootstrap.json")])
                status("complete", "Backup restored. Sign in with the source installation's account.",
                       recovery=rollback_archive.name, backup=summary(manifest))
                archive.unlink(missing_ok=True)
            except Exception as error:
                recovery_error = ""
                try:
                    if stopped:
                        command(["systemctl", "stop", *UNITS], timeout=120)
                        swap.rollback()
                        if initial_setup:
                            # A fresh setup's recovery point is a stopped
                            # bootstrap, not a configured public DMR server.
                            command(["systemctl", "disable", *UNITS])
                        else:
                            command(["systemctl", "start", *UNITS], timeout=120)
                except Exception as secondary:
                    recovery_error = f" Automatic rollback needs attention: {secondary}"
                if recovery_error:
                    # Keep the untouched old installation for manual recovery.
                    rescue = root.parent / ("hblink4-recovery-" + token)
                    shutil.move(str(work), str(rescue))
                with contextlib.suppress(Exception):
                    status("failed", str(error) + recovery_error,
                           recovery=rollback_archive.name if rollback_archive.exists() else "")
                raise
            finally:
                if prepared is not None:
                    cleanup_prepared_python(cfg, prepared)

def main():
    parser = argparse.ArgumentParser(description="HBlink4 isolated restore helper")
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--snapshot", metavar="OUTPUT")
    parser.add_argument("--write-status", action="store_true")
    parser.add_argument("--write-file", choices=("restore-requirements.txt", "restore-repository.bundle"))
    args = parser.parse_args()
    cfg = _host_config()
    if args.write_status or args.write_file:
        if os.geteuid() != int(cfg["uid"]):
            raise BackupError("Control files must be written as the service account.")
        control = Path(cfg["data_dir"]) / CONTROL
        if args.write_status:
            value = json.loads(sys.stdin.read(16384))
            atomic_json(control / "restore-status.json", value)
        else:
            # A symlink can at worst target files already writable by the
            # service account; this process has no additional privileges.
            with open(control / args.write_file, "wb") as out:
                shutil.copyfileobj(sys.stdin.buffer, out, 1024 * 1024)
                os.chmod(out.fileno(), 0o600)
        return
    if args.snapshot:
        if os.geteuid() != int(cfg["uid"]):
            raise BackupError("Recovery snapshots must run as the configured service account.")
        create_archive(cfg["root"], cfg["data_dir"], args.snapshot,
                       version={"label": "automatic recovery"}, system_units=collect_units(),
                       python=Path(cfg["root"]) / "venv/bin/python")
        return
    if os.geteuid() != 0:
        raise BackupError("The restore helper must be started through its configured sudo rule.")
    if args.worker:
        restore_worker(cfg)
    else:
        command(["systemctl", "start", "hblink4-restore.service"])


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"HBlink4 restore failed: {exc}", file=sys.stderr)
        sys.exit(1)
