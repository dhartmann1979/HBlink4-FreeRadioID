"""
APRS server of the dashboard (dashboard/aprs/): packets, filters, the APRS-IS
server over real TCP sockets, the uplink, DAPRS gateway, objects, settings,
certificate names and the map API.
"""
import asyncio
import copy
import socket
import tempfile
import time
import unittest
from pathlib import Path

from dashboard.aprs import packet as P
from dashboard.aprs.filters import FilterError, FilterSet, addressed_to
from dashboard.aprs.service import AprsService
from dashboard.aprs.store import AprsStore


class TestPacket(unittest.TestCase):
    def test_passcode(self):
        self.assertEqual(P.passcode("N0CALL"), 13023)
        self.assertEqual(P.passcode("n0call-9"), 13023)          # SSID and case do not matter

    def test_uncompressed_with_extensions(self):
        p = P.parse("DL1ABC-9>APDR16,TCPIP*,qAC,T2GER:=5217.38N/00854.97E>088/036/A=001234 Hallo")
        self.assertEqual((p.type, p.src, p.symbol, p.course), ("position", "DL1ABC-9", "/>", 88))
        self.assertAlmostEqual(p.lat, 52.2897, places=3)
        self.assertAlmostEqual(p.speed_kmh, 66.7, places=1)
        self.assertAlmostEqual(p.altitude_m, 376.1, places=1)
        self.assertEqual(p.comment, "Hallo")
        self.assertTrue(p.messaging)
        self.assertEqual(p.q_construct(), ("qAC", "T2GER"))

    def test_compressed_mice_object_item(self):
        c = P.parse("DK1XX-5>APRS:!/5L!!<*e7>7P[")
        self.assertAlmostEqual(c.lat, 49.5, places=3)
        self.assertAlmostEqual(c.lon, -72.75, places=3)
        self.assertEqual((c.course, c.symbol), (88, "/>"))
        m = P.parse("N0CALL>S32U6T,WIDE1-1:`(_fn\"Oj/]Mic-E")
        self.assertEqual((m.type, m.symbol, m.course), ("position", "/j", 251))
        self.assertAlmostEqual(m.lat, 33.4273, places=3)
        self.assertAlmostEqual(m.lon, -12.129, places=3)
        o = P.parse("DK1XX>APRS:;LEADER   _092345z4903.50N/07201.75W>088/036")
        self.assertEqual((o.type, o.name, o.alive, o.station), ("object", "LEADER", False, "LEADER"))
        i = P.parse("DK1XX>APRS:)AID #2!4903.50N/07201.75WA")
        self.assertEqual((i.type, i.name, i.symbol), ("item", "AID #2", "/A"))

    def test_message_ack_status_weather(self):
        m = P.parse("DK1XX>APRS::DL1ABC-9 :Hello there{12")
        self.assertEqual((m.type, m.msg_to, m.msg_text, m.msg_id), ("message", "DL1ABC-9", "Hello there", "12"))
        a = P.parse("DK1XX>APRS::DL1ABC-9 :ack12")
        self.assertEqual((a.type, a.msg_id), ("ack", "12"))
        self.assertEqual(P.parse("DK1XX>APRS:>Op Klaus").status, "Op Klaus")
        w = P.parse("OE1XYZ>APRS:@092345z4903.50N/07201.75W_220/004g005t077r000p000P000h50b09900wRSW")
        self.assertEqual(w.type, "weather")
        self.assertEqual((w.weather["temp_c"], w.weather["humidity"], w.weather["pressure_hpa"]), (25.0, 50, 990.0))

    def test_invalid(self):
        for bad in ("", "# comment", "no header", "TOOLONGCALL1>APRS:!x", "DL1ABC>APRS,BAD PATH:!x",
                    "DL1ABC>APRS:" + "x" * 600):
            with self.assertRaises(P.APRSError, msg=bad):
                P.parse(bad)

    def test_build_position_and_object(self):
        body = P.position_body(52.28969, 8.91612, "/[", "DMR TG 262", course=84, speed_kmh=23)
        self.assertEqual(body, "!5217.38N/00854.97E[084/012 DMR TG 262")
        p = P.build("DL1ABC-7", body, ["DMR*", "qAS", "DB0N8S-10"])
        self.assertAlmostEqual(p.lat, 52.2897, places=3)
        o = P.parse("DB0N8S>APZN8D:" + P.object_body("DB0QMI", 52.273, 8.918, "/r", "439.175MHz -760 CC1"))
        self.assertEqual((o.type, o.name, o.symbol, o.comment), ("object", "DB0QMI", "/r", "439.175MHz -760 CC1"))

    def test_sanitize_comment(self):
        self.assertEqual(P.sanitize_comment("Grüße aus Münster | ~ TG 262"), "Grusse aus Munster   TG 262")


class TestFilters(unittest.TestCase):
    POS = P.parse("DL1ABC-9>APDR16,DB0XX*,qAR,DB0IG:=5217.38N/00854.97E>moving")

    def lookup(self, call):
        return {"DL9ZZZ": (52.0, 8.5)}.get(call)

    def test_kinds(self):
        cases = {
            "r/52.3/8.9/10": True, "r/48.1/11.5/50": False,
            "a/53/8/52/9": True, "p/DL1": True, "p/DO": False,
            "b/DL1ABC*": True, "b/DL1ABC": False, "t/p": True, "t/m": False,
            "t/p/DL9ZZZ/50": True, "t/p/DL9ZZZ/5": False,
            "s/>": True, "s/[": False, "d/DB0XX": True, "e/DB0IG": True, "u/APDR*": True,
            "f/DL9ZZZ/50": True, "m/50": True, "m/20": False,
        }
        for text, want in cases.items():
            self.assertEqual(FilterSet(text).matches(self.POS, "DL9ZZZ", self.lookup), want, text)

    def test_exclusion_and_errors(self):
        self.assertFalse(FilterSet("r/52.3/8.9/50 -p/DL1").matches(self.POS, "X", self.lookup))
        self.assertFalse(FilterSet("").matches(self.POS, "X", self.lookup))
        for bad in ("x/1", "r/1/2", "r/a/b/c"):
            with self.assertRaises(FilterError):
                FilterSet(bad)

    def test_messages_reach_the_login(self):
        m = P.parse("DK1XX>APRS::DL1ABC-9 :hi{1")
        self.assertTrue(addressed_to(m, "DL1ABC-9"))
        self.assertTrue(addressed_to(m, "DL1ABC"))          # login without SSID gets all SSIDs
        self.assertFalse(addressed_to(m, "DL1ABC-7"))


class TestStore(unittest.TestCase):
    def test_stations_tracks_packets_survive_restart(self):
        path = Path(tempfile.mkdtemp()) / "aprs.db"
        st = AprsStore(path)
        st.add(P.parse("DL1ABC-9>APDR16:=5217.38N/00854.97E>first"), "client")
        st.add(P.parse("DL1ABC-9>APDR16:=5218.38N/00855.97E>second"), "client")
        st.add(P.parse("DL1ABC-9>APDR16:>status text"), "client")
        st.add(P.parse("DK1XX>APRS::DL1ABC-9 :hi{1"), "uplink")   # message: no station
        self.assertEqual(st.stations["DL1ABC-9"]["comment"], "second")
        self.assertEqual(st.stations["DL1ABC-9"]["status"], "status text")
        self.assertNotIn("DK1XX", st.stations)
        st.flush()
        st2 = AprsStore(path)
        self.assertEqual(st2.stations["DL1ABC-9"]["packets"], 3)
        self.assertEqual(len(st2.track("DL1ABC-9", 1)), 2)
        self.assertEqual(len(st2.recent), 4)
        self.assertEqual(len(st2.packets_of("DL1ABC-9")), 3)
        st2.purge(0, 0, 0)
        self.assertEqual(st2.stations, {})


def _cfg(**over):
    cfg = {"aprs": {"enabled": True, "server_id": "DB0N8S-10",
                    "server": {"enabled": True, "port_filter": _free_port(), "port_full": _free_port(), "bind": "127.0.0.1"},
                    "uplink": {"enabled": False}},
           "daprs": {"enabled": True, "ssid": 7, "symbol": "/[", "comment": "DMR TG{tg}", "min_interval": 60,
                     "to_aprsis": True, "block_guests": True, "overrides": [],
                     "objects": {"repeaters": True, "hotspots": False, "to_aprsis": False}}}
    for k, v in over.items():
        cur = cfg
        parts = k.split("__")
        for part in parts[:-1]:
            cur = cur.setdefault(part, {})
        cur[parts[-1]] = v
    return cfg


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class _Conn:
    def __init__(self, r, w):
        self.r, self.w = r, w

    @classmethod
    async def open(cls, port, login):
        r, w = await asyncio.open_connection("127.0.0.1", port)
        c = cls(r, w)
        await c.line()                       # banner
        w.write((login + "\r\n").encode())
        return c

    async def line(self, timeout=2.0):
        return (await asyncio.wait_for(self.r.readline(), timeout)).decode().strip()

    def send(self, text):
        self.w.write((text + "\r\n").encode())

    async def lines_until(self, pred, timeout=2.0):
        end = time.time() + timeout
        seen = []
        while time.time() < end:
            try:
                ln = await self.line(max(0.05, end - time.time()))
            except asyncio.TimeoutError:
                break
            seen.append(ln)
            if pred(ln):
                return seen
        return seen


class TestServer(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.cfg = _cfg()
        self.reps = []
        self.svc = AprsService(lambda: self.cfg, Path(tempfile.mkdtemp()), version="1.2.0",
                               callsign_of={2621234: "DL1ABC", 2625555: "DO7GST"}.get,
                               repeaters=lambda: self.reps)
        await self.svc.start()

    async def asyncTearDown(self):
        await self.svc.stop()
        self.svc.close()

    async def test_login_filter_and_distribution(self):
        fport = self.cfg["aprs"]["server"]["port_filter"]
        full = await _Conn.open(self.cfg["aprs"]["server"]["port_full"], "user DK0FULL pass -1 vers test 1")
        self.assertIn("unverified", await full.line())
        near = await _Conn.open(fport, f"user DL1ABC-9 pass {P.passcode('DL1ABC')} vers APRSdroid 1.6 filter r/52.3/8.9/20")
        self.assertIn("logresp DL1ABC-9 verified, server DB0N8S-10", await near.line())
        far = await _Conn.open(fport, f"user DO9QQQ pass {P.passcode('DO9QQQ')} vers x filter r/48.1/11.5/20")
        await far.line()

        near.send("DL1ABC-9>APDR16,TCPIP*:=5217.38N/00854.97E>hello")     # from the client itself: qAC
        got = await full.lines_until(lambda l: "hello" in l)
        self.assertIn("DL1ABC-9>APDR16,TCPIP*,qAC,DB0N8S-10:=5217.38N/00854.97E>hello", got)
        near.send("DL1ABC-9>APDR16,TCPIP*:=5217.38N/00854.97E>hello")     # duplicate within 30 s
        far.send("DO1RF>APRS,WIDE1-1:!5218.00N/00855.00E-gated from RF")   # igate: qAR,<login>
        got = await near.lines_until(lambda l: "gated from RF" in l)
        self.assertIn("DO1RF>APRS,WIDE1-1,qAR,DO9QQQ:!5218.00N/00855.00E-gated from RF", got)
        self.assertNotIn("hello", " ".join(await far.lines_until(lambda l: False, 0.4)))   # outside the far filter
        self.assertEqual(self.svc.stats["dupes"], 1)

        # unverified clients may listen but not send
        full.send("DK0FULL>APRS:!5000.00N/00800.00E-x")
        await asyncio.sleep(0.2)
        self.assertEqual(self.svc.stats["unverified_dropped"], 1)
        # messages reach their addressee even outside the filter; #filter changes the filter
        near.send("DL1ABC-9>APDR16,TCPIP*::DO9QQQ   :Hallo{7")
        got = await far.lines_until(lambda l: ":Hallo{7" in l)
        self.assertTrue(any(":DO9QQQ   :Hallo{7" in l for l in got))
        far.send("#filter p/DL1")
        self.assertIn("filter p/DL1 active", " ".join(await far.lines_until(lambda l: "active" in l)))
        for c in (full, near, far):
            c.w.close()

    async def test_daprs_positions(self):
        port = self.cfg["aprs"]["server"]["port_full"]
        feed = await _Conn.open(port, "user DK0FULL pass -1 vers test 1")
        await feed.line()
        ev = {"radio_id": 2621234, "lat": 52.2897, "lon": 8.9161, "source": "embedded", "slot": 2, "dst_id": 262,
              "group": True, "repeater_callsign": "DB0QMI", "auth_method": "freeradioid", "speed_kmh": 30, "course": 90}
        p = self.svc.on_gps(ev)
        self.assertEqual(p.raw, "DL1ABC-7>APZN8D,DMR*,qAS,DB0N8S-10:!5217.38N/00854.97E[090/016 DMR TG262")
        got = await feed.lines_until(lambda l: l.startswith("DL1ABC-7>"))
        self.assertTrue(got and got[-1].startswith("DL1ABC-7>APZN8D"))
        st = self.svc.store.stations["DL1ABC-7"]
        self.assertEqual((st["source"], st["dmr_id"], st["tg"], st["via"], st["gps"]), ("dmr", 2621234, 262, "DB0QMI", "embedded"))
        # unknown ID: nothing; override: own callsign, SSID, symbol; switched off ID: nothing
        self.assertIsNone(self.svc.on_gps({**ev, "radio_id": 2629999}))
        self.cfg["daprs"]["overrides"] = [{"dmr_id": 2625555, "callsign": "DL9QAA", "ssid": 9, "symbol": "/>"},
                                          {"dmr_id": 2621234, "off": True}]
        q = self.svc.on_gps({**ev, "radio_id": 2625555, "lat": 52.0})
        self.assertTrue(q.raw.startswith("DL9QAA-9>APZN8D,DMR*,qAS,DB0N8S-10:!5200.00N/00854.97E>"))
        self.assertIsNone(self.svc.on_gps({**ev, "lat": 52.5}))
        feed.w.close()

    async def test_daprs_gating_rules(self):
        """To APRS-IS only when connected, not for guests, at most every min_interval."""
        sent = []
        self.svc._to_uplink = lambda p: sent.append(p.raw)
        self.svc.uplink_ready = lambda: True
        ev = {"radio_id": 2621234, "lat": 52.2, "lon": 8.9, "dst_id": 262, "auth_method": "freeradioid"}
        self.svc.on_gps(ev)
        self.svc.on_gps({**ev, "lat": 52.3})                       # within 60 s
        self.svc.on_gps({**ev, "radio_id": 2625555, "auth_method": "guest"})
        self.assertEqual(len(sent), 1)
        self.assertIn("DO7GST-7", self.svc.store.stations)          # guest: on the local map anyway
        self.svc.uplink_ready = lambda: False
        self.svc._daprs_last.clear()
        self.svc.on_gps({**ev, "lat": 52.4})
        self.assertEqual(len(sent), 1)

    async def test_repeater_objects(self):
        self.reps = [{"repeater_id": 262916, "callsign": "DB0QMI", "connection_type": "repeater",
                      "latitude": "52.2730", "longitude": "8.9180", "tx_freq": "439175000", "rx_freq": "431575000",
                      "colorcode": "1", "location": "Minden"},
                     {"repeater_id": 263123401, "callsign": "DL1ABC", "connection_type": "hotspot",
                      "latitude": "52.24", "longitude": "8.93", "tx_freq": "430412500", "rx_freq": "430412500"},
                     {"repeater_id": 262917, "callsign": "DB0NUL", "connection_type": "repeater",
                      "latitude": "0.0000", "longitude": "0.0000"}]
        self.assertEqual(self.svc.object_pass(), 1)              # hotspots off, 0/0 ignored
        st = self.svc.store.stations["DB0QMI"]
        self.assertEqual((st["kind"], st["source"], st["owner"], st["alive"]), ("object", "rpt", "DB0N8S-10", True))
        self.assertTrue(st["comment"].startswith("439.175MHz -760 CC1"))
        self.assertEqual(self.svc.object_pass(), 0)              # not due again yet
        self.cfg["daprs"]["objects"]["hotspots"] = True
        self.assertEqual(self.svc.object_pass(), 1)
        self.assertIn("DL1ABC-01", self.svc.store.stations)
        self.reps = []                                           # both left: objects are killed
        self.svc.object_pass()
        self.assertFalse(self.svc.store.stations["DB0QMI"]["alive"])

    async def test_uplink(self):
        """Login with passcode and filter, packets in both directions, no echo back."""
        received, logins = [], []

        async def upstream(r, w):
            w.write(b"# aprsc test\r\n")
            logins.append((await r.readline()).decode().strip())
            w.write(b"# logresp DB0N8S-10 verified, server T2TEST\r\n")
            w.write(b"DK9QWX-13>APRS,TCPIP*,qAC,T2GER:!5157.40N/00839.20E_wx\r\n")
            await w.drain()
            while True:
                ln = await r.readline()
                if not ln:
                    break
                received.append(ln.decode().strip())

        srv = await asyncio.start_server(upstream, "127.0.0.1", 0)
        port = srv.sockets[0].getsockname()[1]
        self.cfg["aprs"]["uplink"] = {"enabled": True, "mode": "aprsis",
                                      "aprsis": {"host": "127.0.0.1", "port": port, "filter": "r/52/9/100"}}
        await self.svc.reload()
        for _ in range(50):
            if self.svc.uplink_ready() and "DK9QWX-13" in self.svc.store.stations:
                break
            await asyncio.sleep(0.05)
        self.assertEqual(logins, [f"user DB0N8S-10 pass {P.passcode('DB0N8S')} vers N8-APRS 1.2.0 filter r/52/9/100"])
        self.assertEqual(self.svc.store.stations["DK9QWX-13"]["source"], "aprsis")
        self.svc.on_gps({"radio_id": 2621234, "lat": 52.2, "lon": 8.9, "dst_id": 262, "auth_method": "local"})
        for _ in range(40):
            if received:
                break
            await asyncio.sleep(0.05)
        self.assertEqual(len(received), 1)
        self.assertTrue(received[0].startswith("DL1ABC-7>APZN8D,DMR*,qAS,DB0N8S-10:"))
        self.assertEqual(self.svc.status()["uplink"]["server_name"], "T2TEST")
        srv.close()

    async def test_cbaprs_and_manual_links(self):
        """CB-APRS with its own login/passcode; manual links with direction up / down."""
        logins = {}
        got = {"A": [], "B": []}

        def make(name, feed):
            async def handler(r, w):
                w.write(b"# test\r\n")
                login = (await r.readline()).decode().strip()
                logins[name] = login
                ok = "pass -1" not in login
                w.write(f"# logresp X {'verified' if ok else 'unverified'}, server {name}\r\n".encode())
                if feed:
                    w.write((feed + "\r\n").encode())
                await w.drain()
                while True:
                    ln = await r.readline()
                    if not ln:
                        break
                    got[name].append(ln.decode().strip())
            return handler

        a = await asyncio.start_server(make("A", "DO1AA>APRS:!5200.00N/00800.00E-from A"), "127.0.0.1", 0)
        b = await asyncio.start_server(make("B", "DO1BB>APRS:!5201.00N/00801.00E-from B"), "127.0.0.1", 0)
        pa, pb = a.sockets[0].getsockname()[1], b.sockets[0].getsockname()[1]
        self.cfg["aprs"]["uplink"] = {"enabled": True, "mode": "cbaprs",
                                      "cbaprs": {"host": "127.0.0.1", "port": pa, "login": "EIFEL", "passcode": "",
                                                 "filter": "r/50/7/300"}}
        await self.svc.reload()
        for _ in range(40):
            if self.svc.uplink_ready():
                break
            await asyncio.sleep(0.05)
        self.assertEqual(logins["A"], f"user EIFEL pass {P.passcode('EIFEL')} vers N8-APRS 1.2.0 filter r/50/7/300")
        self.assertEqual(self.svc.network_label, "CB-APRS")

        logins.clear()
        self.svc.store.stations.clear()
        self.cfg["aprs"]["uplink"] = {"enabled": True, "mode": "manual", "manual": [
            {"name": "A", "host": "127.0.0.1", "port": pa, "direction": "up", "filter": "r/50/7/300"},
            {"name": "B", "host": "127.0.0.1", "port": pb, "direction": "down", "passcode": "-1", "filter": "r/50/7/300"},
            {"name": "off", "host": "127.0.0.1", "port": 1, "enabled": False}]}
        await self.svc.reload()
        for _ in range(60):
            if len(logins) == 2 and "DO1BB" in self.svc.store.stations:
                break
            await asyncio.sleep(0.05)
        self.assertEqual(len(self.svc.links), 2)
        self.assertNotIn("filter", logins["A"])                  # up only: no downlink filter
        self.assertIn("pass -1", logins["B"])
        self.assertIn("DO1BB", self.svc.store.stations)          # down link: received
        self.assertNotIn("DO1AA", self.svc.store.stations)       # up-only link: ignored
        self.svc.on_gps({"radio_id": 2621234, "lat": 52.2, "lon": 8.9, "dst_id": 262, "auth_method": "local"})
        await asyncio.sleep(0.3)
        self.assertEqual(len(got["A"]), 1)                       # only up-capable link gets it
        self.assertEqual(got["B"], [])
        a.close()
        b.close()

    async def test_without_server_id_nothing_listens(self):
        self.cfg["aprs"]["server_id"] = ""
        await self.svc.reload()
        self.assertEqual(self.svc.listening, [])
        self.assertTrue(any("server ID" in m for _, m in self.svc.errors))


class TestAprsSettings(unittest.TestCase):
    def setUp(self):
        from dashboard.auth import AuthStore
        from dashboard.settings import SettingsStore
        a = AuthStore(Path(tempfile.mkdtemp()) / "s.db")
        self.st = SettingsStore(a)
        self.cfg = {}
        self.st.seed_and_apply(self.cfg)

    def test_defaults(self):
        self.assertFalse(self.cfg["aprs"]["enabled"])                # APRS is off until switched on
        self.assertFalse(self.st.dmr_values()["dmr.daprs.enabled"])
        self.assertFalse(self.cfg["aprs"]["server"]["enabled"])       # TCP ports closed until switched on
        self.assertFalse(self.cfg["aprs"]["uplink"]["enabled"])
        self.assertFalse(self.cfg["daprs"]["objects"]["hotspots"])    # home addresses
        self.assertEqual([self.cfg["aprs"][f"site{n}"]["domain"] for n in (1, 2, 3)], ["", "", ""])
        self.assertEqual(self.cfg["aprs"]["uplink"]["mode"], "aprsis")
        self.assertEqual(self.cfg["aprs"]["uplink"]["cbaprs"]["port"], 27235)
        self.assertIsNone(self.st.dmr_values()["dmr.daprs.data_ids"])

    def test_validation(self):
        from dashboard.settings import SettingsError
        ch = self.st.update(self.cfg, {"aprs.server_id": "db0n8s-10", "aprs.site1.domain": "APRS.Example.org.",
                                       "daprs.overrides": '[{"dmr_id": "2621234", "callsign": "dl1abc", "ssid": "9"}]'}, "t")
        self.assertEqual(len(ch), 3)
        self.assertEqual(self.cfg["aprs"]["server_id"], "DB0N8S-10")
        self.assertEqual(self.cfg["aprs"]["site1"]["domain"], "aprs.example.org")
        self.assertEqual(self.cfg["daprs"]["overrides"], [{"dmr_id": 2621234, "callsign": "DL1ABC", "ssid": 9}])
        for bad in ({"aprs.server_id": "not a call"}, {"aprs.site2.domain": "http://x"}, {"daprs.symbol": "x"},
                    {"aprs.map.center": "north"}, {"aprs.uplink.aprsis.filter": "r/1/2"},
                    {"aprs.uplink.manual": '[{"host": "x y", "port": 1}]'}, {"aprs.uplink.manual": '[{"host": "a.b", "direction": "sideways"}]'},
                    {"aprs.map.packet_days": 91},
                    {"daprs.overrides": '[{"dmr_id": 1, "ssid": 99}]'}):
            with self.assertRaises(SettingsError, msg=bad):
                self.st.update(self.cfg, bad, "t")


class TestCertNames(unittest.IsolatedAsyncioTestCase):
    async def test_extra_names_need_dns_pointing_here(self):
        from dashboard.tls import CertManager
        cm = CertManager({"domain": "dmr.example.org", "letsencrypt": True}, Path(tempfile.mkdtemp()),
                         extra_domains=["aprs.example.org", "aprs2.example.org", "bad domain", "dmr.example.org"])
        self.assertEqual(cm.all_domains, ["dmr.example.org", "aprs.example.org", "aprs2.example.org"])
        dns = {"dmr.example.org": {"203.0.113.5"}, "aprs.example.org": {"203.0.113.5"}, "aprs2.example.org": {"198.51.100.1"}}
        cm._addresses = lambda name: dns.get(name, set())
        self.assertEqual(await cm.resolvable_extra(), ["aprs.example.org"])
        self.assertEqual(cm.missing_names(), ["aprs.example.org", "aprs2.example.org"])    # no certificate yet
        self.assertEqual(cm.https_url("/x", "aprs.example.org:80"), "https://aprs.example.org/x")
        self.assertEqual(cm.https_url("/x", "evil.example.com"), "https://dmr.example.org/x")


class TestMapApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient
        from dashboard import server
        cls.server = server
        cls.client = TestClient(server.app)

    def setUp(self):
        self.aprs = self.server.state.aprs
        self.saved = copy.deepcopy({k: self.server.dashboard_config.get(k) for k in ("aprs", "daprs")})
        a = self.server.dashboard_config["aprs"]
        a["enabled"] = True
        a["site1"].update(domain="aprs.example.org", title="", logo="")
        a["site2"].update(domain="aprs.auf-der-nachtschicht.de", title="Auf der NachtSchicht", logo="/static/adn-icon.svg")
        a["site3"].update(domain="map.example.org", https=False)
        self.server.dashboard_config["daprs"]["enabled"] = True
        self.aprs.running = True
        self.aprs.store.stations.clear()
        self.aprs.store.recent.clear()
        self.aprs._dupes.clear()

    def tearDown(self):
        self.aprs.running = False
        for k, v in self.saved.items():
            self.server.dashboard_config[k] = v

    def test_map_sends_an_origin_referrer_to_tile_servers(self):
        from fastapi.testclient import TestClient
        # All map entry points must permit an origin Referer to OSM. HTTPS
        # alone cannot fix a same-origin policy, which suppresses it entirely.
        for scheme in ("http", "https"):
            client = TestClient(self.server.app, base_url=f"{scheme}://dmr.example.org")
            for path, host in (("/aprs", "dmr.example.org"),
                               ("/aprs?embed=1", "dmr.example.org"),
                               ("/", "aprs.example.org")):
                with self.subTest(scheme=scheme, path=path, host=host):
                    response = client.get(path, headers={"host": host})
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response.headers["referrer-policy"],
                                     "strict-origin-when-cross-origin")
            # Other dashboard pages retain their existing policy.
            self.assertEqual(client.get("/dashboard").headers["referrer-policy"], "same-origin")

    def test_map_page_on_aprs_domain_and_api(self):
        self.assertIn("<title>DMR Die N8schicht</title>", self.client.get("/").text)
        page = self.client.get("/", headers={"host": "aprs.auf-der-nachtschicht.de"}).text
        self.assertIn("leaflet", page)
        cfg = self.client.get("/api/aprs/config", headers={"host": "aprs.auf-der-nachtschicht.de"}).json()
        self.assertEqual(cfg["site"]["title"], "Auf der NachtSchicht")
        self.assertEqual(cfg["site"]["logo"], "/static/adn-icon.svg")
        self.assertIn("openstreetmap", cfg["map"]["tiles"])
        # beyond the last zoom of the tile server the tiles are enlarged instead of missing (dark map)
        self.assertEqual((cfg["map"]["native_zoom"], cfg["map"]["max_zoom"]), (19, 20))
        self.assertEqual(self.client.get("/api/aprs/config").json()["site"]["title"], "DMR Die N8schicht")
        m = self.client.get("/api/aprs/config", headers={"host": "map.example.org"}).json()["site"]
        self.assertEqual((m["title"], m["subtitle"]), ("DMR Die N8schicht", "APRS map · map.example.org"))
        self.assertIn("<title>DMR Die N8schicht</title>",
                      self.client.get("/dashboard", headers={"host": "map.example.org"}).text)
        self.assertEqual(self.server._aprs_domains(https_only=True), ["aprs.example.org", "aprs.auf-der-nachtschicht.de"])

        self.aprs.ingest_line("DO1RF>APRS,qAR,DB0IG:!5218.00N/00855.00E-from APRS-IS", "uplink")
        self.aprs.on_gps({"radio_id": 2621234, "lat": 52.2, "lon": 8.9, "dst_id": 262, "auth_method": "local"})
        self.aprs.callsign_of = lambda rid: "DL1ABC"
        self.aprs.on_gps({"radio_id": 2621234, "lat": 52.2, "lon": 8.9, "dst_id": 262, "auth_method": "local"})
        calls = {s["call"] for s in self.client.get("/api/aprs/stations").json()["stations"]}
        self.assertEqual(calls, {"DO1RF", "DL1ABC-7"})
        det = self.client.get("/api/aprs/station/DL1ABC-7").json()
        self.assertEqual(det["station"]["dmr_id"], 2621234)
        self.assertEqual(len(det["packets"]), 1)
        self.assertEqual(len(self.client.get("/api/aprs/packets").json()["packets"]), 2)
        # only DMR and own clients
        self.server.dashboard_config["aprs"]["map"]["sources"] = "local"
        calls = {s["call"] for s in self.client.get("/api/aprs/stations").json()["stations"]}
        self.assertEqual(calls, {"DL1ABC-7"})
        self.assertEqual(self.client.get("/api/aprs/station/DO1RF").status_code, 404)

    def test_configuration_tab_explains_daprs(self):
        st = self.server.state.settings
        old = st.dmr_values()["dmr.daprs.enabled"], st.dmr_values()["dmr.daprs.data_ids"]
        try:
            st.db.write("dmr.daprs.enabled", True, "t")
            st.db.write("dmr.daprs.data_ids", [900999], "t")
            d = self.client.get("/api/connect").json()["daprs"]
            self.assertEqual((d["data_ids"], d["ssid"], d["embedded"], d["data"]), ([900999], 7, True, True))
            self.assertEqual(d["map_url"], "http://aprs.example.org/")
            self.server.dashboard_config["aprs"]["enabled"] = False
            self.assertIsNone(self.client.get("/api/connect").json()["daprs"])
        finally:
            st.db.write("dmr.daprs.enabled", old[0], "t")
            st.db.write("dmr.daprs.data_ids", old[1], "t")

    def test_switched_off_and_private(self):
        self.server.dashboard_config["aprs"]["enabled"] = False
        self.assertEqual(self.client.get("/aprs").status_code, 404)
        self.assertEqual(self.client.get("/api/aprs/stations").status_code, 404)
        self.assertNotIn("leaflet", self.client.get("/", headers={"host": "aprs.example.org"}).text)
        self.server.dashboard_config["aprs"]["enabled"] = True
        self.server.dashboard_config["aprs"]["map"]["public"] = False
        self.assertEqual(self.client.get("/api/aprs/stations").status_code, 401)
        self.assertEqual(self.client.get("/api/admin/aprs").status_code, 401)
        self.assertEqual(self.client.get("/api/admin/aprs/passcode?call=N0CALL").status_code, 401)


if __name__ == "__main__":
    unittest.main()
