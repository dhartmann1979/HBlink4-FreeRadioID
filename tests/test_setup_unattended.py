"""setup.sh ohne Rückfragen (HB4_ANSWERS) – für den Web-Installer des HobbyRadioPortals."""
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SETUP = ROOT / "scripts" / "setup.sh"


class TestUnattendedSetup(unittest.TestCase):
    def test_syntax_and_mode(self):
        self.assertEqual(subprocess.run(["bash", "-n", str(SETUP)]).returncode, 0)
        s = SETUP.read_text()
        self.assertIn('UNATTENDED=0; [ -n "${HB4_ANSWERS:-}" ] && UNATTENDED=1', s)
        self.assertIn('fi   # Fragen oder HB4_ANSWERS', s)

    def test_ask_helpers_take_default_without_tty(self):
        """ask/ask_yn liefern im Modus die Vorgabe, ohne zu lesen."""
        s = SETUP.read_text()
        start, end = s.index("UNATTENDED=0;"), s.index("ask_secret() {")
        script = s[start:end] + 'ask A "Frage" "vorgabe"; ask_yn J "Frage" j; ask_yn N "Frage" n; echo "$A $J $N"\n'
        out = subprocess.run(["bash", "-c", script], env={"HB4_ANSWERS": "/x", "PATH": "/usr/bin:/bin"},
                             capture_output=True, text=True, timeout=10, stdin=subprocess.DEVNULL)
        self.assertEqual(out.stdout.strip(), "vorgabe true false")


if __name__ == "__main__":
    unittest.main()
