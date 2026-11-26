# 🎙️ Dashboard

[← Übersicht](../../readme.md) · [Installation](installation.md) · **Dashboard** · [Adminbereich](adminbereich.md) · [APRS](aprs.md) · [Anleitungen](anleitungen.md) · [Konfiguration](konfiguration.md) · [FreeRadioID](freeradioid.md) · [Betrieb & Fehlersuche](betrieb.md)

---

<p align="center">
  <img src="../images/dashboard-desktop.png" alt="Dashboard" width="74%">
  &nbsp;
  <img src="../images/dashboard-mobile.png" alt="Dashboard am Smartphone" width="22%">
</p>

Das Dashboard zeigt live, was auf dem DMR-Server passiert. Es ist für Desktop und Smartphone gebaut; auf dem Handy rücken die Spalten zusammen und unwichtige Spalten verschwinden.

## Kopfzeile mit Menü und Statusleiste

<p align="center"><img src="../images/header-desktop.png" alt="Kopfzeile mit Menü und Statusleiste" width="95%"></p>

Oben gibt es nur noch **ein** Menü: links Logo und Titel, in der Mitte die Reiter, rechts 🔗 Links, das Sprachmenü **🌐 DE ▾** (neun Sprachen) und ganz rechts **🔐 Anmelden** – angemeldet Avatar + Name ▾ mit Passwort ändern, Adminbereich und Abmelden.
Direkt darunter hängt eine schmale **Statusleiste** – deutlich niedriger als das Menü –, die nur zeigt, wie es den Diensten geht.
Beides bleibt beim Scrollen oben stehen, du wechselst also von überall die Ansicht.

Nach dem Login wird **⚙️ Admin** ein eigener Menüpunkt (gestrichelt umrandet). Rechts stehen dann dein Avatar mit Namen
(Klick = Passwort ändern) und **⏻** zum Abmelden – ein Aufklappmenü gibt es nicht mehr.

<p align="center"><img src="../images/header-login.png" alt="Kopfzeile nach dem Login" width="95%"></p>

- **Ab 1500 Pixel Breite:** Menü mit vollen Namen und den Zählern (z. B. *Statistics 8*).
- **1100–1500 Pixel:** kurze Namen (Stats, OBP, TGs, Setup); ab 1280 abwärts zeigt der Login-Knopf nur noch den Avatar.
- **Tablet und Smartphone:** Das Menü steht als eigene Zeile in derselben festen Leiste und nutzt die ganze Breite; die Statusleiste
  bleibt eine Zeile mit kurzen Texten (*Live*, *DMR*, *APRS*).

<p align="center"><img src="../images/header-mobile.png" alt="Kopfzeile am Smartphone" width="40%"></p>

**Menü**

| Element | Bedeutung |
|---|---|
| Logo, Titel, Untertitel, Farben | einstellbar im Adminbereich unter [🎨 Appearance](adminbereich.md#-appearance) |
| **Reiter** | 🎙️ Live · 📈 Statistics · ↔️ OpenBridge · 🗂️ Talkgroups · 🗺️ APRS · 🛠️ Configuration (OpenBridge und APRS nur, wenn eingerichtet) |
| **⚙️ Admin** | nach dem Login als Admin; öffnet den [Adminbereich](adminbereich.md) |
| **🌐 DE ▾** | Sprache der Oberfläche – neun Sprachen (Deutsch, English, Français, Français (Belgique), Magyar, Svenska, Nederlands, Italiano, Español). Beim ersten Besuch die Sprache des Browsers, sonst **Deutsch**; die Wahl gilt sofort (ohne Neuladen) und für alle N8schicht-Seiten auf demselben Server (Cookie `n8_lang`), also auch für die APRS-Karte, adn-frn-server, N8-HotSpot und N8 Crosslink. Mehr in [Sicherheit & N8 Kit](sicherheit.md#sprache--neun-sprachen) |
| **🔗 Links** | eigenes Link-Menü, wenn im [Adminbereich](adminbereich.md#-links) eingerichtet; alternativ als Knopfreihe unter der Kopfzeile |
| **🔐 Anmelden** bzw. **Avatar + Name ▾** | Anmelden im [Anmeldefenster](sicherheit.md#anmeldung); angemeldet öffnet der Name ein Menü mit Rolle, 🔑 Passwort ändern, ⚙️ Adminbereich und ⏻ Abmelden |

**Statusleiste** – der farbige Punkt sagt den Zustand: grün = verbunden, gelb = wartet, rot = Verbindung weg.

| Anzeige | Bedeutung |
|---|---|
| **Live data** | Der Browser bekommt Live-Daten. Rot: *Offline – click to reconnect*; ein Klick verbindet neu. |
| **DMR server** | HBlink4, der DMR-Server, ist mit dem Dashboard verbunden; rot: *DMR server offline*. |
| **APRS online · n stations** | nur bei eingeschaltetem APRS: Server läuft, Zahl der Stationen der letzten Stunde (alle 60 s aktualisiert) |
| **🔇 / 🔊 Notifications** (rechts) | Töne bei Verbindungen und Gesprächen an/aus |

## Statistik

🔌 Verbindungen (Repeater, Hotspots, Outbound-Links und aktive OpenBridge-Trunks) · 🎙️ laufende Gespräche · 📞 Gespräche heute · 🔁 weitergeleitet heute · ⏱️ Sprechzeit heute · ↔️ OpenBridge · 🛡️ FreeRadioID. Die Tageswerte werden um Mitternacht zurückgesetzt. Auf breiten Bildschirmen stehen alle Kacheln in einer Reihe, darunter vier pro Reihe. Am Smartphone stehen sechs gleich große Kacheln in zwei Reihen zu je drei; „weitergeleitet heute“ und die Zusatzzahlen von OpenBridge und FreeRadioID entfallen dort.

- **↔️ OpenBridge** zeigt aktive und eingerichtete Trunks (z. B. `1/1`) sowie die Gespräche von heute: ⬇ empfangen und ⬆ gesendet. Die Kachel erscheint nur, wenn ein Trunk eingerichtet ist. Ein Klick öffnet den [Tab OpenBridge](#️-openbridge--die-trunks-im-detail).
- **🛡️ FreeRadioID** zeigt verifizierte Stationen und Gäste. Die Kachel erscheint nur, wenn der FreeRadioID-Login aktiv ist.

## Tabs: 🎙️ Live, 📈 Statistics, ↔️ OpenBridge, 🗂️ Talkgroups, 🗺️ APRS, 🛠️ Configuration

Im Menü der Kopfzeile wählst du zwischen bis zu sechs Ansichten:

- **🎙️ Live**: alles, was gerade passiert, also Statistik, Last Heard und Verbindungen. Diese Ansicht ist der Start.
- **📈 Statistics**: die [Talkgroup-Statistik](#-talkgroup-statistik). Die Zahl am Tab gibt an, wie viele Talkgroups heute aktiv waren.
- **↔️ OpenBridge** (am Smartphone „OBP“): [die Trunks im Detail](#️-openbridge--die-trunks-im-detail). Die Zahl am Tab zeigt aktive und eingerichtete Trunks. Der Tab erscheint nur, wenn ein Trunk eingerichtet ist.
- **🗂️ Talkgroups** (am Smartphone „TGs“): [das Talkgroup-Verzeichnis](#️-talkgroups--das-verzeichnis) mit Suche.
- **🗺️ APRS**: die [APRS-Karte](aprs.md#die-karte) mit DMR-Positionen, Repeatern und APRS-Stationen. Der Tab erscheint, wenn APRS eingeschaltet ist; **⤢ Full screen** öffnet die Karte auf eigener Seite (`/aprs`).
- **🛠️ Configuration** (am Smartphone „Setup“): [alles, was man zum Verbinden braucht](#️-configuration--so-verbindest-du-dich).

Der gewählte Tab steht in der Adresse (`…/#stats`, `…/#openbridge`, `…/#talkgroups`, `…/#aprs`, `…/#config`). So landest du nach dem Neuladen wieder dort und kannst die Tabs direkt verlinken, z. B. `https://dmr.die-n8schicht.de/#config` für neue Funkamateure.

## ↔️ OpenBridge – die Trunks im Detail

<p align="center">
  <img src="../images/openbridge-tab.png" alt="Tab OpenBridge" width="72%">
  &nbsp;
  <img src="../images/openbridge-tab-mobile.png" alt="Tab OpenBridge am Smartphone" width="22%">
</p>

Ein OpenBridge-Trunk führt oft über tausend Talkgroups. In der Live-Ansicht steht deshalb nur eine kompakte Karte: Name, Netzwerk-ID, Protokoll, Laufzeit, Gegenstelle, die **Anzahl** der Talkgroups mit Zeitschlitz, die Gespräche von heute (↓ empfangen, ↑ gesendet) und die laufenden Gespräche. Ein Klick auf den Kopf öffnet den Tab.

<p align="center"><img src="../images/openbridge-card.png" alt="OpenBridge-Karte in der Live-Ansicht" width="45%"></p>

Die Karte ist genauso gebaut wie die Stationskarten und steht mit ihnen im Raster [Verbundene Systeme](#-verbundene-systeme); jedes laufende Gespräch ist eine eigene Zeile. Ein Klick auf den Sprecher öffnet seine [Stationsinfo](#stationsinfo-zu-jeder-dmr-id).

Im Tab **↔️ OpenBridge** steht alles zu einem Trunk. Bei mehreren Trunks wählst du oben den Trunk aus.

| Bereich | Inhalt |
|---|---|
| **Kopf** | Name, Beschreibung, **UP**/**DOWN**; Gegenstelle mit Port, lokaler UDP-Port, Netzwerk-ID, verbunden seit, letzter Verkehr, Anzahl Talkgroups, was als RptrId gesendet wird; darunter die laufenden Gespräche |
| **Zeitraum / Messgröße** | Heute · 24 h · 7 Tage · 30 Tage, ⏱️ Sprechzeit oder 📞 Gespräche |
| **Kennzahlen** | ⬇️ empfangen und ⬆️ gesendet (Gespräche, Sprechzeit, Sprecher), Sprechzeit gesamt mit Anteil empfangen/gesendet, aktive Talkgroups |
| **Top talkgroups** | die 10 meistgenutzten Talkgroups auf dem Trunk; blau = empfangen, orange = gesendet |
| **Traffic** | Verlauf pro Stunde oder Tag: empfangen über der Linie, gesendet darunter |
| **Latest calls on the trunk** | die letzten 25 Gespräche mit Richtung, Station, Talkgroup, Zeitschlitz und Dauer |
| **Talkgroups on the trunk** | die komplette Liste mit Namen und Zeitschlitz, mit Suche und Filtern (*Active*, *TS1*, *TS2*); aktive Talkgroups sind hervorgehoben |

<p align="center">
  <img src="../images/openbridge-talkgroups.png" alt="Talkgroups auf dem Trunk, Suche nach „nord“" width="80%">
</p>

<p align="center"><img src="../images/openbridge-tab-mobile-2.png" alt="OpenBridge-Diagramme am Smartphone" width="28%"></p>

**Adressen und Ports** der Gegenstelle und unser lokaler Port sind nur für eingeloggte Admins sichtbar; alle anderen sehen **🔒 hidden**. Bei einem Trunk ohne Talkgroup-Filter steht „All TGs“ statt der Liste.

Jedes Gespräch über den Trunk wird mit Richtung, Talkgroup und Dauer in SQLite gespeichert, und zwar in beide Richtungen. Speicherdauer und Sichtbarkeit ohne Login sind dieselben wie bei der [Talkgroup-Statistik](#-talkgroup-statistik). Das Passwort (`passphrase`) des Trunks erscheint nirgends im Dashboard.

Eingerichtet wird ein Trunk im [Adminbereich unter ↔️ OpenBridge](adminbereich.md#️-openbridge): entweder mit allen Talkgroups ohne Filter oder nur mit ausgewählten. Bei ausgewählten Talkgroups verwirft HBlink4 alle anderen in beide Richtungen.

## 🗂️ Talkgroups – das Verzeichnis

<p align="center">
  <img src="../images/talkgroups-tab.png" alt="Talkgroup-Verzeichnis" width="72%">
  &nbsp;
  <img src="../images/talkgroups-mobile.png" alt="Talkgroup-Verzeichnis am Smartphone" width="22%">
</p>

Alle Talkgroups mit Namen aus der **Talkgroup-Liste der N8schicht** ([`talkgroup_ids.json`](https://github.com/dhartmann1979/n8schicht/blob/main/talkgroup_ids.json), rund 1.400 Einträge) und den eigenen Namen aus dem Adminbereich (*own*).

- **Suche** nach Nummer (Anfang, z. B. `262`) oder Namen (z. B. `Bayern`, `nord`)
- **📡 Active (30 days)**: nur Talkgroups, auf denen der Server in den letzten 30 Tagen Gespräche hatte, sortiert nach Sprechzeit; mit Gesprächen, Sprechzeit und letztem Gespräch
- **✏️ Own names**: nur die selbst vergebenen Namen

<p align="center"><img src="../images/talkgroups-search.png" alt="Suche im Verzeichnis" width="80%"></p>

Die Namen erscheinen auch überall sonst im Dashboard:
- **Last Heard:** unter der Talkgroup-Nummer
- **Zeitschlitze der Karten:** unter *Destination*
- **TS1/TS2-Listen der Karten:** als Tooltip; gepunktet unterstrichene Nummern haben einen Namen
- **Detailansicht** der Stationen
- **Talkgroup-Statistik** und **Configuration-Tab**

Die Liste wird täglich zusammen mit der Rufzeichen-Datenbank neu geladen. Bis zum ersten Download nutzt das Dashboard eine mitgelieferte Kopie, die Namen funktionieren also sofort und auch offline.

## 🛠️ Configuration – so verbindest du dich

<p align="center">
  <img src="../images/config-tab.png" alt="Tab Configuration" width="72%">
  &nbsp;
  <img src="../images/config-tab-mobile.png" alt="Tab Configuration am Smartphone" width="22%">
</p>

Der Tab erklärt mit dem N8schicht-Logo in drei Schritten, wie ein Hotspot oder Repeater auf den Server kommt. Alle Werte kommen live aus dem Adminbereich, sie stimmen also immer:

| Karte | Inhalt |
|---|---|
| **① Server** | Adresse und UDP-Port mit **⧉ Copy**-Knopf, Passwort-Hinweis, Radio-ID (Hotspots mit zwei Ziffern Suffix); die *Options*-Zeile nur, wenn Geräte ihre Talkgroups selbst wählen dürfen (`trust`) |
| **② Login** | 🛡️ **FreeRadioID** (empfohlen): eigene DMR-ID und persönliches Passwort von FreeRadioID.net, volle Rechte, mit Link zur Registrierung · 👤 **Gast**: das Standard-Passwort, senden nur auf die Gast-Talkgroups. Ohne FreeRadioID-Login steht hier nur das Passwort. |
| **③ Talkgroups** | TS1, TS2 und die Gast-Talkgroups als Kacheln, mit den Namen aus dem Adminbereich |
| **🧰 Ready-made settings** | fertige Zeile für Pi-Star/WPSD (`/root/DMR_Hosts.txt`) und der Abschnitt `[DMR Network]` für MMDVMHost, je zum Kopieren |
| **📍 APRS – show your position on the map (DAPRS)** | nur wenn APRS und die DAPRS-Dekodierung an sind – siehe unten |
| **📌 Note from the sysop** | freier Text aus dem Adminbereich, z. B. Regeln und Kontakt; Links werden klickbar |

### 📍 DAPRS: so sendest du deine Position

<p align="center"><img src="../images/config-daprs.png" alt="Karte DAPRS im Tab Configuration" width="90%"></p>

Sind im Adminbereich unter *APRS → DAPRS decoding* die Dekodierung und mindestens ein Weg eingeschaltet, erklärt die Karte,
wie Funkgeräte ihre GPS-Position schicken. Die Karte zeigt nur die Wege, die der Server auch annimmt:

- **A · GPS im Sprachruf** (*Decode embedded GPS* an): Geräte mit eingebautem GPS, die die Position bei jedem Durchgang mitschicken
  (Embedded GPS, z. B. Motorola, Hytera, andere ETSI-Geräte). GPS im Gerät einschalten und Senden der Position erlauben – sonst nichts.
- **B · GPS-Report als Datenruf** (*Decode GPS data calls* an): Geräte mit „Digital APRS“ bzw. GPS-Report (AnyTone, TYT/Retevis,
  MD-380-GPS-Firmware, Motorola LRRP). Die Karte nennt die **Ziel-ID** aus *Accept GPS data sent to* (z. B. `900999`, mit Kopier-Knopf),
  **Private call**, Format **NMEA oder LRRP, unbestätigt, Rate ½** und das kürzeste sinnvolle **Intervall**.
- **Wo du erscheinst:** Link zur Karte (erste eigene Domain, sonst `/aprs`) und – wenn der Uplink an ist – im APRS-Netz (APRS-IS bzw. CB-APRS).
- **Wer geht ins APRS-Netz:** Stationen mit FreeRadioID-Login; Gäste nur auf der lokalen Karte (wenn so eingestellt).
- **Hotspot-Hinweis:** Pi-Star/WPSD/MMDVMHost reichen GPS-Daten selbst durch; mit DMRGateway und mehreren Netzen muss die Ziel-ID zu diesem Server geroutet werden.

SSID, Symbol und Kommentar kommen aus den DAPRS-Einstellungen; eigene Werte pro ID legt der Sysop fest. Details: [APRS & DAPRS](aprs.md).

<p align="center"><img src="../images/config-mmdvm.png" alt="Fertige Einstellungen für MMDVMHost" width="80%"></p>

Ob der Tab erscheint, welche Adresse er zeigt, ob das Standard-Passwort zu sehen ist und welcher Hinweis darunter steht, stellst du im [Adminbereich](adminbereich.md#-dashboard) ein. Sonst steht dort „ask the sysop“. Eigene Passwörter aus Patterns zeigt der Tab nie.

## 📈 Talkgroup-Statistik

<p align="center"><img src="../images/dashboard-stats-tab.png" alt="Tab Statistics" width="95%"></p>

Der Tab **📈 Statistics** zeigt, **welche Talkgroups wie viel genutzt werden**. Jedes Gruppengespräch wird mit Talkgroup, Dauer und DMR-ID in SQLite gespeichert. Weitergeleitete Kopien desselben Gesprächs zählen nicht doppelt, Einzelrufe und Datenrufe zählen nicht mit.

| Element | Inhalt |
|---|---|
| **Zeitraum** | Heute · 24 h · 7 Tage · 30 Tage |
| **Messgröße** | ⏱️ Sprechzeit oder 📞 Anzahl Gespräche; gilt für beide Diagramme |
| **Kennzahlen** | aktive Talkgroups, Gespräche, Sprechzeit, verschiedene Sprecher im Zeitraum |
| **Top talkgroups** | die 10 meistgenutzten Talkgroups als Balken, mit Namen |
| **Activity** | Verlauf pro Stunde (Heute, 24 h) bzw. pro Tag (7/30 Tage); die 5 größten Talkgroups farbig, der Rest grau als „other“ |
| **Where the calls come from** | Anteil der Gespräche von lokalen Repeatern und Hotspots, über OpenBridge und über Outbound-Links |
| **Tabelle** | alle Talkgroups mit Gesprächen, Sprechzeit, Anteil, Sprechern, aktivster Station und letztem Gespräch; **↔ 40 %** zeigt, welcher Anteil der Sprechzeit über OpenBridge kam |

<p align="center"><img src="../images/tg-stats-origin.png" alt="Herkunft der Gespräche" width="90%"></p>

Gespräche über OpenBridge zählen in der Statistik mit, wenn sie hereinkommen. Was der Server selbst über den Trunk hinausschickt, ist eine Kopie eines Gesprächs, das schon gezählt ist; es steht im Tab OpenBridge als „gesendet“.

Fährst du mit der Maus über eine Säule oder einen Balken, erscheinen die genauen Werte. Eine Talkgroup behält ihre Farbe, auch wenn du den Zeitraum wechselst. Die Ansicht aktualisiert sich nach jedem Gespräch von selbst.

<p align="center">
  <img src="../images/tg-stats-hover.png" alt="Werte beim Überfahren" width="60%">
  &nbsp;
  <img src="../images/tg-stats-mobile.png" alt="Talkgroup-Statistik am Smartphone" width="28%">
</p>

Auf dem Smartphone liegen die Diagramme untereinander, und die Tabelle zeigt nur Talkgroup, Gespräche und Sprechzeit. Namen für die Talkgroups, die Speicherdauer und ob der Tab ohne Login sichtbar ist, stellst du im [Adminbereich](adminbereich.md#-dashboard) ein.

<p align="center"><img src="../images/tg-stats-7d.png" alt="Talkgroup-Statistik über 7 Tage" width="95%"></p>

## ON AIR – wer spricht, steht oben

<p align="center"><img src="../images/on-air.png" alt="ON AIR" width="90%"></p>

- **Last Heard:** Wer gerade spricht, steht in der ersten Zeile, grün hinterlegt und mit **● ON AIR**.
- **Repeater und Hotspots:** Die Station, die gerade sendet, rückt an den Anfang ihrer Gruppe. Ihre Karte leuchtet grün und trägt **ON AIR**.
- **Reihenfolge:** Danach folgen Stationen mit reservierter Talkgroup (Hang-Time), dann der Rest alphabetisch.

## Last Heard

<p align="center">
  <img src="../images/last-heard.png" alt="Last Heard" width="74%">
  &nbsp;
  <img src="../images/last-heard-mobile.png" alt="Last Heard am Smartphone" width="22%">
</p>

Jeder Eintrag ist eine kompakte Zeile. Am Desktop steht alles in einer Zeile, am Smartphone in zwei kurzen Zeilen (oben Rufzeichen, ID und Zeit, unten Talkgroup, Zeitschlitz und woher).

| Spalte | Inhalt |
|---|---|
| Radio ID | DMR-ID des Sprechers |
| Callsign | Avatar von FreeRadioID (sonst Initialen), Rufzeichen und **FRID**, wenn die ID bei FreeRadioID.net registriert ist |
| Source | über welchen Repeater oder welche Verbindung das Gespräch kam; 🛡️ = per FreeRadioID angemeldet |
| TS | Zeitschlitz TS1 oder TS2 |
| Destination | 👥 Gruppenruf / 👤 Einzelruf, 🎤 Sprache / 📟 Daten, Talkgroup mit Namen |
| Last heard | **ON AIR** oder vor wie vielen Sekunden/Minuten |

Damit die Liste nicht die halbe Seite füllt, stehen am Desktop die ersten **8**, am Smartphone die ersten **5** Einträge da. **Show all** zeigt alle zehn, **Show less** klappt wieder ein. Wer gerade spricht, steht immer oben und wird nie ausgeblendet.

Klappst du **Last Heard** über den Pfeil zu, siehst du nur die laufenden Gespräche.

Ein Klick auf **Radio ID** oder **Callsign** öffnet die [Stationsinfo](#stationsinfo-zu-jeder-dmr-id).

## 📻 Talker Alias – der Name aus dem Funkgerät

Viele Funkgeräte senden beim Sprechen ihren **Talker Alias** mit – meist „Rufzeichen Name“, z. B. `DL1ABC Hans`. HBlink4 liest ihn jetzt aus und zeigt ihn **anstelle des Namens aus der Rufzeichen-Datenbank** an, markiert mit **TA**:

<p align="center"><img src="../images/talker-alias-last-heard.png" alt="Talker Alias in Last Heard und in den Slots" width="95%"></p>

| Wo | Was passiert |
|---|---|
| **Last Heard** | der Talker Alias steht statt des Rufzeichens, dahinter **TA**; mit der Maus darauf steht das Rufzeichen aus der Datenbank |
| **Slots der Repeater/Hotspots** (Karte und Detail) | Spalte *Callsign* bzw. Zeile des Slots zeigt den Talker Alias |
| **OpenBridge / Outbound** | auch bei Gesprächen, die über Trunks und Links hereinkommen |
| **📈 Statistics** | eigene Rangliste **📻 Talker Alias** und bei jeder Talkgroup der TA der aktivsten Station (siehe unten) |

**Woher er kommt:** im Sprachrahmen (*Embedded LC*, Blöcke FLCO 4–7, alle zwei Superframes) und als eigenes HomeBrew-Paket **DMRA** (MMDVMHost/DMRGateway). Unterstützt werden alle vier Formate (7-Bit, ISO-8859-1 mit Umlauten, UTF-8, UTF-16), bis 31 Zeichen. Er baut sich während des Gesprächs auf: der erste Block erscheint nach etwa einer Sekunde, der vollständige Text, sobald alle Blöcke da sind. Jede neue Übertragung beginnt leer – ein alter Alias bleibt nicht an einer anderen Station hängen.

**Statistik:** Jedes Gespräch speichert den zuletzt empfangenen Talker Alias mit (neue Spalte `talker_alias` in `tg_calls`, ältere Gespräche bleiben leer). Die Rangliste **📻 Talker Alias** zählt **getrennt von den DMR-IDs**: Gespräche, Sprechzeit, welche IDs/Rufzeichen diesen Namen gesendet haben, Talkgroups und letztes Gespräch. Gleiche Namen in unterschiedlicher Groß-/Kleinschreibung werden zusammengefasst.

<p align="center"><img src="../images/tg-stats-talker-alias.png" alt="Rangliste Talker Alias" width="95%"></p>

Im Server-Log erscheint jeder vollständige Alias einmal: `📻 Talker Alias src=2621234: "DL1ABC Hans"`.

## Stationsinfo zu jeder DMR-ID

<p align="center">
  <img src="../images/station-popup.png" alt="Stationsinfo" width="66%">
  &nbsp;
  <img src="../images/station-popup-mobile.png" alt="Stationsinfo am Smartphone" width="22%">
</p>

Überall, wo ein Sprecher auftaucht, kannst du ihn anklicken: in **Last Heard**, in den Zeitschlitz-Zeilen der Stationskarten, bei den laufenden Gesprächen auf OpenBridge und in der Gesprächsliste im Tab OpenBridge. Die Infos kommen von **FreeRadioID.net**:

| Bereich | Inhalt |
|---|---|
| Kopf | Avatar, Rufzeichen, DMR-ID, Name und Ort, ob die ID bei FreeRadioID.net registriert ist |
| 🛡️ FreeRadioID.net | Status, Rufzeichen, Name, Ort, Bemerkung und der Link zum Profil. Kennt FreeRadioID die ID nicht, steht das Rufzeichen aus der Rufzeichen-Datenbank da |
| 🎙️ Heard here | wann die ID zuletzt auf diesem Server gehört wurde (oder **ON AIR**), Talkgroup, Zeitschlitz, über welche Station, Sprache oder Daten |

Ist die ID selbst als Station hier angemeldet (Repeater, Hotspot, App), führt **Station logged in here – details ›** zur [Detailansicht](#detailansicht). Die Abfrage bei FreeRadioID.net wird eine Stunde zwischengespeichert; IP-Adressen stehen in der Stationsinfo nie.

## Fußzeile

<p align="center"><img src="../images/footer.png" alt="Fußzeile" width="70%"></p>

Am Ende jeder Seite steht **© Die N8schicht** mit der installierten Version (Versionsnummer und Commit) und ihrem Datum. So sieht man auf einen Blick, welcher Stand läuft.

## 🔌 Verbundene Systeme

<p align="center"><img src="../images/connected-systems.png" alt="Verbundene Systeme als ein Raster" width="95%"></p>

Alles, was mit dem Server verbunden ist – **OpenBridge-Trunks, Repeater, Hotspots, Apps, Netzwerke (ein- und ausgehend) und unbekannte
Geräte** – steht in **einem gemeinsamen Raster**. Alle Karten sind gleich breit, Karten einer Reihe gleich hoch. Das Raster passt sich der
Breite an: am großen Monitor vier bis sechs Karten nebeneinander, am Tablet zwei, am Smartphone eine.

Über dem Raster zählen **Filter-Pillen** die Systeme pro Art. Ein Klick zeigt nur diese Art, *Alle* wieder alles; der Browser merkt sich die Auswahl.

<p align="center"><img src="../images/connected-systems-filter.png" alt="Filter: nur Repeater" width="95%"></p>

### So ist eine Karte aufgebaut

| Teil | Inhalt |
|---|---|
| **Streifen links** | Farbe der Art: ↔️ OpenBridge orange · 📶 Repeater grün · 📱 Hotspot hellblau · 📲 App violett · 🔗 Netzwerk cyan · ❔ Unbekannt gelb |
| **Kopf** | Avatar mit Art-Symbol, Rufzeichen und DMR-ID (bei OpenBridge Name und NetID), darunter Login-Art und Standort |
| **Zustand rechts** | **ON AIR** / **LIVE** (es läuft ein Gespräch) · *online* · *n verpasst* (Keep-Alive-Pings fehlen) · *wartet* / *offline* |
| **Kennzahlen** | vier gleich breite Felder: Stationen *Online · TX MHz · TS1 · TS2* (RX im Tooltip) · Outbound *Online · Server · TS1 · TS2* · OpenBridge *Online · Server · Talkgroups · Heute ↓↑* |
| **Unten** | die Zeitschlitze (siehe unten), bei OpenBridge jedes laufende Gespräch als Zeile |

Von den Talkgroups pro Zeitschlitz stehen höchstens zwei als Chip da, der Rest als **+N** (die ganze Liste im Tooltip). **Alle** (grün)
heißt: keine Einschränkung konfiguriert; **Keine** heißt: alles gesperrt. Gold markierte Talkgroups werden übersetzt (🔀).

Die Zeitschlitze:
- Sind beide frei, ist es eine Zeile: `TS1 IDLE · TS2 IDLE`.
- Läuft ein Gespräch, zeigt die Zeile **⬇️ RX** (empfangen) oder **⬆️ TX** (gesendet), den Sprecher, die Talkgroup mit Namen und die Dauer.
- In der Nachlaufzeit (**HANG**) steht nur die Talkgroup.
- Ein Klick auf den Sprecher öffnet die [Stationsinfo](#stationsinfo-zu-jeder-dmr-id), ein Klick auf den Kopf der Karte die [Detailansicht](#detailansicht) (bei OpenBridge den Tab OpenBridge).

Die Login-Art steht als kleines Etikett unter dem Rufzeichen:

| Anzeige | Bedeutung |
|---|---|
| <img src="../images/dashboard-freeradioid-card.png" width="300"> | **✓ FRID** (grün): Die Station hat sich mit ihrem FreeRadioID-Passwort angemeldet und hat volle Rechte. |
| <img src="../images/dashboard-guest-card.png" width="300"> | **👤 Gast** (gelb): Die Station hat sich mit dem Standard-Passwort angemeldet. Sie darf nur auf die Gast-Talkgroups senden, empfangen kann sie alles. |
| ohne Etikett | angemeldet mit dem Passwort eines eigenen Patterns, bei dem FreeRadioID aus ist |

### Gerätearten: Repeater, Hotspot, App

HBlink4 sortiert jede Station anhand des **Paketnamens**, den ihre Software beim Login meldet (steht in der Detailansicht unter *Connection → Package*):

| Symbol | Bereich | Was ist das? | Beispiele für den Paketnamen |
|---|---|---|---|
| 📶 | **Repeaters** | Relaisstation mit eigener Hardware | `MMDVM`, `…Repeater`, `STM32…` |
| 📱 | **Hotspots** | persönliches Funkmodem, meist mit Pi-Star oder WPSD | `MMDVM_HS_Hat`, `ZUMspot`, `DVMega`, `MMDVM_DMO` |
| 📲 | **Apps** | Handy- oder PC-App **ohne Funkgerät** | `Z3DMR`, `DroidStar`, `BlueDV`, `DVSM`, `Peanut` |
| 🔗 | **Network Inbound** | ein anderer Server verbindet sich hierher | `HBlink`, `FreeDMR`, `BrandMeister` |
| ❔ | **Unknown device type** | Paketname steht in keiner Liste | – |

Die Art erkennst du am Symbol unten rechts am Avatar und an der Farbe des Streifens; mit den Filter-Pillen zeigst du nur eine Art:

<p align="center">
  <img src="../images/device-type-app.png" alt="Filter Apps" width="95%">
</p>
<p align="center"><img src="../images/station-detail-app.png" alt="Detailansicht einer App-Station" width="60%"></p>

Bei **❔ Unbekanntes Gerät** steht die gemeldete Software direkt auf der Karte (*Minden · OpenGD77-Net · v4.2*). Das heißt nur
„Paketname steht in keiner Liste“, nicht „Fehler“:

<p align="center"><img src="../images/device-type-unknown.png" alt="Filter Unbekanntes Gerät" width="95%"></p>

Ein Admin sortiert solche Geräte unter **Adminbereich → Settings → 📲 Device detection** ein (siehe [Adminbereich](adminbereich.md#️-dmr-server-hblink4)). Verbundene Stationen wandern nach dem Speichern sofort zur richtigen Art.

> **Hinweis DroidStar:** DroidStar meldet ab Werk den Paketnamen `MMDVM_MMDVM_HS_Hat` und sieht damit für den Server genau wie ein Hotspot aus. Als App erscheint es nur, wenn in DroidStar ein eigener Paketname eingetragen ist (z. B. `DroidStar`). Z3DMR meldet sich korrekt als `Z3DMR`.

**OpenBridge** und **Netzwerk ausgehend** zeigen Verbindungen zu anderen Servern. Bei OpenBridge steht statt der langen Talkgroup-Liste nur die Anzahl; alles Weitere zeigt der [Tab OpenBridge](#️-openbridge--die-trunks-im-detail).

## Detailansicht

Ein Klick auf Rufzeichen oder Avatar öffnet die Details:

<p align="center">
  <img src="../images/station-detail-desktop.png" alt="Detailansicht" width="74%">
  &nbsp;
  <img src="../images/station-detail-mobile.png" alt="Detailansicht am Smartphone" width="22%">
</p>

- **Kopf**: Avatar, Rufzeichen, ID, Typ, online, Name und Ort aus dem FreeRadioID-Profil, Login-Art
- **Kennzahlen**: Uptime, Gespräche heute, Aktivität TS1/TS2, verpasste Pings
- **Kacheln**: Talkgroups, Zugang, Verbindung, Funkdaten, Standort mit Link zu OpenStreetMap, FreeRadioID-Profil

Die **IP-Adresse** steht nur für eingeloggte Admins in der Kachel *Connection*. Alle anderen sehen *🔒 hidden*. Schließen mit `Esc`, ✕ oder einem Klick daneben.

---

Weiter: [⚙️ Adminbereich](adminbereich.md)
