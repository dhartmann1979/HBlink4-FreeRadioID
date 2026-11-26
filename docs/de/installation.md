# 📦 Installation

[← Übersicht](../../readme.md) · **Installation** · [Dashboard](dashboard.md) · [Adminbereich](adminbereich.md) · [APRS](aprs.md) · [Anleitungen](anleitungen.md) · [Konfiguration](konfiguration.md) · [FreeRadioID](freeradioid.md) · [Betrieb & Fehlersuche](betrieb.md)

---

## Voraussetzungen

| | |
|---|---|
| **System** | Debian 12/13 oder Ubuntu 22.04+ (auch Raspberry Pi OS), 1 CPU, 512 MB RAM reichen |
| **Python** | 3.9 oder neuer; das Skript installiert alles Nötige |
| **Netzwerk** | **UDP 62031** für Repeater und Hotspots, **TCP 8080** für das Dashboard; mit HTTPS stattdessen **TCP 80 und 443** |
| **HTTPS (optional)** | ein DNS-Name, der auf den Server zeigt, z. B. `dmr.die-n8schicht.de` |
| **Rechte** | root bzw. `sudo` für die Installation; HBlink4 und das Dashboard laufen danach als normaler Benutzer |

> ⚠️ **Nur ein DMR-Server pro Port.** Läuft auf dem Server schon ein anderer DMR-Server, zum Beispiel ADN/FreeDMR mit seinem Proxy auf 62031, braucht HBlink4 einen anderen Port.

## Geführte Installation

```bash
git clone https://github.com/dhartmann1979/HBlink4-FreeRadioID /opt/HBlink4
sudo /opt/HBlink4/scripts/setup.sh
```

Am Anfang wählst du **Neu einrichten** oder **Backup wiederherstellen**. Mit Enter bleibt
**Neu einrichten** ausgewählt; anschließend folgen die bisherigen zehn Schritte.
Jede Frage zeigt eine Vorgabe in `[Klammern]`; mit **Enter** übernimmst du sie.

### Vorhandenes Backup beim Initial Setup einspielen

Ein mit der vollständigen HBlink4-Backup-Funktion erstelltes Archiv lässt sich direkt beim Einrichten übernehmen. Ein vorheriger
Dashboard-Login oder das Anlegen neuer DMR-, APRS- und Superadmin-Einstellungen entfällt.

1. Dieses Repository auf dem Zielserver unter einem rootgeschützten Verzeichnis bereitstellen,
   beispielsweise `/opt/HBlink4`. Die `.tar.gz`-Sicherung außerhalb dieses Verzeichnisses ablegen,
   beispielsweise `/home/sa7bnt/HBlink4-Backup.tar.gz`. Verschlüsselte AutoBackups
   (`.tar.gz.age`) werden ebenfalls unterstützt; das Setup fragt nach dem lokalen
   Pfad zum separaten Wiederherstellungsschlüssel (`.agekey`).
2. `sudo /opt/HBlink4/scripts/setup.sh` starten und **Vorhandenes HBlink4-Backup wiederherstellen?**
   mit `j` beantworten. Den vollständigen Pfad zur Sicherung eingeben.
3. Das Setup installiert bei Bedarf die Grundpakete und prüft anschließend das ganze Archiv:
   Dateipfade, Prüfsummen, Datenbanken, Größenlimits und Python-Metadaten. Quelle und Ziel benötigen
   Python ab 3.9; unterschiedliche Unterversionen werden unterstützt, sofern Code und gespeicherte
   Anwendungspakete kompatibel sind. Bei einer frischen Installation das Dienstkonto auswählen.
4. Datum, Version, Zielverzeichnis und Quellkonto in der Vorschau prüfen. Erst **RESTORE** bestätigt
   die Änderungen an der Zielinstallation. Enter bricht ab. Bis hier werden weder Konfigurationen
   und Daten ersetzt noch Dienste umgestellt; eventuell angeforderte Grundpakete können bereits installiert sein.
5. Das Setup bereitet auf einem frischen Ziel die Python-Umgebung und zunächst gestoppte Dienste vor,
   installiert den Wiederherstellungshelfer und wartet auf dessen Ergebnis. Bei abweichendem Python
   prüft der Helfer Code und gespeicherte Anwendungspakete vor dem Stoppen oder Ersetzen vorhandener Dienste.
   Installationswerkzeuge wie pip werden für die Ziel-Python-Version vorbereitet. Nach Erfolg laufen beide Dienste
   mit den Einstellungen und Konten aus dem Backup und sind für den Systemstart aktiviert.

Bereits eingerichtete Dienste im selben Installationsverzeichnis behalten ihr Dienstkonto und
ihre systemd-Konfiguration. Vor dem Ersetzen entsteht ein automatisches Ziel-Backup. Bei Fehlern
wird die vorhandene Installation wiederhergestellt und gestartet; auf einem frischen Ziel bleibt
die zurückgespielte Bootstrap-Installation gestoppt und deaktiviert. Das Setup kann danach erneut
mit der Backup-Auswahl gestartet werden.

Der unabhängige Dienst läuft auch nach einem SSH-Abbruch weiter. Der Status ist über
`sudo systemctl status hblink4-restore.service` und `sudo journalctl -u hblink4-restore.service`
abrufbar. Firewall und DNS werden im Wiederherstellungsmodus nicht automatisch umgestellt.
Wenn das Backup automatisches HTTPS nutzt, wird `certbot` bei Bedarf installiert;
mit `SKIP_APT=1` muss es bereits vorhanden sein. `SKIP_SERVICES=1` ist in diesem Modus nicht möglich.

Die Wiederherstellung übernimmt auch den Programmstand des Backups. Nach dem Einspielen eines
älteren Stands kann daher eine erneute Installation des Diensthelfers nötig sein; das Setup weist
darauf hin. Die vollständigen Voraussetzungen stehen unter [Backup und Klonen](backup.md).

### Neu einrichten

<p align="center"><img src="../images/setup-1.png" alt="setup.sh – Schritte 1 bis 5" width="80%"></p>

| Schritt | Was passiert | Worauf achten |
|---|---|---|
| 1 Systempakete | installiert `python3`, `python3-venv`, `pip`, `git`, `iproute2` | – |
| 2 Dienst-Benutzer | Benutzer, unter dem die Dienste laufen; legt ihn bei Bedarf an (Vorgabe `hblink` bzw. der Besitzer des Verzeichnisses) | Auf einem Server mit ADN/FreeDMR kannst du dessen Benutzer nehmen, z. B. `adn`. |
| 3 Python-Umgebung | legt `venv/` an und installiert die Module | dauert etwa eine Minute |
| 4 DMR-Server | Name des Servers, DMR-Port, Talkgroups für Zeitschlitz 1 und 2 | `all` = alle Talkgroups, `none` = keine |
| 5 Zugang | FreeRadioID Secure Login an/aus, Standard-Passwort, Gast-Talkgroups | Mit FreeRadioID ist das Standard-Passwort der **Gastzugang**. |
| 6 Dashboard | Titel, Beschreibung, Web-Port, öffentlich ja/nein, **Superadmin** mit Passwort | Das Passwort wird nur als Hash gespeichert. |
| 7 HTTPS | Domain und E-Mail für Let's Encrypt; installiert certbot | nur, wenn die Domain schon auf den Server zeigt |
| 8 APRS | APRS ein/aus (Vorgabe: **aus**), Server-ID, bis zu drei Karten-Domains, APRS-Ports öffnen, Uplink & Downlink: keiner, APRS-IS, CB-APRS oder manuell | siehe [APRS](aprs.md); alles lässt sich später im Adminbereich ändern |
| 9 Zusammenfassung | zeigt alles an und fragt nach der Bestätigung | Erst danach wird etwas geändert. Alte Configs werden als `*.bak` gesichert. |
| 10 Abschluss | Firewall (ufw, mit APRS-Ports TCP 14580/10152), Rechte, systemd-Dienste, Start, `check.sh` | – |

<p align="center"><img src="../images/setup-2.png" alt="setup.sh – Schritte 6 bis 9" width="80%"></p>

Danach öffnest du das Dashboard (`http://dein-server:8080` bzw. `https://deine-domain`) und meldest dich oben rechts mit **🔐 Anmelden** als Superadmin an. Alles Weitere stellst du im [Adminbereich](adminbereich.md) ein.

### Das Skript erneut ausführen

`setup.sh` kann jederzeit erneut laufen. Auf einer bestehenden Installation zeigt es die **aktuellen** Werte als Vorgabe, auch die, die inzwischen im Adminbereich geändert wurden. Beim Superadmin-Passwort lässt Enter das bisherige Passwort stehen.

Optionen per Umgebungsvariable:

| Variable | Wirkung |
|---|---|
| `SKIP_APT=1` | keine Systempakete installieren |
| `SKIP_SERVICES=1` | keine systemd-Dienste einrichten (dann `run_all.sh` zum Testen) |
| `SKIP_FIREWALL=1` | Firewall nicht anfassen |
| `HB4_ANSWERS=/pfad/answers.json` | **ohne Rückfragen neu einrichten** (ab 1.9.0) – Antworten als JSON, siehe unten |

### Ohne Rückfragen (`HB4_ANSWERS`)

Für Skripte und automatische Installationen. Alle Schlüssel sind optional – was fehlt, nimmt die Vorgabe
(bzw. den aktuellen Wert); nur `admin_password` braucht eine Neuinstallation:

```bash
cat > /root/hb4.json <<'JSON'
{"server_name": "dmr.example.org", "dmr_port": 62031, "frid": true, "passphrase": "Gast-Passwort", "guest_tgs": "9, 262",
 "dashboard_title": "DMR Die N8schicht", "server_description": "", "web_port": 8080, "public": true,
 "admin_user": "sysop", "admin_password": "mindestens-8-Zeichen", "https": false,
 "aprs": true, "aprs_id": "DB0ABC-10", "aprs_domains": "aprs.example.org", "aprs_ports": true, "aprs_uplink": 1}
JSON
chmod 600 /root/hb4.json
sudo HB4_ANSWERS=/root/hb4.json ./scripts/setup.sh
rm /root/hb4.json
```

Weitere Schlüssel: `svc_user` (Dienst-Benutzer, Vorgabe `hblink`), `ts1`, `ts2`, `domain`, `email`, `aprs_cb_login`. Das Passwort wird
sofort als scrypt-Hash gespeichert. Ablauf und Prüfung am Ende sind dieselben wie mit Fragen.

## Was das Skript anlegt

| Datei / Ort | Inhalt |
|---|---|
| `config/config.json` | DMR-Server: nur das Nötigste für den ersten Start, siehe [Konfiguration](konfiguration.md) |
| `dashboard/config.json` | Dashboard: Superadmin, Web-Adresse, Verbindung zu HBlink4 |
| `dashboard/data/dashboard.db` | **SQLite: alle Einstellungen**, Benutzer, Sitzungen, Protokoll, Avatare |
| `/etc/systemd/system/hblink4.service`, `hblink4-dash.service` | die beiden Dienste, Start beim Booten |
| `venv/` | Python-Umgebung |

## HTTPS mit Let's Encrypt

Am einfachsten richtest du HTTPS gleich in Schritt 7 des Skripts ein. Später geht es im Adminbereich unter **Settings → 🔒 HTTPS & web**, danach startest du das Dashboard neu (Knopf im Adminbereich).

- **Port 80** beantwortet die Let's-Encrypt-Prüfung und leitet auf HTTPS um.
- **Port 8080** leitet ebenfalls um.
- **Erneuerung:** Das Zertifikat wird automatisch erneuert und ohne Neustart geladen.
- **Ohne root:** certbot läuft als Dienst-Benutzer und speichert alles in `dashboard/data/letsencrypt/`.
- **APRS-Domains:** Karten-Domains aus **📡 APRS → Domains** kommen als zusätzliche Namen ins selbe Zertifikat, sobald sie per DNS auf den Server zeigen ([APRS → Eigene Domains](aprs.md#eigene-domains-mit-lets-encrypt)).
- **Wenn es nicht klappt:** Das Dashboard bleibt per HTTP erreichbar, und der Grund steht im Log (`journalctl -u hblink4-dash`).

## Aktualisieren

```bash
sudo /opt/HBlink4/scripts/update.sh           # ab 1.10.0 – siehe Betrieb → Aktualisieren
sudo /opt/HBlink4/scripts/check.sh
```

Ältere Stände (vor 1.10.0) einmal von Hand: `cd /opt/HBlink4 && sudo -u hblink git pull --ff-only`, danach gibt es `scripts/update.sh`.

`git pull` ändert weder die Config-Dateien noch die Datenbank. Neue Einstellungen erscheinen nach dem Neustart im Adminbereich mit ihrer Vorgabe.

## Ohne das Skript (Handarbeit)

Wer jeden Schritt selbst machen will, geht so vor:

```bash
cd /opt/HBlink4
python3 -m venv venv
./venv/bin/pip install -r requirements.txt -r requirements-dashboard.txt
cp config/config_sample.json config/config.json
cp dashboard/config_sample.json dashboard/config.json
./venv/bin/python -m dashboard.auth hash-password      # Hash für den Superadmin
nano dashboard/config.json                              # auth.superadmin eintragen
sudo chown -R hblink:hblink /opt/HBlink4
sudo ./scripts/install_services.sh
```

Was in den beiden Dateien steht, erklärt [Konfiguration](konfiguration.md).

---

Weiter: [🎙️ Dashboard](dashboard.md)
