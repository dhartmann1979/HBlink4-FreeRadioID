#!/bin/bash
# =============================================================================
#  DMR Die N8schicht – geführte Installation
#  HBlink4 DMR-Server + FreeRadioID Secure Login + Dashboard
#
#      sudo ./scripts/setup.sh
#
#  Fragt alle wichtigen Einstellungen ab (Vorgabe in [Klammern], Enter
#  übernimmt sie), schreibt die Config-Dateien und die Einstellungs-Datenbank,
#  richtet die Dienste ein und prüft am Ende alles. Auf einer bestehenden
#  Installation werden die aktuellen Werte als Vorgabe angeboten -- das Skript
#  kann also jederzeit erneut laufen.
#
#  Umgebungsvariablen: SKIP_APT=1 (keine Pakete installieren),
#  SKIP_SERVICES=1 (keine systemd-Dienste), SKIP_FIREWALL=1.
#
#  Ohne Rückfragen neu einrichten (z. B. Web-Installer des HobbyRadioPortals):
#    HB4_ANSWERS=/pfad/answers.json   Antworten als JSON (600), fehlende Werte = Vorgaben. Schlüssel:
#      svc_user, server_name, dmr_port, ts1, ts2, frid, passphrase, guest_tgs, dashboard_title, server_description,
#      web_port, public, admin_user, admin_password (min. 8), https, domain, email,
#      aprs, aprs_id, aprs_domains, aprs_ports, aprs_uplink (0–3), aprs_cb_login
# =============================================================================
set -u

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT" || exit 1

B='\033[1m'; D='\033[2m'; R='\033[0;31m'; G='\033[0;32m'; Y='\033[0;33m'; C='\033[0;36m'; M='\033[0;35m'; N='\033[0m'
STEP=0; STEPS=10

banner() {
    echo
    echo -e "${M}   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${N}"
    echo -e "    🌙  ${B}DMR Die N8schicht${N} – Einrichtung"
    echo -e "        ${D}HBlink4 · FreeRadioID Secure Login · Dashboard${N}"
    echo -e "${M}   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${N}"
    echo
}
step()  { STEP=$((STEP + 1)); echo; echo -e "${C}━━ ${B}Schritt ${STEP}/${STEPS}: $*${N}"; }
info()  { echo -e "   ${D}$*${N}"; }
ok()    { echo -e "   ${G}✓${N} $*"; }
warn()  { echo -e "   ${Y}!${N} $*"; }
fail()  { echo -e "   ${R}✗ $*${N}"; exit 1; }

UNATTENDED=0; [ -n "${HB4_ANSWERS:-}" ] && UNATTENDED=1
ask() {        # ask VAR "Frage" "Vorgabe"
    local __v="$1" __q="$2" __d="${3-}" __a=""
    if [ "$UNATTENDED" = 1 ]; then printf -v "$__v" '%s' "$__d"; return; fi
    read -r -p "$(echo -e "   ${B}?${N} $__q ${D}[$__d]${N}: ")" __a
    printf -v "$__v" '%s' "${__a:-$__d}"
}
ask_yn() {     # ask_yn VAR "Frage" j|n
    local __v="$1" __q="$2" __d="$3" __a="" __hint
    if [ "$UNATTENDED" = 1 ]; then [ "$__d" = j ] && printf -v "$__v" true || printf -v "$__v" false; return; fi
    [ "$__d" = j ] && __hint="J/n" || __hint="j/N"
    while true; do
        read -r -p "$(echo -e "   ${B}?${N} $__q ${D}[$__hint]${N}: ")" __a
        __a="${__a:-$__d}"
        case "$__a" in [jJyY]*) printf -v "$__v" true; return ;; [nN]*) printf -v "$__v" false; return ;; esac
    done
}
ask_secret() { # ask_secret VAR "Frage" erlaube_leer(0/1)
    local __v="$1" __q="$2" __empty="$3" __a="" __b=""
    while true; do
        read -r -s -p "$(echo -e "   ${B}?${N} $__q: ")" __a; echo
        if [ -z "$__a" ] && [ "$__empty" = 1 ]; then printf -v "$__v" ''; return; fi
        if [ ${#__a} -lt 8 ]; then warn "mindestens 8 Zeichen"; continue; fi
        read -r -s -p "$(echo -e "   ${B}?${N} Wiederholen: ")" __b; echo
        [ "$__a" = "$__b" ] && { printf -v "$__v" '%s' "$__a"; return; }
        warn "Die Eingaben stimmen nicht überein."
    done
}
jget() { python3 -c "import json,sys; v=json.load(sys.stdin)[sys.argv[1]]; print(str(v).lower() if isinstance(v,bool) else v)" "$1"; }

banner
[ "$(id -u)" -eq 0 ] || fail "Bitte mit sudo starten: sudo ./scripts/setup.sh"
info "Installationsverzeichnis: $REPO_ROOT"

echo -e "   ${B}Einrichtungsart${N}"
info "Neu einrichten: Einstellungen Schritt für Schritt eingeben."
info "Backup wiederherstellen: Programm, Einstellungen und Benutzer aus einer Sicherung übernehmen."
if [ "$UNATTENDED" = 1 ]; then
    [ -f "$HB4_ANSWERS" ] || fail "HB4_ANSWERS nicht gefunden: $HB4_ANSWERS"
    info "Ohne Rückfragen mit den Antworten aus $(basename "$HB4_ANSWERS")"
fi
ask_yn RESTORE_SETUP "Vorhandenes HBlink4-Backup wiederherstellen?" n
BACKUP_FILE=""
if [ "$RESTORE_SETUP" = true ]; then
    [ "${SKIP_SERVICES:-0}" != 1 ] || fail "Wiederherstellen benötigt systemd-Dienste; SKIP_SERVICES=1 ist dafür nicht möglich."
    ask BACKUP_FILE "Pfad zur Backup-Datei (.tar.gz)" ""
    [ -n "$BACKUP_FILE" ] && [ -f "$BACKUP_FILE" ] || fail "Backup-Datei nicht gefunden: $BACKUP_FILE"
    STEPS=2
fi

# ---------------------------------------------------------------------- 1
step "Systempakete"
if [ "${SKIP_APT:-0}" = 1 ]; then
    info "übersprungen (SKIP_APT=1)"
elif command -v apt-get >/dev/null 2>&1; then
    apt-get update -qq >/dev/null 2>&1
    if DEBIAN_FRONTEND=noninteractive apt-get install -y -qq python3 python3-venv python3-pip git iproute2 age >/dev/null 2>&1; then
        ok "python3, venv, pip, git, iproute2, age"
    else
        fail "apt-get konnte die Pakete nicht installieren"
    fi
else
    warn "kein apt-get gefunden: bitte python3, python3-venv, pip und git selbst installieren"
fi

if [ "$RESTORE_SETUP" = true ]; then
    step "Backup prüfen und wiederherstellen"
    exec python3 "$REPO_ROOT/scripts/setup_restore.py" "$REPO_ROOT" "$BACKUP_FILE"
fi

# ---------------------------------------------------------------------- 2
step "Dienst-Benutzer"
info "HBlink4 und das Dashboard laufen als normaler Benutzer, nicht als root."
DEF_USER="$(stat -c %U "$REPO_ROOT")"; [ "$DEF_USER" = root ] && DEF_USER="hblink"
[ "$UNATTENDED" = 1 ] && DEF_USER="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("svc_user") or sys.argv[2])' "$HB4_ANSWERS" "$DEF_USER")"
ask SVC_USER "Benutzer für die Dienste" "$DEF_USER"
if ! id "$SVC_USER" >/dev/null 2>&1; then
    useradd --system --create-home --shell /usr/sbin/nologin "$SVC_USER" && ok "Benutzer $SVC_USER angelegt"
else
    ok "Benutzer $SVC_USER vorhanden"
fi
SVC_GROUP="$(id -gn "$SVC_USER")"

# ---------------------------------------------------------------------- 3
step "Python-Umgebung"
[ -x venv/bin/python ] || python3 -m venv venv || fail "venv konnte nicht angelegt werden"
info "Pakete werden installiert (kann eine Minute dauern) …"
if venv/bin/pip install -q -r requirements.txt -r requirements-dashboard.txt >/tmp/n8-setup-pip.log 2>&1; then
    ok "$(venv/bin/python --version) mit allen Modulen"
else
    fail "pip ist fehlgeschlagen, siehe /tmp/n8-setup-pip.log"
fi
CUR="$(venv/bin/python scripts/setup_apply.py current "$REPO_ROOT" 2>/dev/null)" || fail "aktuelle Werte nicht lesbar"
cur() { echo "$CUR" | jget "$1"; }

if [ "$UNATTENDED" = 1 ]; then
# ---------------------------------------------------------------------- 4–9 aus HB4_ANSWERS
step "DMR-Server"; step "Zugang für Repeater & Hotspots"; step "Dashboard & Superadmin"; step "HTTPS"; step "APRS"; step "Zusammenfassung"
eval "$(CUR_JSON="$CUR" python3 - "$HB4_ANSWERS" <<'PY'
import json, os, shlex, sys
cur = json.loads(os.environ["CUR_JSON"] or "{}")
a = json.load(open(sys.argv[1]))
m = {"SERVER_NAME": "server_name", "DMR_PORT": "dmr_port", "TS1": "ts1", "TS2": "ts2", "FRID": "frid", "PASSPHRASE": "passphrase",
     "GUEST_TGS": "guest_tgs", "TITLE": "dashboard_title", "DESCRIPTION": "server_description", "WEB_PORT": "web_port", "PUBLIC": "public",
     "ADMIN_USER": "admin_user", "HTTPS": "https", "DOMAIN": "domain", "EMAIL": "email", "APRS": "aprs", "APRS_ID": "aprs_id",
     "APRS_DOMAINS": "aprs_domains", "APRS_PORTS": "aprs_ports", "APRS_UPLINK": "aprs_uplink", "APRS_CB_LOGIN": "aprs_cb_login"}
for var, key in m.items():
    v = a.get(key, cur.get(key, ""))
    if isinstance(v, bool):
        v = "true" if v else "false"
    elif isinstance(v, list):
        v = ", ".join(str(x) for x in v)
    elif v is None:
        v = ""
    print(f"{var}={shlex.quote(str(v))}")
pw = str(a.get("admin_password") or "")
print(f"ADMIN_PW={shlex.quote(pw)}")
PY
)" || fail "HB4_ANSWERS ist kein gültiges JSON"
[ "$APRS" = true ] || APRS_PORTS=false
[ -n "$APRS_ID" ] || APRS_UPLINK=0
[ -n "$DOMAIN" ] || DOMAIN="$SERVER_NAME"
if [ -n "$ADMIN_PW" ]; then
    [ ${#ADMIN_PW} -ge 8 ] || fail "admin_password: mindestens 8 Zeichen"
elif [ "$(cur admin_has_password)" != true ]; then
    fail "admin_password fehlt (Superadmin ohne Passwort)"
fi
ADMIN_HASH=""
[ -n "$ADMIN_PW" ] && ADMIN_HASH="$(printf '%s' "$ADMIN_PW" | venv/bin/python scripts/setup_apply.py hash)"
unset ADMIN_PW
if [ "$HTTPS" = true ] && [ "${SKIP_APT:-0}" != 1 ] && ! command -v certbot >/dev/null 2>&1; then
    DEBIAN_FRONTEND=noninteractive apt-get install -y -qq certbot >/dev/null 2>&1 || warn "certbot konnte nicht installiert werden"
fi
ok "Server $SERVER_NAME · DMR UDP $DMR_PORT · Superadmin $ADMIN_USER · HTTPS $HTTPS · APRS $APRS"
GO=true
else
# ---------------------------------------------------------------------- 4
step "DMR-Server"
info "Repeater und Hotspots verbinden sich per HomeBrew-Protokoll (UDP)."
ask SERVER_NAME "Name/Adresse des Servers" "$(cur server_name)"
ask DMR_PORT "DMR-Port (UDP)" "$(cur dmr_port)"
ask TS1 "Talkgroups Zeitschlitz 1 (Komma, all, none)" "$(cur ts1)"
ask TS2 "Talkgroups Zeitschlitz 2" "$(cur ts2)"

# ---------------------------------------------------------------------- 5
step "Zugang für Repeater & Hotspots"
info "Mit FreeRadioID-Login melden sich Stationen mit ihrem persönlichen"
info "FreeRadioID.net-Passwort an. Das Standard-Passwort ist dann der Gastzugang."
DEF_FRID=n; [ "$(cur frid)" = true ] && DEF_FRID=j
ask_yn FRID "FreeRadioID Secure Login einschalten?" "$DEF_FRID"
if [ "$FRID" = true ]; then
    ask PASSPHRASE "Gast-Passwort (Standard-Passwort)" "$(cur passphrase)"
    ask GUEST_TGS "Gäste dürfen senden auf (Komma, all, none)" "$(cur guest_tgs)"
else
    ask PASSPHRASE "Passwort für Repeater und Hotspots" "$(cur passphrase)"
    GUEST_TGS="$(cur guest_tgs)"
fi

# ---------------------------------------------------------------------- 6
step "Dashboard & Superadmin"
ask TITLE "Titel des Dashboards" "$(cur dashboard_title)"
ask DESCRIPTION "Beschreibung" "$(cur server_description)"
ask WEB_PORT "Web-Port (HTTP)" "$(cur web_port)"
DEF_PUB=n; [ "$(cur public)" = true ] && DEF_PUB=j
ask_yn PUBLIC "Dashboard öffentlich (ohne Login sichtbar)?" "$DEF_PUB"
info "Der Superadmin meldet sich im Dashboard an und verwaltet dort alles."
ask ADMIN_USER "Superadmin-Benutzername" "$(cur admin_user)"
if [ "$(cur admin_has_password)" = true ]; then
    ask_secret ADMIN_PW "Superadmin-Passwort (leer = unverändert)" 1
else
    ask_secret ADMIN_PW "Superadmin-Passwort (min. 8 Zeichen)" 0
fi
ADMIN_HASH=""
[ -n "$ADMIN_PW" ] && ADMIN_HASH="$(printf '%s' "$ADMIN_PW" | venv/bin/python scripts/setup_apply.py hash)"

# ---------------------------------------------------------------------- 7
step "HTTPS mit Let's Encrypt"
info "Voraussetzung: der Name zeigt auf diesen Server, Ports 80 und 443 sind erreichbar."
DEF_HTTPS=n; [ "$(cur https)" = true ] && DEF_HTTPS=j
ask_yn HTTPS "HTTPS einrichten?" "$DEF_HTTPS"
DOMAIN="$(cur domain)"; [ -z "$DOMAIN" ] && DOMAIN="$SERVER_NAME"
EMAIL="$(cur email)"
if [ "$HTTPS" = true ]; then
    ask DOMAIN "Domain" "$DOMAIN"
    ask EMAIL "E-Mail für Let's Encrypt" "${EMAIL:-sysop@$DOMAIN}"
    if [ "${SKIP_APT:-0}" != 1 ] && ! command -v certbot >/dev/null 2>&1; then
        DEBIAN_FRONTEND=noninteractive apt-get install -y -qq certbot >/dev/null 2>&1 && ok "certbot installiert" || warn "certbot konnte nicht installiert werden"
    fi
fi

# ---------------------------------------------------------------------- 8
step "APRS: Karte, DAPRS und APRS-Server"
info "Positionen von DMR-Funkgeräten (DAPRS) als APRS, eine Karte im N8-Design, optional ein eigener"
info "APRS-Server (Python) mit Uplink & Downlink zu APRS-IS, CB-APRS oder eigenen Servern. Vorgabe: aus."
DEF_APRS=n; [ "$(cur aprs)" = true ] && DEF_APRS=j
ask_yn APRS "APRS einschalten?" "$DEF_APRS"
APRS_ID="$(cur aprs_id)"; APRS_DOMAINS="$(cur aprs_domains)"; APRS_PORTS=false; APRS_UPLINK="$(cur aprs_uplink)"; APRS_CB_LOGIN="$(cur aprs_cb_login)"
if [ "$APRS" = true ]; then
    ask APRS_ID "Server-ID (dein Rufzeichen mit SSID, z. B. DB0ABC-10; leer = nur Karte)" "$APRS_ID"
    ask APRS_DOMAINS "Domains für die Karte (bis zu 3, mit Komma; leer = nur $SERVER_NAME/aprs)" "$APRS_DOMAINS"
    [ -n "$APRS_DOMAINS" ] && info "Die Domains müssen per DNS auf diesen Server zeigen; mit HTTPS kommen sie ins Let's-Encrypt-Zertifikat."
    if [ -n "$APRS_ID" ]; then
        DEF_P=n; [ "$(cur aprs_ports)" = true ] && DEF_P=j
        ask_yn APRS_PORTS "APRS-Ports für Apps und iGates öffnen (TCP 14580 Filter, 10152 Full Feed)?" "$DEF_P"
        info "Uplink & Downlink: 0 = keiner, 1 = APRS-IS (Amateurfunk), 2 = CB-APRS (eu.cbaprs.net), 3 = manuell (im Adminbereich)"
        while true; do
            ask APRS_UPLINK "Netz" "${APRS_UPLINK:-0}"
            case "$APRS_UPLINK" in 0|1|2|3) break ;; *) warn "0, 1, 2 oder 3" ;; esac
        done
        [ "$APRS_UPLINK" = 2 ] && ask APRS_CB_LOGIN "Login bei CB-APRS (leer = Server-ID)" "$APRS_CB_LOGIN"
    else
        APRS_UPLINK=0
    fi
fi

# ---------------------------------------------------------------------- 9
step "Zusammenfassung"
FR_TXT="aus"; [ "$FRID" = true ] && FR_TXT="an, Gäste senden auf: $GUEST_TGS"
HT_TXT="aus (http://$SERVER_NAME:$WEB_PORT)"; [ "$HTTPS" = true ] && HT_TXT="an (https://$DOMAIN)"
PUB_TXT="nein, nur mit Login"; [ "$PUBLIC" = true ] && PUB_TXT="ja"
row() { echo -e "   ${D}$1${N}  $2"; }
row "Server             " "$SERVER_NAME"
row "DMR-Port           " "UDP $DMR_PORT"
row "Talkgroups TS1/TS2 " "$TS1 / $TS2"
row "FreeRadioID-Login  " "$FR_TXT"
row "Dashboard          " "$TITLE – $DESCRIPTION"
row "Öffentlich         " "$PUB_TXT"
row "Superadmin         " "$ADMIN_USER"
row "HTTPS              " "$HT_TXT"
AP_TXT="aus"
if [ "$APRS" = true ]; then
    AP_TXT="an, Karte: ${APRS_DOMAINS:-$SERVER_NAME/aprs}"
    [ -n "$APRS_ID" ] && AP_TXT="$AP_TXT · ID $APRS_ID"
    [ "$APRS_PORTS" = true ] && AP_TXT="$AP_TXT · Ports 14580/10152"
    case "$APRS_UPLINK" in 1) AP_TXT="$AP_TXT · APRS-IS" ;; 2) AP_TXT="$AP_TXT · CB-APRS" ;; 3) AP_TXT="$AP_TXT · manuell" ;; esac
fi
row "APRS               " "$AP_TXT"
row "Dienst-Benutzer    " "$SVC_USER"
ask_yn GO "So einrichten?" j
[ "$GO" = true ] || { warn "Abgebrochen, nichts geändert."; exit 0; }
fi   # Fragen oder HB4_ANSWERS

STAMP="$(date +%Y%m%d-%H%M%S)"
for f in config/config.json dashboard/config.json; do
    [ -f "$f" ] && cp -p "$f" "$f.$STAMP.bak" && info "Sicherung: $f.$STAMP.bak"
done
ANSWERS="$(mktemp)"
N8_SERVER_NAME="$SERVER_NAME" N8_DMR_PORT="$DMR_PORT" N8_TS1="$TS1" N8_TS2="$TS2" N8_FRID="$FRID" \
N8_PASSPHRASE="$PASSPHRASE" N8_GUEST_TGS="$GUEST_TGS" N8_TITLE="$TITLE" N8_DESCRIPTION="$DESCRIPTION" \
N8_WEB_PORT="$WEB_PORT" N8_PUBLIC="$PUBLIC" N8_ADMIN_USER="$ADMIN_USER" N8_ADMIN_HASH="$ADMIN_HASH" \
N8_HTTPS="$HTTPS" N8_DOMAIN="$DOMAIN" N8_EMAIL="$EMAIL" N8_APRS="$APRS" N8_APRS_ID="$APRS_ID" \
N8_APRS_DOMAINS="$APRS_DOMAINS" N8_APRS_PORTS="$APRS_PORTS" N8_APRS_UPLINK="$APRS_UPLINK" N8_APRS_CB_LOGIN="$APRS_CB_LOGIN" \
python3 - "$ANSWERS" <<'PY'
import json, os, sys
e = lambda k: os.environ.get("N8_" + k, "")
json.dump({
    "server_name": e("SERVER_NAME"), "dmr_port": e("DMR_PORT"), "ts1": e("TS1"), "ts2": e("TS2"),
    "frid": e("FRID") == "true", "passphrase": e("PASSPHRASE"), "guest_tgs": e("GUEST_TGS"),
    "dashboard_title": e("TITLE"), "server_description": e("DESCRIPTION"), "web_port": e("WEB_PORT"),
    "public": e("PUBLIC") == "true", "admin_user": e("ADMIN_USER"), "admin_hash": e("ADMIN_HASH"),
    "https": e("HTTPS") == "true", "domain": e("DOMAIN"), "email": e("EMAIL"),
    "aprs": e("APRS") == "true", "aprs_id": e("APRS_ID"), "aprs_domains": e("APRS_DOMAINS"),
    "aprs_ports": e("APRS_PORTS") == "true", "aprs_uplink": e("APRS_UPLINK") or "0", "aprs_cb_login": e("APRS_CB_LOGIN"),
}, open(sys.argv[1], "w"))
PY
if venv/bin/python scripts/setup_apply.py write "$REPO_ROOT" "$ANSWERS"; then
    ok "config/config.json, dashboard/config.json und Einstellungs-Datenbank geschrieben"
else
    rm -f "$ANSWERS"; fail "Einstellungen ungültig (siehe oben)"
fi
rm -f "$ANSWERS"

# ---------------------------------------------------------------------- 10
step "Firewall, Dienste & Prüfung"
if [ "${SKIP_FIREWALL:-0}" != 1 ] && command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | grep -q "Status: active"; then
    ufw allow "$DMR_PORT/udp" >/dev/null && ok "ufw: UDP $DMR_PORT offen"
    if [ "$HTTPS" = true ]; then ufw allow 80/tcp >/dev/null; ufw allow 443/tcp >/dev/null; ok "ufw: TCP 80 und 443 offen"
    else ufw allow "$WEB_PORT/tcp" >/dev/null && ok "ufw: TCP $WEB_PORT offen"; fi
    if [ "$APRS_PORTS" = true ]; then ufw allow 14580/tcp >/dev/null; ufw allow 10152/tcp >/dev/null; ok "ufw: TCP 14580 und 10152 offen (APRS)"; fi
else
    info "keine aktive ufw-Firewall gefunden – Ports ggf. selbst freigeben: UDP $DMR_PORT, TCP $([ "$HTTPS" = true ] && echo "80 und 443" || echo "$WEB_PORT")"
fi
[ "$APRS_PORTS" = true ] && info "APRS-Server: TCP 14580 und 10152 müssen von außen erreichbar sein"
rm -f /tmp/hblink4.sock 2>/dev/null
chown -R "$SVC_USER:$SVC_GROUP" "$REPO_ROOT" && ok "Dateien gehören $SVC_USER"
if [ "${SKIP_SERVICES:-0}" = 1 ] || ! command -v systemctl >/dev/null 2>&1; then
    info "Dienste übersprungen. Manuell starten: sudo -u $SVC_USER ./run_all.sh"
else
    ASSUME_YES=1 SVC_USER="$SVC_USER" SVC_GROUP="$SVC_GROUP" ./scripts/install_services.sh >/tmp/n8-setup-services.log 2>&1 \
        && ok "Dienste hblink4 und hblink4-dash eingerichtet und gestartet" \
        || { warn "Dienst-Installation meldet Probleme, siehe /tmp/n8-setup-services.log"; }
    info "Warte, bis alles läuft …"; sleep 8
    ./scripts/check.sh | sed 's/^/ /'
fi

URL="http://$SERVER_NAME:$WEB_PORT"; [ "$HTTPS" = true ] && URL="https://$DOMAIN"
echo
echo -e "${G}   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${N}"
echo -e "    ✅  ${B}Fertig!${N}"
echo -e "${G}   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${N}"
echo -e "   Dashboard:    ${B}$URL${N}"
echo -e "   Anmelden:     🔐 Login oben rechts als ${B}$ADMIN_USER${N}"
echo -e "   Repeater:     $SERVER_NAME, Port $DMR_PORT, Passwort wie eingegeben"
[ "$FRID" = true ] && echo -e "   FreeRadioID:  eigenes FreeRadioID-Passwort = volle Rechte, Standard-Passwort = Gast"
[ "$APRS" = true ] && echo -e "   APRS-Karte:   ${B}$URL/aprs${N}${APRS_DOMAINS:+ und $APRS_DOMAINS} (alles Weitere: ⚙️ Admin area → 📡 APRS)"
echo -e "   Alles weitere stellst du im Dashboard ein: ⚙️ Admin area → Settings."
echo
