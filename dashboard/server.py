"""
HBlink4 Dashboard - Separate Process
FastAPI + Uvicorn + WebSockets for real-time monitoring

Updates every 10 superframes (60 packets = 1 second) for smooth real-time feel
"""
import asyncio
import json
import socket
import os
import ipaddress
import sys
import atexit
import base64
import re
import time
from datetime import datetime, date, timedelta
from collections import deque
from typing import Any, Dict, List, Set, Optional
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, Body
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pathlib import Path
import logging

# Allow this file to be run directly by path (python dashboard/server.py) as
# well as imported. Establishing the package context means user_db is imported
# once, as dashboard.user_db, rather than a second bare copy under sys.path
# surgery.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).parent.parent))
    __package__ = "dashboard"
    import dashboard  # noqa: F401  (parent package must be in sys.modules)

from .user_db import UserDatabase, compute_next_refresh_seconds, _age_str
from .auth import AuthStore, AuthError, ADMIN_ROLES, redact_ips, sniff_image
from .settings import SettingsStore, SettingsError, FIELD_BY_KEY
from .avatars import AvatarStore, DEFAULT_URL as FRID_AVATAR_URL
from .tgstats import TGStats, parse_names as _parse_tg_names, RANGES as TG_RANGES
from .obpstats import OBPStats
from .talkgroups import Talkgroups
from . import version as _version
from . import siteicons as _siteicons
from . import n8_security as _sec
from .n8_admin import N8Admin as _N8Admin, own_unit
from . import backup as _backup
from . import autobackup as _autobackup
from .aprs.service import AprsService
from .aprs.store import public as _aprs_public
from .aprs.packet import passcode as _aprs_passcode, valid_call as _aprs_valid_call

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="DMR Die N8schicht Dashboard", version="1.6.2", **_sec.FASTAPI_KWARGS)

# Load dashboard configuration
def load_config() -> dict:
    """Load dashboard configuration from config.json"""
    config_path = Path(__file__).parent / "config.json"
    default_config = {
        "server_name": "dmr.die-n8schicht.de",
        "server_description": "N8schicht DMR Network",
        "dashboard_title": "DMR Die N8schicht",
        "refresh_interval": 1000,
        "max_events": 50,
        "web": {
            "bind": "0.0.0.0",
            "port": 8080
        },
        # Addresses we LISTEN on for hblink4's incoming event connection.
        # bind_* = we listen here (host_* would mean we dial out, which we never do).
        "event_receiver": {
            "transport": "unix",
            "bind_ipv4": "127.0.0.1",
            "bind_ipv6": "::1",
            "port": 8765,
            "unix_socket": "/tmp/hblink4.sock",
            "disable_ipv6": False
        },
        "user_database": {
            "enabled": True,
            "source_url": "https://freeradioid.net/api/subscriber_ids.csv",
            "user_agent": "HBlink4-Dashboard (contact=operator@example.org)",
            "refresh": {
                "schedule": "daily",
                "time_of_day": "03:17",
                "jitter_minutes": 15,
                "on_startup_if_older_than_hours": 36
            },
            "filter": {
                "countries": "all",
                "callsign_regex": None,
                "radio_id_ranges": None
            }
        },
        # Login, user management and who may see what
        "auth": {
            "superadmin": {"username": "", "password": "", "password_hash": ""},
            "public_dashboard": True,
            "session_hours": 12,
            "remember_days": 30
        },
        # HTTPS with automatic Let's Encrypt certificates (see dashboard/tls.py)
        "https": {
            "enabled": False,
            "domain": "",
            "email": "",
            "port": 443,
            "http_port": 80,
            "letsencrypt": True,
            "staging": False,
            "cert_file": "",
            "key_file": ""
        },
        # FreeRadioID.net integration: avatars and live profile lookups
        "freeradioid": {
            "avatar_url": "https://freeradioid.net/api/idimg-{id}.png",
            "profile_lookup": True,
            "profile_url": "https://freeradioid.net/api/dmr/user/?id={id}"
        }
    }
    
    if config_path.exists():
        try:
            with open(config_path) as f:
                config = json.load(f)
                # Merge with defaults, nested sections included: the config file
                # may hold only the few keys needed for the first start
                def deep_merge(base, over):
                    out = dict(base)
                    for k, v in over.items():
                        out[k] = deep_merge(base[k], v) if isinstance(v, dict) and isinstance(base.get(k), dict) else v
                    return out
                return deep_merge(default_config, config)
        except Exception as e:
            logger.warning(f"Failed to load config.json: {e}, using defaults")
            return default_config
    else:
        # Create default config file
        try:
            with open(config_path, 'w') as f:
                json.dump(default_config, f, indent=4)
            logger.info(f"Created default config at {config_path}")
        except Exception as e:
            logger.warning(f"Failed to create config.json: {e}")
        return default_config

dashboard_config = load_config()
# Untouched copy of config.json (+ defaults): "reset to config.json" in the admin area
import copy as _copy
_file_config = _copy.deepcopy(dashboard_config)


def _load_dmr_file_config() -> dict:
    """config/config.json of HBlink4: source of the DMR settings on the very first start."""
    path = Path(__file__).resolve().parent.parent / "config" / "config.json"
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return {}

def _ensure_writable(data_dir: Path) -> None:
    """
    The dashboard must own its data files. A start as root (run_all.sh, or the
    server by hand) leaves root-owned files behind that the service user cannot
    write -- SQLite then fails with "attempt to write a readonly database".
    Explain that with the exact fix instead of a traceback, and stop.
    """
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    bad = []
    if not os.access(data_dir, os.W_OK):
        bad.append(data_dir)
    for f in data_dir.iterdir() if data_dir.is_dir() else []:
        # update.log/update.result schreibt n8-admin.sh als root („Update jetzt“) – der Dashboard liest sie nur
        if f.name in ("update.log", "update.result", "keepalive.json", "keepalive.log", "keepalive.state"):
            continue
        if f.is_file() and not os.access(f, os.W_OK):
            bad.append(f)
    if not bad:
        return
    import getpass
    try:
        me = getpass.getuser()
    except Exception:
        me = str(os.getuid())
    root = data_dir.parent.parent
    logger.error("❌ The dashboard (running as %s) cannot write these files:", me)
    for f in bad[:10]:
        try:
            owner = f.owner()
        except Exception:
            owner = "?"
        logger.error(f"     {f}  (owner: {owner})")
    logger.error("   They were probably created by a start as root. Fix (as root):")
    fix = root / "scripts" / "n8-admin.sh"
    logger.error(f"     sudo {fix} fix-perms" if fix.exists() else f"     chown -R {me}:{me} {data_dir}")
    logger.error("   and from now on start only the services (systemctl), or run_all.sh as that user.")
    sys.exit(1)


# Open event links from HBlink4; the admin area sends commands back over them
_hblink_links: set = set()


def send_hblink_command(message: dict) -> bool:
    """Send a command (apply_settings, restart) to HBlink4. False if not connected."""
    data = json.dumps(message).encode("utf-8")
    frame = len(data).to_bytes(4, byteorder="big") + data
    sent = False
    for t in list(_hblink_links):
        if t.is_closing():
            _hblink_links.discard(t)
            continue
        try:
            t.write(frame)
            sent = True
        except Exception:
            _hblink_links.discard(t)
    return sent


# In-memory state (could be Redis/database for persistence)
class DashboardState:
    """Maintains state for the dashboard"""
    def __init__(self):
        self.repeaters: Dict[int, dict] = {}
        self.repeater_details: Dict[int, dict] = {}  # Detailed info (sent once per connection)
        self.outbounds: Dict[str, dict] = {}  # Outbound connections (key: connection_name)
        self.openbridges: Dict[str, dict] = {}  # OpenBridge trunks (key: connection_name)
        self.streams: Dict[str, dict] = {}  # key: f"{repeater_id}.{slot}" (OBP: f"{name}.{stream_id}")
        self.events: deque = deque(maxlen=500)  # Ring buffer of recent events
        self.last_heard: List[dict] = []  # Last heard users
        self.last_heard_stats: dict = {}  # User cache statistics
        self.websocket_clients: Set[WebSocket] = set()
        self.hblink_connected: bool = False  # Track HBlink4 connection status
        self.stats = {
            'total_calls_today': 0,      # Total RX calls (streams) received today
            'total_duration_today': 0.0,  # Total duration of RX streams only (seconds)
            'retransmitted_calls': 0,    # Total calls retransmitted today (may be higher than received)
            'start_time': datetime.now().isoformat(),
            'last_reset_date': date.today().isoformat()  # Track when stats were last reset
        }
        
        # Persistence file paths
        # HBLINK4_DASH_DATA_DIR: tests point this at a temporary directory
        self._data_dir = Path(os.environ.get("HBLINK4_DASH_DATA_DIR") or Path(__file__).parent / "data")
        self._stats_file = self._data_dir / "stats.json"
        self._last_heard_file = self._data_dir / "last_heard.json"
        self._persistence_disabled = False  # Will be set to True if write permissions fail

        # User database (radio_id -> callsign) with background refresh.
        # Loaded from disk snapshot on startup; populated/refreshed by
        # user_db_refresh_task() registered in startup_event().
        self.user_db = UserDatabase(self._data_dir)

        # Users, sessions, audit log and settings (SQLite)
        _ensure_writable(self._data_dir)
        self.auth = AuthStore(self._data_dir / "dashboard.db")
        self.icons = _siteicons.IconCache(self._data_dir / "dashboard.db")   # favicons of the link menu
        self.auth.sync_superadmin((dashboard_config.get("auth") or {}).get("superadmin") or {})

        # FreeRadioID avatars, cached in the same database
        self.avatars = AvatarStore(
            self.auth, lambda: (dashboard_config.get("freeradioid") or {}).get("avatar_url", FRID_AVATAR_URL))
        try:   # the file cache of an earlier version is no longer used
            import shutil as _shutil
            _shutil.rmtree(self._data_dir / "avatars", ignore_errors=True)
        except Exception:
            pass

        # Talkgroup statistics (one row per group call), same database
        self.tgstats = TGStats(self.auth)
        # OpenBridge statistics (one row per stream and direction on a trunk)
        self.obpstats = OBPStats(self.auth)
        # Talkgroup names (N8schicht list, bundled copy until the first download)
        self.talkgroups = Talkgroups(self.auth)

        # Settings: seeded from config.json on the first start, SQLite afterwards
        self.settings = SettingsStore(self.auth, _load_dmr_file_config())
        seeded = self.settings.seed_and_apply(dashboard_config)
        if seeded:
            logger.info(f"⚙️ {seeded} settings taken over from config.json into the database; "
                        "from now on they are edited in the admin area")

        # APRS server, APRS-IS uplink and DAPRS gateway (dashboard/aprs/), own database aprs.db
        self.aprs = AprsService(
            lambda: dashboard_config, self._data_dir, version=_version._package_version(),
            callsign_of=lambda rid: self.user_db.get(rid, ""),
            name_of=lambda rid: (self.user_db.frid_info(rid) or {}).get("name", ""),
            repeaters=lambda: _aprs_repeaters())

        # Load persisted data
        self._load_persisted_data()
    
    def reset_daily_stats(self):
        """Reset daily statistics at midnight"""
        self.stats['total_calls_today'] = 0
        self.stats['total_duration_today'] = 0.0
        self.stats['retransmitted_calls'] = 0
        self.stats['last_reset_date'] = date.today().isoformat()
        logger.info(f"📊 Daily stats reset at midnight (server time)")
    
    def _load_persisted_data(self):
        """Load persisted statistics and last heard data on startup, purge old data"""
        try:
            # Test write permissions early
            self._check_write_permissions()
            self._cleanup_temp_files()
            self._load_stats()
            self._load_last_heard()
            self.user_db.load_from_disk()
            self._purge_old_data()
            logger.info("📁 Loaded persisted dashboard data")
        except PermissionError as e:
            logger.error(f"❌ No write permissions for persistence directory: {e}")
            logger.error("💡 Dashboard will run without persistence - restart data will not be saved")
            self._persistence_disabled = True
        except Exception as e:
            logger.warning(f"⚠️ Could not load persisted data: {e}")
    
    def _check_write_permissions(self):
        """Test write permissions to data directory"""
        try:
            # Create data directory if needed
            self._data_dir.mkdir(exist_ok=True)
            
            # Test write permissions with a temp file
            test_file = self._data_dir / ".write_test"
            test_file.write_text("test")
            test_file.unlink()
            
            # Set flag to enable persistence
            self._persistence_disabled = False
            
        except (PermissionError, OSError) as e:
            logger.error(f"❌ Cannot write to persistence directory {self._data_dir}: {e}")
            raise PermissionError(f"No write access to {self._data_dir}")
    
    def _cleanup_temp_files(self):
        """Remove any orphaned temp files from previous unclean shutdown"""
        try:
            if not self._data_dir.exists():
                return
                
            removed_count = 0
            for temp_file in self._data_dir.glob("*.tmp"):
                try:
                    temp_file.unlink()
                    removed_count += 1
                    logger.debug(f"🗑️ Removed orphaned temp file: {temp_file.name}")
                except OSError as e:
                    logger.warning(f"⚠️ Could not remove temp file {temp_file.name}: {e}")
            
            if removed_count > 0:
                logger.info(f"🧹 Cleaned up {removed_count} orphaned temp file(s) from previous session")
                
        except Exception as e:
            logger.warning(f"⚠️ Could not cleanup temp files: {e}")
    
    def _purge_old_data(self):
        """Remove old data files to prevent accumulation"""
        if self._persistence_disabled:
            return
            
        try:
            # Check if stats file is from a previous day and remove it
            if self._stats_file.exists():
                try:
                    with open(self._stats_file, 'r') as f:
                        saved_stats = json.load(f)
                    
                    today = date.today().isoformat()
                    if saved_stats.get('last_reset_date') != today:
                        self._stats_file.unlink()
                        logger.info("🗑️ Removed old stats file from previous day")
                except (json.JSONDecodeError, KeyError) as e:
                    # If we can't read it, try to remove it
                    try:
                        self._stats_file.unlink()
                        logger.info("🗑️ Removed corrupted stats file")
                    except OSError as remove_error:
                        logger.warning(f"⚠️ Could not remove corrupted stats file: {remove_error}")
                except OSError as e:
                    logger.warning(f"⚠️ Could not read/remove old stats file: {e}")
                
        except Exception as e:
            logger.warning(f"⚠️ Could not purge old data: {e}")
    
    def _load_stats(self):
        """Load statistics from file, validate date, reset if needed"""
        if not self._stats_file.exists():
            logger.debug("No stats file found, using fresh stats")
            return
        
        try:
            with open(self._stats_file, 'r') as f:
                saved_stats = json.load(f)
            
            # Check if stats are from today
            today = date.today().isoformat()
            if saved_stats.get('last_reset_date') == today:
                # Stats are still valid for today, load them
                self.stats.update(saved_stats)
                logger.info(f"📊 Loaded today's stats: {self.stats['total_calls_today']} calls, {self.stats['retransmitted_calls']} retransmitted")
            else:
                # Stats are from a previous day, keep fresh stats but log
                logger.info(f"📊 Previous day's stats found ({saved_stats.get('last_reset_date')}), using fresh daily stats")
        
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(f"⚠️ Could not parse stats file: {e}")
    
    def _load_last_heard(self):
        """Load last heard users, filtering out entries older than 4 hours (more aggressive)"""
        if not self._last_heard_file.exists():
            logger.debug("No last heard file found, starting fresh")
            return
        
        try:
            with open(self._last_heard_file, 'r') as f:
                saved_data = json.load(f)
            
            # More aggressive filtering - only keep entries from last 4 hours
            cutoff_time = datetime.now() - timedelta(hours=4)
            valid_users = []
            
            for user in saved_data.get('users', []):
                try:
                    last_seen = datetime.fromisoformat(user['last_seen'])
                    if last_seen > cutoff_time:
                        valid_users.append(user)
                except (ValueError, KeyError):
                    continue  # Skip malformed entries
            
            # Only keep data if we have recent users, otherwise start fresh
            if valid_users:
                self.last_heard = valid_users
                self.last_heard_stats = saved_data.get('stats', {})
                logger.info(f"📻 Loaded {len(valid_users)} recent users from last heard")
            else:
                logger.info("📻 No recent users found, starting fresh last heard list")
        
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(f"⚠️ Could not parse last heard file: {e}")
    
    def save_stats(self):
        """Save current statistics to file with atomic write (called only on shutdown)"""
        if self._persistence_disabled:
            logger.debug("📁 Persistence disabled - skipping stats save")
            return
            
        try:
            self._data_dir.mkdir(exist_ok=True)
            temp_file = self._stats_file.with_suffix('.tmp')
            
            with open(temp_file, 'w') as f:
                json.dump(self.stats, f, indent=2)
            
            # Atomic operation - replace file only if write succeeded
            temp_file.rename(self._stats_file)
            logger.debug(f"📁 Saved stats to {self._stats_file}")
            
        except PermissionError as e:
            logger.error(f"❌ Permission denied saving stats: {e}")
            logger.error("💡 Dashboard will exit gracefully without saving persistence data")
        except Exception as e:
            logger.error(f"❌ Failed to save stats: {e}")
    
    def save_last_heard(self):
        """Save last heard users and stats to file with atomic write (called only on shutdown)"""
        if self._persistence_disabled:
            logger.debug("📁 Persistence disabled - skipping last heard save")
            return
            
        try:
            self._data_dir.mkdir(exist_ok=True)
            temp_file = self._last_heard_file.with_suffix('.tmp')
            
            data = {
                'timestamp': datetime.now().isoformat(),
                'users': self.last_heard,
                'stats': self.last_heard_stats
            }
            
            with open(temp_file, 'w') as f:
                json.dump(data, f, indent=2)
            
            # Atomic operation - replace file only if write succeeded
            temp_file.rename(self._last_heard_file)
            logger.debug(f"📁 Saved last heard to {self._last_heard_file}")
            
        except PermissionError as e:
            logger.error(f"❌ Permission denied saving last heard: {e}")
            logger.error("💡 Dashboard will exit gracefully without saving persistence data")
        except Exception as e:
            logger.error(f"❌ Failed to save last heard: {e}")
    
    def save_all_data(self):
        """Save all persistent data"""
        self.save_stats()
        self.save_last_heard()

state = DashboardState()


async def broadcast_hblink_status(connected: bool):
    """Broadcast HBlink4 connection status to all WebSocket clients"""
    state.hblink_connected = connected
    message = {
        'type': 'hblink_status',
        'data': {
            'connected': connected,
            'timestamp': datetime.now().isoformat()
        }
    }
    
    # Broadcast to all connected clients
    disconnected_clients = set()
    for client in state.websocket_clients:
        try:
            await client.send_json(message)
            
            # If HBlink just connected, also send full current state to ensure browser has everything
            if connected:
                await client.send_json({
                    'type': 'initial_state',
                    'data': {
                        'repeaters': list(state.repeaters.values()),
                        'repeater_details': state.repeater_details,
                        'outbounds': list(state.outbounds.values()),
                        'openbridges': list(state.openbridges.values()),
                        'streams': list(state.streams.values()),
                        'events': list(state.events)[-50:],
                        'stats': state.stats,
                        'last_heard': state.last_heard,
                        'hblink_connected': state.hblink_connected
                    }
                })
        except Exception as e:
            logger.debug(f"Failed to send status to client: {e}")
            disconnected_clients.add(client)
    
    # Clean up disconnected clients
    state.websocket_clients -= disconnected_clients


class TCPProtocol(asyncio.Protocol):
    """TCP protocol handler for receiving events from hblink4"""
    
    def __init__(self, callback):
        self.callback = callback
        self.buffer = b''
        self.transport = None
    
    def connection_made(self, transport):
        """Called when TCP connection established"""
        peername = transport.get_extra_info('peername')
        logger.info(f"✅ HBlink4 connected via TCP from {peername}")
        self.transport = transport

        # Tune TCP keepalive on the accepted socket so a silently-severed hblink4
        # connection (NIC flap, DHCP renew, firewall/conntrack eviction) is
        # detected within ~2 minutes and fires connection_lost, instead of the
        # dashboard holding a dead connection (hblink_connected stuck True) until
        # hblink4 happens to reconnect.
        sock = transport.get_extra_info('socket')
        if sock is not None:
            try:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
                if hasattr(socket, 'TCP_KEEPIDLE'):
                    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 60)
                    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 15)
                    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 4)
            except OSError as e:
                logger.debug(f"Could not tune TCP keepalive on accepted socket: {e}")
        
        # Clear dashboard state on reconnect
        # HBlink4 will re-send all current repeaters via repeater_connected events
        logger.info("🔄 Clearing dashboard state - requesting HBlink4 state sync")
        state.repeaters.clear()
        state.outbounds.clear()
        state.openbridges.clear()
        state.streams.clear()
        
        # Set connection status synchronously (async broadcast may be delayed)
        state.hblink_connected = True
        
        # Send sync request to HBlink4 to trigger initial state send
        try:
            sync_request = json.dumps({'type': 'sync_request'}).encode('utf-8')
            length = len(sync_request)
            frame = length.to_bytes(4, byteorder='big') + sync_request
            transport.write(frame)
            _hblink_links.add(transport)
            logger.info("📤 Sent sync_request to HBlink4")
        except Exception as e:
            logger.error(f"Failed to send sync_request: {e}")
        
        # Notify all browser clients that HBlink4 is connected
        asyncio.create_task(broadcast_hblink_status(True))
    
    def data_received(self, data):
        """Called when TCP data received (handles framing)"""
        self.buffer += data
        
        # Process all complete frames in buffer
        while len(self.buffer) >= 4:
            # Read length prefix (4 bytes, big-endian)
            length = int.from_bytes(self.buffer[:4], byteorder='big')
            
            # Check if we have complete frame
            if len(self.buffer) < 4 + length:
                break  # Wait for more data
            
            # Extract frame
            frame = self.buffer[4:4+length]
            self.buffer = self.buffer[4+length:]
            
            # Process event
            asyncio.create_task(self.callback(frame))
    
    def connection_lost(self, exc):
        """Called when TCP connection lost"""
        if exc:
            logger.warning(f"⚠️ HBlink4 TCP connection lost: {exc}")
        else:
            logger.info("HBlink4 TCP connection closed")
        
        # Set connection status synchronously (async broadcast may be delayed)
        state.hblink_connected = False
        
        # Notify all browser clients that HBlink4 is disconnected
        asyncio.create_task(broadcast_hblink_status(False))


class UnixProtocol(asyncio.Protocol):
    """Unix socket protocol handler for receiving events from hblink4"""
    
    def __init__(self, callback):
        self.callback = callback
        self.buffer = b''
        self.transport = None
    
    def connection_made(self, transport):
        """Called when Unix socket connection established"""
        logger.info(f"✅ HBlink4 connected via Unix socket")
        self.transport = transport
        
        # Clear dashboard state on reconnect
        # HBlink4 will re-send all current repeaters via repeater_connected events
        logger.info("🔄 Clearing dashboard state - requesting HBlink4 state sync")
        state.repeaters.clear()
        state.outbounds.clear()
        state.openbridges.clear()
        state.streams.clear()
        
        # Set connection status synchronously (async broadcast may be delayed)
        state.hblink_connected = True
        
        # Send sync request to HBlink4 to trigger initial state send
        try:
            sync_request = json.dumps({'type': 'sync_request'}).encode('utf-8')
            length = len(sync_request)
            frame = length.to_bytes(4, byteorder='big') + sync_request
            transport.write(frame)
            _hblink_links.add(transport)
            logger.info("📤 Sent sync_request to HBlink4")
        except Exception as e:
            logger.error(f"Failed to send sync_request: {e}")
        
        # Notify all browser clients that HBlink4 is connected
        asyncio.create_task(broadcast_hblink_status(True))
    
    def data_received(self, data):
        """Called when data received (handles framing)"""
        self.buffer += data
        
        # Process all complete frames in buffer
        while len(self.buffer) >= 4:
            # Read length prefix (4 bytes, big-endian)
            length = int.from_bytes(self.buffer[:4], byteorder='big')
            
            # Check if we have complete frame
            if len(self.buffer) < 4 + length:
                break  # Wait for more data
            
            # Extract frame
            frame = self.buffer[4:4+length]
            self.buffer = self.buffer[4+length:]
            
            # Process event
            asyncio.create_task(self.callback(frame))
    
    def connection_lost(self, exc):
        """Called when Unix socket connection lost"""
        if exc:
            logger.warning(f"⚠️ HBlink4 Unix socket connection lost: {exc}")
        else:
            logger.info("HBlink4 Unix socket connection closed")
        
        # Set connection status synchronously (async broadcast may be delayed)
        state.hblink_connected = False
        
        # Notify all browser clients that HBlink4 is disconnected
        asyncio.create_task(broadcast_hblink_status(False))


class EventReceiver:
    """Receives events from hblink4 via TCP or Unix socket.

    This side listens; hblink4 (hblink4/events.py EventEmitter) initiates the
    connection and sends the events. The addresses below are bind addresses.
    """
    
    def __init__(self, transport='unix', bind_ipv4='127.0.0.1', bind_ipv6='::1',
                 port=8765, unix_socket='/tmp/hblink4.sock', disable_ipv6=False):
        """
        Initialize event receiver with transport abstraction

        Args:
            transport: 'tcp' or 'unix'
            bind_ipv4: Address to bind the IPv4 listener to (for TCP)
            bind_ipv6: Address to bind the IPv6 listener to (for TCP)
            port: Port to listen on (for TCP)
            unix_socket: Path of the Unix socket to create and listen on
            disable_ipv6: Disable IPv6 (for networks with broken IPv6)
        """
        self.transport = transport.lower()
        self.bind_ipv4 = bind_ipv4
        self.bind_ipv6 = bind_ipv6 if not disable_ipv6 else None
        self.disable_ipv6 = disable_ipv6
        
        if disable_ipv6 and transport == 'tcp':
            logger.warning('⚠️  IPv6 disabled for event receiver - using IPv4 only')
        self.port = port
        self.unix_socket = unix_socket
        self.server = None
        self.server_v6 = None
    
    async def start(self):
        """Start receiving events from hblink4"""
        loop = asyncio.get_event_loop()
        
        if self.transport == 'tcp':
            await self._start_tcp(loop)
        elif self.transport == 'unix':
            await self._start_unix(loop)
        else:
            logger.error(f"Unknown transport: {self.transport} (valid options: 'tcp', 'unix')")
            raise ValueError(f"Unknown transport: {self.transport}")
    
    async def _start_tcp(self, loop):
        """Start TCP server on both IPv4 and IPv6"""
        # Start IPv4 listener
        if self.bind_ipv4:
            try:
                self.server = await loop.create_server(
                    lambda: TCPProtocol(self.process_event),
                    self.bind_ipv4, self.port,
                    family=socket.AF_INET
                )
                logger.info(f"✓ Listening for HBlink4 events via TCP on {self.bind_ipv4}:{self.port} (IPv4)")
            except Exception as e:
                logger.error(f"✗ Failed to start IPv4 TCP listener: {e}")
        
        # Start IPv6 listener
        if self.bind_ipv6:
            try:
                self.server_v6 = await loop.create_server(
                    lambda: TCPProtocol(self.process_event),
                    self.bind_ipv6, self.port,
                    family=socket.AF_INET6
                )
                logger.info(f"✓ Listening for HBlink4 events via TCP on [{self.bind_ipv6}]:{self.port} (IPv6)")
            except Exception as e:
                logger.error(f"✗ Failed to start IPv6 TCP listener: {e}")
    
    async def _start_unix(self, loop):
        """Start Unix socket server"""
        # Remove existing socket file if it exists
        if os.path.exists(self.unix_socket):
            try:
                os.unlink(self.unix_socket)
                logger.info(f"Removed existing socket file: {self.unix_socket}")
            except PermissionError:
                try:
                    owner = Path(self.unix_socket).owner()
                except Exception:
                    owner = "another user"
                logger.error(f"❌ {self.unix_socket} belongs to {owner} (left over from a start as root) and "
                             f"cannot be replaced: HBlink4 will not reach the dashboard. Fix as root: "
                             f"rm -f {self.unix_socket} && systemctl restart hblink4-dash hblink4")
                return
            except Exception as e:
                logger.warning(f"Failed to remove existing socket: {e}")
        
        self.server = await loop.create_unix_server(
            lambda: UnixProtocol(self.process_event),
            self.unix_socket
        )
        
        # Set socket permissions (readable/writable by owner and group)
        try:
            os.chmod(self.unix_socket, 0o660)
        except Exception as e:
            logger.warning(f"Failed to set socket permissions: {e}")
        
        logger.info(f"📡 Listening for HBlink4 events via Unix socket at {self.unix_socket}")
    
    async def process_event(self, data: bytes):
        """Process incoming event from hblink4"""
        try:
            event = json.loads(data.decode('utf-8'))
            await self.handle_event(event)
        except Exception as e:
            logger.error(f"Error processing event: {e}")
    
    async def handle_event(self, event: dict):
        """Update state and broadcast to WebSocket clients"""
        event_type = event['type']
        data = event['data']
        
        # Update internal state based on event type
        if event_type == 'repeater_connected':
            state.repeaters[data['repeater_id']] = {
                **data,
                # Prefer the server's session start. repeater_connected is also
                # emitted on missed pings, on recovery, and when this dashboard
                # reconnects and the server replays state — using the event's
                # arrival time would reset uptime for repeaters that never dropped.
                # Fall back for servers older than this field.
                'connected_at': data.get('connect_time', event['timestamp']),
                'last_activity': event['timestamp'],
                'last_ping': data.get('last_ping', event['timestamp']),
                'missed_pings': data.get('missed_pings', 0),
                'status': 'connected'
            }
            logger.info(f"Repeater connected: {data['repeater_id']} ({data.get('callsign', 'UNKNOWN')})")
        
        elif event_type == 'repeater_keepalive':
            if data['repeater_id'] in state.repeaters:
                state.repeaters[data['repeater_id']]['last_ping'] = data.get('last_ping', event['timestamp'])
                state.repeaters[data['repeater_id']]['missed_pings'] = data.get('missed_pings', 0)
                state.repeaters[data['repeater_id']]['last_activity'] = event['timestamp']
        
        elif event_type == 'repeater_disconnected':
            if data['repeater_id'] in state.repeaters:
                # Remove repeater from state immediately
                del state.repeaters[data['repeater_id']]
                logger.info(f"Repeater disconnected: {data['repeater_id']} ({data.get('callsign', 'UNKNOWN')}) - reason: {data.get('reason', 'unknown')}")
        
        elif event_type == 'gps_position':
            # DAPRS: a radio reported its position (embedded GPS or GPS data call)
            try:
                state.aprs.on_gps(data)
            except Exception as e:
                logger.error(f"📍 DAPRS: {e}")
            return

        elif event_type == 'repeater_details':
            # Store detailed repeater information (sent once on connection)
            state.repeater_details[data['repeater_id']] = {
                **data,
                'received_at': event['timestamp']
            }
            logger.debug(f"Repeater details received: {data['repeater_id']} - Pattern: {data.get('matched_pattern', 'Unknown')}")
        
        elif event_type == 'repeater_options_updated':
            # RPTO received - update TG lists in real-time
            if data['repeater_id'] in state.repeaters:
                state.repeaters[data['repeater_id']]['slot1_talkgroups'] = data.get('slot1_talkgroups', [])
                state.repeaters[data['repeater_id']]['slot2_talkgroups'] = data.get('slot2_talkgroups', [])
                state.repeaters[data['repeater_id']]['rpto_received'] = data.get('rpto_received', False)
                state.repeaters[data['repeater_id']]['translations'] = data.get('translations', [])
                logger.info(f"Repeater options updated via RPTO: {data['repeater_id']}")
        
        elif event_type == 'stream_start':
            # Handle both repeater streams and outbound connection streams
            connection_type = data.get('connection_type', 'repeater')
            
            if connection_type == 'openbridge':
                # OBP is stream-multiplexed - key by connection_name.stream_id
                key = f"{data['connection_name']}.{data.get('stream_id')}"
            elif connection_type == 'outbound':
                # Outbound stream - key by connection_name.slot
                key = f"{data['connection_name']}.{data['slot']}"
            else:
                repeater_id = data.get('repeater_id')
                if repeater_id is None:
                    logger.error("Stream start missing repeater_id: %s", event)
                    return
                # Repeater stream - key by repeater_id.slot (legacy behavior)
                key = f"{repeater_id}.{data['slot']}"
            
            # Look up callsign from user database
            src_id = data.get('rf_src') or data.get('src_id')  # Handle both field names
            callsign = state.user_db.get(src_id, '') if src_id else ''
            
            state.streams[key] = {
                **data,
                'callsign': callsign,  # Add callsign to stream data
                'start_time': event['timestamp'],
                'packets': 0,
                'duration': 0,
                'status': 'active'
            }
            
            # Count different stream types
            if not data.get('is_assumed', False):
                # RX streams: actual traffic being received (from repeaters OR outbound connections)
                # Only exclude TX streams (is_assumed=True)
                state.stats['total_calls_today'] += 1
                
                # Add/update user in last_heard immediately with "active" status
                # Only for actual received calls, not retransmitted calls
                if src_id:
                    # Build source display: "Name (originating_repeater_id)"
                    # For repeaters: callsign (repeater_id)
                    # For outbound: connection_name (remote_repeater_id)
                    if connection_type == 'openbridge':
                        # OBP source: trunk name + the origin peer that rides in
                        # the frame (bytes 11:15). Present only when the far end
                        # preserves the source peer; a far end stamping its own
                        # network_id sends no usable peer, so fall back to the
                        # bare trunk name. This is the closest-hop source peer —
                        # over multi-hop OBP it reflects the immediate upstream,
                        # not the full path (we can't control other nodes).
                        conn_name = data.get('connection_name', 'OpenBridge')
                        remote_rid = data.get('remote_repeater_id')
                        source_name = f"{conn_name} ({remote_rid})" if remote_rid else conn_name
                    elif connection_type == 'outbound':
                        conn_name = data.get('connection_name', 'Unknown')
                        remote_rid = data.get('remote_repeater_id', 0)
                        source_name = f"{conn_name} ({remote_rid})"
                    else:
                        repeater_id = data.get('repeater_id', 0)
                        # Look up repeater callsign from state
                        repeater_info = state.repeaters.get(repeater_id, {})
                        repeater_callsign = repeater_info.get('callsign', '')
                        if repeater_callsign:
                            source_name = f"{repeater_callsign} ({repeater_id})"
                        else:
                            source_name = str(repeater_id)
                    
                    # Find existing entry or create new one
                    existing_idx = next((i for i, u in enumerate(state.last_heard) if u['radio_id'] == src_id), None)
                    user_entry = {
                        'radio_id': src_id,
                        'callsign': callsign,
                        'source_name': source_name,
                        'slot': data['slot'],
                        'talkgroup': data.get('dst_id', 0),
                        'call_type': data.get('call_type', 'group'),  # "group" or "private" (addressing)
                        'is_data': data.get('is_data', False),  # voice vs data (payload kind)
                        'frid': state.user_db.is_frid(src_id),  # registered at FreeRadioID.net
                        'last_heard': event['timestamp'],
                        'active': True  # Mark as currently active
                    }
                    # Only local repeater ingresses have translation state we can reference;
                    # outbound- and OBP-ingresses are remote and carry no local map.
                    if connection_type == 'repeater':
                        user_entry['source_repeater_id'] = data.get('repeater_id')
                    
                    if existing_idx is not None:
                        state.last_heard[existing_idx] = user_entry
                    else:
                        state.last_heard.insert(0, user_entry)  # Add to front
                    
                    # Keep only most recent 10 entries
                    state.last_heard = state.last_heard[:10]
            else:
                # TX streams: traffic being retransmitted to repeaters or outbound connections
                # Don't add to last_heard - these represent the same call being forwarded
                state.stats['retransmitted_calls'] += 1
            
            # Update repeater/outbound/OBP last activity
            if connection_type == 'openbridge' and data['connection_name'] in state.openbridges:
                state.openbridges[data['connection_name']]['last_activity'] = event['timestamp']
            elif connection_type == 'outbound' and data['connection_name'] in state.outbounds:
                state.outbounds[data['connection_name']]['last_activity'] = event['timestamp']
            elif data.get('repeater_id') in state.repeaters:
                state.repeaters[data['repeater_id']]['last_activity'] = event['timestamp']
        
        elif event_type == 'talker_alias':
            # DMR Talker Alias of a running call – replaces the name in Live / Last Heard
            connection_type = data.get('connection_type', 'repeater')
            if connection_type == 'openbridge':
                key = f"{data['connection_name']}.{data.get('stream_id')}"
            elif connection_type == 'outbound':
                key = f"{data['connection_name']}.{data['slot']}"
            else:
                key = f"{data.get('repeater_id')}.{data['slot']}"
            alias = (data.get('talker_alias') or '').strip()
            if key in state.streams and alias:
                state.streams[key]['talker_alias'] = alias
                state.streams[key]['talker_alias_complete'] = bool(data.get('complete'))
            src_id = data.get('src_id')
            if src_id and alias:
                entry = next((u for u in state.last_heard if u['radio_id'] == src_id), None)
                if entry:
                    entry['talker_alias'] = alias
                    entry['talker_alias_complete'] = bool(data.get('complete'))

        elif event_type == 'stream_update':
            # Handle both repeater and outbound streams
            connection_type = data.get('connection_type', 'repeater')
            if connection_type == 'openbridge':
                key = f"{data['connection_name']}.{data.get('stream_id')}"
            elif connection_type == 'outbound':
                key = f"{data['connection_name']}.{data['slot']}"
            else:
                key = f"{data['repeater_id']}.{data['slot']}"

            if key in state.streams:
                state.streams[key]['packets'] = data['packets']
                state.streams[key]['duration'] = data['duration']
        
        elif event_type == 'stream_end':
            # Handle both repeater and outbound streams
            connection_type = data.get('connection_type', 'repeater')
            if connection_type == 'openbridge':
                key = f"{data['connection_name']}.{data.get('stream_id')}"
            elif connection_type == 'outbound':
                key = f"{data['connection_name']}.{data['slot']}"
            else:
                key = f"{data['repeater_id']}.{data['slot']}"

            if key in state.streams:
                # Stream ended and entering hang time (combined event)
                stream = state.streams[key]
                stream['status'] = 'hang_time'
                stream['packets'] = data.get('packet_count', data.get('packets', 0))
                stream['duration'] = data['duration']
                stream['end_reason'] = data.get('end_reason', 'unknown')
                if data.get('talker_alias'):
                    stream['talker_alias'] = data['talker_alias']
                stream['hang_time'] = data.get('hang_time', 0)
                
                # Only accumulate duration for RX streams (not assumed/TX streams or outbound)
                if not data.get('is_assumed', False) and connection_type != 'outbound':
                    state.stats['total_duration_today'] += data['duration']

                # Talkgroup statistics: every received group call, once
                if not data.get('is_assumed', stream.get('is_assumed', False)):
                    _record_tg_call(stream, data, connection_type, event.get('timestamp'))
                # OpenBridge statistics: both directions on the trunk
                if connection_type == 'openbridge':
                    _record_obp_call(stream, data, event.get('timestamp'))
                
                # Update last_heard entry to mark as no longer active (only for repeater RX streams)
                if connection_type != 'outbound':
                    src_id = stream.get('rf_src') or stream.get('src_id')
                    if src_id:
                        user_entry = next((u for u in state.last_heard if u['radio_id'] == src_id), None)
                        if user_entry:
                            user_entry['active'] = False
                            user_entry['last_heard'] = event['timestamp']

                # OBP is stream-multiplexed with no hang time — drop the ended stream now.
                if connection_type == 'openbridge':
                    del state.streams[key]
        
        elif event_type == 'hang_time_expired':
            # Hang time has expired, clear the slot (handle both repeater and outbound)
            connection_type = data.get('connection_type', 'repeater')
            if connection_type == 'outbound':
                key = f"{data['connection_name']}.{data['slot']}"
            else:
                key = f"{data['repeater_id']}.{data['slot']}"
                
            if key in state.streams:
                del state.streams[key]
                logger.debug(f"Hang time expired for {key}")
        
        elif event_type == 'outbound_connecting':
            # Outbound connection is attempting to connect
            conn_name = data['connection_name']
            state.outbounds[conn_name] = {
                **data,
                'connecting_at': event['timestamp'],
                'last_activity': event['timestamp'],
                'status': 'connecting'
            }
            logger.info(f"Outbound connection attempting: {conn_name} (radio_id={data.get('radio_id')})")
        
        elif event_type == 'outbound_connected':
            # Outbound connection established
            conn_name = data['connection_name']
            state.outbounds[conn_name] = {
                **data,
                'connected_at': event['timestamp'],
                'last_activity': event['timestamp'],
                'status': 'connected'
            }
            _tag_origin(conn_name, 'outbound')
            logger.info(f"Outbound connection established: {conn_name} (radio_id={data.get('radio_id')}) at {data.get('remote_address')}:{data.get('remote_port')}")

        elif event_type == 'openbridge_connected':
            # OpenBridge trunk is up (bound socket; no auth handshake)
            conn_name = data['connection_name']
            state.openbridges[conn_name] = {
                **data,
                'connected_at': event['timestamp'],
                'last_activity': event['timestamp'],
                'status': 'connected',
            }
            _tag_origin(conn_name, 'openbridge')
            logger.info(f"OpenBridge trunk up: {conn_name} (network_id={data.get('network_id')}) "
                        f"→ {data.get('remote_address')}:{data.get('remote_port')} "
                        f"({len(data.get('talkgroups', {}))} talkgroups)")

        elif event_type == 'openbridge_status':
            # FreeDMR bridge control: keep-alive state and negotiated protocol version
            conn_name = data['connection_name']
            if conn_name in state.openbridges:
                state.openbridges[conn_name].update({k: v for k, v in data.items() if k != 'connection_name'})

        elif event_type == 'openbridge_disconnected':
            conn_name = data['connection_name']
            if conn_name in state.openbridges:
                state.openbridges[conn_name]['status'] = 'disconnected'
                state.openbridges[conn_name]['disconnected_at'] = event['timestamp']

        elif event_type == 'outbound_disconnected':
            # Outbound connection lost - change to disconnected status but don't remove
            conn_name = data['connection_name']
            if conn_name in state.outbounds:
                state.outbounds[conn_name]['status'] = 'disconnected'
                state.outbounds[conn_name]['disconnected_at'] = event['timestamp']
                state.outbounds[conn_name]['disconnect_reason'] = data.get('reason', 'unknown')
                logger.info(f"Outbound connection disconnected: {conn_name} - reason: {data.get('reason', 'unknown')}")
        
        elif event_type == 'outbound_error':
            # Outbound connection error
            conn_name = data['connection_name']
            if conn_name in state.outbounds:
                state.outbounds[conn_name]['status'] = 'error'
                state.outbounds[conn_name]['error_message'] = data.get('error_message', 'Unknown error')
                state.outbounds[conn_name]['last_error'] = event['timestamp']
            else:
                # Connection failed before it was established
                state.outbounds[conn_name] = {
                    **data,
                    'status': 'error',
                    'error_message': data.get('error_message', 'Unknown error'),
                    'last_error': event['timestamp']
                }
            logger.warning(f"Outbound connection error: {conn_name} - {data.get('error_message', 'Unknown error')}")
        

        
        # Add to event log (only for user-facing on-air activity events)
        # Skip system events like repeater_connected, repeater_disconnected, hang_time_expired, repeater_keepalive
        # Skip TX/assumed streams from the events log (but they're still tracked in state.streams for repeater cards)
        if event_type in ['stream_start', 'stream_end']:
            # Only add RX streams to the events log (TX streams have is_assumed=True)
            if not data.get('is_assumed', False):
                state.events.append(event)
        
        # For stream events, include updated last_heard list in the event
        if event_type in ['stream_start', 'stream_end', 'hang_time_expired', 'talker_alias']:
            event['last_heard'] = state.last_heard
        
        # Send to all WebSocket clients
        await self.send_to_clients(event)
    
    async def send_to_clients(self, event: dict):
        """Send event to all connected WebSocket clients"""
        if not state.websocket_clients:
            return
        
        message = json.dumps(event)
        disconnected = set()
        
        for client in state.websocket_clients:
            try:
                await client.send_text(message)
            except:
                disconnected.add(client)
        
        # Remove disconnected clients
        state.websocket_clients -= disconnected


# ======================================================================
# Authentication, IP visibility, user management
# ======================================================================
SESSION_COOKIE = "n8dash_session"
_PUBLIC_CONFIG_KEYS = ("server_name", "server_description", "dashboard_title", "logo", "favicon",
                       "announcement", "network_info", "refresh_interval", "max_events",
                       "page_title", "theme", "logo_size", "logo_radius", "links")
_redact_memo: tuple = (None, None)


def _auth_cfg() -> dict:
    return dashboard_config.get("auth") or {}


def _public_dashboard() -> bool:
    return bool(_auth_cfg().get("public_dashboard", True))


def _client_ip(conn) -> str:
    return conn.client.host if conn.client else ""


def current_user(conn) -> Optional[dict]:
    """User of a Request or WebSocket from its session cookie (or None)."""
    return state.auth.session_user(conn.cookies.get(SESSION_COOKIE))


def is_admin(user: Optional[dict]) -> bool:
    return bool(user and user.get("role") in ADMIN_ROLES)


def view_for(user: Optional[dict], data):
    """IP addresses are for admins only."""
    return data if is_admin(user) else redact_ips(data)


def _redact_text(text: str) -> str:
    global _redact_memo
    if _redact_memo[0] is text:
        return _redact_memo[1]
    try:
        out = json.dumps(redact_ips(json.loads(text)))
    except ValueError:
        out = text
    _redact_memo = (text, out)
    return out


class ClientSocket:
    """A dashboard WebSocket that redacts IP addresses for non-admins."""

    def __init__(self, ws: WebSocket, token: Optional[str], user: Optional[dict]):
        self.ws = ws
        self.token = token
        self.user = user
        self._checked = datetime.now().timestamp()

    @property
    def admin(self) -> bool:
        now = datetime.now().timestamp()
        if self.token and now - self._checked > 60:   # session revoked or demoted?
            self.user = state.auth.session_user(self.token)
            self._checked = now
        return is_admin(self.user)

    async def send_text(self, text: str):
        await self.ws.send_text(text if (text == 'pong' or self.admin) else _redact_text(text))

    async def send_json(self, obj):
        await self.ws.send_json(obj if self.admin else redact_ips(obj))


def _require_user(request: Request) -> dict:
    user = current_user(request)
    if not user:
        raise _HTTPError(401, "Please log in.")
    return user


def _require_admin(request: Request) -> dict:
    user = _require_user(request)
    if not is_admin(user):
        raise _HTTPError(403, "Admins only.")
    return user


def _require_backup_owner(request: Request) -> dict:
    user = _require_admin(request)
    if user.get("role") != "superadmin":
        raise _HTTPError(403, "Full backups contain all credentials. Superadmin access is required.")
    return user


class _HTTPError(Exception):
    def __init__(self, status: int, message: str):
        self.status, self.message = status, message


@app.exception_handler(_HTTPError)
async def _http_error_handler(request: Request, exc: _HTTPError):
    return JSONResponse({"error": exc.message}, status_code=exc.status)


@app.exception_handler(AuthError)
async def _auth_error_handler(request: Request, exc: AuthError):
    return JSONResponse({"error": str(exc)}, status_code=400)


@app.middleware("http")
async def _security_middleware(request: Request, call_next):
    path = request.url.path
    if path.startswith("/api/"):
        # CSRF: state-changing calls must come from our own page (custom header +
        # SameSite=Strict cookie).
        if request.method in ("POST", "PUT", "PATCH", "DELETE") and request.headers.get("x-dashboard") != "1":
            return JSONResponse({"error": "Missing X-Dashboard header."}, status_code=403)
        # Private dashboard: everything but login and branding needs a session.
        if (not _public_dashboard() and not path.startswith("/api/auth/") and path != "/api/config"
                and not (path.startswith("/api/aprs/") and state.aprs.c("aprs.map.public", True))
                and not current_user(request)):
            return JSONResponse({"error": "Please log in."}, status_code=401)
    response = await call_next(request)
    _sec.headers(response, https=_sec.is_https(request))
    return response


def _set_session_cookie(request: Request, response: Response, token: str, max_age: Optional[int]):
    response.set_cookie(SESSION_COOKIE, token, max_age=max_age, httponly=True, samesite="strict",
                        secure=request.url.scheme == "https", path="/")


@app.post("/api/auth/login")
async def auth_login(request: Request, body: dict = Body(...)):
    remember = bool(body.get("remember"))
    hours = float(_auth_cfg().get("remember_days", 30)) * 24 if remember else float(_auth_cfg().get("session_hours", 12))
    token, user = await asyncio.to_thread(
        state.auth.login, str(body.get("username") or ""), str(body.get("password") or ""),
        _client_ip(request), request.headers.get("user-agent", ""), hours)
    logger.info(f"🔐 Login: {user['username']} ({user['role']}) from {_client_ip(request)}")
    response = JSONResponse({"user": user})
    _set_session_cookie(request, response, token, int(hours * 3600) if remember else None)
    return response


@app.post("/api/auth/logout")
async def auth_logout(request: Request):
    user = current_user(request)
    state.auth.logout(request.cookies.get(SESSION_COOKIE))
    if user:
        state.auth.audit("logout", user["username"], "", _client_ip(request))
    response = JSONResponse({"ok": True})
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response


@app.get("/api/auth/me")
async def auth_me(request: Request):
    return {"user": current_user(request), "public_dashboard": _public_dashboard(),
            "https": request.url.scheme == "https"}


@app.post("/api/auth/password")
async def auth_password(request: Request, body: dict = Body(...)):
    user = _require_user(request)
    await asyncio.to_thread(state.auth.change_own_password, user, str(body.get("old") or ""),
                            str(body.get("new") or ""), _client_ip(request))
    return {"ok": True}


@app.get("/api/admin/users")
async def admin_users(request: Request):
    _require_admin(request)
    return {"users": state.auth.list_users()}


@app.post("/api/admin/users")
async def admin_create_user(request: Request, body: dict = Body(...)):
    actor = _require_admin(request)
    user = await asyncio.to_thread(
        state.auth.create_user, actor, str(body.get("username") or ""), str(body.get("password") or ""),
        str(body.get("role") or "user"), str(body.get("display_name") or ""), body.get("dmr_id"),
        _client_ip(request))
    return {"user": user}


@app.patch("/api/admin/users/{user_id}")
async def admin_update_user(user_id: int, request: Request, body: dict = Body(...)):
    actor = _require_admin(request)
    allowed = {k: body[k] for k in ("password", "role", "display_name", "dmr_id", "disabled") if k in body}
    user = await asyncio.to_thread(state.auth.update_user, actor, user_id, allowed, _client_ip(request))
    return {"user": user}


@app.delete("/api/admin/users/{user_id}")
async def admin_delete_user(user_id: int, request: Request):
    actor = _require_admin(request)
    state.auth.delete_user(actor, user_id, _client_ip(request))
    return {"ok": True}


@app.get("/api/admin/sessions")
async def admin_sessions(request: Request):
    _require_admin(request)
    return {"sessions": state.auth.list_sessions()}


@app.delete("/api/admin/sessions/{session_id}")
async def admin_revoke_session(session_id: str, request: Request):
    actor = _require_admin(request)
    state.auth.revoke_session(session_id)
    state.auth.audit("session_revoked", actor["username"], session_id, _client_ip(request))
    return {"ok": True}


def _require_human_admin(request: Request) -> dict:
    user = _require_admin(request)
    if user.get("api"):
        raise _HTTPError(403, "Not for the HobbyRadioPortal – log in to the dashboard.")
    return user


@app.get("/api/admin/audit")
async def admin_audit(request: Request):
    _require_admin(request)
    return {"audit": state.auth.audit_log()}


@app.get("/api/version")
async def api_version():
    """Version line for the footer (public: no addresses, only version and commit)."""
    v = _version.local_version()
    return {"version": v["version"], "base": v.get("base", ""), "commit": v["short"], "date": v["date"]}


def _update_cfg() -> dict:
    return dashboard_config.get("update") or {}


def _update_hours() -> int:
    try:
        return max(1, min(168, int(_update_cfg().get("interval_hours") or 1)))
    except (TypeError, ValueError):
        return 1


async def _update_check(force: bool = False) -> dict:
    cfg = _update_cfg()
    return await asyncio.to_thread(_version.check, cfg.get("repo") or _version.DEFAULT_REPO,
                                   cfg.get("branch") or "main", _update_hours() * 3600, force)


def _may_install(user: dict) -> bool:
    role = str(_update_cfg().get("install_role") or "superadmin")
    if role == "nobody":
        return False
    if role == "admin":
        return user.get("role") in ADMIN_ROLES
    return user.get("role") == "superadmin"


async def _update_loop() -> None:
    """Ask GitHub on clock-hour boundaries, also when nobody is logged in."""
    await asyncio.sleep(60)
    while True:
        now = datetime.now()
        next_check = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        hours = _update_hours()
        while next_check.hour % hours:
            next_check += timedelta(hours=1)
        try:
            if _update_cfg().get("enabled", True) is not False:
                res = await _update_check(force=True)
                if res.get("available"):
                    logger.info(f"⬆️ Update available: {res['behind']} new change(s) on GitHub "
                                f"({res['local'].get('short')} → {(res.get('latest') or {}).get('short')})")
        except Exception as e:
            logger.debug(f"update check failed: {e}")
        await asyncio.sleep(max(1, (next_check - datetime.now()).total_seconds()))


_update_lock = asyncio.Lock()
_update_last_try = 0.0


@app.get("/api/admin/update")
async def api_admin_update(request: Request, force: bool = False):
    """Is a newer version on GitHub? Cached for the configured interval."""
    user = _require_admin(request)
    cfg = _update_cfg()
    if cfg.get("enabled") is False and not force:
        return {"enabled": False, "available": False, "local": _version.local_version()}
    res = await _update_check(force)
    ready = _n8().update_state()["ready"]
    res = {**res, "can_install": _may_install(user) and bool(res["local"].get("commit")) and ready, "n8_ready": ready,
           "install_role": str(cfg.get("install_role") or "superadmin"),
           "systemd": bool(os.environ.get("INVOCATION_ID")),
           "sudo_restart": await asyncio.to_thread(_version.sudo_restart_allowed),
           "origin": await asyncio.to_thread(_version.origin_url)}
    try:
        import pwd
        owner = pwd.getpwuid(_version.REPO_ROOT.stat().st_uid).pw_name
    except Exception:
        owner = ""
    return {"enabled": True, **res, "path": str(_version.REPO_ROOT), "owner": owner,
            "result": _n8().update_state()["result"]}


@app.post("/api/admin/update/install")
async def api_admin_update_install(request: Request, body: dict = Body(...)):
    """Update now (no password, admin session only): fast-forward to the shown commit, then restart both services."""
    global _update_last_try
    user = _require_admin(request)
    _backup_idle()
    ip = _client_ip(request)
    if not _may_install(user):
        raise _HTTPError(403, "You may not install updates (Settings → ⬆️ Updates → Who may press “Update now”).")
    # no password: an admin session (cookie + CSRF header) and the "Update now" role are enough – the same in every N8 system
    if _update_lock.locked() or time.time() - _update_last_try < 30:
        raise _HTTPError(429, "An update is already running – please wait a moment.")
    async with _update_lock:
        _update_last_try = time.time()
        # installiert wird als root über scripts/n8-admin.sh update --auto (update.request → hblink4-update.path):
        # vorspulen, Pakete, Rechte und sudo, beide Dienste neu starten, Dashboard prüfen – sonst zurück auf den alten Stand
        ok, msg = _n8().request_update()
        if not ok:
            state.auth.audit("update_failed", user["username"], msg[:200], ip)
            raise _HTTPError(409, msg)
    state.auth.audit("update", user["username"], "angefordert (n8-admin.sh)", ip)
    logger.info(f"⬆️ Update angefordert von {user['username']} – n8-admin.sh übernimmt")
    return {"ok": True, "requested": True, "changed": True, "restart": "n8admin", "message": msg, "version": _version.local_version()}


# ---------------------------------------------------------------- Dienste, Berechtigungen & sudo, Update-Protokoll (scripts/n8-admin.sh)
_n8_obj = None


def _n8() -> "_N8Admin":
    global _n8_obj
    if _n8_obj is None or _n8_obj.state_dir != Path(state._data_dir):
        _n8_obj = _N8Admin(state._data_dir)
    return _n8_obj


@app.get("/api/admin/services")
async def admin_services(request: Request):
    _require_admin(request)
    return {"ready": _n8().ready, "units": await _n8().units()}


@app.post("/api/admin/services/{unit}/{action}")
async def admin_service_action(unit: str, action: str, request: Request):
    actor = _require_admin(request)
    ok, out = await _n8().unit_action(unit, action)
    state.auth.audit("service", actor["username"], f"{action} {unit}: {'ok' if ok else out[:120]}", _client_ip(request))
    if not ok:
        raise _HTTPError(400, out or "failed")
    return {"ok": True, "message": out, "units": await _n8().units(), "self": action in ("restart", "stop") and unit == own_unit()}


@app.get("/api/admin/perms")
async def admin_perms(request: Request):
    _require_admin(request)
    return await _n8().check_perms()


@app.post("/api/admin/perms/fix")
async def admin_perms_fix(request: Request):
    actor = _require_admin(request)
    ok, out = await _n8().fix_perms()
    state.auth.audit("perms_fix", actor["username"], "ok" if ok else "errors remain", _client_ip(request))
    return {"ok": ok, "message": out, "check": await _n8().check_perms()}


# Abstürze (N8 Kit 1.3): scripts/n8-admin.sh crash-hook, Keep-Alive und n8_crash.CrashWatch (Dashboard und HBlink4) schreiben
# <Datenordner>/crashes.jsonl – gleiche Adressen in allen N8-Systemen
@app.get("/api/admin/crashes")
async def admin_crashes(request: Request):
    _require_admin(request)
    return await asyncio.to_thread(_n8().crashes)


@app.get("/api/admin/crashes/{cid}")
async def admin_crash_log(cid: str, request: Request):
    _require_admin(request)
    txt = await asyncio.to_thread(_n8().crash_log, cid)
    if txt is None:
        raise _HTTPError(404, "Befund nicht gefunden")
    return {"id": cid, "log": txt}


@app.post("/api/admin/crashes/ack")
async def admin_crashes_ack(request: Request):
    _require_admin(request)
    try:
        b = await request.json()
    except ValueError:
        b = {}
    b = b if isinstance(b, dict) else {}
    ids = b.get("ids") if isinstance(b.get("ids"), list) else []
    return await asyncio.to_thread(_n8().crash_ack, [str(i) for i in ids][:500], bool(b.get("all")))


@app.get("/api/admin/keepalive")
async def admin_keepalive(request: Request):
    _require_admin(request)
    return _n8().keepalive()


@app.post("/api/admin/keepalive")
async def admin_keepalive_set(request: Request):
    actor = _require_admin(request)
    try:
        b = await request.json()
        c = _n8().keepalive_set(b if isinstance(b, dict) else {})
    except (ValueError, TypeError) as e:
        raise _HTTPError(400, str(e))
    state.auth.audit("keepalive", actor["username"], ", ".join(f"{k}={'…' if 'url' in k and v else v}" for k, v in c.items()),
                     _client_ip(request))
    return _n8().keepalive()


@app.get("/api/n8/health")
async def n8_health(request: Request):
    """Für den Keep-Alive (scripts/n8-admin.sh): Zustand der Teile – nur direkt von diesem Rechner, nie über einen Proxy."""
    host = request.client.host if request.client else ""
    if host not in ("127.0.0.1", "::1") or any(h in request.headers for h in ("x-forwarded-for", "x-real-ip", "forwarded", "via")):
        raise _HTTPError(403, "local only")
    a = state.aprs.status() if getattr(state, "aprs", None) else {"enabled": False}
    aprs_ok, why = True, ""
    if a.get("enabled"):
        if a.get("server_enabled") and not a.get("listening"):
            aprs_ok, why = False, "APRS-Server lauscht nicht (Ports 14580/10152)"
        elif a.get("uplink_enabled") and (a.get("uplink") or {}).get("state") != "connected":
            u = a.get("uplink") or {}
            aprs_ok, why = False, f"APRS-Uplink nicht verbunden ({u.get('server') or '?'}: {u.get('error') or u.get('state') or '?'})"
    return {"ok": True, "items": {
        "web": {"ok": True},
        "hblink": {"ok": bool(state.hblink_connected), "why": "" if state.hblink_connected else "HBlink4 meldet sich nicht beim Dashboard (Event-Verbindung)"},
        "aprs": {"ok": aprs_ok, "why": why},
    }}


@app.get("/api/admin/update-log")
async def admin_update_log(request: Request):
    _require_admin(request)
    return _n8().update_state()


@app.get("/api/admin/system")
async def admin_system(request: Request):
    _require_admin(request)
    https_cfg = dashboard_config.get("https") or {}
    info = {"https_enabled": bool(https_cfg.get("enabled")), "domain": https_cfg.get("domain", ""),
            "letsencrypt": bool(https_cfg.get("letsencrypt", True)), "served_over_https": request.url.scheme == "https",
            "cert_expires": None, "public_dashboard": _public_dashboard(),
            "superadmin": ((_auth_cfg().get("superadmin") or {}).get("username") or ""),
            "users": len(state.auth.list_users()), "systemd": bool(os.environ.get("INVOCATION_ID")),
            "hblink_connected": bool(state.hblink_connected),
            "frid_ids": len(state.user_db.frid_ids()), "frid_avatars": state.avatars.stats()["with_avatar"],
            "version": "HBlink4-FreeRadioID", "build": _version.local_version(),
            "aprs_domains": _aprs_domains(), "cert_names": sorted(_tls_manager.cert_names()) if _tls_manager else []}
    if _tls_manager is not None and _tls_manager.have_cert():
        try:
            import ssl as _ssl
            info["cert_expires"] = _ssl._ssl._test_decode_cert(_tls_manager.cert_file).get("notAfter")
        except Exception:
            pass
    return info


# ---------------------------------------------------------------- settings
_USERDB_KEYS = {"user_database.source_url", "user_database.filter.countries",
                "user_database.freeradioid.enabled", "freeradioid.avatars"}


_APRS_RELOAD_PREFIXES = ("aprs.enabled", "aprs.server_id", "aprs.server.", "aprs.uplink.")


async def _after_settings_change(changed: List[str]):
    if any(k.startswith(_APRS_RELOAD_PREFIXES) for k in changed):
        asyncio.create_task(state.aprs.reload())
    elif any(k.startswith("daprs.objects.") for k in changed):
        state.aprs._obj_sent.clear()          # objects are sent again with the new values
    if any(k.startswith("talkgroups.") for k in changed):
        asyncio.create_task(refresh_talkgroups("settings"))
    elif "tg_stats.names" in changed:
        asyncio.create_task(broadcast_talkgroups())
    if not changed:
        return
    # Pages reload title, logo, banner etc.
    message = json.dumps({"type": "config_changed", "timestamp": datetime.now().timestamp()})
    for client in list(state.websocket_clients):
        try:
            await client.send_text(message)
        except Exception:
            pass
    if _USERDB_KEYS & set(changed):
        asyncio.create_task(_refresh_userdb_now("settings"))


async def _refresh_userdb_now(trigger: str):
    udb_cfg = dashboard_config.get("user_database", {}) or {}
    # a new source or filter must be downloaded in full, not answered with 304
    state.user_db.meta.last_modified_header = ""
    status = await state.user_db.refresh_from_upstream(udb_cfg)
    await broadcast_user_db_status(trigger=trigger, status=status)
    asyncio.create_task(sync_avatars(trigger))
    asyncio.create_task(refresh_talkgroups(trigger))


@app.get("/api/admin/settings")
async def admin_settings(request: Request):
    _require_admin(request)
    return {"sections": state.settings.describe(dashboard_config)}


@app.put("/api/admin/settings")
async def admin_save_settings(request: Request, body: dict = Body(...)):
    actor = _require_admin(request)
    changes = body.get("changes") or {}
    if not isinstance(changes, dict):
        raise _HTTPError(400, "changes must be an object")
    try:
        changed = state.settings.update(dashboard_config, changes, actor["username"])
    except SettingsError as e:
        raise _HTTPError(400, str(e))
    if "aprs.enabled" in changed and "dmr.daprs.enabled" not in changes:
        # APRS on/off also switches the GPS decoding in the DMR server
        changed += state.settings.update(dashboard_config, {"dmr.daprs.enabled": bool(state.aprs.enabled)},
                                         actor["username"])
    if changed:
        state.auth.audit("settings_changed", actor["username"], ", ".join(changed), _client_ip(request))
    await _after_settings_change(changed)
    if "links.items" in changed:
        asyncio.create_task(_refresh_link_icons())
    return _settings_result(changed)


def _settings_result(changed: List[str]) -> dict:
    dmr_changed = [k for k in changed if FIELD_BY_KEY[k].is_dmr]
    dmr_applied = send_hblink_command({"type": "apply_settings"}) if dmr_changed else False
    return {"changed": changed,
            "restart_required": any(FIELD_BY_KEY[k].restart and not FIELD_BY_KEY[k].is_dmr for k in changed),
            "dmr_changed": bool(dmr_changed), "dmr_applied": dmr_applied,
            "dmr_restart_required": any(FIELD_BY_KEY[k].restart for k in dmr_changed),
            "sections": state.settings.describe(dashboard_config)}


# ---------------------------------------------------------------- configuration converter
@app.get("/api/admin/import/formats")
async def import_formats(request: Request):
    _require_admin(request)
    from .converter import FORMATS
    return {"formats": [[k, v] for k, v in FORMATS.items()]}


@app.post("/api/admin/import/analyze")
async def import_analyze(request: Request, body: dict = Body(...)):
    _require_admin(request)
    from .converter import analyze, ConvertError
    try:
        result = await asyncio.to_thread(analyze, str(body.get("text") or ""), str(body.get("format") or "auto"),
                                         str(body.get("rules") or ""))
    except ConvertError as e:
        raise _HTTPError(400, str(e))
    current = state.settings.dmr_values()
    for it in result["items"]:
        if not it["merge"]:
            cur = current.get(it["key"])
            it["current"] = "••••••••" if it["key"].endswith("passphrase") else ("all" if cur is None else cur)
            it["same"] = cur == it["value"]
            if it["same"]:
                it["selected"] = False
        else:
            names = {e.get("name") for e in (current.get(it["key"]) or [])}
            it["replaces"] = any(e.get("name") in names for e in it["value"])
    return result


@app.post("/api/admin/obp/parse")
async def obp_parse(request: Request, body: dict = Body(...)):
    """OpenBridge stanza(s) from an hblink.cfg pasted into the trunk editor -> trunks."""
    _require_admin(request)
    from .converter import parse_obp_stanzas, ConvertError
    own = [str(dashboard_config.get("server_name") or ""),
           str(((dashboard_config.get("connect") or {}).get("host")) or ""),
           str(((dashboard_config.get("https") or {}).get("domain")) or ""),
           request.url.hostname or ""]
    try:
        return await asyncio.to_thread(parse_obp_stanzas, str(body.get("text") or ""), own)
    except ConvertError as e:
        raise _HTTPError(400, str(e))


@app.post("/api/admin/import/apply")
async def import_apply(request: Request, body: dict = Body(...)):
    actor = _require_admin(request)
    from .converter import merge_list
    items = body.get("items") or []
    if not isinstance(items, list) or not items:
        raise _HTTPError(400, "Nothing selected.")
    current = state.settings.dmr_values()
    changes: Dict[str, Any] = {}
    for it in items:
        key = str((it or {}).get("key") or "")
        if key not in FIELD_BY_KEY or not FIELD_BY_KEY[key].is_dmr:
            raise _HTTPError(400, f"Unknown setting {key}.")
        if it.get("merge"):
            base = changes.get(key, current.get(key) or [])
            changes[key] = merge_list(base, it.get("value") or [])
        else:
            changes[key] = it.get("value")
    try:
        changed = state.settings.update(dashboard_config, changes, actor["username"])
    except SettingsError as e:
        raise _HTTPError(400, str(e))
    state.auth.audit("config_imported", actor["username"], f"{body.get('format', '')}: {', '.join(changed)}",
                     _client_ip(request))
    await _after_settings_change(changed)
    if "links.items" in changed:
        asyncio.create_task(_refresh_link_icons())
    return _settings_result(changed)


@app.post("/api/admin/settings/reset")
async def admin_reset_settings(request: Request, body: dict = Body(...)):
    actor = _require_admin(request)
    section = str(body.get("section") or "")
    before = {k: _copy.deepcopy(_get_cfg(k)) for k in FIELD_BY_KEY}
    try:
        state.settings.reset_section(dashboard_config, _file_config, section, actor["username"])
    except SettingsError as e:
        raise _HTTPError(400, str(e))
    changed = [k for k in FIELD_BY_KEY if _get_cfg(k) != before[k]]
    state.auth.audit("settings_reset", actor["username"], section, _client_ip(request))
    await _after_settings_change(changed)
    if "links.items" in changed:
        asyncio.create_task(_refresh_link_icons())
    return _settings_result(changed)


def _get_cfg(key: str):
    from .settings import get_path
    if FIELD_BY_KEY[key].is_dmr:
        return state.settings.dmr_values().get(key)
    return get_path(dashboard_config, key)


@app.post("/api/admin/dmr/restart")
async def admin_restart_dmr(request: Request):
    actor = _require_admin(request)
    if not send_hblink_command({"type": "restart"}):
        raise _HTTPError(409, "HBlink4 is not connected to the dashboard.")
    state.auth.audit("dmr_restart", actor["username"], "", _client_ip(request))
    return {"ok": True}


@app.post("/api/admin/userdb/refresh")
async def admin_refresh_userdb(request: Request):
    actor = _require_admin(request)
    state.auth.audit("userdb_refresh", actor["username"], "", _client_ip(request))
    asyncio.create_task(_refresh_userdb_now("admin"))
    return {"ok": True}


@app.post("/api/admin/restart")
async def admin_restart(request: Request):
    actor = _require_admin(request)
    if not os.environ.get("INVOCATION_ID"):
        raise _HTTPError(400, "Only possible when the dashboard runs as a systemd service (Restart=always).")
    state.auth.audit("restart", actor["username"], "", _client_ip(request))
    import signal as _signal
    from .n8_crash import mark_planned
    mark_planned(str(state._data_dir), "hblink4-dash.service", "Neustart aus dem Adminbereich")   # kein „Absturz“ im Absturz-Wächter
    asyncio.get_running_loop().call_later(0.5, os.kill, os.getpid(), _signal.SIGTERM)
    return {"ok": True}


# ---------------------------------------------------------------- 🌐 Netz, Ports & Domains (N8 Kit 1.4, Vorbild N8 Crosslink)
# Alle Ports an einer Stelle; Web-Port, HTTP/HTTPS-Ports, HTTPS und die Domain stehen NUR hier (nicht mehr unter Einstellungen).
_PORT_GROUPS = [
    ("🌐 Webinterface", "Dashboard und Live-Daten. HTTP- und HTTPS-Port gelten nur mit HTTPS (Let's Encrypt prüft immer auf Port 80).", [
        ("web.port", "Web-Port", "in", "TCP", "http://IP:Port des Dashboards (ohne HTTPS)"),
        ("https.http_port", "HTTP-Port", "in", "TCP", "Let's-Encrypt-Prüfung und Weiterleitung auf HTTPS"),
        ("https.port", "HTTPS-Port", "in", "TCP", "https:// der Domain (Standard 443)")]),
    ("🛰️ DMR-Server (HBlink4)", "Hier verbinden sich Repeater, Hotspots und Apps.", [
        ("dmr.global.port_ipv4", "DMR-Port", "in", "UDP", "HomeBrew-Standard 62031")]),
    ("📡 APRS", "Nur wenn der APRS-Server eingeschaltet ist.", [
        ("aprs.server.bind", "APRS-Adresse (Bind)", "in", "", "leer = alle Schnittstellen"),
        ("aprs.server.port_filter", "APRS Filter-Port", "in", "TCP", "für APRS-Apps (Standard 14580)"),
        ("aprs.server.port_full", "APRS Full-Feed-Port", "in", "TCP", "kompletter Datenstrom (Standard 10152)"),
        ("aprs.uplink.aprsis.port", "APRS-IS (Uplink)", "out", "TCP", "zum APRS-IS-Server"),
        ("aprs.uplink.cbaprs.port", "CB-APRS (Uplink)", "out", "TCP", "zum CB-APRS-Server")]),
]
NET_KEYS = {k for _, _, rows in _PORT_GROUPS for k, *_ in rows} | {"https.enabled", "https.domain", "https.email", "https.staging"}


async def _apply_settings(request: Request, changes: dict) -> dict:
    actor = _require_admin(request)
    try:
        changed = state.settings.update(dashboard_config, changes, actor["username"])
    except SettingsError as e:
        raise _HTTPError(400, str(e))
    if changed:
        state.auth.audit("settings_changed", actor["username"], ", ".join(changed), _client_ip(request))
    await _after_settings_change(changed)
    return _settings_result(changed)


def _restart_text(r: dict) -> str:
    if not r["changed"]:
        return "Nichts geändert."
    parts = ["Gespeichert: " + ", ".join(r["changed"])]
    if r["restart_required"]:
        parts.append("Das Dashboard braucht einen Neustart, damit das gilt.")
    if r["dmr_restart_required"]:
        parts.append("Der DMR-Server braucht einen Neustart, damit das gilt.")
    return " ".join(parts)


@app.get("/api/admin/ports")
async def admin_ports(request: Request):
    _require_admin(request)
    groups = []
    for title, help_, rows in _PORT_GROUPS:
        groups.append({"title": title, "help": help_, "rows": [
            {"key": k, "label": lab, "dir": d, "proto": pr, "help": h, "value": _get_cfg(k),
             "kind": "text" if FIELD_BY_KEY[k].kind == "text" else "port", "min": FIELD_BY_KEY[k].min or 1}
            for k, lab, d, pr, h in rows if k in FIELD_BY_KEY]})
    return {"intro": "Alle Ports von HBlink4-FreeRadioID an einer Stelle. Eingehend: in Firewall und Router freigeben, wenn das von außen "
                     "erreichbar sein soll. Ausgehend: die Gegenstelle muss erreichbar sein.",
            "groups": groups, "restart": {"button": "Dashboard neu starten", "url": "/api/admin/restart"} if os.environ.get("INVOCATION_ID") else None}


@app.post("/api/admin/ports")
async def admin_ports_save(request: Request, body: dict = Body(...)):
    vals = body.get("values") or {}
    keys = {k for _, _, rows in _PORT_GROUPS for k, *_ in rows}
    changes = {k: v for k, v in vals.items() if k in keys and k in FIELD_BY_KEY and v != _get_cfg(k)}
    r = await _apply_settings(request, changes)
    return {"ok": True, "message": _restart_text(r), **{k: r[k] for k in ("changed", "restart_required", "dmr_restart_required")}}


def _cert_info() -> Optional[dict]:
    if _tls_manager is None or not _tls_manager.have_cert():
        return None
    try:
        import ssl as _ssl
        from datetime import datetime as _dt
        c = _ssl._ssl._test_decode_cert(str(_tls_manager.cert_file))
        exp = _dt.strptime(c.get("notAfter", ""), "%b %d %H:%M:%S %Y %Z")
        issuer = " ".join(v for part in c.get("issuer", ()) for k, v in part if k in ("organizationName", "commonName"))
        return {"days": (exp - _dt.utcnow()).days, "expires": exp.strftime("%d.%m.%Y"), "issuer": issuer,
                "staging": "STAGING" in issuer.upper() or "(STAGING)" in issuer.upper()}
    except Exception:  # noqa: BLE001
        return {"days": None, "expires": "", "issuer": "", "staging": False}


def _dns(name: str) -> List[str]:
    try:
        return sorted({a[4][0] for a in socket.getaddrinfo(name, None)})
    except OSError:
        return []


@app.get("/api/admin/domains")
async def admin_domains(request: Request):
    _require_admin(request)
    h = dashboard_config.get("https") or {}
    on, dom = bool(h.get("enabled")), str(h.get("domain") or "").strip().lower()
    cert = _cert_info()
    names = _tls_manager.cert_names() if _tls_manager else set()
    sites = []
    if dom:
        sites.append({"domain": dom, "label": "Dashboard", "https": on and cert is not None, "cert": cert if on else None,
                      "dns": await asyncio.to_thread(_dns, dom), "info": "" if on else "HTTPS ist aus"})
    for d in _aprs_domains():
        sites.append({"domain": d, "label": "APRS-Karte", "https": on and d in names, "cert": cert if on and d in names else None,
                      "dns": await asyncio.to_thread(_dns, d), "info": "Titel und Logo unter Betrieb → APRS → Domains", "remove": False})
    hint = ""
    if on and not dom:
        hint = "HTTPS ist an, aber es ist keine Domain eingetragen."
    elif on and _tls_manager is None:
        hint = "HTTPS ist eingeschaltet, läuft aber erst nach einem Neustart des Dashboards."
    return {"intro": "Eigene Domain für das Dashboard mit kostenlosem Zertifikat von Let's Encrypt – das Dashboard macht HTTPS selbst "
                     "(certbot im Webroot-Verfahren, ohne nginx). Die APRS-Kartendomains kommen mit ins selbe Zertifikat. Voraussetzung: "
                     "die Domain zeigt per DNS auf diesen Server und der HTTP-Port (Let's Encrypt prüft immer auf 80) und der HTTPS-Port "
                     "sind aus dem Internet erreichbar (siehe 🔌 Ports).",
            "hint": hint, "sites": sites, "renew_auto": True if (on and _tls_manager is not None) else None,
            "options": [{"key": "https.enabled", "label": "HTTPS mit Let's Encrypt", "value": on,
                         "help": "Aus = nur http://IP:Web-Port. Ein- und Ausschalten startet das Dashboard neu."}],
            "add": {"allowed": not dom, "email": h.get("email", ""), "staging": bool(h.get("staging")), "placeholder": "dmr.example.org",
                    "button": "Domain eintragen & Zertifikat holen",
                    "reason": "" if not dom else "Das Dashboard hat eine Domain. Zum Wechseln die bisherige erst entfernen."}}


def _restart_soon() -> None:
    if os.environ.get("INVOCATION_ID"):
        import signal as _signal
        from .n8_crash import mark_planned
        mark_planned(str(state._data_dir), "hblink4-dash.service", "HTTPS/Domain geändert")
        asyncio.get_running_loop().call_later(1.0, os.kill, os.getpid(), _signal.SIGTERM)


@app.post("/api/admin/domains")
async def admin_domains_add(request: Request, body: dict = Body(...)):
    dom = str(body.get("domain") or "").strip().lower().rstrip(".")
    if not re.fullmatch(r"(?=.{4,253}$)([a-z0-9-]{1,63}\.)+[a-z]{2,63}", dom):
        raise _HTTPError(400, "Keine gültige Domain")
    r = await _apply_settings(request, {"https.domain": dom, "https.email": str(body.get("email") or "").strip(),
                                         "https.staging": bool(body.get("staging")), "https.enabled": True})
    _restart_soon()
    return {"ok": True, "message": f"{dom} eingetragen, HTTPS ist an. Das Dashboard startet neu und holt das Zertifikat – "
                                   f"in einer Minute unter https://{dom}/ öffnen." + ("" if os.environ.get("INVOCATION_ID") else
                                   " (Nicht als systemd-Dienst gestartet – bitte von Hand neu starten.)"), **{"changed": r["changed"]}}


@app.post("/api/admin/domains/{domain}/renew")
async def admin_domains_renew(domain: str, request: Request):
    _require_admin(request)
    if _tls_manager is None:
        raise _HTTPError(400, "HTTPS läuft noch nicht – erst einschalten und das Dashboard neu starten.")
    ok = await _tls_manager.obtain() if not _tls_manager.have_cert() or _tls_manager.missing_names() else await _tls_manager.renew()
    return {"ok": bool(ok) or _tls_manager.have_cert(), "message": "Zertifikat geholt bzw. aktuell." if ok or _tls_manager.have_cert()
            else "certbot ist fehlgeschlagen – zeigt die Domain auf diesen Server und ist Port 80 von außen erreichbar? Einzelheiten im Log."}


@app.delete("/api/admin/domains/{domain}")
async def admin_domains_remove(domain: str, request: Request):
    h = dashboard_config.get("https") or {}
    if domain.strip().lower() != str(h.get("domain") or "").strip().lower():
        raise _HTTPError(400, "Nur die Domain des Dashboards lässt sich hier entfernen (APRS-Domains unter APRS → Domains).")
    await _apply_settings(request, {"https.domain": "", "https.enabled": False})
    _restart_soon()
    return {"ok": True, "message": f"{domain} entfernt, HTTPS ist aus. Das Dashboard startet neu und ist wieder unter http://IP:Web-Port erreichbar."}


@app.post("/api/admin/domains/options")
async def admin_domains_options(request: Request, body: dict = Body(...)):
    if "https.enabled" not in body:
        raise _HTTPError(400, "unbekannte Option")
    await _apply_settings(request, {"https.enabled": bool(body["https.enabled"])})
    _restart_soon()
    return {"ok": True, "message": "HTTPS " + ("eingeschaltet" if body["https.enabled"] else "ausgeschaltet") + " – das Dashboard startet neu."}


# ---------------------------------------------------------------- full backups
_backup_lock = asyncio.Lock()
_BACKUP_NAME = re.compile(r"(?:(?:backup-[0-9T-]+-[a-f0-9]{32}|before-restore-[0-9-]+)\.tar\.gz|auto-\d{8}T\d{6}Z-[a-f0-9]{32}\.tar\.gz\.age)\Z")
_auto_cache = None
_auto_loop_task = None


async def _create_backup_snapshot(path):
    state.save_all_data()
    await asyncio.to_thread(state.aprs.store.flush)
    units = await asyncio.to_thread(_backup.collect_units)
    return await asyncio.to_thread(_backup.create_archive, _version.REPO_ROOT, state._data_dir, path,
                                   version=_version.local_version(), system_units=units)


def _auto_service():
    global _auto_cache
    key = (str(_version.REPO_ROOT.resolve()), str(state._data_dir.resolve()))
    if _auto_cache is None or _auto_cache[0] != key:
        _auto_cache = (key, _autobackup.AutoBackup(_version.REPO_ROOT, state._data_dir,
                                                _create_backup_snapshot, _backup_lock, _backup_idle))
    return _auto_cache[1]


def _secure_backup_transport(request):
    if request.url.scheme != "https" and (request.client is None or request.client.host not in ("127.0.0.1", "::1", "testclient")):
        raise _HTTPError(400, "Zugangsdaten und Schlüssel nur über HTTPS oder einen lokalen SSH-Tunnel übertragen.")


def _cleanup_recovery_keys():
    folder = _backup_dir()
    for path in folder.iterdir():
        if re.fullmatch(r"recovery-[a-f0-9]{32}\.(?:key|json)", path.name) and time.time() - path.lstat().st_mtime > 3600:
            path.unlink(missing_ok=True)


def _backup_dir() -> Path:
    path = state._data_dir / _backup.CONTROL
    if path.is_symlink():
        raise _HTTPError(409, "The backup directory must not be a symlink.")
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    return path


def _restore_status() -> dict:
    path = _backup_dir() / "restore-status.json"
    try:
        status = json.loads(path.read_text())
        if status.get("state") in ("queued", "running") and time.time() - status.get("updated_at", 0) > 60:
            import subprocess
            try:
                live = subprocess.run(["systemctl", "show", "hblink4-restore.service", "-p", "ActiveState", "--value"],
                                      capture_output=True, text=True, timeout=5)
                if live.returncode == 0 and live.stdout.strip() in ("inactive", "failed"):
                    status = {"state": "failed", "message": "Restore helper stopped unexpectedly. Check journalctl -u hblink4-restore before retrying.", "updated_at": time.time()}
                    _backup.atomic_json(path, status)
            except (OSError, subprocess.SubprocessError):
                pass
        return status
    except (OSError, ValueError):
        return {"state": "idle"}


def _backup_idle():
    if _auto_cache and _auto_cache[1].task and not _auto_cache[1].task.done():
        try:
            own_task = asyncio.current_task()
        except RuntimeError:
            own_task = None
        if _auto_cache[1].task is not own_task:
            raise _HTTPError(409, "AutoBackup wurde bereits gestartet.")
    if _update_lock.locked() or _backup_lock.locked() or _restore_status().get("state") in ("queued", "running"):
        raise _HTTPError(409, "A backup or restore is already running.")


@app.exception_handler(_backup.BackupError)
async def _backup_error_handler(request: Request, exc: _backup.BackupError):
    return JSONResponse({"error": str(exc)}, status_code=400)


@app.get("/api/admin/backup")
async def admin_backup_status(request: Request):
    _require_backup_owner(request)
    folder = _backup_dir()
    archives = [{"name": p.name, "size": p.stat().st_size, "created_at": p.stat().st_mtime}
                for p in folder.iterdir() if _BACKUP_NAME.fullmatch(p.name) and p.is_file() and not p.is_symlink()]
    archives.sort(key=lambda x: x["created_at"], reverse=True)
    return {"archives": archives, "busy": _backup_lock.locked(), "restore": _restore_status(),
            "can_restore": await asyncio.to_thread(_backup.helper_available, _version.REPO_ROOT, state._data_dir),
            "max_upload_bytes": _backup.MAX_UPLOAD, "version": _version.local_version(),
            "install_command": "sudo ./scripts/install_backup_helper.sh"}


@app.post("/api/admin/backup/create")
async def admin_backup_create(request: Request):
    import uuid
    actor = _require_backup_owner(request)
    _backup_idle()
    async with _backup_lock:
        name = "backup-" + datetime.now().strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex + ".tar.gz"
        path = _backup_dir() / name
        # Flush in-memory state in the event loop before the SQLite snapshots.
        try:
            manifest = await _create_backup_snapshot(path)
        except Exception:
            path.unlink(missing_ok=True)
            raise
        state.auth.audit("backup_created", actor["username"], name, _client_ip(request))
        return {"ok": True, "name": name, "size": path.stat().st_size, "backup": _backup.summary(manifest)}


@app.get("/api/admin/backup/download/{name}")
async def admin_backup_download(name: str, request: Request):
    from fastapi.responses import FileResponse
    actor = _require_backup_owner(request)
    path = _backup_dir() / name
    if not _BACKUP_NAME.fullmatch(name) or path.is_symlink() or not path.is_file():
        raise _HTTPError(404, "Backup not found.")
    state.auth.audit("backup_downloaded", actor["username"], name, _client_ip(request))
    return FileResponse(path, media_type="application/gzip", filename=name,
                        headers={"Cache-Control": "no-store"})


@app.delete("/api/admin/backup/{name}")
async def admin_backup_delete(name: str, request: Request, body: dict = Body(...)):
    actor = _require_backup_owner(request)
    _backup_idle()
    if not _BACKUP_NAME.fullmatch(name):
        raise _HTTPError(404, "Backup nicht gefunden.")
    if body.get("confirmation") != name:
        raise _HTTPError(400, "Das Löschen dieses Backups muss bestätigt werden.")
    async with _backup_lock:
        path = _backup_dir() / name
        if path.is_symlink() or not path.is_file():
            raise _HTTPError(404, "Backup nicht gefunden.")
        try:
            path.unlink()
        except FileNotFoundError:
            raise _HTTPError(404, "Backup nicht gefunden.") from None
        except OSError:
            raise _HTTPError(409, "Backup konnte nicht gelöscht werden. Dateirechte auf dem Server prüfen.") from None
        if _autobackup.AUTO_NAME.fullmatch(name):
            service = _auto_service()
            auto_state = service.state()
            entry = auto_state.get("catalog", {}).get(name)
            if entry:
                entry["local"] = False
                if not entry.get("targets"):
                    del auto_state["catalog"][name]
                service.state_write(auto_state)
        state.auth.audit("backup_deleted", actor["username"], name, _client_ip(request))
    return {"ok": True}


@app.post("/api/admin/backup/inspect")
async def admin_backup_inspect(request: Request):
    """Stream the upload to disk, then validate it without touching live data."""
    import tempfile
    import uuid
    actor = _require_backup_owner(request)
    _cleanup_recovery_keys()
    _backup_idle()
    async with _backup_lock:
        folder = _backup_dir()
        token = uuid.uuid4().hex
        path = folder / (token + ".tar.gz")
        total = 0
        try:
            with open(path, "xb") as out:
                os.chmod(path, 0o600)
                async for chunk in request.stream():
                    total += len(chunk)
                    if total > _backup.MAX_ENCRYPTED_UPLOAD:
                        raise _HTTPError(413, "Backup exceeds the 2 GiB upload limit.")
                    out.write(chunk)
            if _backup.encrypted(path):
                key_token = request.headers.get("x-backup-key", "")
                identity = None
                uploaded_identity = None
                if re.fullmatch(r"[a-f0-9]{32}", key_token):
                    try:
                        info = json.loads((folder / ("recovery-" + key_token + ".json")).read_text())
                    except (OSError, ValueError):
                        info = {}
                    if info.get("actor_id") != actor["id"] or time.time() - info.get("created_at", 0) > 3600:
                        raise _HTTPError(400, "Wiederherstellungsschlüssel erneut auswählen.")
                    identity = folder / ("recovery-" + key_token + ".key")
                    uploaded_identity = identity
                else:
                    try:
                        identity = _auto_service().vault.host()["identity"]
                    except _autobackup.AutoError:
                        pass
                plain = folder / (token + ".plain.tar.gz")
                try:
                    await asyncio.to_thread(_backup.plain_archive, path, plain, identity)
                    os.replace(plain, path)
                finally:
                    plain.unlink(missing_ok=True)
                    if uploaded_identity:
                        uploaded_identity.unlink(missing_ok=True)
                        uploaded_identity.with_suffix(".json").unlink(missing_ok=True)
            elif total > _backup.MAX_UPLOAD:
                raise _HTTPError(413, "Backup exceeds 2 GiB.")
            with tempfile.TemporaryDirectory(prefix="inspect-", dir=folder) as tmp:
                manifest = await asyncio.to_thread(_backup.unpack_archive, path, Path(tmp))
            sha = await asyncio.to_thread(_backup.digest, path)
            _backup.atomic_json(folder / (token + ".json"), {"token": token, "sha256": sha,
                                "actor_id": actor["id"], "created_at": time.time(), "backup": _backup.summary(manifest)})
        except BaseException:
            path.unlink(missing_ok=True)
            raise
        state.auth.audit("backup_checked", actor["username"], token, _client_ip(request))
        return {"ok": True, "token": token, "sha256": sha, "backup": _backup.summary(manifest)}


# ---------------------------------------------------------------- Umzug ins HobbyRadioPortal
# Superadmin legt einen Umzugscode an; der Web-Installer des Portals holt damit Vorschau und Klon (verschlüsselt).
@app.post("/api/admin/backup/recovery-key")
async def admin_backup_recovery_key(request: Request):
    import uuid
    actor = _require_backup_owner(request)
    _secure_backup_transport(request)
    _cleanup_recovery_keys()
    token = uuid.uuid4().hex
    path = _backup_dir() / ("recovery-" + token + ".key")
    content = bytearray()
    async for chunk in request.stream():
        content.extend(chunk)
        if len(content) > 4096:
            raise _HTTPError(413, "Wiederherstellungsschlüssel ist zu groß.")
    _autobackup._atomic_bytes(path, bytes(content))
    try:
        await asyncio.to_thread(_backup.identity_recipient, path)
    except Exception:
        path.unlink(missing_ok=True)
        raise
    _backup.atomic_json(path.with_suffix(".json"), {"actor_id": actor["id"], "created_at": time.time()})
    return {"token": token}


@app.get("/api/admin/autobackup")
async def admin_autobackup(request: Request):
    _require_backup_owner(request)
    return await asyncio.to_thread(_auto_service().status)


@app.post("/api/admin/autobackup/config")
async def admin_autobackup_save(request: Request, body: dict = Body(...)):
    actor = _require_backup_owner(request)
    _secure_backup_transport(request)
    _backup_idle()
    async with _backup_lock:
        service = _auto_service()
        old = await asyncio.to_thread(service.vault.read)
        cfg = _autobackup.validate(body, old)
        await asyncio.to_thread(service.vault.write, cfg)
        state.auth.audit("autobackup_configured", actor["username"], "Zeitplan und Ziele gespeichert", _client_ip(request))
    return {"ok": True, **await asyncio.to_thread(service.status)}


@app.post("/api/admin/autobackup/key")
async def admin_autobackup_key(request: Request, body: dict = Body(...)):
    actor = _require_backup_owner(request)
    _secure_backup_transport(request)
    _backup_idle()
    await asyncio.to_thread(state.auth.confirm_password, actor, str(body.get("password") or ""), _client_ip(request))
    _backup_idle()
    async with _backup_lock:
        service = _auto_service()
        cfg = await asyncio.to_thread(service.vault.read)
        host = await asyncio.to_thread(service.vault.host)
        data = Path(host["identity"]).read_bytes()
        cfg["key_exported"] = True
        await asyncio.to_thread(service.vault.write, cfg)
        state.auth.audit("autobackup_key_exported", actor["username"], "Wiederherstellungsschlüssel exportiert", _client_ip(request))
    return Response(data, media_type="application/octet-stream", headers={"Cache-Control": "no-store",
                    "Content-Disposition": 'attachment; filename="HBlink4-Wiederherstellung.agekey"'})


@app.post("/api/admin/autobackup/test/{ident}")
async def admin_autobackup_test(ident: str, request: Request):
    actor = _require_backup_owner(request)
    _backup_idle()
    async with _backup_lock:
        result = await asyncio.to_thread(_auto_service().test_target, ident)
    state.auth.audit("autobackup_target_tested", actor["username"], ident, _client_ip(request))
    return result


@app.post("/api/admin/autobackup/run")
async def admin_autobackup_run(request: Request):
    actor = _require_backup_owner(request)
    _backup_idle()
    service = _auto_service()
    if service.task and not service.task.done():
        raise _HTTPError(409, "AutoBackup läuft bereits.")
    cfg = await asyncio.to_thread(service.vault.read)
    _backup_idle()
    if not cfg["key_exported"] or not any(t["enabled"] for t in cfg["targets"]):
        raise _HTTPError(400, "Zuerst Schlüssel exportieren und mindestens ein Ziel speichern.")
    service.task = asyncio.create_task(service.run())
    state.auth.audit("autobackup_started", actor["username"], "Manuell ausgelöst", _client_ip(request))
    return {"ok": True, "queued": True}


@app.post("/api/admin/autobackup/unlock")
async def admin_autobackup_unlock(request: Request, body: dict = Body(...)):
    actor = _require_backup_owner(request)
    _secure_backup_transport(request)
    _backup_idle()
    await asyncio.to_thread(state.auth.confirm_password, actor, str(body.get("password") or ""), _client_ip(request))
    token = str(body.get("key_token") or "")
    if not re.fullmatch(r"[a-f0-9]{32}", token):
        raise _HTTPError(400, "Wiederherstellungsschlüssel auswählen.")
    folder = _backup_dir()
    key = folder / ("recovery-" + token + ".key")
    try:
        info = json.loads(key.with_suffix(".json").read_text())
    except (OSError, ValueError):
        raise _HTTPError(400, "Schlüssel erneut auswählen.")
    if info.get("actor_id") != actor["id"] or time.time() - info.get("created_at", 0) > 3600:
        raise _HTTPError(400, "Schlüssel erneut auswählen.")
    _backup_idle()
    async with _backup_lock:
        try:
            await asyncio.to_thread(_auto_service().vault.recover, key)
        finally:
            key.unlink(missing_ok=True)
            key.with_suffix(".json").unlink(missing_ok=True)
    state.auth.audit("autobackup_unlocked", actor["username"], "Ziele entsperrt; Zeitplan deaktiviert", _client_ip(request))
    return {"ok": True}


@app.post("/api/admin/autobackup/reset")
async def admin_autobackup_reset(request: Request, body: dict = Body(...)):
    actor = _require_backup_owner(request)
    _secure_backup_transport(request)
    _backup_idle()
    if body.get("confirmation") != "RESET":
        raise _HTTPError(400, "Zum Zurücksetzen RESET eingeben.")
    await asyncio.to_thread(state.auth.confirm_password, actor, str(body.get("password") or ""), _client_ip(request))
    _backup_idle()
    async with _backup_lock:
        await asyncio.to_thread(_auto_service().vault.reset)
    state.auth.audit("autobackup_reset", actor["username"], "Ziele und Zeitplan zurückgesetzt", _client_ip(request))
    return {"ok": True}


@app.post("/api/admin/backup/restore")
async def admin_backup_restore(request: Request, body: dict = Body(...)):
    actor = _require_backup_owner(request)
    _backup_idle()
    if body.get("confirmation") != "RESTORE":
        raise _HTTPError(400, "Type RESTORE to confirm replacement of this installation.")
    await asyncio.to_thread(state.auth.confirm_password, actor, str(body.get("password") or ""), _client_ip(request))
    token = str(body.get("token") or "")
    if not re.fullmatch(r"[a-f0-9]{32}", token):
        raise _HTTPError(400, "Upload and check a backup first.")
    async with _backup_lock:
        folder = _backup_dir()
        try:
            preview = json.loads((folder / (token + ".json")).read_text())
        except (OSError, ValueError):
            raise _HTTPError(400, "Upload and check a backup first.")
        if preview.get("actor_id") != actor["id"] or time.time() - preview.get("created_at", 0) > 3600:
            raise _HTTPError(400, "The preview expired or belongs to another account. Upload it again.")
        if not await asyncio.to_thread(_backup.helper_available, _version.REPO_ROOT, state._data_dir):
            raise _HTTPError(409, "Install the restore helper first: sudo ./scripts/install_backup_helper.sh")
        if await asyncio.to_thread(_backup.digest, folder / (token + ".tar.gz")) != preview["sha256"]:
            raise _HTTPError(409, "The backup changed after validation. Upload it again.")
        _backup.atomic_json(folder / "restore-status.json", {"state": "queued", "updated_at": time.time(),
                                                           "message": "Restore queued; services will restart."})
        state.auth.audit("backup_restore_requested", actor["username"], token, _client_ip(request))
        # The root-owned systemd path unit observes this atomic rename. No sudo
        # from the dashboard: its NoNewPrivileges hardening stays enabled.
        _backup.atomic_json(folder / "restore-request.json", {"token": token, "sha256": preview["sha256"]})
        return {"ok": True, "state": "queued", "message": "Restore started. Both services will restart; sign in with the source account afterwards."}


# ---------------------------------------------------------------- branding
# Own logo and favicon, uploaded in the admin area and kept in SQLite.
_BRANDING_KINDS = {"logo": "logo", "favicon": "favicon", "aprs.site1.logo": "aprs.site1.logo",
                   "aprs.site2.logo": "aprs.site2.logo", "aprs.site3.logo": "aprs.site3.logo"}
_BRANDING_MAX = 1024 * 1024
_SVG_FORBIDDEN = re.compile(rb"<script|<foreignobject|\bon[a-z]+\s*=|javascript:|<iframe|<embed|<object"
                            rb"|xlink:href\s*=\s*[\"']\s*(?!#|data:image/)|\bhref\s*=\s*[\"']\s*(?!#|data:image/)",
                            re.I)


def _branding_db():
    state.auth._x("CREATE TABLE IF NOT EXISTS branding (kind TEXT PRIMARY KEY, mime TEXT NOT NULL, "
                  "data BLOB NOT NULL, updated REAL NOT NULL)")


def _sniff_branding(data: bytes) -> Optional[str]:
    mime = sniff_image(data)
    if mime:
        return mime
    if data[:4] == b"\x00\x00\x01\x00":
        return "image/x-icon"
    head = data[:2048].lstrip().lower()
    if head.startswith(b"<?xml") or head.startswith(b"<svg") or b"<svg" in head:
        if _SVG_FORBIDDEN.search(data):
            raise _HTTPError(400, "This SVG contains scripts or external links and is not accepted.")
        return "image/svg+xml"
    return None


@app.get("/branding/{kind}")
async def get_branding(kind: str):
    if kind not in _BRANDING_KINDS:
        raise _HTTPError(404, "Not found")
    _branding_db()
    rows = state.auth._q("SELECT mime, data FROM branding WHERE kind = ?", (kind,))
    if not rows:
        return FileResponse(Path(__file__).parent / "static" / "n8schicht-icon.svg", media_type="image/svg+xml")
    return Response(bytes(rows[0]["data"]), media_type=rows[0]["mime"], headers={
        "Cache-Control": "public, max-age=86400",
        "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; img-src data:"})


@app.post("/api/admin/branding/{kind}")
async def upload_branding(kind: str, request: Request, body: dict = Body(...)):
    actor = _require_admin(request)
    if kind not in _BRANDING_KINDS:
        raise _HTTPError(404, "Unknown image.")
    raw = str(body.get("data") or "")
    if "," in raw and raw.startswith("data:"):
        raw = raw.split(",", 1)[1]
    try:
        data = base64.b64decode(raw, validate=True)
    except Exception:
        raise _HTTPError(400, "The image could not be read.")
    if not data or len(data) > _BRANDING_MAX:
        raise _HTTPError(400, "The image must be smaller than 1 MB.")
    mime = _sniff_branding(data)
    if not mime:
        raise _HTTPError(400, "Please upload a PNG, JPEG, GIF, WebP, SVG or ICO image.")
    _branding_db()
    now = time.time()
    state.auth._x("INSERT OR REPLACE INTO branding (kind, mime, data, updated) VALUES (?,?,?,?)", (kind, mime, data, now))
    url = f"/branding/{kind}?v={int(now)}"
    changed = state.settings.update(dashboard_config, {kind: url}, actor["username"])
    state.auth.audit("branding_uploaded", actor["username"], f"{kind} ({mime}, {len(data)} bytes)", _client_ip(request))
    await _after_settings_change(changed)
    return {"ok": True, "url": url, "mime": mime, "size": len(data)}


@app.delete("/api/admin/branding/{kind}")
async def delete_branding(kind: str, request: Request):
    actor = _require_admin(request)
    if kind not in _BRANDING_KINDS:
        raise _HTTPError(404, "Unknown image.")
    _branding_db()
    state.auth._x("DELETE FROM branding WHERE kind = ?", (kind,))
    changed = state.settings.update(dashboard_config, {kind: FIELD_BY_KEY[kind].default}, actor["username"])
    state.auth.audit("branding_removed", actor["username"], kind, _client_ip(request))
    await _after_settings_change(changed)
    return {"ok": True}


# ---------------------------------------------------------------- avatars
# Only for IDs registered at FreeRadioID, served from SQLite (see dashboard/avatars.py).
# Proxying also keeps viewers' IPs away from third parties.
def _avatars_enabled() -> bool:
    frid = dashboard_config.get("freeradioid") or {}
    return bool(frid.get("avatars", True) and frid.get("avatar_url", True))


async def sync_avatars(trigger: str = ""):
    """Fetch new/stale avatars of all FreeRadioID-registered IDs into SQLite."""
    if not _avatars_enabled():
        return
    ids = state.user_db.frid_ids()
    if not ids:
        return
    try:
        result = await state.avatars.sync(ids)
    except Exception as e:
        logger.warning(f"🖼️ Avatar sync failed ({trigger}): {e}")
        return
    if result.get("fetched"):
        # open pages switch to the new image URLs (and so past any cached "no avatar")
        message = json.dumps({"type": "avatars_updated", "timestamp": datetime.now().timestamp(),
                              "data": {"version": state.avatars.version()}})
        for client in list(state.websocket_clients):
            try:
                await client.send_text(message)
            except Exception:
                pass


@app.get("/api/avatar/{dmr_id}")
async def get_avatar(dmr_id: int):
    # short: an ID may get an avatar with the next sync
    miss = Response(status_code=404, headers={"Cache-Control": "public, max-age=300"})
    if not _avatars_enabled() or not state.user_db.is_frid(dmr_id):
        return miss       # not registered at FreeRadioID: no avatar, no request to FreeRadioID
    hit = state.avatars.get(dmr_id)
    if hit is None:       # registered but not synced yet: fetch this one now
        try:
            await asyncio.to_thread(state.avatars.fetch_one, dmr_id)
        except Exception as e:
            logger.debug(f"Avatar {dmr_id}: {e}")
            return miss
        hit = state.avatars.get(dmr_id)
    if not hit or not hit[0]:
        return miss
    return Response(hit[2], media_type=hit[1] or "image/png", headers={"Cache-Control": "public, max-age=86400"})


# REST API endpoints
@app.get("/api/config")
async def get_config():
    """Public part of the dashboard configuration (no secrets)."""
    cfg = {k: dashboard_config[k] for k in _PUBLIC_CONFIG_KEYS if k in dashboard_config}
    frid = dashboard_config.get("freeradioid") or {}
    cfg["freeradioid"] = {"avatars": bool(frid.get("avatars", True) and frid.get("avatar_url", True)),
                          "avatar_version": state.avatars.version()}
    cfg["public_dashboard"] = _public_dashboard()
    tgs = _tg_cfg()
    cfg["tg_stats"] = {"enabled": bool(tgs.get("enabled", True)), "public": bool(tgs.get("public", True))}
    cfg["connect"] = {"enabled": bool((dashboard_config.get("connect") or {}).get("enabled", True))}
    cfg["aprs"] = {"enabled": state.aprs.enabled,
                   "tab": bool(state.aprs.enabled and state.aprs.c("aprs.map.dashboard_tab", True))}
    # link menu: address of the cached site icon of every web link
    links = dict(cfg.get("links") or {})
    if links.get("items"):
        links["items"] = [{**i, "icon_key": _siteicons.key_for(i["url"]) if i.get("site_icon", True) else None}
                          for i in links["items"] if isinstance(i, dict)]
        cfg["links"] = links
    return cfg


def _link_icon_urls() -> List[str]:
    items = ((dashboard_config.get("links") or {}).get("items")) or []
    return [i["url"] for i in items if isinstance(i, dict) and i.get("site_icon", True) is not False
            and _siteicons.origin_for(i.get("url", ""))]


async def _refresh_link_icons(force: bool = False) -> None:
    urls = _link_icon_urls()
    if urls:
        try:
            await asyncio.to_thread(state.icons.refresh_many, urls, force)
        except Exception as e:
            logger.debug(f"link icons: {e}")


@app.get("/api/link-icon/{key}")
async def link_icon(key: str):
    """Cached favicon of a linked website (only for links that are in the menu)."""
    if not re.fullmatch(r"[0-9a-f]{64}", key):
        raise _HTTPError(404, "unknown icon")
    url = next((u for u in _link_icon_urls() if _siteicons.key_for(u) == key), None)
    if not url:
        raise _HTTPError(404, "unknown icon")
    icon = state.icons.cached(key)
    if icon is None:                       # not fetched yet: fill the cache now (once per hour at most)
        await asyncio.to_thread(state.icons.refresh_one, url)
        icon = state.icons.cached(key)
    if icon is None:
        raise _HTTPError(404, "no icon")
    return Response(icon["data"], media_type=icon["content_type"], headers={
        "Cache-Control": "public, max-age=86400", "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; img-src data:"})


@app.post("/api/admin/link-icons/refresh")
async def admin_refresh_link_icons(request: Request):
    actor = _require_admin(request)
    urls = _link_icon_urls()
    try:
        await asyncio.to_thread(state.icons.refresh_many, urls, True)
    except Exception as e:
        logger.exception("Manual site icon refresh failed")
        raise _HTTPError(502, f"Site icon refresh failed: {e}")
    statuses = [state.icons.status(_siteicons.key_for(url)) for url in urls]
    cached = sum(bool(item and item["ok"]) for item in statuses)
    failed = len(urls) - cached
    state.auth.audit("site_icons_refresh", actor["username"], f"{cached} cached, {failed} unavailable",
                     _client_ip(request))
    return {"ok": True, "total": len(urls), "cached": cached, "unavailable": failed}


@app.get("/api/repeaters")
async def get_repeaters(request: Request):
    """Get all connected repeaters"""
    return view_for(current_user(request), {"repeaters": list(state.repeaters.values())})


@app.get("/api/outbounds")
async def get_outbounds(request: Request):
    """Get all outbound connections"""
    return view_for(current_user(request), {"outbounds": list(state.outbounds.values())})


@app.get("/api/streams")
async def get_streams(request: Request):
    """Get all active streams"""
    return view_for(current_user(request), {"streams": list(state.streams.values())})


@app.get("/api/last-heard")
async def get_last_heard(request: Request):
    """Last heard stations – the same list the dashboard shows (used by HobbyRadioPortal, plugin "dmr")."""
    return view_for(current_user(request), {"last_heard": state.last_heard})


@app.get("/api/events")
async def get_events(request: Request, limit: int = 100):
    """Get recent events"""
    return view_for(current_user(request), {"events": list(state.events)[-limit:]})


# ---------------------------------------------------------------- talkgroup statistics
def _tg_cfg() -> dict:
    return dashboard_config.get("tg_stats") or {}


_tg_names_memo: tuple = (None, {})


def _own_tg_names() -> Dict[int, str]:
    global _tg_names_memo
    text = _tg_cfg().get("names") or ""
    if _tg_names_memo[0] != text:
        _tg_names_memo = (text, _parse_tg_names(text))
    return _tg_names_memo[1]


def _tg_names() -> Dict[int, str]:
    """Talkgroup names: the N8schicht list, overridden/completed by the own names (admin area)."""
    tl = dashboard_config.get("talkgroups") or {}
    names = dict(state.talkgroups.names()) if tl.get("list", True) else {}
    names.update(_own_tg_names())
    return names


async def refresh_talkgroups(trigger: str = "") -> None:
    tl = dashboard_config.get("talkgroups") or {}
    if not tl.get("list", True):
        await broadcast_talkgroups()
        return
    try:
        await asyncio.to_thread(state.talkgroups.refresh, tl.get("url") or "")
    except Exception:
        return
    await broadcast_talkgroups()


async def broadcast_talkgroups() -> None:
    if not state.websocket_clients:
        return
    msg = json.dumps({"type": "talkgroups", "timestamp": datetime.now().timestamp(),
                      "data": {"names": {str(k): v for k, v in _tg_names().items()}}})
    for ws in list(state.websocket_clients):
        try:
            await ws.send_text(msg)
        except Exception:
            pass


@app.get("/api/talkgroups")
async def get_talkgroups(request: Request, activity: int = 0):
    """All talkgroup names (list + own); with activity=1 also the calls of the last 30 days."""
    out: Dict[str, Any] = {"names": {str(k): v for k, v in _tg_names().items()},
                           "own": [str(k) for k in _own_tg_names()],
                           "list": {"enabled": bool((dashboard_config.get("talkgroups") or {}).get("list", True)),
                                    "count": state.talkgroups.count(), "updated": state.talkgroups.updated,
                                    "error": state.talkgroups.error}}
    if activity:
        since = time.time() - 30 * 86400
        rows = state.auth._q("SELECT tg, COUNT(*) AS n, SUM(duration) AS d, MAX(ts) AS last FROM tg_calls "
                             "WHERE ts >= ? AND is_data = 0 GROUP BY tg", (since,))
        out["activity"] = {str(r["tg"]): {"calls": r["n"], "duration": round(r["d"] or 0, 1), "last": r["last"]} for r in rows}
    return out


def _record_tg_call(stream: dict, data: dict, connection_type: str, ts) -> None:
    """Store one finished group call for the talkgroup statistics."""
    if not _tg_cfg().get("enabled", True):
        return
    if (stream.get('call_type') or data.get('call_type') or 'group') != 'group':
        return
    tg = stream.get('dst_id') or data.get('dst_id')
    if not tg:
        return
    if connection_type in ('openbridge', 'outbound'):
        source = data.get('connection_name') or stream.get('connection_name') or connection_type
    else:
        source = str(stream.get('repeater_id') or data.get('repeater_id') or '')
    try:
        state.tgstats.record(int(tg), float(data.get('duration') or 0), slot=data.get('slot') or stream.get('slot'),
                             src_id=stream.get('rf_src') or stream.get('src_id') or data.get('src_id'),
                             is_data=bool(stream.get('is_data') or data.get('is_data')), source=source,
                             ts=float(ts) if ts else None,
                             origin=connection_type if connection_type in ('openbridge', 'outbound') else 'repeater',
                             talker_alias=(data.get('talker_alias') or stream.get('talker_alias') or None))
    except Exception as e:
        logger.warning(f"📈 Could not store talkgroup statistics: {e}")


def _record_obp_call(stream: dict, data: dict, ts) -> None:
    """Store one finished OBP stream (rx = from the far end, tx = to the far end)."""
    if not _tg_cfg().get("enabled", True):
        return
    if (stream.get('call_type') or data.get('call_type') or 'group') != 'group':
        return
    tg = stream.get('dst_id') or data.get('dst_id')
    trunk = data.get('connection_name') or stream.get('connection_name')
    if not tg or not trunk:
        return
    tx = bool(data.get('is_assumed', stream.get('is_assumed', False)))
    try:
        state.obpstats.record(trunk, 'tx' if tx else 'rx', int(tg), float(data.get('duration') or 0),
                              slot=data.get('slot') or stream.get('slot'),
                              src_id=stream.get('rf_src') or stream.get('src_id') or data.get('src_id'),
                              is_data=bool(stream.get('is_data') or data.get('is_data')),
                              ts=float(ts) if ts else None)
    except Exception as e:
        logger.warning(f"↔️ Could not store OpenBridge statistics: {e}")


def _tag_origin(source: str, origin: str) -> None:
    try:
        state.tgstats.tag_origin(source, origin)
    except Exception as e:
        logger.debug(f"origin backfill for {source}: {e}")


def _obp_stats_allowed(request) -> bool:
    cfg = _tg_cfg()
    return bool(cfg.get("enabled", True)) and (bool(cfg.get("public", True)) or bool(current_user(request)))


def _obp_public(o: dict) -> dict:
    """Trunk info for the browser (never the passphrase)."""
    tgs = o.get('talkgroups') or {}
    ts1 = sum(1 for v in tgs.values() if str(v) == '1')
    return {k: o.get(k) for k in ('connection_name', 'network_id', 'remote_address', 'remote_port', 'local_address',
                                  'local_port', 'description', 'preserve_source_peer', 'status', 'connected_at',
                                  'disconnected_at', 'last_activity', 'alive', 'last_keepalive', 'peer_version',
                                  'tx_version', 'protocol', 'enhanced_obp', 'all_talkgroups', 'default_slot')} | {
        'talkgroup_count': len(tgs), 'ts1': ts1, 'ts2': len(tgs) - ts1}


@app.get("/api/openbridge")
async def get_openbridge(request: Request, range: str = "today", trunk: str = "", brief: int = 0):
    """OpenBridge trunks: status, talkgroup map with names, traffic in both directions."""
    if range not in TG_RANGES:
        raise _HTTPError(400, f"range must be one of {', '.join(TG_RANGES)}")
    allowed = _obp_stats_allowed(request)
    today = await asyncio.to_thread(state.obpstats.today) if allowed else {}
    out = {"stats": allowed, "range": range, "trunks": []}
    names = _tg_names() if not brief else {}
    for o in state.openbridges.values():
        t = _obp_public(o)
        t["today"] = today.get(o.get('connection_name'), {"rx": 0, "tx": 0, "rx_duration": 0.0, "tx_duration": 0.0})
        if not brief and (not trunk or trunk == o.get('connection_name')):
            tgs = o.get('talkgroups') or {}
            t["talkgroups"] = sorted(([int(k), int(v), names.get(int(k), "")] for k, v in tgs.items()),
                                     key=lambda x: x[0])
            if allowed:
                t["summary"] = await asyncio.to_thread(
                    state.obpstats.summary, o.get('connection_name'), range, names,
                    lambda rid: state.user_db.get(rid, '') if rid else '')
        out["trunks"].append(t)
    return view_for(current_user(request), out)


@app.get("/api/stats/talkgroups")
async def get_tg_stats(request: Request, range: str = "today"):
    """Calls and airtime per talkgroup, plus a time series for the charts."""
    cfg = _tg_cfg()
    if not cfg.get("enabled", True):
        raise _HTTPError(404, "Talkgroup statistics are switched off.")
    if not cfg.get("public", True) and not current_user(request):
        raise _HTTPError(401, "Please log in.")
    if range not in TG_RANGES:
        raise _HTTPError(400, f"range must be one of {', '.join(TG_RANGES)}")
    return await asyncio.to_thread(state.tgstats.summary, range, _tg_names(),
                                   lambda rid: state.user_db.get(rid, '') if rid else '')


# ---------------------------------------------------------------- configuration tab
@app.get("/api/connect")
async def get_connect_info():
    """What a sysop needs to connect a hotspot or repeater (public part only)."""
    con = dashboard_config.get("connect") or {}
    if not con.get("enabled", True):
        raise _HTTPError(404, "The configuration tab is switched off.")
    d = state.settings.dmr_values()
    p = "dmr.repeater_configurations.default."
    frid = bool(d.get("dmr.freeradioid.enabled", True))
    slot1, slot2 = d.get(p + "slot1_talkgroups"), d.get(p + "slot2_talkgroups")
    guest = d.get("dmr.freeradioid.guest_talkgroups") if frid else []
    names = _tg_names()
    wanted = {int(t) for lst in (slot1, slot2, guest) if isinstance(lst, list) for t in lst}
    return {
        "title": dashboard_config.get("dashboard_title") or "DMR Die N8schicht",
        "description": dashboard_config.get("server_description") or "",
        "logo": dashboard_config.get("logo") or "",
        "host": (con.get("host") or "").strip() or dashboard_config.get("server_name") or "",
        "port": d.get("dmr.global.port_ipv4", 62031),
        "freeradioid": frid,
        "password": d.get(p + "passphrase") if con.get("show_password", True) else None,
        "slot1": slot1, "slot2": slot2, "guest": guest,
        "trust": bool(d.get(p + "trust", False)),
        "unit_calls": bool(d.get(p + "default_unit_calls", False)),
        "tg_names": {str(k): v for k, v in names.items() if k in wanted},
        "note": con.get("note") or "",
        "daprs": _connect_daprs(d),
    }


def _connect_daprs(d: dict) -> Optional[dict]:
    """How to send GPS positions (DAPRS) – only when APRS and the decoding in the DMR server are on."""
    a = state.aprs
    if not (a.enabled and a.c("daprs.enabled", True) and d.get("dmr.daprs.enabled")):
        return None
    https_cfg = dashboard_config.get("https") or {}
    doms = _aprs_domains()
    scheme = "https" if https_cfg.get("enabled") else "http"
    map_url = f"{scheme}://{doms[0]}/" if doms else "/aprs"
    up = a.c("aprs.uplink.enabled", False) and a.c("daprs.to_aprsis", True)
    return {
        "embedded": bool(d.get("dmr.daprs.embedded_gps", True)),
        "data": bool(d.get("dmr.daprs.data_gps", True)),
        "data_ids": d.get("dmr.daprs.data_ids"),            # None = any destination
        "ssid": int(a.c("daprs.ssid", 7) or 0),
        "symbol": a.c("daprs.symbol", "/[") or "/[",
        "interval": int(a.c("daprs.min_interval", 60) or 60),
        "uplink": bool(up), "network": a.network_label if up else "",
        "guests_local": bool(a.c("daprs.block_guests", True)),
        "map_url": map_url,
    }


@app.get("/api/stats")
async def get_stats():
    """Get system statistics"""
    return {
        "stats": state.stats,
        "repeaters_connected": len([r for r in state.repeaters.values() if r.get('status') == 'connected']),
        "active_streams": len([s for s in state.streams.values() if s.get('status') == 'active'])
    }


# ---------------------------------------------------------------- FreeRadioID
_frid_profile_cache: Dict[int, tuple] = {}   # radio_id -> (timestamp, profile or None)
_FRID_PROFILE_TTL = 3600


def _frid_profile_fetch_sync(radio_id: int) -> Optional[dict]:
    import urllib.request
    cfg = dashboard_config.get("freeradioid", {}) or {}
    url = cfg.get("profile_url", "https://freeradioid.net/api/dmr/user/?id={id}").replace("{id}", str(radio_id))
    req = urllib.request.Request(url, headers={"User-Agent": "HBlink4-Dashboard FreeRadioID"})
    with urllib.request.urlopen(req, timeout=4) as resp:
        raw = json.loads(resp.read(65536).decode("utf-8", errors="replace"))
    results = raw.get("results") or []
    if not results:
        return None
    r = results[0]
    return {
        "registered": bool(raw.get("reg")),
        "callsign": r.get("callsign") or "",
        "name": " ".join(x for x in (r.get("fname"), r.get("surname")) if x) or "",
        "city": r.get("city") or "",
        "state": r.get("state") if isinstance(r.get("state"), str) else "",
        "country": r.get("country") or "",
        "remarks": r.get("remarks") or "",
    }


async def freeradioid_profile(radio_id: int) -> Optional[dict]:
    """
    FreeRadioID profile for a radio ID: live API (cached for an hour), falling
    back to the downloaded registry. None if FreeRadioID knows nothing about it.
    """
    cfg = dashboard_config.get("freeradioid", {}) or {}
    profile = None
    if cfg.get("profile_lookup", True):
        cached = _frid_profile_cache.get(radio_id)
        if cached and datetime.now().timestamp() - cached[0] < _FRID_PROFILE_TTL:
            profile = cached[1]
        else:
            try:
                profile = await asyncio.to_thread(_frid_profile_fetch_sync, radio_id)
            except Exception as e:
                logger.debug(f"FreeRadioID profile lookup for {radio_id} failed: {e}")
                profile = cached[1] if cached else None
            else:
                _frid_profile_cache[radio_id] = (datetime.now().timestamp(), profile)
    if profile is None:
        reg = state.user_db.frid_info(radio_id)
        if reg:
            profile = {**reg, "registered": True, "remarks": ""}
    if profile is not None:
        profile = dict(profile)
        profile["registered"] = profile.get("registered") or state.user_db.is_frid(radio_id)
        profile["avatar"] = f"/api/avatar/{radio_id}"
    return profile


@app.get("/api/freeradioid/{radio_id}")
async def get_freeradioid_profile(radio_id: int):
    """FreeRadioID profile (name, location, registration, avatar) for a radio ID."""
    return {"radio_id": radio_id, "profile": await freeradioid_profile(radio_id)}


@app.get("/api/station/{radio_id}")
async def get_station_info(radio_id: int):
    """Popup for any radio ID (Last Heard, slots, OpenBridge): FreeRadioID profile,
    callsign database and the last call heard here. Contains no addresses."""
    if not 1 <= radio_id <= 0xFFFFFFFF:
        raise _HTTPError(400, "Invalid radio ID")
    heard = next((dict(u) for u in state.last_heard if u.get("radio_id") == radio_id), None)
    if heard:
        heard = {k: heard.get(k) for k in ("callsign", "source_name", "slot", "talkgroup", "call_type",
                                            "is_data", "last_heard", "active")}
    return {
        "radio_id": radio_id,
        "callsign": state.user_db.get(radio_id, "") or (heard or {}).get("callsign") or "",
        "profile": await freeradioid_profile(radio_id),
        "heard": heard,
        "connected": radio_id in state.repeaters,   # a station logged in here -> station detail view
    }


@app.get("/api/repeater/{repeater_id}")
async def get_repeater_details(repeater_id: int, request: Request):
    return view_for(current_user(request), await _repeater_details(repeater_id))


async def _repeater_details(repeater_id: int):
    """Get detailed information about a specific repeater"""
    if repeater_id not in state.repeaters:
        raise _HTTPError(404, "Repeater not found")
    
    repeater = state.repeaters[repeater_id]
    details = state.repeater_details.get(repeater_id, {})
    
    # If no details event received yet, try to determine from config
    if not details or not details.get('matched_pattern'):
        # Try to load pattern from config
        config_path = Path(__file__).parent.parent / 'config' / 'config.json'
        try:
            with open(config_path) as f:
                config = json.load(f)
            
            # Import here to avoid circular dependencies
            import sys
            sys.path.insert(0, str(Path(__file__).parent.parent))
            from hblink4.access_control import RepeaterMatcher
            
            matcher = RepeaterMatcher(config)
            pattern = matcher.get_pattern_for_repeater(repeater_id, repeater.get('callsign'))
            
            if pattern:
                details['matched_pattern'] = pattern.name
                details['pattern_description'] = pattern.description
            else:
                details['matched_pattern'] = 'Default'
                details['pattern_description'] = 'Using default configuration'
        except Exception as e:
            logger.warning(f'Could not determine pattern for repeater {repeater_id}: {e}')
            details['matched_pattern'] = details.get('matched_pattern', 'Default')
            details['pattern_description'] = details.get('pattern_description', 'Using default configuration')
    
    # Calculate runtime statistics
    current_time = datetime.now().timestamp()
    uptime_seconds = int(current_time - repeater.get('connected_at', current_time))
    
    # Count streams for this repeater
    total_streams = len([e for e in state.events 
                        if e.get('type') == 'stream_start' 
                        and e.get('data', {}).get('repeater_id') == repeater_id])
    
    # Find active streams
    slot1_active = any(s.get('repeater_id') == repeater_id and s.get('slot') == 1 
                      and s.get('status') == 'active' 
                      for s in state.streams.values())
    slot2_active = any(s.get('repeater_id') == repeater_id and s.get('slot') == 2 
                      and s.get('status') == 'active' 
                      for s in state.streams.values())
    
    # Clean up IPv4-mapped IPv6 addresses
    address = repeater.get('address', '')
    if address.startswith('::ffff:'):
        address = address[7:]  # Remove '::ffff:' prefix
    
    # Build comprehensive response
    return {
        "repeater_id": repeater_id,
        "callsign": repeater.get('callsign', 'UNKNOWN'),
        "connection_type": repeater.get('connection_type', details.get('connection_type', 'unknown')),
        "connection": {
            "address": address,
            "connected_at": repeater.get('connected_at', 0),
            "uptime_seconds": uptime_seconds,
            "last_ping": repeater.get('last_ping', 0),
            "missed_pings": repeater.get('missed_pings', 0),
            "status": repeater.get('status', 'unknown')
        },
        "location": {
            "location": repeater.get('location', ''),
            "latitude": details.get('latitude', ''),
            "longitude": details.get('longitude', ''),
            "height": details.get('height', '')
        },
        "frequencies": {
            "rx_freq": repeater.get('rx_freq', ''),
            "tx_freq": repeater.get('tx_freq', ''),
            "tx_power": details.get('tx_power', ''),
            "colorcode": repeater.get('colorcode', ''),
            "slots": details.get('slots', '')
        },
        "access_control": {
            "connection_category": details.get('matched_pattern', 'Default'),
            "category_description": details.get('pattern_description', 'Using default configuration'),
            "rpto_received": repeater.get('rpto_received', False),
            "auth_method": repeater.get('auth_method', 'local'),
            "slot1_talkgroups": repeater.get('slot1_talkgroups') if 'slot1_talkgroups' in repeater else None,
            "slot2_talkgroups": repeater.get('slot2_talkgroups') if 'slot2_talkgroups' in repeater else None,
            "talkgroups_source": "RPTO" if repeater.get('rpto_received') else "Pattern/Config"
        },
        "metadata": {
            "description": details.get('description', ''),
            "url": details.get('url', ''),
            "software_id": repeater.get('software_id') or details.get('software_id', ''),
            "package_id": repeater.get('package_id') or details.get('package_id', '')
        },
        "freeradioid": await freeradioid_profile(repeater_id),
        "statistics": {
            "total_streams_today": total_streams,
            "slot1_active": slot1_active,
            "slot2_active": slot2_active
        }
    }


# WebSocket endpoint
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket connection for real-time updates"""
    token = websocket.cookies.get(SESSION_COOKIE)
    user = state.auth.session_user(token)
    if not _public_dashboard() and not user:
        await websocket.close(code=4401)
        return
    await websocket.accept()
    raw_ws = websocket
    websocket = ClientSocket(raw_ws, token, user)
    state.websocket_clients.add(websocket)
    logger.info(f"🌐 WebSocket client connected (total: {len(state.websocket_clients)})")
    
    # Log current state for debugging
    logger.info(f"📊 Sending initial_state: hblink_connected={state.hblink_connected}, repeaters={len(state.repeaters)}, streams={len(state.streams)}")
    
    # Send initial state
    await websocket.send_json({
        'type': 'initial_state',
        'data': {
            'repeaters': list(state.repeaters.values()),
            'repeater_details': state.repeater_details,
            'outbounds': list(state.outbounds.values()),
            'openbridges': list(state.openbridges.values()),
            'streams': list(state.streams.values()),
            'events': list(state.events)[-50:],
            'stats': state.stats,
            'last_heard': state.last_heard,
            'hblink_connected': state.hblink_connected,
            'user_db_status': state.user_db.status_dict()
        }
    })
    
    try:
        while True:
            # Keep connection alive (client can send ping)
            data = await raw_ws.receive_text()
            if data == 'ping':
                await websocket.send_text('pong')
    except WebSocketDisconnect:
        logger.debug(f"WebSocket client disconnected (remaining: {len(state.websocket_clients) - 1})")
    except asyncio.CancelledError:
        # Expected during shutdown - don't log as error
        logger.debug(f"WebSocket task cancelled during shutdown")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        # Always clean up, regardless of how we exited
        state.websocket_clients.discard(websocket)


# Serve frontend
# ===================================================================== APRS
# APRS-IS server, uplink and DAPRS gateway live in dashboard/aprs/. Here: the map
# page (also at / for the APRS domains), its API, live updates and the admin API.
_APRS_HTML = Path(__file__).parent / "static" / "aprs.html"
_OSM_ATTR = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
_APRS_TILES = {
    "osm": ("https://tile.openstreetmap.org/{z}/{x}/{y}.png", _OSM_ATTR),
    "topo": ("https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png",
             _OSM_ATTR + ', SRTM | &copy; <a href="https://opentopomap.org">OpenTopoMap</a> (CC-BY-SA)'),
}


_APRS_SITES = (1, 2, 3)


def _aprs_domains(https_only: bool = False) -> List[str]:
    """Domains that open the map directly; https_only: those that go into the certificate."""
    if not state.aprs.enabled:
        return []
    out: List[str] = []
    for n in _APRS_SITES:
        d = str(state.aprs.c(f"aprs.site{n}.domain", "") or "").strip().lower()
        if d and d not in out and (not https_only or state.aprs.c(f"aprs.site{n}.https", True)):
            out.append(d)
    return out


def _request_host(conn) -> str:
    return (conn.headers.get("host") or "").split(":")[0].strip().lower()


def _aprs_site(conn) -> dict:
    """Title, subtitle and logo of the map for the domain it was opened on."""
    host = _request_host(conn)
    for n in _APRS_SITES:
        d = str(state.aprs.c(f"aprs.site{n}.domain", "") or "").strip().lower()
        if d and d == host:
            return {"domain": d, "title": state.aprs.c(f"aprs.site{n}.title", "") or dashboard_config.get("dashboard_title")
                    or "APRS", "subtitle": state.aprs.c(f"aprs.site{n}.subtitle", "") or f"APRS map · {d}",
                    "logo": state.aprs.c(f"aprs.site{n}.logo", "") or ""}
    return {"domain": host, "title": dashboard_config.get("dashboard_title") or "DMR Die N8schicht",
            "subtitle": f"APRS map · {dashboard_config.get('server_name') or host}",
            "logo": ""}


def _aprs_repeaters() -> List[dict]:
    """Connected repeaters/hotspots with their login position (for the APRS objects)."""
    out = []
    for rid, r in list(state.repeaters.items()):
        d = state.repeater_details.get(rid) or {}
        out.append({**r, "latitude": d.get("latitude", ""), "longitude": d.get("longitude", ""),
                    "height": d.get("height", ""), "url": d.get("url", "")})
    return out


def _aprs_allowed(conn) -> bool:
    return bool(state.aprs.c("aprs.map.public", True)) or current_user(conn) is not None


def _aprs_check(request: Request) -> None:
    if not state.aprs.enabled:
        raise _HTTPError(404, "APRS is switched off.")
    if not _aprs_allowed(request):
        raise _HTTPError(401, "Please log in.")


def _aprs_sources() -> Optional[set]:
    return None if state.aprs.c("aprs.map.sources", "all") == "all" else {"dmr", "rpt", "local"}


def _aprs_page() -> HTMLResponse:
    if not _APRS_HTML.exists():
        return HTMLResponse("<h1>APRS map not found</h1>", status_code=404)
    # OSM tiles require a Referer. The dashboard's same-origin default hides
    # it from external tile servers even when the map itself uses HTTPS.
    return HTMLResponse(_APRS_HTML.read_text(encoding="utf-8"),
                        headers={"Referrer-Policy": "strict-origin-when-cross-origin"})


@app.get("/aprs", response_class=HTMLResponse)
async def aprs_map_page():
    if not state.aprs.enabled:
        return HTMLResponse("<h1>APRS is switched off</h1>", status_code=404)
    return _aprs_page()


@app.get("/api/aprs/config")
async def aprs_config(request: Request):
    if not state.aprs.enabled:
        raise _HTTPError(404, "APRS is switched off.")
    c = state.aprs.c
    try:
        lat, lon = (float(x) for x in str(c("aprs.map.center", "51.2, 10.4")).replace(";", ",").split(","))
    except ValueError:
        lat, lon = 51.2, 10.4
    style = c("aprs.map.tiles", "auto")
    if style not in ("auto", "dark", "osm", "topo", "custom"):
        style = "auto"
    url, attribution = _APRS_TILES["topo" if style == "topo" else "osm"]
    if style == "custom" and c("aprs.map.tile_url", ""):
        url, attribution = str(c("aprs.map.tile_url")), "Map tiles: own tile server"
    https_cfg = dashboard_config.get("https") or {}
    dash_url = (f"https://{https_cfg.get('domain')}/" if https_cfg.get("enabled") and https_cfg.get("domain")
                else "/dashboard" if _request_host(request) in _aprs_domains() else "/")
    site = _aprs_site(request)
    user = current_user(request)
    ports = []
    if state.aprs.running and state.aprs.c("aprs.server.enabled", False) and state.aprs.listening:
        ports = [p for p in (c("aprs.server.port_filter", 14580),) if p]
    return {
        "site": site,
        "theme": dashboard_config.get("theme") or {},
        "logo_size": dashboard_config.get("logo_size", 44),
        "logo_radius": dashboard_config.get("logo_radius", 0),
        "favicon": dashboard_config.get("favicon") or "",
        "map": {"center": [lat, lon], "zoom": int(c("aprs.map.zoom", 6) or 6), "tiles": url,
                "attribution": attribution, "dark": style if style in ("auto", "dark") else False,
                "tracks": bool(c("aprs.map.tracks", True)), "show_packets": bool(c("aprs.map.show_packets", True)),
                "max_age_hours": int(c("aprs.map.max_age_hours", 24) or 24), "sources": c("aprs.map.sources", "all")},
        "allowed": _aprs_allowed(request),
        "logged_in": bool(user), "admin": is_admin(user),
        "dashboard_url": dash_url,
        "network": state.aprs.network_label,
        "server": {"id": state.aprs.my_id, "ports": ports, "host": site["domain"] or _request_host(request),
                   "uplink": state.aprs.uplink.get("state") == "connected" and bool(state.aprs.uplink.get("verified"))},
        "version": _version._package_version(),
    }


@app.get("/api/aprs/stations")
async def aprs_stations(request: Request, hours: float = 0):
    _aprs_check(request)
    max_h = float(state.aprs.c("aprs.map.max_age_hours", 24) or 24)
    h = min(max_h, hours) if hours > 0 else max_h
    return {"stations": state.aprs.store.list(h * 3600, _aprs_sources()), "now": time.time()}


@app.get("/api/aprs/station/{call}")
async def aprs_station(call: str, request: Request):
    _aprs_check(request)
    call = call.strip()[:12]
    st = state.aprs.store.stations.get(call) or state.aprs.store.stations.get(call.upper())
    if not st:
        raise _HTTPError(404, "Unknown station.")
    sources = _aprs_sources()
    if sources is not None and st.get("source") not in sources:
        raise _HTTPError(404, "Unknown station.")
    hours = float(state.aprs.c("aprs.map.max_age_hours", 24) or 24)
    out = {"station": _aprs_public(st),
           "track": await asyncio.to_thread(state.aprs.store.track, st["call"], hours)
           if state.aprs.c("aprs.map.tracks", True) else []}
    if state.aprs.c("aprs.map.show_packets", True):
        out["packets"] = await asyncio.to_thread(state.aprs.store.packets_of, st["call"], 25)
    return out


@app.get("/api/aprs/packets")
async def aprs_packets(request: Request, limit: int = 100):
    _aprs_check(request)
    if not state.aprs.c("aprs.map.show_packets", True):
        return {"packets": []}
    sources = _aprs_sources()
    items = [p for p in reversed(state.aprs.store.recent)
             if sources is None or p.get("origin") != "uplink"]
    return {"packets": items[:max(1, min(500, limit))]}


@app.get("/api/aprs/status")
async def aprs_status(request: Request):
    _aprs_check(request)
    st = state.aprs.status(admin=False)
    return {k: st[k] for k in ("enabled", "running", "server_enabled", "clients", "counts", "version")} | {
        "uplink": {"state": st["uplink"].get("state"), "verified": st["uplink"].get("verified")},
        "stats": {k: st["stats"].get(k, 0) for k in ("rx", "daprs_positions", "from_uplink", "from_clients")}}


@app.websocket("/api/aprs/ws")
async def aprs_ws(websocket: WebSocket):
    if not state.aprs.enabled or not _aprs_allowed(websocket):
        await websocket.close(code=4401)
        return
    await websocket.accept()
    q = state.aprs.subscribe()

    async def reader():
        while True:
            msg = await websocket.receive_text()
            if msg == "ping":
                await websocket.send_text("pong")

    rt = asyncio.create_task(reader())
    try:
        while not rt.done():
            try:
                first = await asyncio.wait_for(q.get(), 15)
            except asyncio.TimeoutError:
                continue
            await asyncio.sleep(0.4)            # collect a few, send them as one frame
            batch = [first]
            while not q.empty() and len(batch) < 400:
                batch.append(q.get_nowait())
            sources = _aprs_sources()
            show_packets = bool(state.aprs.c("aprs.map.show_packets", True))
            items = []
            for m in batch:
                if m["type"] == "station" and (sources is None or m["station"].get("source") in sources):
                    items.append(m)
                elif m["type"] == "packet" and show_packets and (sources is None or m["packet"]["origin"] != "uplink"):
                    items.append(m)
            if items:
                await websocket.send_json({"type": "batch", "items": items})
    except Exception:
        pass
    finally:
        rt.cancel()
        state.aprs.unsubscribe(q)


# -- admin
@app.get("/api/admin/aprs")
async def admin_aprs(request: Request):
    _require_admin(request)
    st = state.aprs.status(admin=True)
    st["domains"] = _aprs_domains()
    st["https_domains"] = _aprs_domains(https_only=True)
    https_cfg = dashboard_config.get("https") or {}
    st["https"] = {"enabled": bool(https_cfg.get("enabled")), "domain": https_cfg.get("domain", ""),
                   "cert_names": sorted(_tls_manager.cert_names()) if _tls_manager else [],
                   "missing": _tls_manager.missing_names() if _tls_manager else []}
    return st


@app.post("/api/admin/aprs/kick/{client_id}")
async def admin_aprs_kick(client_id: int, request: Request):
    actor = _require_admin(request)
    if not state.aprs.kick(client_id):
        raise _HTTPError(404, "Client not connected.")
    state.auth.audit("aprs_client_kicked", actor["username"], str(client_id), _client_ip(request))
    return {"ok": True}


@app.post("/api/admin/aprs/reload")
async def admin_aprs_reload(request: Request):
    actor = _require_admin(request)
    await state.aprs.reload()
    state.auth.audit("aprs_restarted", actor["username"], "", _client_ip(request))
    return {"ok": True, "status": state.aprs.status(admin=True)}


@app.post("/api/admin/aprs/objects")
async def admin_aprs_objects(request: Request):
    _require_admin(request)
    state.aprs._obj_sent.clear()
    return {"ok": True, "sent": state.aprs.object_pass()}


@app.get("/api/admin/aprs/passcode")
async def admin_aprs_passcode(request: Request, call: str = ""):
    _require_admin(request)
    call = call.strip().upper()
    if not _aprs_valid_call(call):
        raise _HTTPError(400, "Callsign like DL1ABC or DL1ABC-9.")
    return {"call": call, "passcode": _aprs_passcode(call)}


@app.get("/dashboard", response_class=HTMLResponse)
@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Serve dashboard HTML (the APRS map at / on the APRS domains; /dashboard is always the dashboard)"""
    if request.url.path == "/" and state.aprs.enabled and _request_host(request) in _aprs_domains():
        return _aprs_page()
    html_path = Path(__file__).parent / 'static' / 'dashboard.html'
    if not html_path.exists():
        return HTMLResponse("<h1>Dashboard HTML not found</h1><p>Please create dashboard/static/dashboard.html</p>", status_code=404)
    with open(html_path) as f:
        return HTMLResponse(f.read())


# Mount static files
static_path = Path(__file__).parent / "static"
if static_path.exists():
    app.mount("/static", StaticFiles(directory=static_path), name="static")


def _ver_short(commit: str) -> str:
    return (commit or "")[:7]


@app.on_event("startup")
async def _start_update_loop():
    global _auto_loop_task
    asyncio.create_task(_update_loop())
    asyncio.create_task(_refresh_link_icons())
    _auto_loop_task = asyncio.create_task(_auto_service().loop())


DASH_CRASH_SERVICES = [
    (r"/dashboard/aprs/", "APRS"), (r"/dashboard/avatars\.py$", "Avatare"), (r"/dashboard/(auto)?backup\.py$", "Backup"),
    (r"/dashboard/auth\.py$", "Anmeldung"), (r"/dashboard/tls\.py$", "HTTPS"), (r"/dashboard/user_db\.py$", "ID-Datenbank"),
    (r"/dashboard/(talkgroups|tgstats)\.py$", "Talkgroups"), (r"/dashboard/obpstats\.py$", "OpenBridge-Statistik"),
    (r"/dashboard/settings\.py$", "Einstellungen"), (r"/dashboard/siteicons\.py$", "Site-Icons"),
    (r"/dashboard/server\.py$", "Dashboard"), (r"/(uvicorn|starlette|fastapi|websockets)/", "Webinterface"),
]


@app.on_event("startup")
async def startup_crashwatch():
    """Absturz-Melder (N8 Kit): Hänger der Event-Loop, abgestürzte Tasks, harter Absturz (faulthandler)."""
    try:
        from .n8_crash import CrashWatch
    except ImportError:
        from n8_crash import CrashWatch
    try:
        CrashWatch(str(state._data_dir), app="HBlink4-FreeRadioID", unit="hblink4-dash.service", services=DASH_CRASH_SERVICES).install()
    except Exception as e:  # noqa: BLE001
        logger.warning(f"Absturz-Melder nicht aktiv: {e}")


@app.on_event("startup")
async def startup_event():
    """Start event receiver on startup"""
    receiver_config = dashboard_config.get('event_receiver', {})

    # These are bind addresses -- hblink4 connects in to us. They were once named
    # host_ipv4/host_ipv6, which collided with the connect-target keys of the same
    # name in hblink4's own config. Accept the old names so existing installs keep
    # working, but the current convention is bind_* for listening, host_* for
    # connecting out.
    def _bind_addr(new_key, old_key, default):
        if new_key in receiver_config:
            return receiver_config[new_key]
        if old_key in receiver_config:
            logger.warning(
                f"⚠️  event_receiver.{old_key} is deprecated -- rename it to "
                f"{new_key} (it is a bind address, not a connect target)"
            )
            return receiver_config[old_key]
        return default

    receiver = EventReceiver(
        transport=receiver_config.get('transport', 'unix'),
        bind_ipv4=_bind_addr('bind_ipv4', 'host_ipv4', '127.0.0.1'),
        bind_ipv6=_bind_addr('bind_ipv6', 'host_ipv6', '::1'),
        port=receiver_config.get('port', 8765),
        unix_socket=receiver_config.get('unix_socket', '/tmp/hblink4.sock'),
        disable_ipv6=receiver_config.get('disable_ipv6', False)
    )
    asyncio.create_task(receiver.start())
    await state.aprs.start()
    asyncio.create_task(midnight_reset_task())
    asyncio.create_task(user_db_refresh_task())
    asyncio.get_running_loop().call_later(15, lambda: asyncio.ensure_future(refresh_talkgroups("startup")))
    logger.info("🚀 HBlink4 Dashboard started!")
    logger.info(f"📡 Event transport: {receiver_config.get('transport', 'unix').upper()}")
    # Report the port actually configured, not the default -- an operator who
    # changed it should not be sent to the wrong URL.
    _web_cfg = dashboard_config.get('web', {}) or {}
    logger.info(f"📊 Access dashboard at http://localhost:{_web_cfg.get('port', 8080)}")

    # Warn operator if they left the placeholder contact in the User-Agent.
    udb_cfg = dashboard_config.get("user_database", {}) or {}
    ua = udb_cfg.get("user_agent", "")
    if "operator@example.org" in ua:
        logger.warning(
            "⚠️ user_database.user_agent still contains the placeholder contact "
            "'operator@example.org' — update it in config.json so radioid.net can "
            "reach you if there's an issue with your traffic."
        )


@app.on_event("shutdown")
async def shutdown_event():
    """Clean shutdown - save data"""
    logger.info("💾 Dashboard shutting down, saving data...")
    if _auto_loop_task:
        _auto_loop_task.cancel()
    if _auto_cache and _auto_cache[1].task and not _auto_cache[1].task.done():
        _auto_cache[1].task.cancel()
    save_persistent_data()
    try:
        await asyncio.wait_for(state.aprs.stop(), 3)
    except Exception:
        pass
    logger.info("✅ Dashboard shutdown complete")


def _purge_tg_stats():
    try:
        n = state.tgstats.purge(int(_tg_cfg().get("retention_days", 30) or 30))
        n += state.obpstats.purge(int(_tg_cfg().get("retention_days", 30) or 30))
        if n:
            logger.info(f"📈 {n} old talkgroup calls removed from the statistics")
    except Exception as e:
        logger.warning(f"📈 Could not clean up talkgroup statistics: {e}")


async def midnight_reset_task():
    """Background task to reset daily stats at midnight"""
    _purge_tg_stats()
    while True:
        # Check if date has changed
        current_date = date.today().isoformat()
        if current_date != state.stats.get('last_reset_date'):
            state.reset_daily_stats()
            _purge_tg_stats()
            # Send stats update to all WebSocket clients
            await send_stats_update()
            await _refresh_link_icons(force=True)

        tomorrow = date.today() + timedelta(days=1)
        midnight = time.mktime((tomorrow.year, tomorrow.month, tomorrow.day, 0, 0, 0, -1, -1, -1))
        await asyncio.sleep(max(1, midnight - time.time()))


async def user_db_refresh_task():
    """
    Background task that refreshes the user database from radioid.net.

    - On startup: if the on-disk snapshot is missing or older than
      `on_startup_if_older_than_hours`, run one catch-up refresh immediately.
    - Then loop: sleep until the next scheduled time_of_day + jitter, refresh,
      repeat.
    - Respects `user_database.enabled=false` as a hard disable.
    - Broadcasts a user_db_status event after each refresh attempt so the UI
      can show "DB updated Nh ago" without a full page reload.
    """
    # Wait a moment for the startup log to settle, then evaluate state.
    await asyncio.sleep(2)

    udb_cfg = dashboard_config.get("user_database", {}) or {}
    if not udb_cfg.get("enabled", True):
        logger.info("📘 user_database.enabled=false — background refresh disabled")
        return

    refresh_cfg = udb_cfg.get("refresh", {}) or {}
    startup_threshold_h = float(refresh_cfg.get("on_startup_if_older_than_hours", 36))

    # Startup catch-up: run now if the snapshot is missing or stale.
    age_h = state.user_db.snapshot_age_hours()
    if age_h is None or age_h >= startup_threshold_h:
        logger.info(
            f"📘 user_db snapshot age={age_h}h >= threshold {startup_threshold_h}h — "
            "running catch-up refresh"
        )
        status = await state.user_db.refresh_from_upstream(udb_cfg)
        await broadcast_user_db_status(trigger="startup", status=status)
        asyncio.create_task(sync_avatars("startup"))
    else:
        frid_age = state.user_db.frid_age_hours()
        if frid_age is None or frid_age >= startup_threshold_h:
            status = await state.user_db.refresh_freeradioid(udb_cfg)
            await broadcast_user_db_status(trigger="startup", status=status)
        asyncio.create_task(sync_avatars("startup"))

    while True:
        # Compute next scheduled refresh.
        delay = compute_next_refresh_seconds(
            schedule=refresh_cfg.get("schedule", "daily"),
            time_of_day=refresh_cfg.get("time_of_day", "03:17"),
            jitter_minutes=int(refresh_cfg.get("jitter_minutes", 15)),
        )
        logger.info(
            f"📘 Next user_db refresh in {delay / 3600:.1f}h "
            f"(schedule={refresh_cfg.get('schedule', 'daily')}, "
            f"time_of_day={refresh_cfg.get('time_of_day', '03:17')})"
        )
        try:
            await asyncio.sleep(delay)
        except asyncio.CancelledError:
            logger.debug("user_db_refresh_task cancelled during sleep")
            return

        status = await state.user_db.refresh_from_upstream(udb_cfg)
        await broadcast_user_db_status(trigger="scheduled", status=status)
        asyncio.create_task(sync_avatars("scheduled"))
        asyncio.create_task(refresh_talkgroups("scheduled"))


async def broadcast_user_db_status(trigger: str, status: str):
    """Send a user_db_status event to all connected clients."""
    if not state.websocket_clients:
        return
    payload = state.user_db.status_dict()
    payload["trigger"] = trigger
    payload["status"] = status
    message = json.dumps({
        "type": "user_db_status",
        "timestamp": datetime.now().timestamp(),
        "data": payload,
    })
    disconnected = set()
    for client in state.websocket_clients:
        try:
            await client.send_text(message)
        except Exception:
            disconnected.add(client)
    state.websocket_clients -= disconnected


async def send_stats_update():
    """Send stats update to all WebSocket clients"""
    if not state.websocket_clients:
        return
    
    message = json.dumps({
        'type': 'stats_reset',
        'timestamp': datetime.now().timestamp(),
        'data': state.stats
    })
    
    disconnected = set()
    for client in state.websocket_clients:
        try:
            await client.send_text(message)
        except:
            disconnected.add(client)
    
    # Remove disconnected clients
    state.websocket_clients -= disconnected


# ========== GRACEFUL SHUTDOWN HANDLING ==========

def save_persistent_data():
    """Save all persistent data on shutdown - called by shutdown_event and atexit"""
    try:
        if state._persistence_disabled:
            logger.info("💾 Dashboard shutdown complete (persistence was disabled)")
            return
            
        state.save_all_data()
        logger.info("💾 Dashboard data saved on shutdown")
    except Exception as e:
        logger.error(f"❌ Failed to save data on shutdown: {e}")
        logger.info("💾 Dashboard shutdown complete (with save errors)")

# SIGTERM/SIGINT are left to uvicorn, which shuts the server down gracefully and
# triggers shutdown_event() above -- that is what saves the data. Installing our
# own handlers here would pre-empt that and exit mid-request.
atexit.register(save_persistent_data)  # Fallback for emergency exit


_tls_manager = None   # dashboard.tls.CertManager when HTTPS is enabled


class _Server:
    """uvicorn.Server without its own signal handling: several servers share one process."""

    @staticmethod
    def make(app_, **kwargs):
        import contextlib
        import uvicorn

        class S(uvicorn.Server):
            @contextlib.contextmanager
            def capture_signals(self):
                yield

        kwargs.setdefault("log_level", "info")
        kwargs.setdefault("access_log", False)
        for k, v in _sec.UVICORN_KWARGS.items():
            kwargs.setdefault(k, v)           # no "server: uvicorn" header
        kwargs.setdefault("loop", "asyncio")   # uvloop breaks Unix socket connections
        return S(uvicorn.Config(app_, **kwargs))


_SELF = {"host": "127.0.0.1", "port": 8080}


def _self_url() -> str:
    h = (_SELF["host"] or "").strip("[]")
    h = "127.0.0.1" if h in ("", "0.0.0.0", "::", "*") else h
    return f"http://{'[' + h + ']' if ':' in h else h}:{int(_SELF['port'])}"


async def _serve(host: str, port: int):
    """
    Start the dashboard over HTTP, or over HTTPS with Let's Encrypt.

    The dashboard itself comes up first (HTTPS if a certificate exists, plain
    HTTP otherwise), so it is reachable while certbot works in the background.
    A stop signal ends everything at once, in any phase.
    """
    _SELF.update(host=host, port=port)
    import signal
    global _tls_manager
    https_cfg = dashboard_config.get("https") or {}
    servers = []
    tasks = []        # server tasks: the process ends when one of them ends
    helpers = []      # background jobs (certbot, renewal): never end the process
    loop = asyncio.get_running_loop()
    stopping = asyncio.Event()

    def stop_all():
        if not stopping.is_set():
            logger.info("🛑 Stop signal received, shutting down …")
            # Watchdog: whatever happens, the process is gone after 8 s, and if it
            # gets that far the journal shows where it was stuck.
            import faulthandler
            try:
                faulthandler.dump_traceback_later(8, exit=True)
            except Exception:
                pass
        stopping.set()
        for srv in servers:
            srv.should_exit = True

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_all)
        except (NotImplementedError, RuntimeError):
            pass

    async def serve_contained(srv):
        # uvicorn calls sys.exit() when it cannot bind; inside a task that
        # SystemExit would tear down the whole event loop (all servers).
        try:
            await srv.serve()
        except SystemExit:
            pass

    async def start(srv, optional: bool = False):
        servers.append(srv)
        task = asyncio.create_task(serve_contained(srv))
        while not srv.started and not task.done() and not stopping.is_set():
            await asyncio.sleep(0.05)
        if not srv.started and not stopping.is_set():
            port_ = srv.config.port
            if optional:
                raise SystemExit(1)
            logger.error(f"❌ Cannot listen on port {port_}: it is in use or not permitted. Is the dashboard "
                         f"already running (systemctl status hblink4-dash, or run_all.sh)? "
                         f"Check: sudo ss -tlpn 'sport = :{port_}'")
            raise SystemExit(1)
        return task

    async def start_optional(srv, what: str):
        try:
            tasks.append(await start(srv, optional=True))
            return True
        except (Exception, SystemExit):
            servers.remove(srv)
            logger.error(f"🔒 {what}: port {srv.config.port} unavailable (in use, or CAP_NET_BIND_SERVICE missing)")
            return False

    if https_cfg.get("enabled"):
        from .tls import CertManager, build_http_app
        _tls_manager = cm = CertManager(https_cfg, state._data_dir, extra_domains=_aprs_domains(https_only=True))
        http_port = int(https_cfg.get("http_port", 80))
        http_app = build_http_app(cm, redirect=True)
        await start_optional(_Server.make(http_app, host=host, port=http_port, lifespan="off"),
                             "Let's Encrypt challenge / redirect")

        def tls_server(lifespan: str):
            return _Server.make(app, host=host, port=cm.https_port, lifespan=lifespan,
                                ssl_certfile=cm.cert_file, ssl_keyfile=cm.key_file)

        async def renew_loop(main):
            while True:
                await asyncio.sleep(12 * 3600)
                if await cm.renew() and main.config.ssl is not None:
                    main.config.ssl.load_cert_chain(cm.cert_file, cm.key_file)
                    logger.info("🔒 Renewed certificate loaded")

        if cm.have_cert():
            main = tls_server("on")
            tasks.append(await start(main))
            print(f"Dashboard on {cm.https_url()}")
            if port not in (http_port, cm.https_port):
                await start_optional(_Server.make(http_app, host=host, port=port, lifespan="off"),
                                     "redirect to HTTPS")
            helpers.append(asyncio.create_task(renew_loop(main)))

            async def expand_cert(main):
                # new APRS domain(s): get them into the certificate and load it without a restart
                missing = cm.missing_names()
                if not missing:
                    return
                ok = [d for d in await cm.resolvable_extra() if d in missing]
                if not ok:
                    return
                logger.info(f"🔒 Adding {', '.join(ok)} to the certificate")
                if await cm.obtain() and main.config.ssl is not None:
                    main.config.ssl.load_cert_chain(cm.cert_file, cm.key_file)
                    logger.info("🔒 Certificate with the new names loaded")
            helpers.append(asyncio.create_task(expand_cert(main)))
        else:
            # Serve over HTTP right away; get the certificate in the background
            tasks.append(await start(_Server.make(app, host=host, port=port)))
            print(f"Dashboard on http://{host}:{port} (requesting a certificate in the background)")

            async def obtain_then_serve():
                if await cm.obtain() and not stopping.is_set():
                    main = tls_server("off")       # app already started by the HTTP server
                    if await start_optional(main, "HTTPS"):
                        print(f"Dashboard on {cm.https_url()}")
                        logger.info("🔒 HTTPS is up. Restart the dashboard once to make "
                                    f"port {port} redirect to HTTPS.")
                        await renew_loop(main)
                elif not stopping.is_set():
                    logger.error("🔒 No certificate: the dashboard stays on plain HTTP. Fix the problem above "
                                 "and restart the dashboard.")
            helpers.append(asyncio.create_task(obtain_then_serve()))
    else:
        tasks.append(await start(_Server.make(app, host=host, port=port)))
        print(f"Dashboard on http://{host}:{port}")
    print("Press CTRL+C to stop\n")

    # Wait for a stop signal or a server ending, then stop the rest
    stop_wait = asyncio.create_task(stopping.wait())
    await asyncio.wait([*tasks, stop_wait], return_when=asyncio.FIRST_COMPLETED)
    stop_all()
    for h in helpers:
        h.cancel()
    # Servers shut down gracefully (lifespan shutdown saves the data)
    pending = [t for t in tasks if not t.done()]
    if pending:
        done, still = await asyncio.wait(pending, timeout=5)
        if still:
            logger.warning(f"🛑 {len(still)} server(s) did not stop within 5 s - exiting anyway")
    logger.info("🛑 Servers stopped, exiting")
    # asyncio.run() would now wait for worker threads that are still
    # downloading (callsign list, avatars) -- minutes on a slow line, which made
    # "systemctl stop/restart" hang. Everything is saved; leave right here.
    _hard_exit(0)


def _hard_exit(code: int):
    try:
        save_persistent_data()
    except Exception as e:
        logger.error(f"Saving data on exit failed: {e}")
    try:
        state.auth._db.close()
    except Exception:
        pass
    logging.shutdown()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)


def run():
    """Console-script entry point (hblink4-dashboard).

    Bind address and port come from the 'web' section of config.json; optional
    CLI arguments override them for one-off/development runs. With https.enabled
    the dashboard is served over HTTPS (see dashboard/tls.py).

    The app object is passed to uvicorn rather than the "dashboard.server:app"
    import string so this module is not executed a second time under a different
    name -- two copies would mean two DashboardState objects and two atexit
    saves, the later one clobbering the real data.
    """
    web_config = dashboard_config.get('web', {})
    host = sys.argv[1] if len(sys.argv) > 1 else web_config.get('bind', '0.0.0.0')
    port = int(sys.argv[2]) if len(sys.argv) > 2 else int(web_config.get('port', 8080))
    code = 0
    try:
        asyncio.run(_serve(host, port))
    except SystemExit as e:
        code = e.code if isinstance(e.code, int) else 1
    except KeyboardInterrupt:
        pass
    _hard_exit(code)


if __name__ == "__main__":
    run()
