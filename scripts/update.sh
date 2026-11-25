#!/usr/bin/env bash
# =============================================================================
#  HBlink4-FreeRadioID – Update von der Konsole (oder vom HobbyRadioPortal)
#
#      sudo ./scripts/update.sh            holt die neueste Version, behält alle Einstellungen und Daten
#      sudo ./scripts/update.sh --check    nur prüfen: JSON {current, latest, behind, notes}
#
#  Wie „Update jetzt installieren“ im Dashboard: nur vorspulen (fast-forward) auf den Branch von „origin“,
#  nie mit von Hand geänderten Dateien. Python-Pakete werden nur bei geänderten requirements* nachinstalliert.
#  Danach werden Besitzer und Rechte geprüft und korrigiert, beide Dienste neu gestartet und der N8 update guard
#  scharf geschaltet: kommt das Dashboard nach drei Starts nicht hoch, setzt er auf den alten Stand zurück.
# =============================================================================
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
G='\033[0;32m'; Y='\033[0;33m'; R='\033[0;31m'; N='\033[0m'
ok()   { echo -e "  ${G}✓${N} $*"; }
warn() { echo -e "  ${Y}!${N} $*"; }
die()  { echo -e "  ${R}✗ $*${N}" >&2; exit 1; }
[[ $EUID -eq 0 ]] || die "Bitte als root starten: sudo $0"
git_() { git -c "safe.directory=$ROOT" -c core.hooksPath=/dev/null -C "$ROOT" "$@"; }
[[ -d "$ROOT/.git" ]] || die "$ROOT ist kein git-Checkout – bitte von Hand aktualisieren"
BRANCH="$(git_ rev-parse --abbrev-ref HEAD)"
CUR="$(tr -d '[:space:]' < "$ROOT/VERSION" 2>/dev/null || echo '?')"
git_ fetch -q --no-tags origin "refs/heads/$BRANCH"
NEW_SHA="$(git_ rev-parse FETCH_HEAD)"; OLD_SHA="$(git_ rev-parse HEAD)"
BEHIND="$(git_ rev-list --count "HEAD..$NEW_SHA")"
LATEST="$(git_ show "$NEW_SHA:VERSION" 2>/dev/null | tr -d '[:space:]' || echo "$CUR")"

if [[ "${1:-}" == "--check" ]]; then
    git_ log --format=%s -n 12 "HEAD..$NEW_SHA" | python3 -c 'import json,sys; print(json.dumps({"current": sys.argv[1], "latest": sys.argv[2],
        "behind": int(sys.argv[3]), "notes": [l.rstrip() for l in sys.stdin if l.strip()]}))' "$CUR" "$LATEST" "$BEHIND"
    exit 0
fi

echo "› HBlink4-FreeRadioID $CUR → $LATEST ($BEHIND neue Commits auf $BRANCH)"
SVC_USER="$(systemctl show -p User --value hblink4.service 2>/dev/null || true)"; SVC_USER="${SVC_USER:-$(stat -c %U "$ROOT")}"
SVC_GROUP="$(id -gn "$SVC_USER" 2>/dev/null || echo "$SVC_USER")"
if [[ "$BEHIND" -gt 0 ]]; then
    DIRTY="$(git_ status --porcelain --untracked-files=no)"
    [[ -z "$DIRTY" ]] || die "Von Hand geänderte Dateien: $(echo "$DIRTY" | head -n 5 | awk '{print $2}' | xargs) – erst zurücksetzen (git stash)"
    git_ merge-base --is-ancestor HEAD "$NEW_SHA" || die "Diese Installation hat eigene Commits – bitte von Hand aktualisieren"
    CHANGED="$(git_ diff --name-only HEAD "$NEW_SHA")"
    git_ merge --ff-only --quiet "$NEW_SHA"
    ok "auf $(git_ rev-parse --short HEAD) vorgespult"
    if grep -qE '^(requirements(-dashboard)?\.txt|pyproject\.toml)$' <<<"$CHANGED"; then
        "$ROOT/venv/bin/pip" install -q -r "$ROOT/requirements.txt" -r "$ROOT/requirements-dashboard.txt" && ok "Python-Pakete aktualisiert"
    fi
    # N8 update guard: kommt das Dashboard nach drei Starts nicht hoch, geht es auf den alten Stand zurück
    "$ROOT/venv/bin/python" -c 'import sys; sys.path.insert(0, sys.argv[1]); from dashboard import n8_update_guard as g; g.mark_pending(sys.argv[2], *sys.argv[3:7])' \
        "$ROOT" "$ROOT/dashboard/data" "$OLD_SHA" "$NEW_SHA" "$CUR" "$LATEST" 2>/dev/null || warn "update guard nicht gesetzt"
else
    ok "schon aktuell ($CUR)"
fi

# Rechte prüfen und korrigieren: alles gehört dem Dienst-Benutzer, Skripte ausführbar, Daten und Konfiguration nicht für alle lesbar
chown -R "$SVC_USER:$SVC_GROUP" "$ROOT"
chmod 755 "$ROOT"/scripts/*.sh 2>/dev/null || true
chmod 750 "$ROOT/dashboard/data" "$ROOT/config" 2>/dev/null || true
find "$ROOT/dashboard/data" -maxdepth 1 -type f -name '*.db*' -exec chmod 600 {} + 2>/dev/null || true
ok "Besitzer $SVC_USER:$SVC_GROUP und Rechte geprüft"

if [[ "$BEHIND" -gt 0 || "${1:-}" == "--restart" ]]; then
    systemctl restart hblink4.service hblink4-dash.service
    for i in $(seq 1 30); do curl -fsS -m 2 http://127.0.0.1:8080/api/version -o /dev/null 2>/dev/null && break; sleep 2; done
    curl -fsS -m 3 http://127.0.0.1:8080/api/version -o /dev/null && ok "Dienste neu gestartet, Dashboard antwortet" \
        || warn "Dashboard antwortet (noch) nicht – journalctl -u hblink4-dash"
fi
echo "✓ HBlink4-FreeRadioID $(tr -d '[:space:]' < "$ROOT/VERSION")"
