# 🔐 Sicherheit & N8 Kit

[← Übersicht](../../readme.md)

Diese Seite beschreibt, wie das Dashboard sich schützt, was du als Betreiber noch tun kannst (Reverse-Proxy), und das **N8 Kit** – die gemeinsamen Bausteine, die HBlink4-FreeRadioID, adn-frn-server, N8-HotSpot und N8 Crosslink gleich aussehen und sich gleich verhalten lassen.

## Was das Dashboard selbst tut

### Keine offene API-Beschreibung

FastAPI legt normalerweise unter `/docs`, `/redoc` und `/openapi.json` eine vollständige Beschreibung aller Routen an – mit allen Admin-Endpunkten und ihren Datenformaten. Das ist **abgeschaltet**; die drei Adressen antworten mit 404.

Zum Entwickeln lässt sie sich einschalten, nur mit einer Umgebungsvariablen beim Start:

```bash
N8_API_DOCS=1 ./venv/bin/python dashboard/server.py
```

### Sicherheits-Header bei jeder Antwort

| Header | Wert | Wofür |
|---|---|---|
| `Content-Security-Policy` | `default-src 'self'`; Skripte, Styles, Schriften nur vom eigenen Server; Bilder auch `https:` (Kartenkacheln, Avatare); Verbindungen nur zum eigenen Server (`ws:`/`wss:` für Live-Daten); `object-src 'none'`, `base-uri 'self'`, `form-action 'self'`, `frame-ancestors 'self'` | fremde Skripte, Plugins, `<base>`-Tricks, fremde Formularziele und Einbetten in fremde Seiten werden vom Browser blockiert |
| `Strict-Transport-Security` | `max-age=31536000` | nur wenn die Seite über **HTTPS** kommt (direkt oder über einen Proxy mit `X-Forwarded-Proto: https`); verhindert SSL-Stripping |
| `Permissions-Policy` | Kamera, Mikrofon, Zahlung, USB, Seriell, Sensoren aus; Standort nur für die eigene Seite | Seiten können diese Geräte nicht ansprechen |
| `X-Content-Type-Options` | `nosniff` | Dateien werden nur als das ausgeführt, was sie sind |
| `X-Frame-Options` | `SAMEORIGIN` | kein Einbetten in fremde Seiten (Clickjacking) |
| `Referrer-Policy` | `same-origin` | Adressen des Dashboards gehen nicht an fremde Seiten |
| `Cross-Origin-Opener-Policy` / `-Resource-Policy` | `same-origin` / `same-site` | Fenster und Dateien sind von fremden Seiten getrennt |

Der Header `server: uvicorn` wird **nicht** mehr gesendet.

`'unsafe-inline'` ist für Skripte noch erlaubt, weil die Seiten Klick-Handler direkt im HTML haben. Deshalb ist das Escapen (nächster Abschnitt) die eigentliche Schutzschicht gegen XSS; die CSP sorgt dafür, dass ein Angreifer keine **fremden** Skripte nachladen und keine Daten an fremde Server schicken kann.

### Daten aus dem Funkverkehr

Rufzeichen, Standort, Beschreibung, Software und Paketname schickt jedes Gerät beim Anmelden selbst (RPTC) – das sind fremde Eingaben. Dazu kommen Talker Alias, APRS-Kommentare und Namen aus Rufzeichenlisten.

- **Beim Empfang** entfernt HBlink4 aus den RPTC-Textfeldern alle HTML-Zeichen `< > " ' `` ` und Steuerzeichen (`&` nur außerhalb der URL). Die Länge der Felder bleibt gleich.
- **Beim Anzeigen** geht jedes dynamische Feld durch `escapeHtml` (bzw. `esc` auf der APRS-Karte) oder wird als `textContent` gesetzt. Geprüft wurden alle Render-Funktionen: Last Heard, ON AIR, Repeater-/Hotspot-Karten, Slots, OpenBridge, Outbound, Ereignisliste, Statistik, Talker Alias, Configuration-Tab, APRS-Karte. 1.5.0 hat dabei ungeescapte Stellen geschlossen (Rufzeichen und Standort der Repeater-Karte, Rufzeichen im Slot, Ereignisliste, Status und Namen der Outbound-Links, OpenBridge-Status, Tooltips übersetzter TGs).
- Hochgeladene Bilder werden am Inhalt erkannt; SVG mit Skript wird abgelehnt.

### Backups (Admin → 💾 Backup)

Backup, Wiederherstellung und AutoBackup ([Backup](backup.md), [AutoBackup](autobackup.md)) sind dem **Superadmin** vorbehalten und laufen ganz über den eigenen Server – die Content-Security-Policy bleibt unverändert. Wiederherstellungsschlüssel und Zugangsdaten werden nur über HTTPS oder einen lokalen SSH-Tunnel angenommen. Update und Backup/Wiederherstellung schließen sich gegenseitig aus; der Zustand des Update-Guards (`update.pending`, `update.result`) kommt nie ins Archiv, damit ein Klon keine fremde Update-Prüfung übernimmt.

### Anmeldung

Sitzungs-Cookie `HttpOnly`, `SameSite=Strict`, über HTTPS `Secure`; jede schreibende Anfrage braucht den Header `X-Dashboard` (CSRF-Schutz); fünf Fehlversuche sperren 15 Minuten. IP-Adressen sehen nur Admins.

## HobbyRadioPortal auf diesem Server (ohne Token)

Das [HobbyRadioPortal](https://github.com/dhartmann1979/HobbyRadioPortal) verwaltet die APRS- und DAPRS-Einstellungen dieses
Dashboards. Seit 1.11.0 gibt es dafür **keine API-Tokens** mehr (die Tabelle `api_tokens` wird beim Start gelöscht). Als Portal gilt
nur ein **direkter Aufruf auf diesem Rechner**:

- Absender **und** `Host` sind Loopback (`127.0.0.1`, `::1`, `localhost`), Kopfzeile `X-HobbyRadioPortal: 1`,
- **keine** Proxy-Kopfzeile (`X-Forwarded-For`, `X-Real-IP`, `Forwarded`, `X-Forwarded-Host/-Proto`, `Via`, `CF-Connecting-IP`,
  `True-Client-IP`, `X-Client-IP`). Anfragen über nginx/Caddy (die auch von 127.0.0.1 kommen) und von anderen Rechnern sind nie
  „das Portal“ – **ein eigener Reverse-Proxy muss `X-Forwarded-For` setzen** (siehe unten, die Vorlage tut das).

Was das Portal darf:

- Rolle **Admin**, nie Superadmin; **nur** alle öffentlichen `/api/`-Daten, `/api/admin/settings` (lesen, ändern, zurücksetzen),
  `/api/admin/aprs…` (Status, Clients trennen, Neustart, Objekte, Passcode) und `/api/admin/audit`.
- **Nie**: Benutzer, Sitzungen, Backups, Anmeldung/Passwort, Updates, Neustarts – und die Einstellungen *Dashboard access*,
  *HTTPS & web* und *Updates* sind gesperrt.
- Der CSRF-Schutz (`X-Dashboard: 1`) gilt auch für das Portal.
- Jede Änderung steht im Protokoll als `portal (<Portal-Benutzer>)`.
- Jedes Programm auf diesem Rechner könnte sich als Portal ausgeben. Wer das nicht will: `HB4_PORTAL_LOCAL=0` in der Umgebung des
  Dashboard-Dienstes (dann zeigt das Portal nur Live-Daten).

## Reverse-Proxy davor (empfohlen)

Das Dashboard kann HTTPS mit Let's Encrypt selbst. Läuft auf dem Server ohnehin ein Webserver, ist ein **Reverse-Proxy** davor die sauberste Lösung: Zertifikate, Header und Protokolle an einer Stelle. Das Dashboard lauscht dann nur lokal (Adminbereich → Settings → HTTPS & web: HTTPS **aus**, Listen address `127.0.0.1`).

**Caddy** (holt das Zertifikat selbst):

```caddy
dmr.example.org {
    encode zstd gzip
    header {
        Strict-Transport-Security "max-age=31536000"
        -Server
    }
    reverse_proxy 127.0.0.1:8080
}
```

**nginx**:

```nginx
server {
    listen 443 ssl http2;
    server_name dmr.example.org;
    ssl_certificate     /etc/letsencrypt/live/dmr.example.org/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/dmr.example.org/privkey.pem;
    server_tokens off;
    add_header Strict-Transport-Security "max-age=31536000" always;

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;          # Live-Daten (WebSocket)
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;      # damit das Dashboard HSTS setzt
        proxy_read_timeout 1h;
    }
}
server { listen 80; server_name dmr.example.org; return 301 https://$host$request_uri; }
```

Die übrigen Sicherheits-Header setzt das Dashboard selbst; der Proxy muss sie nur durchreichen (beide Beispiele tun das). Die DMR-Ports (UDP 62031, OpenBridge) und die APRS-Ports laufen **nicht** über den Proxy.

## N8 Kit

Gemeinsame Bausteine für **HBlink4-FreeRadioID, adn-frn-server, N8-HotSpot und N8 Crosslink**. Die Dateien sind in allen vier Repositories **identisch**; wer eine ändert, kopiert sie in die anderen.

| Datei | Inhalt |
|---|---|
| `dashboard/static/n8-kit.js` | Sprache DE/EN, Übersetzung, Sprachumschalter, Update-Hinweis, Updates-Kachel, Update-Fortschritt |
| `dashboard/static/n8-kit.css` | Aussehen dieser Bausteine, auf Basis der N8-Theme-2-Farben |
| `dashboard/n8_security.py` | Sicherheits-Header, API-Doku aus, kein `server`-Header |
| `dashboard/n8_update_guard.py` + `scripts/n8-update-guard.sh` | Prüfung nach dem Update und automatisches Zurücksetzen |
| `dashboard/static/i18n-dashboard.js` | die deutschen Texte dieses Dashboards (eigene Datei je Projekt) |

### Sprache DE | EN

<p align="center"><img src="../images/header-english.png" alt="Dashboard auf Englisch" width="95%"></p>

- Der Umschalter steht in der Kopfzeile neben 🔗 Links und dem Login, auch ohne Anmeldung.
- **Standard ist Deutsch.** Die Wahl gilt **sofort**, ohne Neuladen, und wird im Cookie `n8_lang` gespeichert. Cookies gelten für alle Ports eines Servers – wer also auf `dmr.example.org` Englisch wählt, sieht auch die APRS-Karte und die anderen N8schicht-Oberflächen auf diesem Server auf Englisch.
- Für einen Link in einer bestimmten Sprache: `?lang=en` oder `?lang=de` an die Adresse hängen.
- Übersetzt wird die fertige Seite: Texte und die Attribute `title`, `placeholder`, `aria-label`, `alt`. Neue Inhalte (Live-Daten, Fenster) werden übersetzt, sobald sie erscheinen; auch Rückfragen (`confirm`) folgen der Sprache. Rufzeichen, Talkgroup-Namen, Talker Alias und Code bleiben, wie sie sind.
- Fehlt ein Wort, erscheint das Original. Ergänzen: in `i18n-dashboard.js` eine Zeile `'English text': 'Deutscher Text',` – ohne führende Emojis und ohne Satzzeichen am Ende, Zahlen über die `rules` am Ende der Datei.

### Updates – überall gleich

| | |
|---|---|
| Prüfen | jede volle Stunde, auch ohne Anmeldung; installiert wird nur auf Knopfdruck |
| Hinweis | unter der Statusleiste, nur für Admins: *Update verfügbar: alt → neu* · Was ist neu? · Jetzt aktualisieren · Details · Später (ein Tag) |
| Installieren | Fenster mit Neuerungen und (hier) Passwortabfrage, dann drei Schritte mit Fortschritt; die Seite lädt danach neu |
| Prüfung danach | die neue Version ruft ihre eigene Weboberfläche auf |
| Rollback | antwortet sie nicht, startet der Dienst neu; nach drei Starts ohne Antwort setzt `n8-update-guard.sh` auf den alten Stand zurück |
| Ergebnis | *Letztes Update* in Admin → System: erfolgreich oder zurückgenommen, mit Zeit |

---

Weiter: [🩺 Betrieb & Fehlersuche](betrieb.md)
