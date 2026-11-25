# Änderungen

Alle Versionen von **HBlink4-FreeRadioID** (DMR Die N8schicht), die neueste oben.
Die Nummern folgen [Semantic Versioning](https://semver.org/lang/de/): `MAJOR.MINOR.PATCH`.
Wie Versionen entstehen, steht in [docs/de/versionen.md](docs/de/versionen.md).

## [1.12.0] – 2026-11-25

**🧩 Gleiches Update-System wie N8 Crosslink – mit Berechtigungsprüfer, sudo-Einrichtung und schlanker Dienste-Übersicht. HobbyRadioPortal-Anbindung und Umzug ins Portal entfernt.**

### ⬆️ Update über den Root-Helfer `scripts/n8-admin.sh`
- Gemeinsamer Helfer der N8schicht-Projekte (dieselbe Datei wie in N8 Crosslink und ADN-FRN-Server; Projektdaten in
  `scripts/n8-admin.conf`).
- **Update now** (weiter mit Passwortabfrage und Rechte-Einstellung *Who may press “Update now”*) legt nur `dashboard/data/update.request`
  an; die Path-Unit `hblink4-update.path` startet `hblink4-update.service` als root → `n8-admin.sh update --auto`: nur vorspulen, Pakete bei
  geänderten `requirements*`, **Berechtigungen und sudo prüfen/korrigieren**, beide Dienste neu starten, Dashboard prüfen – antwortet es
  90 s nicht, **zurück auf den alten Stand**. Ergebnis unter *Letztes Update*, Protokoll unter *🖥️ System → 📜 Update-Protokoll*.
- `scripts/update.sh` macht von der Konsole dasselbe (`--check` entfällt). Der alte *N8 update guard* (`n8-update-guard.sh`, `ExecStartPre`,
  `n8_update_guard.py`) entfällt; das Update entfernt die Zeile aus der installierten Unit und die alte Regel `/etc/sudoers.d/hblink4-update`.
- **Das Programmverzeichnis gehört jetzt root**; nur `dashboard/data`, `config/`, `logs/` und `dashboard/config.json` gehören dem
  Dienst-Benutzer. `config.json` und Datenbanken 600.

### 🔐 Berechtigungen & sudo · 🧩 Dienste (Adminbereich → 🖥️ System)
- Prüfliste mit Abzeichen und **🛠️ Korrigieren**: Dienst-Benutzer, Programm root-eigen, Daten und Konfiguration, systemd-Units,
  Update-Auslöser, `hblink4-dash` darf sudo (kein `NoNewPrivileges`, keine enge `CapabilityBoundingSet` – sonst Drop-in
  `n8-admin.conf`), sudo installiert/eingebunden/gültig/aktuell/wirksam. Konsole: `sudo scripts/n8-admin.sh check-perms` / `fix-perms`.
- Dienste `hblink4`, `hblink4-dash` und der Update-Auslöser schlank mit Status, **Autostart**-Schalter und **▶ / 🔄 / ⏹**.
- sudo-Freigaben in `/etc/sudoers.d/hblink4-n8admin`, nur exakte Befehle. Die mitgelieferte `hblink4-dash.service` läuft deshalb mit
  `NoNewPrivileges=no` und ohne `CapabilityBoundingSet` (nur `AmbientCapabilities=CAP_NET_BIND_SERVICE` bleibt).
- API: `GET /api/admin/services`, `POST /api/admin/services/{unit}/{action}`, `GET /api/admin/perms`, `POST /api/admin/perms/fix`,
  `GET /api/admin/update-log`; alles im Audit-Log. `install_services.sh` ruft am Ende `n8-admin.sh fix-perms` auf.

### 🧹 HobbyRadioPortal entfernt
- Keine lokale Portal-Schnittstelle mehr (`X-HobbyRadioPortal`, `HB4_PORTAL_LOCAL`, Pseudo-Benutzer „portal“, gesperrte
  Portal-Einstellungen); alle Admin-Adressen brauchen eine Anmeldung.
- **📦 Umzug ins HobbyRadioPortal** entfernt: Umzugscodes, `/api/admin/migration…`, `/api/migration/export`, `dashboard/migration.py`
  (auch `portalize`). Backup, Wiederherstellung, Klonen und AutoBackup bleiben unverändert.
- Doku bereinigt (Betrieb, Adminbereich, APRS, Backup, Installation, Sicherheit, README).

### ⚠️ Einmalig nach dem Update
- Von 1.11 oder älter: einmal `sudo /opt/HBlink4/scripts/n8-admin.sh fix-perms` (bzw. Pfad deiner Installation) – richtet Besitzer, sudo,
  „Update now“ und die Drop-in-Datei für `hblink4-dash` ein; danach `sudo systemctl restart hblink4-dash`.

## [1.11.0] – 2026-11-25

**🔌 HobbyRadioPortal ohne Token.** Läuft das Portal auf demselben Rechner, verwaltet es APRS und DAPRS direkt – kein Token anlegen,
kopieren und im Portal eintragen mehr. Ausführlich: [docs/de/sicherheit.md](docs/de/sicherheit.md#hobbyradioportal-auf-diesem-server-ohne-token).

### Was sich ändert
- **API-Tokens sind weg:** der Bereich *🔌 Portal-Zugang (API-Token)* unter Sessions, `GET/POST /api/admin/api-tokens`,
  `DELETE /api/admin/api-tokens/{id}` und `python -m dashboard.auth api-token …`; die Tabelle `api_tokens` in `dashboard.db` wird beim Start
  gelöscht. Unter Sessions steht stattdessen ein kurzer Hinweis, was das Portal darf.
- **Als Portal gilt nur ein direkter Aufruf auf diesem Rechner:** Absender und `Host` Loopback (`127.0.0.1`, `::1`, `localhost`),
  Kopfzeile `X-HobbyRadioPortal: 1`, **keine** Proxy-Kopfzeile (`X-Forwarded-For`, `X-Real-IP`, `Forwarded`, `X-Forwarded-Host/-Proto`,
  `Via`, `CF-Connecting-IP`, `True-Client-IP`, `X-Client-IP`). Anfragen über nginx/Caddy (die auch von 127.0.0.1 kommen) und von anderen
  Rechnern sind damit nie „das Portal“. Die Proxy-Vorlagen in der Doku setzen `X-Forwarded-For` (Caddy macht es von selbst).
- **Was das Portal darf, bleibt gleich:** öffentliche Daten, `/api/admin/settings` (ohne *Dashboard access*, *HTTPS & web*, *Updates*),
  `/api/admin/aprs…`, `/api/admin/audit` – nie Benutzer, Sitzungen, Backups, Passwörter, Updates oder Neustarts. `X-Dashboard: 1`
  (CSRF) bleibt Pflicht. Im Protokoll steht `portal (<Portal-Benutzer>)` statt `api:<Token-Name> (…)`.
- **Abschalten:** `HB4_PORTAL_LOCAL=0` in der Umgebung des Dashboard-Dienstes (das Portal zeigt dann nur Live-Daten).

### Doku und Tests
- [Sicherheit](docs/de/sicherheit.md), [Adminbereich](docs/de/adminbereich.md), [Betrieb](docs/de/betrieb.md), [APRS](docs/de/aprs.md)
  umgestellt; Screenshot *Sitzungen* neu.
- `tests/test_portal_local.py` statt `test_api_tokens.py`: erlaubte und gesperrte Pfade, gesperrte Einstellungen, Proxy-Kopfzeilen und
  öffentlicher Host abgelehnt, ohne Kennung oder von einem anderen Rechner kein Zugriff, CSRF bleibt, Protokoll, Abschalten.

## [1.10.0] – 2026-11-25

**`scripts/update.sh` – Update mit einem Befehl, für die Konsole und das HobbyRadioPortal.** Das
[HobbyRadioPortal](https://github.com/dhartmann1979/HobbyRadioPortal) (ab 0.13.0) hat eine Seite *🧩 Dienste*, die alle Dienste auf
dem Server auf Updates prüft und aktualisiert – einzeln oder alle auf einmal. Für HBlink4 nutzt es dieses Skript.
Ausführlich: [docs/de/betrieb.md](docs/de/betrieb.md#aktualisieren).

### ⌨️ `sudo scripts/update.sh [--check]`
- `--check` gibt nur JSON aus: installierte und neueste Version, Zahl der neuen Commits und ihre Titel.
- Ohne Option: holt den Branch von `origin` und spult **nur vor** (fast-forward) – wie *Update now* im Dashboard: nie über von Hand
  geänderte Dateien (Abbruch mit Dateiliste) und nie über eigene Commits.
- Python-Pakete werden nur nachinstalliert, wenn sich `requirements.txt`, `requirements-dashboard.txt` oder `pyproject.toml` geändert haben.
- **Rechte prüfen und korrigieren:** alles gehört dem Dienst-Benutzer (aus `hblink4.service`, sonst Besitzer des Verzeichnisses),
  Skripte ausführbar, `config/` und `dashboard/data/` 750, Datenbanken 600.
- Startet `hblink4` und `hblink4-dash` neu, wartet, bis das Dashboard antwortet, und schaltet den **N8 update guard** scharf
  (`dashboard/data/update.pending`): kommt das Dashboard nach drei Starts nicht hoch, geht es automatisch auf den alten Stand zurück.
- Ohne neue Commits ändert es nichts außer den Rechten (`--restart` startet trotzdem neu).

### 🧪 Geprüft
- Auf einem echten älteren Klon: `--check` (JSON mit Versionen und Commit-Titeln), Update vorgespult, update guard gesetzt,
  Rechte korrigiert, Neustart angestoßen; ein unbrauchbarer Dienst-Benutzer aus systemd fällt auf den Besitzer des Verzeichnisses zurück.

## [1.9.0] – 2026-11-25

**`setup.sh` ohne Rückfragen: `HB4_ANSWERS=/pfad/answers.json`.** Damit kann der Web-Installer des
[HobbyRadioPortals](https://github.com/dhartmann1979/HobbyRadioPortal) (ab 0.11.0) HBlink4 nicht nur umziehen oder aus einem Backup
holen, sondern auch **frisch installieren** (*DMR & APRS → ✨ HBlink4 neu installieren*). Ausführlich:
[docs/de/installation.md](docs/de/installation.md#ohne-rückfragen-hb4_answers).

### ⌨️ `HB4_ANSWERS`
- Die Antworten kommen aus einer JSON-Datei statt aus der Konsole: `server_name`, `dmr_port`, `ts1`, `ts2`, `frid`, `passphrase`,
  `guest_tgs`, `dashboard_title`, `server_description`, `web_port`, `public`, `admin_user`, `admin_password`, `https`, `domain`, `email`,
  `aprs`, `aprs_id`, `aprs_domains`, `aprs_ports`, `aprs_uplink`, `aprs_cb_login`, `svc_user`.
- Fehlende Schlüssel nehmen die Vorgabe bzw. den aktuellen Wert einer bestehenden Installation – derselbe Weg wie Enter bei einer Frage.
- `admin_password` (mindestens 8 Zeichen) wird sofort zum scrypt-Hash; ohne Passwort bricht eine Neuinstallation ab.
- Ohne Backup-Frage, ohne „So einrichten?“; alles Weitere (Konfiguration schreiben, Firewall, Dienste, `check.sh`) wie gewohnt.
- Alle Fragen-Helfer (`ask`, `ask_yn`) nehmen in diesem Modus die Vorgabe – nichts wartet mehr auf eine Eingabe.

### 🧪 Geprüft
- Echter Lauf auf einem frischen Klon (`SKIP_APT=1 SKIP_SERVICES=1 SKIP_FIREWALL=1 HB4_ANSWERS=…`): alle 10 Schritte ohne Eingabe,
  Einstellungen (Server, Titel, FreeRadioID, APRS mit ID und Domain) in der Datenbank, Superadmin-Passwort prüfbar.
- `tests/test_setup_unattended.py`: `setup.sh` kennt `HB4_ANSWERS`, ist syntaktisch in Ordnung und fragt im Modus nichts.

## [1.8.1] – 2026-11-25

**Normale Sicherungen lassen sich jetzt im HobbyRadioPortal wiederherstellen – auch ohne laufenden alten Server.**

Bisher kam HBlink4 nur per Umzugscode ins [HobbyRadioPortal](https://github.com/dhartmann1979/HobbyRadioPortal). Ab Portal 0.10.0 kann
der Web-Installer auch eine **Backup-Datei** einspielen. Dafür gibt es hier einen neuen Baustein. Ausführlich:
[docs/de/backup.md](docs/de/backup.md#aus-einer-sicherung-ins-portal-ab-181).

### 📦 `python3 -m dashboard.migration portalize QUELLE ZIEL [--identity SCHLÜSSEL]`
- Nimmt eine normale Sicherung aus *💾 Backup* (`backup-*.tar.gz`) **oder** ein verschlüsseltes AutoBackup (`auto-*.tar.gz.age`)
  mit dem Wiederherstellungsschlüssel (`.agekey`).
- Prüft das Archiv wie jede Wiederherstellung (sichere Pfade, Größen, SHA-256 jeder Datei, `PRAGMA quick_check` der Datenbanken).
- Schaltet in der **Kopie** das eigene HTTPS aus – Dashboard und alle APRS-Domains –, weil im Portal nginx Port 80/443 übernimmt.
  Das ist dieselbe Änderung, die das Umzugspaket bekommt (`PORTAL_OVERRIDES`).
- Bildet Manifest und Prüfsummen neu und schreibt das Ergebnis atomar mit Rechten 600. Das Original bleibt unverändert.
- Gibt die Vorschau als JSON aus (Version, Titel, Domains, Ports, Benutzer, Datum der Sicherung) – das Portal zeigt sie im Installer.
- Fehler (falscher Schlüssel, beschädigte oder fremde Datei) enden mit Exit-Code 2 und einer klaren Meldung, ohne Zieldatei.

### 🧪 Tests
- `tests/test_migration.py`: normale Sicherung → portalfertig (HTTPS aus, Prüfsummen gültig, Original unverändert, Rechte 600);
  verschlüsseltes AutoBackup nur mit Schlüssel; unbrauchbare Datei → Exit-Code 2 ohne Zieldatei.

## [1.8.0] – 2026-11-24

**Umzug ins HobbyRadioPortal: Der Web-Installer des Portals holt sich diesen DMR-Server mit einem Umzugscode – komplett und verschlüsselt.**

Ziehst du HBlink4 auf den Server des [HobbyRadioPortals](https://github.com/dhartmann1979/HobbyRadioPortal) (ab 0.9.0) um, musst du
kein Backup mehr herunterladen und hochladen. Ausführlich: [docs/de/backup.md](docs/de/backup.md#umzug-ins-hobbyradioportal) und die
[Umzugsanleitung des Portals](https://github.com/dhartmann1979/HobbyRadioPortal/blob/main/docs/UMZUG.md).

### 📦 Admin → 💾 Backup → Umzug ins HobbyRadioPortal
- Neue Karte im Backup-Bereich (nur Superadmin): was mitkommt (Version, Benutzer, Repeater-Regeln, OpenBridge, APRS), welche Domains
  das Portal neu einrichtet und welche **Ports** der neue Server braucht (DMR, OpenBridge, APRS-IS).
- **➕ Umzugscode anlegen**: `hb4m_…`, wird **einmal** angezeigt (mit 📋 Kopieren), gilt **2 Stunden** und für höchstens **3 Abrufe**;
  gespeichert wird nur der SHA-256 des Geheimteils. Liste der Codes mit Zustand, Abrufen und letzter IP, **Widerrufen**.
- Über HTTP verbunden? Ein roter Hinweis rät zu HTTPS oder einem SSH-Tunnel, bevor der Code angezeigt wird.
- Protokoll: *Umzugscode angelegt/widerrufen*, *Umzugspaket geliefert* (mit Größe und IP).

### 🔐 Wie das Portal den Server holt
- `POST /api/migration/info` (Bearer = Umzugscode): Vorschau – Version, Titel, Zahlen, Domains, Ports. Verbraucht keinen Abruf.
- `POST /api/migration/export` (Bearer = Umzugscode): erstellt den **Klon** wie unter 💾 Backup (Programm, Konfiguration, Benutzer,
  Zugangsdaten, Datenbanken, APRS, eigene Dateien, Paketversionen, Repository) und liefert ihn **verschlüsselt** aus.
- Verschlüsselung `n8mig` (nur Standardbibliothek, auch ohne HTTPS sicher): Schlüssel aus dem Geheimteil des Codes per **scrypt**,
  SHAKE-256-Schlüsselstrom und **HMAC-SHA-256** über alles (encrypt-then-MAC). Ohne passenden Code oder bei der kleinsten Änderung
  verwirft das Portal das Paket. `dashboard/n8mig.py` ist im Portal identisch (`portal/n8mig.py`, per Test geprüft).
- Das Paket ist **portalfertig**: im Klon sind das eigene HTTPS von HBlink4 und das Let's Encrypt der APRS-Domains ausgeschaltet –
  auf dem neuen Server übernimmt nginx des Portals Port 80/443 und leitet die Domains an das Dashboard weiter. Die Prüfsummen werden
  erst danach gebildet, die Wiederherstellung prüft das Archiv also vollständig wie jedes Backup. **Der alte Server bleibt unverändert.**
- Zu viele falsche Codes von einer Adresse sperren sie 15 Minuten. Bei privatem Dashboard brauchen nur diese beiden Endpunkte keine
  Sitzung (sie prüfen den Code selbst); CSRF (`X-Dashboard`) gilt auch für sie.
- Kein Zwischenstand bleibt liegen: unverschlüsseltes und verschlüsseltes Paket werden nach dem Senden gelöscht.

### 🛠️ Wiederherstellen ohne Rückfragen
- `scripts/setup_restore.py VERZEICHNIS BACKUP.tar.gz --yes [--account BENUTZER]`: für den Root-Helfer des Portals. Die Vorschau wird
  angezeigt, die Bestätigung *RESTORE* gilt als gegeben, der Dienst-Benutzer kommt aus dem alten Server. Sonst alles wie bisher
  (Ziel-Backup vorher, Rollback bei Fehlern, Paketprüfung mit der Python-Version des Ziels).
- `create_archive(…, stage_hook=…)`: Klon-Kopie vor den Prüfsummen ändern (nutzt der Umzug).

### 🧪 Tests
- `tests/test_migration.py`: Ver- und Entschlüsselung (mehrere Blöcke, falscher Code, verändertes Byte → nichts bleibt liegen),
  Codes (Abrufe, Ablauf, Widerruf, Sperre nach Fehlversuchen, falsches Präfix), Vorschau mit Domains und Ports, der ganze Weg über
  die API bis zum entschlüsselten Klon, den `unpack_archive` vollständig prüft – mit HTTPS aus im Klon und unverändertem alten Server.
- Zusätzlich gegen das echte Portal geprüft: Portal prüft Adresse und Code, holt 147 MB in 7 s, entschlüsselt und übergibt.

## [1.7.0] – 2026-11-24

**Portal-Zugang: API-Token für das HobbyRadioPortal – APRS und DAPRS lassen sich jetzt dort verwalten.**

### 🔌 API-Token
- Neu im Adminbereich unter **🔑 Sessions → 🔌 Portal-Zugang (API-Token)**: Token anlegen (Name), **einmal anzeigen und kopieren**,
  Liste mit den letzten vier Zeichen, angelegt von/wann, zuletzt benutzt, letzte IP, **Beenden** (widerrufen). Höchstens 20 Token.
- Token `hb4p_…` mit 256 Bit Zufall; gespeichert wird nur der SHA-256 (neue Tabelle `api_tokens` in `dashboard.db`, kommt mit ins Backup).
- Anmeldung per `Authorization: Bearer …`. Ein Token handelt mit der Rolle **Admin** (nie Superadmin) und erreicht **nur**
  öffentliche `/api/`-Daten, `/api/admin/settings`, `/api/admin/aprs…` und `/api/admin/audit`. Gesperrt: Benutzer, Sitzungen,
  Token, Backups, Anmeldung/Passwort, Updates, Neustarts sowie die Einstellungsbereiche *Dashboard access*, *HTTPS & web* und *Updates*.
- CSRF-Schutz (`X-Dashboard: 1`) gilt weiter. Im Protokoll steht der Token als `api:<Name> (<Portal-Benutzer>)` (Kopfzeile `X-Portal-User`).
- Kommandozeile: `python -m dashboard.auth api-token create NAME | list | revoke ID [--db PFAD]` – z. B. für Installer.
- Neue Endpunkte (nur für angemeldete Admins, nicht für Token): `GET/POST /api/admin/api-tokens`, `DELETE /api/admin/api-tokens/{id}`.

### 🛰️ Wofür
- Das [HobbyRadioPortal](https://github.com/dhartmann1979/HobbyRadioPortal) 0.5.0 bringt damit den kompletten Tab **📡 APRS** ins
  Portal: APRS-Server, Uplink & Downlink (APRS-IS, CB-APRS, manuell), **DAPRS** (Erkennen im DMR-Server und Weitergabe an APRS,
  SSID/Symbol/Kommentar je ID), Repeater-/Hotspot-Objekte, Karte, APRS-Domains, verbundene Clients, Neustart, Passcode.

### 🧪 Tests
- `tests/test_api_tokens.py`: anlegen/benutzen/widerrufen, ungültige Namen, erlaubte und verbotene Pfade, gesperrte Einstellungen,
  Protokolleintrag mit Portal-Benutzer, CSRF auch mit Token, ohne Token bei privatem Dashboard 401.

### 📖 Doku
- [Adminbereich → Sessions](docs/de/adminbereich.md#-sessions--log--system) mit neuem Screenshot, [Sicherheit → API-Token](docs/de/sicherheit.md#api-token-für-das-hobbyradioportal),
  [Betrieb → Im HobbyRadioPortal](docs/de/betrieb.md#im-hobbyradioportal), [APRS → Im HobbyRadioPortal](docs/de/aprs.md#im-hobbyradioportal).

## [1.6.2] – 2026-11-24

### 🔌 Für das HobbyRadioPortal
- Neuer Endpunkt **`GET /api/last-heard`**: dieselbe Liste wie *Last Heard* im Dashboard (Rufzeichen, DMR-ID, Talkgroup, Zeitschlitz,
  Quelle, FRID, aktiv), bisher nur über den WebSocket zu haben. Wie alle Live-Daten gehen IP-Adressen nur an Admins (`view_for`).
  Das Plugin `dmr` im [HobbyRadioPortal](https://github.com/dhartmann1979/HobbyRadioPortal) füllt damit „Zuletzt gehört“.
- Doku: [Betrieb → Im HobbyRadioPortal](docs/de/betrieb.md#im-hobbyradioportal) listet alle Schnittstellen, die das Portal liest.
- Test: der Endpunkt gibt die Liste nur über `view_for` heraus.

## [1.6.1] – 2026-11-24

**Live-Ansicht aufgeräumt: „🔌 Verbundene Systeme“ – ein gemeinsames Raster, eine schlanke Karte für alles**

Bisher standen OpenBridge, Repeater, Hotspots, Apps, Netzwerke und Outbound-Links in eigenen Bereichen, die auf breiten
Bildschirmen in zwei bzw. drei Spalten (`column-count`) ungleich übereinander rutschten. Jede Art hatte ihren eigenen Kartenaufbau
(OpenBridge mit Chips, Stationen mit zweispaltiger Textliste, Badge in eigener Zeile). Das ist jetzt einheitlich.

### 🧱 Ein Raster für alle verbundenen Systeme
- Ein Abschnitt **🔌 Verbundene Systeme** mit Gesamtzahl ersetzt die sieben Einzelbereiche. Alle Karten stehen in **einem Raster**
  mit gleich breiten Spalten (mind. 300 px): am großen Monitor 4–6 nebeneinander, am Tablet 2, am Smartphone 1.
- Karten einer Reihe sind **gleich hoch**; die Zeitschlitz-Zeile sitzt immer unten.
- Reihenfolge: OpenBridge → Repeater → Hotspots → Apps → Netzwerk eingehend → Unbekannte Geräte → Netzwerk ausgehend,
  innerhalb einer Art steht oben, wer gerade spricht.
- **Filter-Pillen** über dem Raster: *Alle 7 · ↔️ OpenBridge 1 · 📶 Repeater 2 · …* – Zählung und Filter in einem. Die Auswahl
  merkt sich der Browser. Gibt es nur eine Art, entfällt die Leiste.
- Ist nichts verbunden, steht *Keine Systeme verbunden*.

### 🪪 Die schlanke Karte (gleich für Repeater, Hotspot, App, Netzwerk, Outbound und OpenBridge)
- **Kopf:** Avatar mit kleinem Art-Symbol unten rechts (📶 📱 📲 🔗 ❔) · Rufzeichen + ID · darunter Login-Art als kleines Etikett
  (**✓ FRID** grün, **👤 Gast** gelb, 🔀 Anzahl Übersetzungen) und Standort · rechts der Zustand als Pille:
  **ON AIR**/**LIVE** (grün, pulsierend), *online*, *n verpasst* (gelb), *wartet*/*offline* (rot).
- **Farbe pro Art** als Streifen links: OpenBridge orange, Repeater grün, Hotspot hellblau, App violett, Netzwerk cyan, Unbekannt gelb.
- **Eine Kennzahlen-Zeile mit vier gleich breiten Feldern:**
  Stationen: *Online · TX MHz · TS1 · TS2* (RX-Frequenz im Tooltip), Outbound: *Online · Server · TS1 · TS2*,
  OpenBridge: *Online · Server · Talkgroups · Heute ↓ empfangen ↑ gesendet*. Am Smartphone 2 × 2.
- Talkgroups als kleine Chips, höchstens zwei sichtbar, der Rest als **+N** (Liste im Tooltip). *Alle* (keine Konfiguration) grün.
- Unten wie bisher die Zeitschlitze (`TS1 IDLE · TS2 IDLE` bzw. RX/TX/HANG mit Sprecher); bei OpenBridge jedes laufende Gespräch als Zeile.
- Ein Klick auf den Kopf öffnet wie bisher die Detailansicht bzw. bei OpenBridge den Tab OpenBridge.
- Der Hinweistext bei unbekannten Geräten steht nicht mehr über dem Raster; die gemeldete Software steht direkt auf der Karte
  (*Minden · OpenGD77-Net · v4.2*), der Weg zur Geräteerkennung weiterhin in der Detailansicht.

### 🐞 Behoben
- **Outbound-Karte zeigte rohes HTML** (`<span class="hidden-ip" …>`), wenn die Adresse für Gäste verborgen ist – der Statustext
  wurde samt Adress-HTML escaped. Jetzt wird nur der Fehlertext escaped, die Adresse erscheint als 🔒.
- Name und ID im Outbound- und OpenBridge-Kopf laufen jetzt über `escapeHtml`. Der OpenBridge-Klick übergibt den Namen über
  ein `data-`Attribut statt als JavaScript-String (Namen mit Apostroph brachen den Klick).
- Gast-Karten färbten durch die Klasse `auth-guest` den ganzen Karteninhalt gelb – entfernt.

### 🌐 Sprache
- Neue Texte deutsch und englisch: *Verbundene Systeme, Keine Systeme verbunden, Unbekanntes Gerät, Netzwerk ein-/ausgehend,
  Ausgehende Verbindung, n verpasst, wartet, kein Verkehr …*

### 📖 Doku
- [Dashboard → Verbundene Systeme](docs/de/dashboard.md#-verbundene-systeme) neu beschrieben; neue Screenshots
  `connected-systems.png`, `connected-systems-filter.png`, `connected-systems-en.png`, aktualisiert `dashboard-desktop.png`,
  `dashboard-mobile.png`, `dashboard-stations.png`, `dashboard-freeradioid-card.png`, `dashboard-guest-card.png`,
  `openbridge-card.png`, `device-type-app.png`, `device-type-unknown.png`.

## [1.6.0] – 2026-11-24

**Vollständige Backups, Wiederherstellung (auch beim Initial Setup) und verschlüsseltes AutoBackup** – Beitrag von SA7BNT
(Pull Request #2), eingebaut auf den Stand 1.5.0 mit Sicherheits-Headern, N8 Kit und Update-Rollback.

### 🔗 Einbau in 1.5.0 (N8 Kit, Sicherheit, Update-Guard)
- **Update und Backup schließen sich aus:** *Update jetzt installieren* wartet nicht auf eine laufende Sicherung/Wiederherstellung,
  sondern lehnt mit Hinweis ab; umgekehrt starten Backup, AutoBackup und Wiederherstellung nicht während eines Updates.
- **Kein geklonter Update-Zustand:** `update.pending`/`update.result` des N8 update guard kommen nicht ins Backup. Sonst würde ein Klon
  nach dem Einspielen eine fremde Update-Prüfung oder gar einen Rollback anstoßen.
- **Sicherheits-Header bleiben:** Backup-Download, Schlüssel-Export und Uploads laufen über den eigenen Server; die
  Content-Security-Policy musste dafür nicht gelockert werden. Die Backup-Routen erscheinen nirgends öffentlich (API-Doku bleibt aus).
- **Sprache:** Die Backup-Oberfläche ist deutsch; mit **EN** erscheint sie auf Englisch (`i18n-dashboard.js`). Der Menüpunkt heißt
  *💾 Backup* / *💾 Backup*, die Kacheln nutzen das N8-Design der APRS-Übersicht (`ap-card`).
- **N8 Kit 1.0.1:** Absätze, die im Quelltext über mehrere Zeilen gehen, werden als Ganzes übersetzt (vorher Zeile für Zeile, deshalb blieben sie stehen).
- **Doku:** Screenshots *Admin → Backup* (deutsch und englisch); Querverweise zwischen [Backup](docs/de/backup.md), [AutoBackup](docs/de/autobackup.md) und [Sicherheit & N8 Kit](docs/de/sicherheit.md).

### Wiederherstellung mit unterschiedlichem Python

- Der Initial Restore und die Archivprüfung im Dashboard lehnen Backups nicht mehr pauschal wegen einer anderen Python-Unterversion ab. Quelle und Ziel benötigen Python ab 3.9.
- Bei einem Versionswechsel prüft der Diensthelfer vor dem Stoppen vorhandener Dienste den Programmcode und baut/installiert die gesicherten Anwendungspakete in einer Testumgebung. Inkompatibilitäten brechen vor dem Ersetzen ab; vorbereitete Pakete werden für die endgültige Umgebung wiederverwendet.
- Die Anwendungspakete behalten ihre Versionen. pip/setuptools/wheel werden für Ziel-Python vorbereitet; Quell- und Zielversion sowie die zusätzliche Prüfung erscheinen in der Vorschau. Rücknahme und Wiederherstellungsbackup bleiben erhalten.

### Gespeicherte Backups löschen

- Admin → Backup bietet für jede gespeicherte Sicherung eine Löschschaltfläche mit Bestätigung.
- Löschen betrifft nur lokale Archive; SFTP-/Drive-Kopien bleiben erhalten. Nur Superadmins dürfen löschen, laufende Sicherungen, Wiederherstellungen und Updates sind geschützt.

### Verschlüsseltes AutoBackup

- Admin → Backup: tägliche/wöchentliche vollständige Sicherungen mit Zeitzone, Aufbewahrung, Verlauf und manuellem Start; Ziele SFTP und Google Drive.
- age verschlüsselt Archive und gespeicherte Zugangsdaten. Exportierbarer Wiederherstellungsschlüssel außerhalb des Backups; SFTP mit SSH-Hostschlüsselprüfung, Drive mit eigenem OAuth-Client und erneuerten Tokens.
- Inhaltsprüfung vor dem Upload und vollständiges Rücklesen danach. Bereinigung nur katalogisierter AutoBackups nach Erfolg auf allen aktivierten Zielen; Wiederholungen bei Fehlern.
- Verschlüsselte Archive im Adminbereich und beim Initial Setup wiederherstellbar. Klone können übernommene Zugangsdaten mit dem alten Schlüssel entsperren und den Zeitplan bewusst neu aktivieren.
- Vorbereitung mit `sudo ./scripts/install_autobackup.sh`; Anleitung: [AutoBackup](docs/de/autobackup.md).

### Backup beim Initial Setup wiederherstellen

- Neue Auswahl zu Beginn von `scripts/setup.sh`: neu einrichten oder eine vorhandene vollständige Sicherung übernehmen.
- Archivprüfung und Vorschau vor Konfigurations-/Datenänderungen; Bestätigung mit `RESTORE`, Anmeldung nachher mit dem Quellkonto.
- Frische Ziele bekommen Python-Umgebung, zunächst gestoppte Dienste und den vorhandenen Wiederherstellungshelfer automatisch eingerichtet. HTTPS übernimmt bei Bedarf die certbot-Voraussetzung.
- Vorhandene Installationen behalten ihr Dienstkonto und die automatische Rücknahme; ein fehlgeschlagener Erstaufbau bleibt gestoppt und deaktiviert. Der Wiederherstellungsdienst läuft unabhängig von der Setup-Konsole.

### 💾 Vollständige Backups und Wiederherstellung

- Neuer Menüpunkt **Admin → Backup** für den Superadmin: vollständiges Archiv erstellen, herunterladen und vor der Wiederherstellung prüfen.
- Enthalten sind Programmcode, lokale Änderungen, Git-Versionsstand, Konfigurationen, Benutzer und Zugangsdaten, SQLite-Datenbanken einschließlich WAL-Inhalten, APRS-Daten, Statistiken, Bilder, Zertifikate und eigene Dateien. Python-Paketversionen und installierte systemd-Dienste werden dokumentiert.
- Wiederherstellung auf einer vorbereiteten Linux/systemd-Installation mit Python ab 3.9 und Kompatibilitätsprüfung bei abweichender Unterversion. Installationspfade werden angepasst; Zielserver-Dienstkonto und systemd-Einrichtung bleiben erhalten. Die Python-Umgebung wird mit den gesicherten Anwendungspaketversionen neu erstellt.
- Separater, einmalig installierter Diensthelfer stoppt beide Dienste, erstellt ein automatisches Wiederherstellungsbackup und startet die geklonte Installation. Fehler beim Einspielen oder Dienststart führen zur Rücknahme einschließlich der ursprünglichen Python-Umgebung.
- Archivprüfung mit SHA-256, Größenlimits, SQLite-Prüfung und Schutz vor fremden Dateipfaden, Links und doppelten Einträgen. Wiederherstellen erfordert Archivvorschau, erneute Passwortbestätigung und `RESTORE`; importierte Sitzungen werden beendet.
- Anleitung: [Backup und Klonen](docs/de/backup.md). Betriebssystem, Firewall, DNS und externe Dienste sind nicht Bestandteil eines HBlink4-Klons.

## [1.5.0] – 2026-11-24

Sicherheit, Sprache und ein Update-System, das in **HBlink4-FreeRadioID, adn-frn-server, N8-HotSpot und N8 Crosslink** gleich aussieht und gleich funktioniert (**N8 Kit**). Ausführlich: [docs/de/sicherheit.md](docs/de/sicherheit.md).

### 🔐 Sicherheit
- **API-Beschreibung aus:** `/docs`, `/redoc` und `/openapi.json` antworten mit 404 (vorher lagen dort alle Routen samt Admin-Endpunkten und Schemas offen). Zum Entwickeln: `N8_API_DOCS=1`.
- **Neue Header bei jeder Antwort:** `Content-Security-Policy` (nur eigene Skripte/Styles/Schriften, Verbindungen nur zum eigenen Server, `object-src 'none'`, `base-uri`, `form-action`, `frame-ancestors`), `Strict-Transport-Security` über HTTPS (auch hinter einem Proxy mit `X-Forwarded-Proto`), `Permissions-Policy`, `Cross-Origin-Opener-Policy`/`-Resource-Policy`. Der Header `server: uvicorn` entfällt.
- **XSS geschlossen:** Alle Render-Funktionen geprüft. Ungeescapt waren Rufzeichen und Standort auf der Repeater-Karte, das Rufzeichen im Slot, die Ereignisliste (*Recent Events*), Status und Name der Outbound-Links, der OpenBridge-Status und der Tooltip übersetzter Talkgroups – jetzt alle über `escapeHtml`.
- **Eingaben vom Gerät bereinigt:** HBlink4 entfernt aus den Textfeldern der Anmeldung (Rufzeichen, Standort, Beschreibung, URL, Software, Paket) HTML-Zeichen und Steuerzeichen, bevor sie irgendwohin gehen.
- Doku mit Beispielen für **Caddy** und **nginx** als Reverse-Proxy.

### 🌐 Sprache DE | EN
- Umschalter **DE | EN** in der Kopfzeile (Dashboard und APRS-Karte), **Standard Deutsch**. Umschalten ohne Neuladen; die Wahl gilt per Cookie für alle N8schicht-Oberflächen auf dem Server. `?lang=en` für Links.
- Deutsche Texte für Menü, Statusleiste, Live-Ansicht, Statistik, OpenBridge, Talkgroups, Configuration-Tab, Adminbereich (alle Settings-Abschnitte, Aussehen, Links, OpenBridge-Editor, Import, APRS, System) und APRS-Karte (`dashboard/static/i18n-dashboard.js`).
- Statusleiste: Kurz- und Langtext getrennt (*Live-Daten* / *Live*), damit sie sich übersetzen lassen.

### ⬆️ Updates wie in N8 Crosslink
- Hinweis unter der Statusleiste im N8-Kit-Stil: *Update verfügbar: alt → neu* mit **Was ist neu?**, **Jetzt aktualisieren**, **Details**, **Später** (einen Tag).
- **Jetzt aktualisieren** öffnet ein Fenster mit Neuerungen und Passwortabfrage, danach drei Schritte mit Fortschritt (*geladen und eingespielt → Dienst startet neu → Weboberfläche wird geprüft*); die Seite lädt danach neu. Ein falsches Passwort lässt das Fenster offen.
- **Admin → System → ⬆️ Updates**: gleiche Kachel wie in den anderen Projekten (installiert, GitHub, zuletzt geprüft, automatische Prüfung, letztes Update, Branch, Neustart, Berechtigung).
- **Rollback:** Vor dem Neustart wird der alte Stand gemerkt; die neue Version prüft ihre eigene Weboberfläche. Antwortet sie nicht, setzt `scripts/n8-update-guard.sh` (`ExecStartPre` in `hblink4-dash.service`) nach drei Starts auf den alten Commit zurück. Ergebnis unter *Letztes Update*. Bestehende Installationen: einmal `sudo ./scripts/install_services.sh`.

### 🧪 Tests
- `tests/test_security.py`: API-Doku aus, alle Header, HSTS hinter Proxy, kein `server`-Header, Bereinigung der Gerätefelder, Rollback nach drei Starts, Bestätigung nach erfolgreichem Start, Kit-Dateien eingebunden.

## [1.4.0] – 2026-11-24

### 📻 Talker Alias
- HBlink4 liest den **DMR Talker Alias** aus (den Namen, den das Funkgerät mitsendet, z. B. „DL1ABC Hans“). Quellen sind der Sprachrahmen (Embedded LC, FLCO 4–7) und **DMRA**-Pakete von MMDVMHost/DMRGateway. Unterstützt werden alle vier Formate (7-Bit, ISO-8859-1, UTF-8, UTF-16) bis 31 Zeichen.
- Das gilt für alle Eingänge: Repeater/Hotspots, Outbound-Links und OpenBridge. Der Alias erscheint schon nach dem ersten Block (etwa 1 s) und vervollständigt sich während des Gesprächs. Jede neue Übertragung beginnt leer.
- Neues Ereignis `talker_alias` zum Dashboard; `stream_end` trägt den Alias mit. Im Log steht jeder vollständige Alias einmal mit `📻`.
- Bisher wurden DMRA-Pakete nur bestätigt; jetzt werden sie ausgewertet. Format: Quell-ID, Blocktyp, 7 Datenbytes.

### 🎙️ Dashboard
- **Der Talker Alias ersetzt den Namen** aus der Rufzeichen-Datenbank: in Last Heard, in den Slots der Repeater-/Hotspot-Karten, in der Slot-Detailansicht und bei OpenBridge/Outbound. Er ist mit **TA** markiert; der Tooltip zeigt das Rufzeichen aus der Datenbank.
- **📈 Statistics:** neue Rangliste **📻 Talker Alias**, getrennt von den DMR-IDs: Gespräche, Sprechzeit, sendende IDs/Rufzeichen, Talkgroups, letztes Gespräch. Gleiche Namen in anderer Schreibweise werden zusammengefasst. In der Talkgroup-Tabelle zeigt *Most active* den TA der aktivsten Station.
- Die Datenbank bekommt die Spalte `talker_alias` in `tg_calls` (wird beim Start automatisch ergänzt, alte Gespräche bleiben leer).
- Demo (`?demo`) mit Talker-Alias-Beispielen.

### 🧪 Tests
- `tests/test_talker_alias.py`: 7-Bit, Latin-1 mit Umlauten, 4 Blöcke mit Teilergebnis, DMRA-Blöcke, neue Übertragung setzt zurück, Müll wird ignoriert (Vektoren aus einem unabhängigen MMDVMHost-Port).
- `tests/test_tgstats.py`: Rangliste und Zusammenfassen gleicher Namen. Ende-zu-Ende geprüft mit echtem Sprachstrom von N8 Crosslink: erst „DL1ABC“, dann vollständig „DL1ABC Hans“.

## [1.3.0] – 2026-11-22

Neue Kopfzeile mit **einem Menü** und einer schmalen **Statusleiste** darunter (gleicher Aufbau wie in frn_adn und N8-HotSpot),
eine aufgeräumte **APRS-Übersicht** im Adminbereich und eine Anleitung zum **Senden von DAPRS-Positionen** im Tab Configuration.

### 🧭 Ein Menü in der Kopfzeile
- Die Kopfzeile enthält nur noch Logo/Titel, die Reiter und rechts 🔗 Links und Anmeldung. Status-Chips stehen nicht mehr darin.
- **⚙️ Admin** ist nach dem Login ein eigener, gestrichelt umrandeter Menüpunkt; das Aufklappmenü unter dem Namen entfällt.
- **🔐 Login** steht ganz rechts. Angemeldet zeigt der Platz Avatar + Namen (Klick = Passwort ändern) und **⏻ Abmelden** daneben.

### 🟢 Statusleiste unter dem Menü
- Neue, 22 px niedrige Leiste direkt unter der Kopfzeile, kleiner als das Menü: **Live data**, **DMR server** und – bei eingeschaltetem APRS –
  **APRS online · n stations** (alle 60 s aus `/api/aprs/status`); rechts **🔇/🔊 Notifications**.
- Zustand als farbiger Punkt (grün, gelb, rot), Texte kurz und ohne ✓/✕: *Offline – click to reconnect*, *DMR server offline*.
  Ein Klick auf *Live data* verbindet weiterhin neu.
- Am Smartphone eine Zeile mit kurzen Texten (*Live*, *DMR*, *APRS*); die Statuspunkte in der Kopfzeile entfallen.

### 🗺️ APRS-Karte
- Die Kopfzeile der Karte folgt demselben Muster: Menü mit **🗺️ APRS map** und **📊 Dashboard**, darunter die Statusleiste mit Live,
  APRS-IS/CB-APRS und rechts Stationen und DMR-Stationen. Panel und Kartenknöpfe sitzen automatisch unter der Leiste (`--below-head`);
  in der eingebetteten Ansicht (Dashboard-Tab) entfällt die Leiste.

### 📡 APRS-Übersicht im Adminbereich
- Neu aufgebaut: oben fünf **Kennzahlen** (Stationen der letzten Stunde, DMR-Positionen, Clients, Pakete rein mit verworfenen Duplikaten,
  gesendet), darunter ein Raster aus Karten: **Server** (Status, Server-ID, Passcode, Ports, Version), **Uplink & downlink** (jede
  Verbindung mit Zustand, Richtung, ↓/↑-Zählern, Login, Gegenstelle, seit wann), **Stations by source** (Balken DMR/Repeater/Clients/
  APRS-IS), **DAPRS** (Positionen, gesendet, IDs ohne Rufzeichen, Repeater-Objekte), **Domains** mit Zertifikatsstatus und
  **Passcode**-Rechner; Clients und letzte Probleme als eigene Karten, die Knöpfe als Leiste darunter.

### 📍 DAPRS im Tab Configuration
- Neue Karte **📍 APRS – show your position on the map (DAPRS)**, nur wenn APRS, DAPRS und die Dekodierung im DMR-Server an sind.
- Sie richtet sich nach *DAPRS decoding*: **A · GPS im Sprachruf** (Embedded GPS) nur bei *Decode embedded GPS*; **B · GPS-Report als
  Datenruf** nur bei *Decode GPS data calls*, mit Ziel-ID aus *Accept GPS data sent to* (z. B. `900999`, Kopier-Knopf; weitere erlaubte
  Ziele werden aufgelistet), *Private call*, NMEA/LRRP unbestätigt Rate ½ und Mindestintervall.
- Dazu: wie du auf der Karte erscheinst (Rufzeichen-SSID, Symbol, Link zur Karte), ob die Position ins APRS-Netz geht, dass Gäste nur
  lokal erscheinen, und ein Hinweis für Hotspots mit DMRGateway.
- `/api/connect` liefert dafür das neue Feld `daprs` (oder `null`).

### 📚 Doku
- *Dashboard*: Abschnitt **Kopfzeile mit Menü und Statusleiste** neu (Menü- und Statustabelle, Screenshots `header-desktop`, `header-login`,
  `header-mobile`) und neuer Abschnitt **📍 DAPRS: so sendest du deine Position** mit `config-daprs.png`.
- *APRS*: Anleitung im Tab Configuration, neue Beschreibung der Übersicht und der Kartenkopfzeile; alle Karten-Screenshots neu.
- *Adminbereich*, *Anleitungen*, *Betrieb*: Login, ⚙️ Admin und Statusleiste statt Benutzermenü und ✓-Chips. `user-menu.png` entfällt.
- Screenshots neu: Dashboard (Desktop/Smartphone), Statistik, Talkgroups, OpenBridge, Configuration, APRS-Übersicht.

## [1.2.1] – 2026-11-22

Eigenes **Logo und Icon für die APRS-Karte** im N8schicht-Design und eine aufgeräumtere Karte – besonders am Smartphone
und auf hellen Kartenstilen (z. B. Topographisch).

### 🎨 Logo und Icon
- **N8schicht-APRS-Logo** (`dashboard/static/n8schicht-aprs-logo.svg`): Nachthimmel mit Mond wie beim DMR-Logo, grüner
  Karten-Pin mit Funkwellen, gepunktete APRS-Spur, „N8“ und Plakette **APRS**. Es steht in der Kopfzeile der Karte, wenn für
  die Domain kein eigenes Logo hochgeladen ist (bisher: Logo des Dashboards).
- **APRS-Icon** ohne Schrift (`n8schicht-aprs-icon.svg`, `n8schicht-aprs-icon-192.png`), bis 16 px lesbar: Favicon,
  Browser-Tab und Homescreen-Symbol der Karte.
- Im Adminbereich heißt der Knopf bei den Domain-Logos **↺ Default** und stellt das APRS-Logo wieder her.

### 🗺️ Karte
- **Smartphone:** Die Stationsliste ist jetzt eine Leiste mit Griff und Zählern („📍 224 stations · 📻 4 DMR“); antippen klappt
  sie auf und zu. Zugeklappt verdeckt sie nur noch einen schmalen Streifen der Karte (vorher wurde die Liste mitten in den
  Filtern abgeschnitten). Der ☰-Knopf in der Kopfzeile entfällt.
- **Filter** stehen in einer Zeile und lassen sich seitlich wischen, statt über drei Zeilen umzubrechen.
- **Panel und Popups deckender** (Glas mit 86 % statt 72 %): auf hellen und bunten Karten (OpenStreetMap, Topographisch) gut lesbar.
- **Kartennachweis kürzer:** Der Hinweis auf die APRS-Symbole steht jetzt unten in der Stationsliste; am Smartphone ist der
  Kachel-Nachweis kleiner und braucht nur noch eine Zeile.

### Doku
- [docs/de/aprs.md](docs/de/aprs.md): neuer Abschnitt *Logo und Icon*, Screenshots der Karte neu.

## [1.2.0] – 2026-11-22

**APRS für DMR Die N8schicht:** ein APRS-Server in Python, Uplink & Downlink wahlweise zu APRS-IS, CB-APRS oder eigenen
Servern, **DAPRS** (GPS-Positionen von DMR-Funkgeräten werden APRS-Positionen) und eine Live-Karte im N8schicht-Design –
auch unter bis zu drei eigenen Domains mit Let's-Encrypt-Zertifikat. Alles im Adminbereich unter **📡 APRS**.
**APRS ist nach dem Update ausgeschaltet**; es ändert sich nichts, bis du es einschaltest. Anleitung: [docs/de/aprs.md](docs/de/aprs.md).

### 🛰️ DAPRS – GPS aus dem DMR-Verkehr (DMR-Server)
- **Embedded GPS:** Funkgeräte, die ihre Position während eines Sprachrufs senden („GPS Info“-LC in den Bursts B–E),
  werden erkannt. Jeder Block wird vollständig geprüft (Hamming, Spaltenparität, Prüfsumme); fehlerhafte werden verworfen.
- **GPS-Datenrufe:** Datenkopf + Rate-½-Blöcke mit **NMEA** (`$GPRMC`/`$GNRMC`/`$GPGGA`/`$GNGGA`, auch als UTF-16-SMS
  und in IP/UDP) und **Motorola LRRP** (UDP 4001), z. B. „Digital APRS“ als Privatruf an `900999`. Rate ¾ und Rate 1
  werden nicht geraten, sondern gezählt.
- Ziele einschränkbar (*Accept GPS data sent to*), Wiederholungen derselben Station innerhalb von 10 s werden unterdrückt.
- Kostet im Hot Path nur einen Vergleich pro Burst; neue Logzeile `📍 DAPRS … position from …`; neues Ereignis
  `gps_position` an das Dashboard. Neue DMR-Einstellungen `dmr.daprs.*` (folgen dem APRS-Schalter).

### 📡 APRS-Server (Dashboard)
- APRS-IS-kompatibel: Port **14580** mit Filtern (`r/ a/ p/ b/ o/ t/ s/ d/ e/ g/ u/ m/ f/`, Ausschluss mit `-`,
  `#filter` im Betrieb) und **10152** Full Feed; Login mit Passcode, `logresp`, Keep-alive, q-Konstrukt (`qAC`, `qAR`, `qAO`),
  Schleifen- und Duplikatschutz (30 s), Flutschutz, Verbindungsgrenzen pro IP, langsame Clients werden getrennt.
- Nachrichten erreichen ihren Empfänger auch außerhalb seines Filters; Clients ohne gültigen Passcode dürfen nur empfangen.
- Ports nur nach Einschalten (*Open the APRS-IS ports*) und nur mit gesetzter **Server-ID** (Rufzeichen).

### 🌍 Uplink & Downlink – wählbar
- **APRS-IS** (Vorgabe `euro.aprs2.net:14580`), **CB-APRS** (`eu.cbaprs.net:27235`, eigenes Login und Passcode oder `-1`)
  oder **manuell**: beliebig viele eigene Server, jeder mit Login, Passcode, Downlink-Filter und Richtung
  (⇅ hoch & runter, ↑ nur hoch, ↓ nur runter).
- Gesendet wird nur über verifizierte Verbindungen; was aus einem Netz kommt, geht nie in ein anderes zurück.
- Änderungen wirken sofort: Server und Verbindungen starten von selbst neu.

### 📍 DMR → APRS
- Rufzeichen aus der ID-Liste (FreeRadioID.net/radioid.net), **SSID** (Vorgabe 7), **Symbol**, **Kommentar** mit
  Platzhaltern (`{tg}`, `{repeater}`, `{dmrid}`, `{slot}`, `{server}`), Tabelle **pro DMR-ID** (eigenes Rufzeichen, SSID,
  Symbol, Kommentar oder abschalten).
- Höchstens eine Position pro Station und Minute ins Netz (einstellbar); **Gäste** (FreeRadioID-Gastzugang) nur auf der lokalen Karte.
- **Repeater als APRS-Objekte** aus den Login-Daten (Frequenz, Ablage, Colour Code); Hotspots möglich, aber aus
  (Wohnadressen); Objekte verlassener Repeater werden gelöscht gemeldet.

### 🗺️ APRS-Karte
- Leaflet-Karte im N8-Design (folgt dem Farbprofil, dunkle Karte bei dunklen Profilen) mit Stationsliste, Suche,
  Filtern (DMR, Repeater, Clients, APRS-IS/CB-APRS, Wetter), APRS-Symbolen, Detailfenster (QTH-Locator, DMR-ID,
  Talkgroup, Hotspot/Repeater, Art der GPS-Meldung, Avatar, Wetter, Rohpakete), Spuren und Live-Paketliste per WebSocket.
- Unter `/aprs`, als Tab **🗺️ APRS** im Dashboard und unter **bis zu drei eigenen Domains** – jede mit eigenem Titel,
  Untertitel und Logo; dort steht unter `/` die Karte, das Dashboard unter `/dashboard`. Am Smartphone als Bottom-Sheet.
- Öffentlich oder nur mit Login – unabhängig vom Dashboard. Kartenstile: automatisch, dunkel, OpenStreetMap, OpenTopoMap, eigener Kachelserver.

### 🔒 Let's Encrypt für die APRS-Domains
- Domains mit *HTTPS* kommen als zusätzliche Namen in das Zertifikat des Dashboards – nur wenn sie per DNS auf diesen
  Server zeigen (sonst eine Logzeile statt eines kaputten Zertifikats). Fehlende Namen werden im Hintergrund nachgeholt
  und ohne Neustart geladen; HTTP leitet auf HTTPS derselben Domain um. Die Übersicht zeigt den Status jeder Domain.

### 💾 Speicherung
- Eigene SQLite-Datenbank `dashboard/data/aprs.db` (Stationen, Spuren, Rohpakete), Schreiben gebündelt im Hintergrund,
  **höchstens 90 Tage** (Vorgabe: Stationen/Spuren 30 Tage, Rohpakete 7 Tage), stündliche Bereinigung.

### ⚙️ Adminbereich und Installation
- Neuer Bereich **📡 APRS**: Übersicht (Ports, Server-ID mit Passcode, jede Verbindung mit Zustand und Zählern, DAPRS,
  Stationen, Zertifikatsstatus, Passcode-Rechner, Clients mit **Disconnect**), Server, Uplink & Downlink, DAPRS-Erkennung,
  DMR → APRS, Karte, Domains.
- `scripts/setup.sh` hat einen neuen Schritt **APRS** (Vorgabe aus): Server-ID, Karten-Domains, Ports, Netz; öffnet bei
  Bedarf TCP 14580/10152 in ufw. `scripts/check.sh` zeigt die APRS-Ports.

### Technik
- Neue Dateien: `hblink4/daprs.py`, `dashboard/aprs/` (`packet.py`, `filters.py`, `store.py`, `service.py`),
  `dashboard/static/aprs.html`, Leaflet 1.9.4 (`dashboard/static/vendor/leaflet/`, BSD-2) und die APRS-Symbole von
  hessu/aprs-symbols (`dashboard/static/aprs-symbols/`, Lizenzen in `COPYRIGHT.md`), `scripts/e2e_daprs.py`.
- Keine neuen Python-Abhängigkeiten. Neue Tests: `tests/test_daprs.py`, `tests/test_aprs.py`; insgesamt 323.

### Wichtig beim Update
- Nichts zu tun: APRS bleibt aus. Zum Einschalten: Adminbereich → **📡 APRS** oder `sudo ./scripts/setup.sh` erneut ausführen.
- Für APRS-Apps die Ports TCP 14580 (und 10152) in der Firewall öffnen; für eigene Karten-Domains DNS-Einträge anlegen.

## [1.1.1] – 2026-11-22

- Link-Site-Icons werden um Mitternacht neu geladen; im Admin-Linkmenü gibt es zusätzlich **Refresh site icons now**.
- Der automatische GitHub-Updatecheck läuft zu vollen Stunden (bei Intervallen über einer Stunde an den passenden vollen Stunden).

## [1.1.0] – 2026-11-22

Frei einstellbare Farben mit hellem Profil und Favicons im Link-Menü. Das Farbsystem (**N8 Theme**) ist jetzt in allen
N8-Oberflächen gleich: diesem Dashboard, der [FRN-Weboberfläche](https://github.com/dhartmann1979/adn-frn-server) und dem
[N8-Hotspot](https://github.com/dhartmann1979/N8-HotSpot).

### 🎨 Aussehen (Adminbereich → Appearance)
- **Neues Farbprofil ☀️ Daylight** – hell, für Tageslicht. Alle Bereiche (Live, Statistik, OpenBridge, Talkgroups, Dialoge,
  Adminbereich) haben dafür eine eigene helle Darstellung (`dashboard/static/n8-light.css`).
- **Jede Farbe frei wählbar:** zusätzlich zu Akzent und Hintergrund jetzt *Accent 2* (Verlauf von Knöpfen und Titel),
  die drei Leuchtfarben des Hintergrunds, *Text* und *Card tint*. „from profile“ zeigt, welche Farbe noch aus dem Profil kommt; ↺ setzt sie zurück.
- **Neuer Regler Roundness** (Ecken von Karten und Knöpfen, 0–28 px).
- **Lesbarkeitsprüfung:** warnt, wenn Text auf dem gewählten Hintergrund schlecht lesbar ist (Kontrast unter 4,5 : 1).
- Farbcodes werden auf dem Server geprüft (`dashboard/n8theme.py`); ungültige Werte werden abgelehnt statt gespeichert.
- Neue Einstellungen: `theme.accent2`, `theme.glow1`–`glow3`, `theme.text`, `theme.panel`, `theme.radius`. Bestehende Einstellungen bleiben gültig.

### 🔗 Link-Menü mit Site-Icons
- Web-Links zeigen das **Favicon der verlinkten Seite** statt des Emojis. Das Dashboard holt es beim Start und nach dem Speichern
  der Links, prüft es und speichert es in SQLite (`link_icons`, 30 Tage; fehlende werden stündlich neu versucht).
  Besucher laden das Bild vom Dashboard (`/api/link-icon/…`), nicht von der fremden Seite.
- Neuer Schalter **site icon** je Link (Vorgabe an); für `mailto:`, `/pfad` und `#tab` ausgegraut.
- Sicherheit: nur öffentliche Adressen (Schutz gegen SSRF, auch über Weiterleitungen), max. 256 KB, nur echte Bilder,
  SVG ohne Skripte und externe Verweise, Auslieferung mit strenger Content-Security-Policy.

### Technik
- Neue Dateien: `dashboard/static/n8-theme.js`, `n8-theme.css`, `n8-light.css`, `dashboard/n8theme.py`, `dashboard/siteicons.py`.
- Neue Tests: `tests/test_n8theme.py`, `tests/test_siteicons.py` (Netz gemockt); insgesamt 282.

## [1.0.0] – 2026-11-21

Erste Version mit Versionsnummer. Sie fasst alles zusammen, was diese Ausgabe gegenüber dem
originalen HBlink4 (Stand 4.8.0) mitbringt. Ab hier steht jede Änderung mit eigener Nummer in dieser Datei.

### Neu im Dashboard
- **Live-Ansicht für Desktop und Smartphone:** feste Kopfzeile mit Menü (Live, Statistics, OpenBridge,
  Talkgroups, Configuration). Am Handy ist die Kopfzeile nur noch eine Zeile plus Tabs; Live und DMR sind dort zwei Statuspunkte.
- **Statistik-Kacheln:** Verbindungen, laufende Gespräche, Gespräche und Sprechzeit heute, OpenBridge,
  FreeRadioID. Am Handy als 3×2-Raster statt sechs Zeilen.
- **Last Heard neu gebaut:** kompakte Zeilen statt breiter Tabelle. Am Desktop eine Zeile pro Eintrag,
  Talkgroup-Name direkt hinter der Nummer; am Handy zwei kurze Zeilen, nichts wird abgeschnitten.
  Es stehen die ersten 8 (Handy: 5) Einträge da, **Show all** zeigt alle. Wer gerade spricht, steht immer oben.
- **Stationen als Raster:** Repeater, Hotspots, Apps, Netzwerke, Outbound-Links und OpenBridge stehen als schmale Karten
  nebeneinander; am breiten Bildschirm stehen die Bereiche zusätzlich in zwei Spalten. Die Zeitschlitze sind kurze Zeilen
  (frei: eine Zeile; aktiv: RX/TX, Sprecher, Talkgroup mit Name, Dauer).
- **Stationsinfo zu jeder DMR-ID:** Klick auf einen Sprecher (Last Heard, Zeitschlitze, OpenBridge) öffnet die Daten von
  FreeRadioID.net (Name, Ort, Registrierung, Profil) und das letzte Gespräch auf diesem Server.
- **Gerätearten:** eigene Bereiche für 📶 Repeater, 📱 Hotspots, 📲 Apps (Z3DMR, DroidStar, BlueDV, …) und 🔗 Netzwerke.
  Unbekannte Geräte heißen „❔ Unknown device type“ und zeigen den gemeldeten Paketnamen.
- **OpenBridge-Tab** mit allen Details eines Trunks: Zustand, Gegenstelle, Talkgroups, Verkehr heute bis 30 Tage, Gespräche.
- **Talkgroup-Verzeichnis und Talkgroup-Statistik**, **Configuration-Tab** mit der Anleitung zum Verbinden.
- **Fußzeile** mit © Die N8schicht, Version, Commit und Datum.
- **Datenschutz:** IP-Adressen und Ports von Stationen, Links und Trunks sieht nur, wer als Admin eingeloggt ist –
  der Server entfernt sie vorher.

### Neu im Adminbereich
- **Aufgeräumt in Tabs:** Users, Settings, Appearance, Links, OpenBridge, Import, Sessions, Log, System; gleich große Fenster,
  am Handy als Auswahlliste.
- **Alle Einstellungen in der Datenbank** statt in Dateien, mit Schaltern, Auswahllisten und Hilfetexten; Erweitertes unter *Advanced*.
- **Appearance:** Farbprofile, eigene Farben, Logo und Favicon hochladen (mit Vorschau), Titel und Untertitel, Logo-Größe.
- **Link-Menü** mit eigenen Links, als Menü oder Leiste.
- **OpenBridge-Editor:** Trunks Schritt für Schritt einrichten, Protokoll Classic oder FreeDMR v5, Talkgroups aus der Liste wählen
  oder ohne Filter; fertiger, editierbarer Abschnitt für die `hblink.cfg` der Gegenstelle; Abschnitte aus einer `hblink.cfg`
  lassen sich einfügen.
- **Import:** Konfigurationen von HBlink3, FreeDMR, ADN und HBlink4 übernehmen (Server, Talkgroups, Trunks, Links, Blacklist).
- **Geräteerkennung:** Listen, an denen Repeater, Hotspots, Apps und Netzwerke erkannt werden, im Adminbereich änderbar.
- **Updates:** Der Server fragt jede Stunde bei GitHub nach einer neuen Version. Admins sehen einen Hinweis mit der neuen
  Versionsnummer und diesen Änderungstexten. **⬇️ Update now** installiert mit Passwort-Bestätigung und startet neu –
  nur vorwärts, nur die angezeigte Version, nur vom eingerichteten Git-Remote. Neustart ohne sudo über systemd oder mit
  einer genau begrenzten sudo-Regel.

### Neu im DMR-Server
- **FreeRadioID.net Secure Login:** Stationen melden sich mit ihrem persönlichen FreeRadioID-Passwort an und bekommen volle
  Rechte; das Standard-Passwort ist der Gastzugang mit eigenen Gast-Talkgroups.
- **OpenBridge zu FreeDMR:** FreeDMR-Protokoll v5 (DMRE, Keep-alives, Versionsabgleich, Source Quench, wechselnde Adressen).
- **OpenBridge parallel:** Jede Talkgroup läuft über alle Trunks, deren Filter sie durchlässt, gleichzeitig; beliebig viele
  Trunks ohne Filter. Gespräche können zwischen Trunks weitergereicht werden (schaltbar), mit Echo-Schutz und Hop-Zähler gegen Schleifen.
- **Apps hören OpenBridge:** Gespräche aus OpenBridge gehen mit 55 Bytes an die Stationen; Apps wie Z3DMR haben die
  kürzeren Pakete vorher verworfen.
- **Geräteart „App“** für Handy- und PC-Apps ohne Funkgerät.

### Dokumentation
- Deutsche Anleitungen mit Screenshots: Installation, Dashboard, Adminbereich, Konfiguration, Betrieb, FreeRadioID,
  Schritt-für-Schritt-Anleitungen, Versionen.
- `scripts/e2e_openbridge.py` prüft OpenBridge von Ende zu Ende auf dem eigenen Rechner.
