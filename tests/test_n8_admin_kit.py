"""N8 Admin-Kit im Dashboard: root-eigene Dateien von „Update jetzt“ und Keep-Alive dürfen den Start nicht verhindern (1.12.4)."""
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def test_root_owned_update_files_do_not_stop_the_dashboard(tmp_path, monkeypatch):
    src = (ROOT / "dashboard" / "server.py").read_text()
    assert '"update.log", "update.result", "keepalive.json"' in src
    import ast
    tree = ast.parse(src)
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_ensure_writable")
    ns = {"os": os, "Path": Path, "sys": sys, "logger": __import__("logging").getLogger("t")}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), "server.py", "exec"), ns)
    (tmp_path / "update.result").write_text("{}")
    (tmp_path / "update.log").write_text("x")
    real = os.access
    monkeypatch.setattr(os, "access", lambda p, m: False if Path(p).name.startswith("update.") else real(p, m))
    ns["_ensure_writable"](tmp_path)              # kein SystemExit
    (tmp_path / "dashboard.db").write_text("x")
    monkeypatch.setattr(os, "access", lambda p, m: False if Path(p).name == "dashboard.db" else real(p, m))
    with pytest.raises(SystemExit):
        ns["_ensure_writable"](tmp_path)
