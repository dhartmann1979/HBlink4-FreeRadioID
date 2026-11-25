# 🩺 Betrieb & Fehlersuche

[← Übersicht](../../readme.md) · [Installation](installation.md) · [Dashboard](dashboard.md) · [Adminbereich](adminbereich.md) · [APRS](aprs.md) · [Anleitungen](anleitungen.md) · [Konfiguration](konfiguration.md) · [FreeRadioID](freeradioid.md) · **Betrieb & Fehlersuche**

---

## Die beiden Dienste

| Dienst | Was | Log |
|---|---|---|
| `hblink4` | DMR-Server (UDP 62031) | `journalctl -u hblink4` und `logs/hblink.log` |
| `hblink4-dash` | Dashboard und Adminbereich (8080, mit HTTPS 80/443) | `journalctl -u hblink4-dash` |

```bash
sudo systemctl status  hblink4 hblink4-dash
sudo systemctl restart hblink4 hblink4-dash
sudo journalctl -u hblink4 -u hblink4-dash -f          # live mitlesen
```

> 💡 **Immer mit `sudo`.** Ohne `sudo` fragt systemd (polkit) nach einem Passwort und wartet. Das sieht dann so aus, als würde der Neustart „hängen“.
> Soll der Dienst-Benutzer die Dienste ohne Passwort neu starten dürfen, hilft eine sudoers-Regel:
>
> ```bash
> echo 'hblink ALL=(root) NOPASSWD: /usr/bin/systemctl restart hblink4, /usr/bin/systemctl restart hblink4-dash, /usr/bin/systemctl restart hblink4 hblink4-dash' \
>   | sudo tee /etc/sudoers.d/hblink4 && sudo chmod 440 /etc/sudoers.d/hblink4 && sudo visudo -c
> ```
> (`hblink` durch deinen Dienst-Benutzer ersetzen.)

Aus dem Browser geht es auch: **Adminbereich → System → Restart dashboard / Restart DMR server**.

**Zum Testen ohne systemd** gibt es `./run_all.sh`. Es startet beides im Vordergrund und beendet es mit Strg+C. Es sollte nur laufen, wenn die Dienste gestoppt sind, und immer als Dienst-Benutzer, nicht als root.

## Schnell-Check: `scripts/check.sh`

```bash
sudo /opt/HBlink4/scripts/check.sh
```

Das Skript prüft der Reihe nach:
- die Dienste und ob sie in einer Neustart-Schleife hängen
- Dateirechte, den Socket `/tmp/hblink4.sock` und die Ports (aus dem Adminbereich bzw. den Config-Dateien)
- ob HBlink4 und das Dashboard als Dienst-Benutzer starten

Zu jedem Problem steht die passende Lösung mit **→** dahinter. Am Ende steht `No problems found.` oder die Zahl der Probleme.

## Typische Fehler

| Meldung / Symptom | Ursache | Lösung |
|---|---|---|
| `attempt to write a readonly database` | Dateien gehören root, weil etwas mit `sudo` gestartet wurde | `sudo chown -R hblink:hblink /opt/HBlink4` und Dienste neu starten |
| Dashboard zeigt **✗ DMR** (gelb) | Socket `/tmp/hblink4.sock` gehört dem falschen Benutzer, oder HBlink4 läuft nicht | `sudo rm -f /tmp/hblink4.sock && sudo systemctl restart hblink4-dash hblink4` |
| `Address already in use` (Port 62031) | Ein anderer DMR-Server (z. B. ADN/FreeDMR-Proxy) belegt den Port | anderen Port im Adminbereich wählen bzw. den anderen Dienst stoppen |
| HTTPS startet nicht | Domain zeigt nicht auf den Server, Port 80 zu oder belegt | Fehler im Log lesen; das Dashboard läuft so lange per HTTP weiter |
| `hblink4-dash` startet in einer Schleife | fehlende Python-Module | `sudo -u hblink ./venv/bin/pip install -r requirements.txt -r requirements-dashboard.txt` |
| Station kommt nicht rein (MSTNAK) | falsches Passwort, ID auf der Blacklist oder FreeRadioID.net nicht erreichbar | `journalctl -u hblink4` zeigt den Grund; zum Test das Gast-Passwort nehmen |
| Keine Avatare | ID nicht bei FreeRadioID.net registriert, Avatare abgeschaltet oder Liste noch nicht geladen | Adminbereich → System zeigt die Zahl der gespeicherten Avatare; **⟳ Refresh now** unter Callsign database |
| OpenBridge verbunden, aber keine Gespräche | Gegenstelle ist FreeDMR mit `ENHANCED_OBP`/`PROTO_VER` > 1, der Trunk läuft aber klassisch; im Log steht dann „is not classic OBP“ | beim Trunk `"enhanced_obp": true`, `"proto_ver": 5`, `"relax_checks": true` setzen, HBlink4 neu starten ([Konfiguration](konfiguration.md#openbridge-zu-einem-freedmr-server)) |
| OpenBridge bleibt auf **WAITING** | keine Keep-alives der Gegenstelle: Port zu, Ports vertauscht oder falsche Adresse | `sudo ufw allow 51084/udp`, Router-Weiterleitung prüfen; `PORT`/`TARGET_PORT` der Gegenstelle müssen zu `target_port`/`local_port` passen |
| `failed authentication – passphrase on both sides identical?` | Passwort verschieden (FreeDMR nutzt höchstens 20 Zeichen) | auf beiden Seiten dasselbe Passwort mit höchstens 20 Zeichen eintragen |
| App (Z3DMR, DroidStar) hört über OpenBridge nichts, Hotspots schon | ältere Version: Gespräche aus OpenBridge gingen mit 53 statt 55 Bytes an die Stationen; Apps verwerfen solche Pakete | aktualisieren (**⬇️ Update now**); seit dieser Version werden die Pakete auf 55 Bytes ergänzt |
| Eine Talkgroup läuft nur über einen der Trunks | ältere Version: eine Talkgroup in der Liste eines Trunks „gehörte“ nur diesem Trunk; Gespräche dieser Talkgroup von anderen Trunks wurden verworfen | aktualisieren; jetzt führen alle Trunks die Talkgroup parallel ([Adminbereich → Wohin ein Gespräch geht](adminbereich.md#wohin-ein-gespräch-geht)) |
| `own stream … came back – dropped` | zwei Trunks führen in Netze, die selbst verbunden sind; unser Gespräch kam über den anderen Trunk zurück | kein Fehler: der Echo-Schutz hat gegriffen |
| `frame is … s off our clock` | Uhrzeit eines Servers falsch | NTP einrichten: `sudo apt install chrony` |
| APRS-Karte leer, `APRS server not started` | APRS aus oder keine Server-ID | Adminbereich → 📡 APRS → Server; mehr in [APRS → Fehlersuche](aprs.md#fehlersuche) |
| `APRS port 14580 not available` | ein anderer APRS-Server (z. B. aprsc) belegt den Port | anderen Dienst stoppen oder anderen Port wählen |
| Karten-Domain ohne Zertifikat (`… is left out of the certificate`) | DNS der Domain zeigt nicht auf den Server | DNS korrigieren, Dashboard neu starten |
| Superadmin-Passwort vergessen | – | neuen Hash erzeugen (`./venv/bin/python -m dashboard.auth hash-password`), in `dashboard/config.json` eintragen, Dashboard neu starten; oder `sudo ./scripts/setup.sh` |

## Aktualisieren

Der Server fragt jede Stunde bei GitHub nach einer neuen Version. Eingeloggte Admins sehen dann einen Hinweis und können mit **⬇️ Update now** direkt im Browser installieren (siehe [Adminbereich → Update now](adminbereich.md#️-update-now)). Auf der Konsole geht es (ab 1.10.0) mit einem Befehl:

```bash
sudo /opt/HBlink4/scripts/update.sh            # holen, Pakete bei Bedarf, Rechte prüfen, beide Dienste neu starten
sudo /opt/HBlink4/scripts/update.sh --check    # nur prüfen: {"current", "latest", "behind", "notes"}
```

`update.sh` spult nur vor (fast-forward) – nie über von Hand geänderte Dateien oder eigene Commits –, installiert Python-Pakete nur bei
geänderten `requirements*`, setzt Besitzer (Dienst-Benutzer) und Rechte neu, startet `hblink4` und `hblink4-dash` neu und schaltet den
**N8 update guard** scharf: Kommt das Dashboard nach drei Starts nicht hoch, geht es automatisch auf den alten Stand zurück.
Dasselbe Skript nutzt das **HobbyRadioPortal** unter *Admin → System → 🧩 Dienste* (auch *Alle aktualisieren*).

Vorher eine [Sicherung](#sicherung) zu machen schadet nie. Die Einstellungen aus dem Adminbereich liegen in der Datenbank und bleiben erhalten. Welche Version läuft, steht unten in der Fußzeile jeder Seite und im Adminbereich unter **🖥️ System**.

**Zurück zur vorherigen Version:** Im **📜 Log** steht bei jedem Update `alt → neu`. Mit dem alten Commit:

```bash
cd /opt/HBlink4
sudo -u hblink git reset --hard <alter-commit>
sudo systemctl restart hblink4 hblink4-dash
```

### Neustart nach dem Update und sudoers

Für **Update now** gibt es zwei Wege, die Dienste neu zu starten. Das Dashboard nimmt automatisch den, der funktioniert; unter **🖥️ System → Restart after update** steht, welcher es ist.

**Weg A – ohne sudo (empfohlen, nichts einzurichten):** Die mitgelieferten Dienste haben `Restart=always`. Nach dem Update beenden sich HBlink4 und das Dashboard selbst, und systemd startet sie nach 10 Sekunden wieder. Dafür braucht das Dashboard keinerlei Root-Rechte, und die Härtung der Dienste (`NoNewPrivileges=true`, `CapabilityBoundingSet=`) bleibt an. Einzige Bedingung: HBlink4 muss in dem Moment mit dem Dashboard verbunden sein (in der Statusleiste hat **DMR server** einen grünen Punkt), sonst startet nur das Dashboard neu; der Dialog sagt das dann.

**Weg B – `systemctl` über sudo:** Wer lieber ein echtes `systemctl restart` will (z. B. weil `Restart=always` geändert wurde), erlaubt dem Dienst-Benutzer genau **einen** Befehl ohne Passwort. Im Beispiel heißt der Benutzer `hblink`; nimm den aus `User=` in `/etc/systemd/system/hblink4-dash.service`.

1. Regel anlegen – immer mit `visudo`, das prüft die Syntax vor dem Speichern (ein Tippfehler in sudoers kann sonst sudo komplett sperren):

   ```bash
   sudo visudo -f /etc/sudoers.d/hblink4-update
   ```

   Inhalt (genau so, eine Zeile pro Eintrag):

   ```
   # HBlink4 "Update now": darf genau diese beiden Dienste neu starten – sonst nichts
   Cmnd_Alias HBLINK4_RESTART = /usr/bin/systemctl --no-block restart hblink4.service hblink4-dash.service
   hblink ALL=(root) NOPASSWD: HBLINK4_RESTART
   ```

2. Rechte und Syntax prüfen:

   ```bash
   sudo chmod 0440 /etc/sudoers.d/hblink4-update
   sudo visudo -c
   ```

3. Testen, ob die Regel greift (zeigt den Befehl, startet nichts neu):

   ```bash
   sudo -u hblink sudo -n -l /usr/bin/systemctl --no-block restart hblink4.service hblink4-dash.service
   ```

4. Die Härtung des **Dashboard-Dienstes** lässt sudo nicht zu (`NoNewPrivileges` verbietet jedes Hochstufen der Rechte). Für Weg B muss sie für diesen einen Dienst gelockert werden:

   ```bash
   sudo systemctl edit hblink4-dash
   ```

   ```ini
   [Service]
   NoNewPrivileges=no
   CapabilityBoundingSet=~
   AmbientCapabilities=CAP_NET_BIND_SERVICE
   ```

   Danach `sudo systemctl restart hblink4-dash`. Unter **🖥️ System** steht jetzt *systemctl via sudo*.

Warum das so eng ist:
- Die Regel erlaubt **nur diesen exakten Befehl** mit genau diesen Argumenten. `systemctl stop`, andere Dienste, `systemctl edit` oder eine Shell bleiben verboten. sudo vergleicht die ganze Befehlszeile, deshalb **keine** Platzhalter wie `*` in die Regel schreiben.
- Immer den vollen Pfad `/usr/bin/systemctl` angeben. Liegt `systemctl` bei dir woanders (`command -v systemctl`), passt die Regel nicht; dann nimmt das Dashboard automatisch Weg A.
- Den Dienst-Benutzer **nie** in die Gruppe `sudo` aufnehmen und **kein** `NOPASSWD: ALL` eintragen. Dann könnte jeder, der das Dashboard übernimmt, den ganzen Server übernehmen.
- Weg B lockert die Härtung des Dashboards. Wer nicht ausdrücklich `systemctl` braucht, bleibt bei Weg A.

**Regel wieder entfernen:** `sudo rm /etc/sudoers.d/hblink4-update` und `sudo systemctl revert hblink4-dash`.

### Schutz gegen Angriffe von außen

- **Wer überhaupt drankommt:** Update now ist nur nach Login und nur für die eingestellte Rolle erreichbar (Standard: Superadmin), und auch dann nur mit erneuter Passworteingabe. Fehlversuche werden wie beim Login gebremst und protokolliert.
- **Schutz vor fremden Seiten:** Anfragen anderer Seiten (CSRF) blockt das Dashboard, weil jede Änderung einen eigenen Kopf-Eintrag braucht und das Login-Cookie `SameSite=Strict` ist.
- **Woher der Code kommt:** Installiert wird nur aus dem Git-Remote, das auf dem Server eingerichtet ist, und nur der Commit, den GitHub gemeldet hat. Es geht nur vorwärts; Hooks und lokale Transporte sind aus. Zum Prüfen: `git -C /opt/HBlink4 remote -v`.
- **Rechte:** Das Dashboard läuft als normaler Benutzer ohne Root. Mit Weg B darf es höchstens die beiden Dienste neu starten.
- **Abschalten:** Wer Updates nur auf der Konsole will, stellt *Who may press “Update now”* auf **Nobody**. Der Hinweis bleibt, installiert wird dann nur von Hand.

## Im HobbyRadioPortal

Das [HobbyRadioPortal](https://github.com/dhartmann1979/HobbyRadioPortal) zeigt DMR und APRS als Plugins (`dmr`, `aprs`).
Es liest dafür nur die öffentlichen Schnittstellen dieses Dashboards: `/api/version`, `/api/repeaters`, `/api/streams`,
`/api/stats`, `/api/openbridge`, `/api/outbounds`, **`/api/last-heard`** (seit 1.6.2: dieselbe Liste wie *Last Heard* im
Dashboard, IP-Adressen nur für Admins), `/api/aprs/status` und `/api/aprs/stations`. Im Portal unter
*Admin → Dienste & Plugins* die Adresse eintragen (meist `http://127.0.0.1:8080/`).

**APRS und DAPRS im Portal verwalten:** Läuft das Portal auf demselben Rechner, stellt es – **ohne Token** (seit 1.11.0) – unter
*Admin → Dienste → APRS* alles ein, was hier im Tab *📡 APRS* steht – APRS-Server, Uplink & Downlink, DAPRS (beide
Seiten: Erkennen im DMR-Server und Weitergabe an APRS), Repeater-Objekte, Karte, APRS-Domains – und zeigt die verbundenen Clients
(trennen), Neustart, Objekte senden und den Passcode-Rechner. Das Portal nutzt dafür `/api/admin/settings` (nur die APRS-Bereiche)
und `/api/admin/aprs…`. Was das Portal darf: [Sicherheit → HobbyRadioPortal](sicherheit.md#hobbyradioportal-auf-diesem-server-ohne-token).

## Sicherung

Alles Wichtige steckt in drei Dateien:

```bash
cd /opt/HBlink4
sudo -u hblink sqlite3 dashboard/data/dashboard.db ".backup '/tmp/dashboard-$(date +%F).db'"
sudo tar czf ~/hblink4-backup-$(date +%F).tgz config/config.json dashboard/config.json /tmp/dashboard-$(date +%F).db
```

Mit APRS kommt `dashboard/data/aprs.db` dazu (Stationen, Spuren, Rohpakete; höchstens 90 Tage): genauso mit `.backup` sichern, oder weglassen – sie füllt sich von selbst wieder.

`.backup` sichert die Datenbank auch im laufenden Betrieb sauber; dafür braucht es das Paket `sqlite3`. **Zurückspielen:** Dienste stoppen, die drei Dateien an ihren Platz kopieren, die Rechte für den Dienst-Benutzer setzen und die Dienste starten.

## Umziehen auf einen neuen Server

1. Auf dem neuen Server [installieren](installation.md) mit `setup.sh`.
2. Dienste stoppen und die drei Dateien aus der Sicherung einspielen.
3. `sudo chown -R hblink:hblink /opt/HBlink4 && sudo systemctl start hblink4 hblink4-dash`.
4. Den DNS-Eintrag umstellen. Das HTTPS-Zertifikat holt das Dashboard auf dem neuen Server selbst.

---

[← Zurück zur Übersicht](../../readme.md)
