"""
The admin area's settings: dashboard and HBlink4 DMR server, stored in SQLite.

Generic parts (field types, validation, storage) live in hblink4/settings_db.py
so that the DMR server reads the same database. This module adds the dashboard's
own fields and the logic the admin area needs:

* first start: every setting missing from the database is taken from
  dashboard/config.json (dashboard fields) or config/config.json (DMR fields),
  or from its default
* afterwards the database wins; "reset to config file" re-seeds one section
* dashboard settings apply live; DMR settings are pushed to HBlink4 over the
  event link (see dashboard/server.py)

Not here on purpose: the superadmin (dashboard/config.json only) and the bind
addresses / event link, which a program needs before it can read the database.
"""
from __future__ import annotations

import copy
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from hblink4.settings_db import (  # noqa: E402
    DMR_FIELDS, DMR_SECTIONS, Field, SettingsDB, SettingsError, get_path, set_path, validate,
)

__all__ = ["APRS_SECTIONS", "SettingsStore", "SettingsError", "FIELDS", "FIELD_BY_KEY", "SECTIONS", "SECTION_HELP", "get_path", "set_path",
           "validate", "RADIOID_URL", "FREERADIOID_ALL_URL"]

RADIOID_URL = "https://database.radioid.net/static/user.csv"
FREERADIOID_ALL_URL = "https://freeradioid.net/api/subscriber_ids.csv"

DASH_SECTIONS: List[Tuple[str, str]] = [
    ("appearance", "🎨 Appearance"),
    ("links", "🔗 Link menu"),
    ("announcement", "📢 Announcement"),
    ("access", "🔐 Dashboard access"),
    ("freeradioid", "🛡️ FreeRadioID data"),
    ("userdb", "📘 Callsign database"),
    ("tgstats", "📈 Talkgroups & statistics"),
    ("connect", "🛠️ Configuration tab"),
    ("https", "🔒 HTTPS & web"),
    ("update", "⬆️ Updates"),
    ("aprs_server", "📡 APRS server"),
    ("aprs_uplink", "🌍 Uplink & downlink"),
    ("aprs_daprs", "🛰️ DAPRS – DMR → APRS"),
    ("aprs_map", "🗺️ APRS map"),
    ("aprs_sites", "🌐 APRS domains"),
]

# Sections shown in the admin area's APRS tab instead of under Settings
APRS_SECTIONS = ("aprs_server", "aprs_uplink", "aprs_daprs", "dmr_daprs", "aprs_map", "aprs_sites")

# One sentence per section for the admin area (what is this about?)
SECTION_HELP: Dict[str, str] = {
    "appearance": "Titles, colours and logos of the dashboard.",
    "links": "Your own links in the header, e.g. to the network website, a chat group or a wiki.",
    "announcement": "A banner above the dashboard for news and maintenance notices.",
    "access": "Who may see the dashboard and how long a login lasts.",
    "freeradioid": "Avatars, profiles and the FRID tag from FreeRadioID.net.",
    "userdb": "Where callsigns and names for the DMR IDs come from.",
    "tgstats": "Talkgroup statistics and talkgroup names.",
    "connect": "The Configuration tab tells new users how to connect their hotspot.",
    "https": "Encrypted access with a free Let's Encrypt certificate.",
    "update": "Logged-in admins get a notice when GitHub has a newer version.",
    "aprs_server": "An APRS-IS compatible server in Python: APRS apps, iGates and trackers connect to it like to any APRS-IS server.",
    "aprs_uplink": "Connection to an APRS network – APRS-IS, CB-APRS or your own servers: DMR positions go up, stations come down onto the map.",
    "aprs_daprs": "What happens with the GPS positions of DMR radios: callsign from the ID list, SSID, symbol, comment, APRS-IS.",
    "aprs_map": "The APRS map: who sees it, what it shows and how long stations stay.",
    "aprs_sites": "Up to three domains that open the map directly, each with its own title and logo and, if wanted, a Let's Encrypt certificate.",
    "dmr_server": "Port and timing of the DMR server.",
    "dmr_access": "Password and talkgroups for repeaters and hotspots.",
    "dmr_frid": "Personal logins via FreeRadioID.net and the guest access.",
    "dmr_types": "How stations are sorted into repeaters, hotspots, apps and networks: by the package name their software reports at login.",
    "dmr_advanced": "Rules per station, blocked IDs and links to other servers – for experienced sysops.",
    "dmr_obp": "Trunks to other networks such as FreeDMR.",
    "dmr_daprs": "The DMR server finds GPS positions in the radio traffic (DAPRS). What happens with them is set in the APRS tab.",
}

THEME_PRESETS = (
    ("n8", "🌙 N8 Night (default)"),
    ("ocean", "🌊 Ocean"),
    ("aurora", "🌌 Aurora (green)"),
    ("ember", "🔥 Ember (orange)"),
    ("violet", "🔮 Violet"),
    ("graphite", "⚫ Graphite"),
    ("daylight", "☀️ Daylight (light)"),
)

DASH_FIELDS: List[Field] = [
    # -- appearance: titles
    Field("dashboard_title", "appearance", "Title", "text", "DMR Die N8schicht", "Large text next to the logo"),
    Field("server_name", "appearance", "Subtitle", "text", "dmr.die-n8schicht.de", "Small line under the title"),
    Field("server_description", "appearance", "Description", "text", "N8schicht DMR Network",
          "Shown in the Configuration tab"),
    Field("page_title", "appearance", "Browser tab title", "text", "", "Empty = the title"),
    # -- appearance: colours
    Field("theme.preset", "appearance", "Colour profile", "choice", "n8", choices=THEME_PRESETS),
    Field("theme.accent", "appearance", "Accent colour", "color", "", "Buttons, numbers, active tabs. Empty = from the profile"),
    Field("theme.accent2", "appearance", "Accent colour 2", "color", "", "Second colour of buttons and the title"),
    Field("theme.background", "appearance", "Background colour", "color", "", "Empty = from the profile"),
    Field("theme.glow1", "appearance", "Glow top left", "color", ""),
    Field("theme.glow2", "appearance", "Glow top right", "color", ""),
    Field("theme.glow3", "appearance", "Glow bottom", "color", ""),
    Field("theme.text", "appearance", "Text colour", "color", "", "Empty = suits the background automatically"),
    Field("theme.panel", "appearance", "Card tint", "color", "", "Colour mixed into the glass cards"),
    Field("theme.glow", "appearance", "Background glow", "int", 100, "0 = flat background", min=0, max=150),
    Field("theme.glass", "appearance", "Card brightness", "int", 50, "How bright the glass cards are", min=0, max=100),
    Field("theme.radius", "appearance", "Roundness (px)", "int", 22, "Corners of cards and buttons", min=0, max=28),
    Field("theme.blur", "appearance", "Glass blur effect", "bool", True, "Off = faster on old phones"),
    # -- appearance: logos
    Field("logo", "appearance", "Logo", "image", "", "Empty = N8schicht logo"),
    Field("logo_size", "appearance", "Logo size (px)", "int", 44, min=24, max=96),
    Field("logo_radius", "appearance", "Logo corners (%)", "int", 0, "0 = as drawn, 50 = round", min=0, max=50),
    Field("favicon", "appearance", "Browser icon (favicon)", "image", "", "Empty = same as the logo"),

    # -- link menu
    Field("links.enabled", "links", "Show the link menu", "bool", False),
    Field("links.label", "links", "Menu button text", "text", "🔗 Links", depends="links.enabled"),
    Field("links.style", "links", "Display", "choice", "menu",
          choices=(("menu", "Button with drop-down menu"), ("bar", "Row of buttons under the header")),
          depends="links.enabled"),
    Field("links.items", "links", "Links", "links", [], depends="links.enabled"),
    Field("network_info.enabled", "links", "Extra button in the header", "bool", False,
          "A single button next to the status badges (older option)", advanced=True),
    Field("network_info.button_text", "links", "Button text", "text", "Network Info",
          depends="network_info.enabled", advanced=True),
    Field("network_info.url", "links", "Button link", "url", "", depends="network_info.enabled", advanced=True),

    Field("announcement.enabled", "announcement", "Show announcement banner", "bool", False),
    Field("announcement.text", "announcement", "Announcement text", "longtext", "", depends="announcement.enabled"),

    Field("auth.public_dashboard", "access", "Public dashboard", "bool", True,
          "Off = nothing is visible without login. IP addresses and ports are always admin-only."),
    Field("auth.session_hours", "access", "Session length (hours)", "int", 12, min=1, max=720),
    Field("auth.remember_days", "access", "\"Stay logged in\" (days)", "int", 30, min=1, max=365),

    Field("freeradioid.avatars", "freeradioid", "Show avatars", "bool", True,
          "Images of FreeRadioID-registered IDs, cached in the database"),
    Field("freeradioid.profile_lookup", "freeradioid", "Look up profiles", "bool", True,
          "Name and location in the station detail view"),
    Field("user_database.freeradioid.enabled", "freeradioid", "Load FreeRadioID ID list", "bool", True,
          "Registered IDs get the FRID tag in Last Heard"),

    Field("user_database.source_url", "userdb", "Source", "choice", FREERADIOID_ALL_URL,
          choices=((FREERADIOID_ALL_URL, "FreeRadioID.net (radioid.net + FreeRadioID)"),
                   (RADIOID_URL, "radioid.net only"))),
    Field("user_database.filter.countries", "userdb", "Countries", "countries", "all",
          "all, or comma separated exactly as the list spells them (Germany, Austria, …)"),
    Field("user_database.refresh.time_of_day", "userdb", "Daily refresh at", "time", "03:17"),

    Field("tg_stats.enabled", "tgstats", "Record talkgroup statistics", "bool", True,
          "Every group call (talkgroup, duration, radio ID) is stored in the database for the charts"),
    Field("tg_stats.public", "tgstats", "Visible without login", "bool", True,
          "Off = only logged-in users see the talkgroup and OpenBridge statistics", depends="tg_stats.enabled"),
    Field("tg_stats.retention_days", "tgstats", "Keep calls for (days)", "int", 30, min=1, max=365,
          depends="tg_stats.enabled"),
    Field("talkgroups.list", "tgstats", "Talkgroup list of the N8schicht", "bool", True,
          "Names of ~1400 talkgroups (github.com/dhartmann1979/n8schicht), updated daily with the callsign database"),
    Field("talkgroups.url", "tgstats", "Talkgroup list URL", "text",
          "https://raw.githubusercontent.com/dhartmann1979/n8schicht/main/talkgroup_ids.json",
          "JSON in the format of talkgroup_ids.json", depends="talkgroups.list", advanced=True),
    Field("tg_stats.names", "tgstats", "Own talkgroup names", "longtext", "",
          "One per line: 26500 = N8schicht Ortsrunde. Override the list or add missing talkgroups"),

    Field("connect.enabled", "connect", "Show the Configuration tab", "bool", True,
          "How to connect: server, port, password, talkgroups and ready-made settings"),
    Field("connect.host", "connect", "Server address for hotspots", "text", "",
          "Empty = the subtitle (Appearance → Subtitle)", depends="connect.enabled"),
    Field("connect.show_password", "connect", "Show the default password", "bool", True,
          "With FreeRadioID login this is the guest password. Off = \"ask the sysop\"", depends="connect.enabled"),
    Field("connect.note", "connect", "Note for users", "longtext", "",
          "Shown at the end of the tab: rules, contact, links", depends="connect.enabled"),

    Field("update.enabled", "update", "Notify admins about updates", "bool", True,
          "Asks GitHub once an hour whether a newer version exists. Nothing is installed automatically."),
    Field("update.repo", "update", "GitHub repository", "text", "dhartmann1979/HBlink4-FreeRadioID",
          "owner/name", depends="update.enabled"),
    Field("update.branch", "update", "Branch", "text", "main", depends="update.enabled", advanced=True),
    Field("update.interval_hours", "update", "Check every (hours)", "int", 1, min=1, max=168,
          depends="update.enabled", advanced=True),
    Field("update.install_role", "update", "Who may press “Update now”", "choice", "superadmin",
          "Always asks for the password again. Pulls only from the git remote set up on the server.",
          choices=(("superadmin", "Superadmin only"), ("admin", "All admins"), ("nobody", "Nobody (update by hand)")),
          depends="update.enabled"),
    # -- APRS server
    Field("aprs.enabled", "aprs_server", "APRS (map, DAPRS, server)", "bool", False,
          "Off by default. Switches on the map, the station database and the DMR → APRS gateway. "
          "The TCP ports and the uplink below are separate switches."),
    Field("aprs.server_id", "aprs_server", "Server ID (your callsign)", "text", "",
          "Callsign with SSID, e.g. DB0ABC-10. Login name at APRS-IS (the passcode is computed) and name in the packet path.",
          depends="aprs.enabled"),
    Field("aprs.server.enabled", "aprs_server", "Open the APRS-IS ports (TCP)", "bool", False,
          "APRSdroid, Xastir, YAAC, iGates and trackers connect here. Open the ports in the firewall.",
          depends="aprs.enabled"),
    Field("aprs.server.port_filter", "aprs_server", "Filter port", "int", 14580,
          "Clients choose what they get with a filter (r/lat/lon/km …)", min=1, max=65535, depends="aprs.server.enabled"),
    Field("aprs.server.port_full", "aprs_server", "Full-feed port", "int", 10152,
          "Everything the server has, unfiltered. 0 = off", min=0, max=65535, depends="aprs.server.enabled", advanced=True),
    Field("aprs.server.bind", "aprs_server", "Listen address", "text", "",
          "Empty = all addresses (IPv4 and IPv6)", depends="aprs.server.enabled", advanced=True),
    Field("aprs.server.max_clients", "aprs_server", "Max. clients", "int", 200, min=1, max=5000,
          depends="aprs.server.enabled", advanced=True),
    Field("aprs.server.dupe_seconds", "aprs_server", "Duplicate window (s)", "int", 30,
          "The same packet again within this time is dropped (APRS-IS standard: 30 s)", min=5, max=300, advanced=True),

    # -- uplink & downlink
    Field("aprs.uplink.enabled", "aprs_uplink", "Uplink & downlink", "bool", False,
          "Connect this server to an APRS network: positions from DMR go up, stations from there come down onto the map."),
    Field("aprs.uplink.mode", "aprs_uplink", "Network", "choice", "aprsis",
          choices=(("aprsis", "🌍 APRS-IS (amateur radio, worldwide)"), ("cbaprs", "📻 CB-APRS (CB radio, eu.cbaprs.net)"),
                   ("manual", "🛠️ Manual – own servers, several links, up/down separately")),
          depends="aprs.uplink.enabled"),
    Field("aprs.uplink.aprsis.host", "aprs_uplink", "APRS-IS server", "text", "euro.aprs2.net",
          "euro.aprs2.net (Europe), rotate.aprs2.net (worldwide) or your own Tier-2 server", depends="aprs.uplink.enabled"),
    Field("aprs.uplink.aprsis.port", "aprs_uplink", "Port", "int", 14580, min=1, max=65535, depends="aprs.uplink.enabled"),
    Field("aprs.uplink.aprsis.filter", "aprs_uplink", "Downlink filter", "text", "r/51.2/10.4/450",
          "What comes down: r/lat/lon/km = radius around a point (default: Germany). Empty = nothing comes down.",
          depends="aprs.uplink.enabled"),
    Field("aprs.uplink.cbaprs.host", "aprs_uplink", "CB-APRS server", "text", "eu.cbaprs.net",
          "eu.cbaprs.net (Europe) or us.cbaprs.net", depends="aprs.uplink.enabled"),
    Field("aprs.uplink.cbaprs.port", "aprs_uplink", "Port", "int", 27235, min=1, max=65535, depends="aprs.uplink.enabled"),
    Field("aprs.uplink.cbaprs.login", "aprs_uplink", "Login (CB callsign)", "text", "",
          "Empty = the server ID", depends="aprs.uplink.enabled"),
    Field("aprs.uplink.cbaprs.passcode", "aprs_uplink", "Passcode", "text", "",
          "Empty = computed from the login; -1 = receive only", depends="aprs.uplink.enabled"),
    Field("aprs.uplink.cbaprs.filter", "aprs_uplink", "Downlink filter", "text", "r/51.2/10.4/450",
          "What comes down from CB-APRS. Empty = nothing", depends="aprs.uplink.enabled"),
    Field("aprs.uplink.manual", "aprs_uplink", "Links", "json", [],
          "One row per server: host, port, login, passcode (empty = computed), filter and direction", depends="aprs.uplink.enabled"),

    # -- DAPRS gateway
    Field("daprs.enabled", "aprs_daprs", "DMR positions become APRS positions", "bool", True,
          "Positions the DMR server finds (DAPRS) go onto the map as CALL-SSID; the callsign comes from the ID list"),
    Field("daprs.to_aprsis", "aprs_daprs", "Send them up (uplink)", "bool", True,
          "Only while the uplink is connected and verified", depends="daprs.enabled"),
    Field("daprs.block_guests", "aprs_daprs", "Not for guests", "bool", True,
          "Stations logged in with the guest password (FreeRadioID) only appear on the local map", depends="daprs.enabled"),
    Field("daprs.ssid", "aprs_daprs", "SSID", "int", 7, "CALL-7 for a handheld; 0 = no SSID. Per ID below.",
          min=0, max=15, depends="daprs.enabled"),
    Field("daprs.symbol", "aprs_daprs", "Symbol", "text", "/[",
          "Table and symbol code: /[ person, /> car, /k truck, /b bike, /- house, /r antenna", depends="daprs.enabled"),
    Field("daprs.comment", "aprs_daprs", "Comment", "text", "DMR TG{tg}",
          "Placeholders: {tg} talkgroup, {repeater} hotspot/repeater callsign, {dmrid}, {slot}, {server}",
          depends="daprs.enabled"),
    Field("daprs.min_interval", "aprs_daprs", "Up at most every (s)", "int", 60,
          "Per station. The local map always shows the newest position.", min=10, max=3600, depends="daprs.enabled"),
    Field("daprs.overrides", "aprs_daprs", "Per DMR ID", "json", [],
          "Own callsign, SSID, symbol or comment for single IDs, or switch one off", depends="daprs.enabled"),
    Field("daprs.objects.repeaters", "aprs_daprs", "Repeaters on the map", "bool", True,
          "As APRS objects at the position they report at login, with frequency and colour code"),
    Field("daprs.objects.hotspots", "aprs_daprs", "Hotspots on the map", "bool", False,
          "Hotspot positions are often home addresses – off by default"),
    Field("daprs.objects.to_aprsis", "aprs_daprs", "Send these objects up (uplink)", "bool", False),
    Field("daprs.objects.interval_min", "aprs_daprs", "Object beacon every (min)", "int", 30, min=5, max=240,
          advanced=True),
    Field("daprs.objects.comment", "aprs_daprs", "Object comment", "text", "DMR",
          "After frequency and colour code", advanced=True),
    Field("daprs.objects.repeater_symbol", "aprs_daprs", "Repeater symbol", "text", "/r", advanced=True),
    Field("daprs.objects.hotspot_symbol", "aprs_daprs", "Hotspot symbol", "text", "/n", advanced=True),

    # -- map
    Field("aprs.map.public", "aprs_map", "Map visible without login", "bool", True,
          "Independent of the dashboard: the map can be public while the dashboard is not"),
    Field("aprs.map.dashboard_tab", "aprs_map", "APRS tab in the dashboard", "bool", True),
    Field("aprs.map.sources", "aprs_map", "Stations on the map", "choice", "all",
          choices=(("all", "All (DMR, own clients and downlink)"), ("local", "Only DMR and own clients"))),
    Field("aprs.map.max_age_hours", "aprs_map", "Show stations of the last (h)", "int", 24, min=1, max=168),
    Field("aprs.map.center", "aprs_map", "Map centre (lat, lon)", "text", "51.2, 10.4",
          "Where the map opens, e.g. 52.29, 8.92"),
    Field("aprs.map.zoom", "aprs_map", "Zoom", "int", 6, "2 = world, 6 = Germany, 10 = region", min=2, max=18),
    Field("aprs.map.tiles", "aprs_map", "Map style", "choice", "auto",
          choices=(("auto", "Automatic – dark map for dark colour profiles, light map for Daylight"),
                   ("dark", "Dark (OpenStreetMap, darkened) – fits the N8 design"), ("osm", "OpenStreetMap"),
                   ("topo", "Topographic (OpenTopoMap)"), ("custom", "Own tile server"))),
    Field("aprs.map.tile_url", "aprs_map", "Own tile URL", "text", "",
          "https://…/{z}/{x}/{y}.png – only for \"Own tile server\" (e.g. with your own API key)", advanced=True),
    Field("aprs.map.tile_max_zoom", "aprs_map", "Highest zoom of the own tile server", "int", 18,
          "Further in the tiles are enlarged instead of missing (OpenStreetMap 19, OpenTopoMap 17 – set automatically)",
          min=10, max=22, advanced=True),
    Field("aprs.map.tracks", "aprs_map", "Show tracks", "bool", True, "Line of the last positions of moving stations"),
    Field("aprs.map.show_packets", "aprs_map", "Show raw packets", "bool", True,
          "Packet log under the map and in the station window"),
    Field("aprs.map.station_days", "aprs_map", "Keep stations (days)", "int", 30, "SQLite, at most 90 days",
          min=1, max=90, advanced=True),
    Field("aprs.map.track_days", "aprs_map", "Keep tracks (days)", "int", 30, "SQLite, at most 90 days",
          min=1, max=90, advanced=True),
    Field("aprs.map.packet_days", "aprs_map", "Keep raw packets (days)", "int", 7, "SQLite, at most 90 days",
          min=1, max=90, advanced=True),

    Field("aprs.site1.domain", "aprs_sites", "Domain 1", "text", "",
          "e.g. aprs.example.org – opens the map at /. Must point to this server (DNS). Empty = off",
          restart=True),
    Field("aprs.site1.https", "aprs_sites", "Domain 1: HTTPS with Let's Encrypt", "bool", True,
          "Goes into the certificate of the dashboard (Settings → HTTPS & web must be on)", restart=True),
    Field("aprs.site1.title", "aprs_sites", "Title 1", "text", "", "Empty = title of the dashboard"),
    Field("aprs.site1.subtitle", "aprs_sites", "Subtitle 1", "text", "", "Empty = APRS map · domain"),
    Field("aprs.site1.logo", "aprs_sites", "Logo 1", "image", "", "Empty = N8schicht APRS logo"),
    Field("aprs.site2.domain", "aprs_sites", "Domain 2", "text", "",
          "e.g. aprs2.example.org – opens the map at /. Must point to this server (DNS). Empty = off",
          restart=True),
    Field("aprs.site2.https", "aprs_sites", "Domain 2: HTTPS with Let's Encrypt", "bool", True,
          "Goes into the certificate of the dashboard (Settings → HTTPS & web must be on)", restart=True),
    Field("aprs.site2.title", "aprs_sites", "Title 2", "text", "", "Empty = title of the dashboard"),
    Field("aprs.site2.subtitle", "aprs_sites", "Subtitle 2", "text", "", "Empty = APRS map · domain"),
    Field("aprs.site2.logo", "aprs_sites", "Logo 2", "image", "", "Empty = N8schicht APRS logo"),
    Field("aprs.site3.domain", "aprs_sites", "Domain 3", "text", "",
          "e.g. map.example.org – opens the map at /. Must point to this server (DNS). Empty = off",
          restart=True),
    Field("aprs.site3.https", "aprs_sites", "Domain 3: HTTPS with Let's Encrypt", "bool", True,
          "Goes into the certificate of the dashboard (Settings → HTTPS & web must be on)", restart=True),
    Field("aprs.site3.title", "aprs_sites", "Title 3", "text", "", "Empty = title of the dashboard"),
    Field("aprs.site3.subtitle", "aprs_sites", "Subtitle 3", "text", "", "Empty = APRS map · domain"),
    Field("aprs.site3.logo", "aprs_sites", "Logo 3", "image", "", "Empty = N8schicht APRS logo"),

    Field("https.enabled", "https", "HTTPS with Let's Encrypt", "bool", False,
          "Needs certbot, the domain pointing here and ports 80/443 open", restart=True),
    Field("https.domain", "https", "Domain", "text", "", restart=True, depends="https.enabled"),
    Field("https.email", "https", "E-mail for Let's Encrypt", "text", "", restart=True, depends="https.enabled"),
    Field("https.staging", "https", "Test certificates (staging)", "bool", False, restart=True,
          depends="https.enabled", advanced=True),
    Field("https.port", "https", "HTTPS port", "int", 443, restart=True, min=1, max=65535,
          depends="https.enabled", advanced=True),
    Field("https.http_port", "https", "HTTP port (challenge + redirect)", "int", 80, restart=True, min=1, max=65535,
          depends="https.enabled", advanced=True),
    Field("web.port", "https", "Plain web port", "int", 8080,
          "Redirects to HTTPS when HTTPS is on", restart=True, min=1, max=65535, advanced=True),
]

FIELDS: List[Field] = DASH_FIELDS + DMR_FIELDS
FIELD_BY_KEY: Dict[str, Field] = {f.key: f for f in FIELDS}
SECTIONS: List[Tuple[str, str]] = DASH_SECTIONS + DMR_SECTIONS

# Values of the original HBlink4 sample configs that nobody chose on purpose
_UPSTREAM_DEFAULTS = {
    "dashboard_title": ("HBlink4 Dashboard",),
    "server_name": ("HBlink4 Server",),
    "server_description": ("Amateur Radio DMR Network",),
    "user_database.filter.countries": (["United States", "Canada"],),
    "user_database.source_url": (RADIOID_URL,),
}
# Values seeded by an older version that switch to the new default as long as
# no admin changed them (updated_by is still the config file)
_MIGRATE_UNTOUCHED = {
    "user_database.source_url": (RADIOID_URL,),
    "user_database.filter.countries": (["United States", "Canada"],),
}
_SEED_SOURCES = ("config.json", "config/config.json", "dashboard/config.json")


_DOMAIN_RE = re.compile(r"^(?=.{4,253}$)([a-z0-9-]{1,63}\.)+[a-z]{2,63}$")
_CALL_RE = re.compile(r"^[A-Z0-9]{3,9}(-[A-Z0-9]{1,2})?$")


def _check_aprs(clean: Dict[str, Any]) -> None:
    """APRS values that the generic field types cannot check."""
    for key in list(clean):
        v = clean[key]
        if key.startswith("aprs.site") and key.endswith(".domain") and v:
            v = v.strip().lower().rstrip(".")
            if not _DOMAIN_RE.match(v):
                raise SettingsError(f"{FIELD_BY_KEY[key].label}: not a domain name (e.g. aprs.example.org).")
            clean[key] = v
        elif key == "aprs.server_id" and v:
            v = v.strip().upper()
            if not _CALL_RE.match(v):
                raise SettingsError("Server ID: a callsign with optional SSID, e.g. DB0ABC-10.")
            clean[key] = v
        elif key in ("daprs.symbol", "daprs.objects.repeater_symbol", "daprs.objects.hotspot_symbol") and v:
            if len(v) != 2 or not (v[0] in "/\\" or v[0].isalnum()) or not 33 <= ord(v[1]) <= 126:
                raise SettingsError(f"{FIELD_BY_KEY[key].label}: two characters, table and code, e.g. /[ or /r.")
        elif key == "aprs.map.center":
            try:
                lat, lon = (float(x) for x in v.replace(";", ",").split(","))
                if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                    raise ValueError
            except ValueError:
                raise SettingsError("Map centre: latitude, longitude – e.g. 52.29, 8.92")
        elif key in ("aprs.uplink.aprsis.filter", "aprs.uplink.cbaprs.filter") and v:
            from .aprs.filters import FilterSet, FilterError
            try:
                FilterSet(v)
            except FilterError as e:
                raise SettingsError(f"APRS-IS filter: {e}")
        elif key == "aprs.uplink.cbaprs.passcode" and v:
            if not re.fullmatch(r"-1|\d{1,5}", v.strip()):
                raise SettingsError("CB-APRS passcode: a number, -1 or empty.")
            clean[key] = v.strip()
        elif key == "aprs.uplink.manual":
            out = []
            for i, o in enumerate(v[:10], 1):
                host = str(o.get("host") or "").strip()
                if not host:
                    continue
                if not re.fullmatch(r"[A-Za-z0-9.:-]{1,253}", host):
                    raise SettingsError(f"Link {i}: invalid host.")
                try:
                    port = int(o.get("port") or 14580)
                except (TypeError, ValueError):
                    port = 0
                if not 1 <= port <= 65535:
                    raise SettingsError(f"Link {i}: port 1–65535.")
                login = str(o.get("login") or "").strip().upper()
                if login and not _CALL_RE.match(login):
                    raise SettingsError(f"Link {i}: login is a callsign, e.g. DB0ABC-10 (empty = server ID).")
                pc = str(o.get("passcode") if o.get("passcode") is not None else "").strip()
                if pc and not re.fullmatch(r"-1|\d{1,5}", pc):
                    raise SettingsError(f"Link {i}: passcode is a number, -1 or empty.")
                flt = str(o.get("filter") or "").strip()
                if flt:
                    from .aprs.filters import FilterSet, FilterError
                    try:
                        FilterSet(flt)
                    except FilterError as e:
                        raise SettingsError(f"Link {i}: filter {e}")
                direction = str(o.get("direction") or "both")
                if direction not in ("both", "up", "down"):
                    raise SettingsError(f"Link {i}: direction both, up or down.")
                out.append({"name": str(o.get("name") or host)[:30], "host": host, "port": port, "login": login,
                            "passcode": pc, "filter": flt, "direction": direction, "enabled": o.get("enabled", True) is not False})
            clean[key] = out
        elif key == "daprs.overrides":
            out = []
            for i, o in enumerate(v[:500], 1):
                try:
                    rid = int(o.get("dmr_id"))
                except (TypeError, ValueError):
                    raise SettingsError(f"Per DMR ID: entry {i} has no valid dmr_id.")
                item: Dict[str, Any] = {"dmr_id": rid}
                if o.get("callsign"):
                    cs = str(o["callsign"]).strip().upper()
                    if not re.match(r"^[A-Z0-9]{3,7}$", cs):
                        raise SettingsError(f"Per DMR ID {rid}: callsign without SSID, e.g. DL1ABC.")
                    item["callsign"] = cs
                if o.get("ssid") not in (None, ""):
                    try:
                        ssid = int(o["ssid"])
                    except (TypeError, ValueError):
                        ssid = -1
                    if not 0 <= ssid <= 15:
                        raise SettingsError(f"Per DMR ID {rid}: SSID 0–15.")
                    item["ssid"] = ssid
                if o.get("symbol"):
                    sym = str(o["symbol"])
                    if len(sym) != 2:
                        raise SettingsError(f"Per DMR ID {rid}: symbol is two characters, e.g. /> .")
                    item["symbol"] = sym
                if o.get("comment"):
                    item["comment"] = str(o["comment"])[:60]
                if o.get("off"):
                    item["off"] = True
                out.append(item)
            clean[key] = out


class SettingsStore:
    def __init__(self, auth_store, dmr_file_cfg: Optional[Dict[str, Any]] = None):
        """Shares the dashboard database (and its lock) with AuthStore."""
        self._a = auth_store
        self.db = SettingsDB(auth_store._q, auth_store._x)
        self._dmr_file_cfg = dmr_file_cfg or {}

    # -- startup -------------------------------------------------------------
    def seed_and_apply(self, cfg: Dict[str, Any]) -> int:
        """
        First start: store every missing setting (dashboard fields from cfg =
        dashboard/config.json, DMR fields from config/config.json). Then apply
        the dashboard fields over cfg. Returns how many were seeded.
        """
        self._migrate_untouched()
        n = self.db.seed(DASH_FIELDS, cfg, "dashboard/config.json", self._fixup_with_cfg(cfg))
        n += self.db.seed(DMR_FIELDS, self._dmr_file_cfg, "config/config.json")
        self.db.apply(DASH_FIELDS, cfg)
        return n

    @staticmethod
    def _fixup_with_cfg(cfg):
        def fix(f: Field, raw: Any) -> Any:
            if f.key == "freeradioid.avatars" and get_path(cfg, "freeradioid.avatar_url", None) == "":
                return False   # old config switched avatars off with an empty URL
            if raw in _UPSTREAM_DEFAULTS.get(f.key, ()):
                return f.default
            return raw
        return fix

    def _migrate_untouched(self) -> None:
        meta = self.db.meta()
        stored = self.db.stored()
        for key, old_values in _MIGRATE_UNTOUCHED.items():
            if key in stored and stored[key] in old_values and meta.get(key, (0, ""))[1] in _SEED_SOURCES:
                self.db.write(key, FIELD_BY_KEY[key].default, "default")

    # -- admin area ----------------------------------------------------------
    def dmr_values(self) -> Dict[str, Any]:
        stored = self.db.stored()
        return {f.key: stored.get(f.key, f.default) for f in DMR_FIELDS}

    def describe(self, cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
        meta = self.db.meta()
        stored = self.db.stored()
        sections = []
        for sid, title in SECTIONS:
            fields = []
            for f in FIELDS:
                if f.section != sid:
                    continue
                value = stored.get(f.key, f.default) if f.is_dmr else get_path(cfg, f.key, f.default)
                ts, by = meta.get(f.key, (None, ""))
                fields.append({"key": f.key, "label": f.label, "kind": f.kind, "help": f.help,
                               "restart": f.restart, "choices": [list(c) for c in f.choices],
                               "min": f.min, "max": f.max, "value": value, "default": f.default,
                               "depends": f.depends, "advanced": f.advanced,
                               "updated_at": ts, "updated_by": by})
            sections.append({"id": sid, "title": title, "dmr": sid.startswith("dmr_"),
                             "help": SECTION_HELP.get(sid, ""), "fields": fields})
        return sections

    def update(self, cfg: Dict[str, Any], changes: Dict[str, Any], who: str) -> List[str]:
        """Validate everything first, then store. Returns the keys that changed."""
        clean = {}
        for key, raw in changes.items():
            f = FIELD_BY_KEY.get(key)
            if not f:
                raise SettingsError(f"Unknown setting {key}.")
            clean[key] = validate(f, raw)
        _check_aprs(clean)
        self._check_dmr_structure(clean)
        stored = self.db.stored()
        changed = []
        for key, value in clean.items():
            f = FIELD_BY_KEY[key]
            old = stored.get(key) if f.is_dmr else get_path(cfg, key)
            if old != value:
                changed.append(key)
            self.db.write(key, value, who)
            if not f.is_dmr:
                set_path(cfg, key, value)
        return changed

    def _check_dmr_structure(self, clean: Dict[str, Any]) -> None:
        """Patterns, blacklist and trunks must be understood by HBlink4 before they are saved."""
        if "dmr.openbridge_connections" in clean:
            from hblink4.config import parse_openbridge_connections
            try:
                parse_openbridge_connections({"openbridge_connections": clean["dmr.openbridge_connections"]},
                                             raise_errors=True)
            except ValueError as e:
                raise SettingsError(f"OpenBridge: {e}")
        if "dmr.outbound_connections" in clean:
            from hblink4.config import parse_outbound_connections
            try:
                parse_outbound_connections({"outbound_connections": clean["dmr.outbound_connections"]},
                                           raise_errors=True)
            except ValueError as e:
                raise SettingsError(f"Links: {e}")
        if not any(k.startswith("dmr.repeater_configurations") or k.startswith("dmr.blacklist") for k in clean):
            return
        trial: Dict[str, Any] = {}
        merged = {**self.dmr_values(), **clean}
        for f in DMR_FIELDS:
            set_path(trial, f.path, merged.get(f.key, f.default))
        try:
            from hblink4.access_control import RepeaterMatcher
            RepeaterMatcher(trial)
        except Exception as e:
            raise SettingsError(f"Patterns/blacklist not accepted by HBlink4: {e}")

    def reset_section(self, cfg: Dict[str, Any], file_cfg: Dict[str, Any], section: str, who: str) -> None:
        """Drop the stored values of a section and seed them again from its config file."""
        fields = [f for f in FIELDS if f.section == section]
        if not fields:
            raise SettingsError("Unknown section.")
        for f in fields:
            self.db.delete(f.key)
        if fields[0].is_dmr:
            self.db.seed(fields, self._dmr_file_cfg, "config/config.json")
        else:
            fresh = copy.deepcopy(file_cfg)
            self.db.seed(fields, fresh, "dashboard/config.json", self._fixup_with_cfg(fresh))
            self.db.apply(fields, cfg)
