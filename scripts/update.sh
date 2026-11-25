#!/usr/bin/env bash
# =============================================================================
#  HBlink4-FreeRadioID – Update von der Konsole
#
#      sudo ./scripts/update.sh            holt die neueste Version, behält alle Einstellungen und Daten
#
#  Genau dasselbe wie „Update jetzt installieren“ im Adminbereich (scripts/n8-admin.sh update): nur vorspulen (fast-forward)
#  auf den Branch von „origin“, nie über von Hand geänderte Dateien; Python-Pakete nur bei geänderten requirements*.
#  Danach Berechtigungen und sudo prüfen/korrigieren, beide Dienste neu starten, Dashboard prüfen – antwortet es nicht,
#  zurück auf den alten Stand.
# =============================================================================
set -euo pipefail
HERE="$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")"
[[ $EUID -eq 0 ]] || { echo "Bitte als root starten: sudo $0"; exit 1; }
chmod 755 "$HERE/n8-admin.sh"
exec "$HERE/n8-admin.sh" update "$@"
