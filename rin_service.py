#!/usr/bin/env python3
"""
Rin Service — Always-on lightweight gateway.

Runs on port 8000 and is always reachable by the mobile app.
When the Start button is pressed it spawns the full agent (main.py)
on port 8001 and proxies all traffic to it.

Resource usage when agent is stopped: ~10 MB RAM, 0% CPU.

Can run as:
  1. Windows Service (via NSSM or sc.exe)
  2. Startup task (Task Scheduler)
  3. Manual daemon (python rin_service.py)
"""

import asyncio
import json
import logging
import os
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

# Add project root to path
PROJECT_ROOT = str(Path(__file__).parent.absolute())
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import requests as http_requests  # rename to avoid clash
import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
import socketio

from src.security import setup_security, get_allowed_origins, ensure_api_key, regenerate_api_key, validate_api_key, LOCAL_IPS

# ─── Logging ───
LOG_DIR = os.path.join(PROJECT_ROOT, "logs")
os.makedirs(LOG_DIR, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(os.path.join(LOG_DIR, "rin_service.log"), encoding="utf-8"),
    ]
)
logger = logging.getLogger("rin.service")

# ─── Constants ───
SERVICE_PORT = 8000
AGENT_PORT = 8001
AGENT_BASE = f"http://127.0.0.1:{AGENT_PORT}"
SERVICE_LOCK_FILE = os.path.join(LOG_DIR, "rin_service.lock")

# ─── Mobile APK Update ───
MOBILE_APK_DIR = os.path.join(PROJECT_ROOT, "mobile")
MOBILE_VERSION_FILE = os.path.join(MOBILE_APK_DIR, "version.json")

def get_mobile_version() -> dict:
    """Read version info from version.json next to the APK."""
    try:
        with open(MOBILE_VERSION_FILE, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"version": "0.0.0", "versionCode": 0, "buildDate": None}


# ─── Singleton ───
def _is_pid_alive(pid: int) -> bool:
    try:
        import ctypes
        SYNCHRONIZE = 0x00100000
        h = ctypes.windll.kernel32.OpenProcess(SYNCHRONIZE, False, pid)
        if h:
            ctypes.windll.kernel32.CloseHandle(h)
            return True
        return False
    except Exception:
        return False


def acquire_service_lock() -> bool:
    if os.path.exists(SERVICE_LOCK_FILE):
        try:
            with open(SERVICE_LOCK_FILE, "r") as f:
                old_pid = int(f.read().strip())
            if _is_pid_alive(old_pid):
                logger.error(f"Rin Service already running (PID {old_pid})")
                return False
            else:
                logger.info(f"Stale lock (PID {old_pid} dead), taking over")
        except (ValueError, FileNotFoundError):
            pass

    with open(SERVICE_LOCK_FILE, "w") as f:
        f.write(str(os.getpid()))
    return True


def release_service_lock():
    try:
        os.remove(SERVICE_LOCK_FILE)
    except Exception:
        pass


# ─── Agent Process Manager ───
class AgentProcessManager:
    """Manages the lifecycle of the full Rin agent (main.py) as a subprocess."""

    def __init__(self):
        self.process: subprocess.Popen = None
        self.log_file = None
        self._lock = threading.Lock()

    @property
    def running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    @property
    def pid(self) -> int:
        return self.process.pid if self.running else None

    def start(self) -> dict:
        with self._lock:
            if self.running:
                return {"status": "already_running", "pid": self.process.pid}

            try:
                python_exe = sys.executable
                main_py = os.path.join(PROJECT_ROOT, "main.py")

                self.log_file = open(os.path.join(LOG_DIR, "agent_stdout.log"), "a", encoding="utf-8")
                self.log_file.write(f"\n--- Agent started by service at {time.ctime()} ---\n")
                self.log_file.flush()

                self.process = subprocess.Popen(
                    [python_exe, main_py, "--service-managed"],
                    stdout=self.log_file,
                    stderr=self.log_file,
                    cwd=PROJECT_ROOT,
                    creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
                )
                logger.info(f"Agent started (PID {self.process.pid})")
                return {"status": "started", "pid": self.process.pid}

            except Exception as e:
                logger.error(f"Failed to start agent: {e}")
                return {"status": "error", "message": str(e)}

    def stop(self) -> dict:
        with self._lock:
            if not self.running:
                return {"status": "not_running"}

            pid = self.process.pid
            try:
                if sys.platform == "win32":
                    # Kill the entire process tree
                    subprocess.run(
                        f"taskkill /F /PID {pid} /T",
                        shell=True, capture_output=True, timeout=10
                    )
                    # Wait for process to actually exit
                    try:
                        self.process.wait(timeout=5)
                    except Exception:
                        pass
                    # Sweep any orphan python processes running main.py
                    self._sweep_orphans()
                else:
                    self.process.terminate()
                    self.process.wait(timeout=10)
            except Exception as e:
                logger.error(f"Error stopping agent: {e}")
                try:
                    self.process.kill()
                except Exception:
                    pass

            self.process = None
            if self.log_file:
                try:
                    self.log_file.close()
                except Exception:
                    pass
                self.log_file = None

            logger.info(f"Agent stopped (was PID {pid})")
            return {"status": "stopped", "pid": pid}

    def _sweep_orphans(self):
        """Kill any lingering main.py processes that survived taskkill."""
        try:
            result = subprocess.run(
                'wmic process where "CommandLine like \'%main.py%--service-managed%\'" get ProcessId /format:list',
                shell=True, capture_output=True, text=True, timeout=5
            )
            for line in result.stdout.strip().split('\n'):
                line = line.strip()
                if line.startswith('ProcessId='):
                    orphan_pid = line.split('=')[1].strip()
                    if orphan_pid and orphan_pid != str(os.getpid()):
                        subprocess.run(f"taskkill /F /PID {orphan_pid}", shell=True, capture_output=True)
                        logger.info(f"Swept orphan process PID {orphan_pid}")
        except Exception as e:
            logger.debug(f"Orphan sweep: {e}")

    def restart(self) -> dict:
        self.stop()
        time.sleep(2)
        return self.start()

    def get_status(self) -> dict:
        if self.running:
            return {"running": True, "pid": self.process.pid, "managed": True}
        return {"running": False, "pid": None, "managed": False}


# ─── Socket.IO Relay ───
class SocketRelay:
    """
    Connects as a Socket.IO client to main.py (port 8001) and rebroadcasts
    all events to the mobile clients connected to rin_service.py (port 8000).
    """
    RELAY_EVENTS = [
        "status", "thought", "action", "frame",
        "chat_message", "voice_state", "voice_partial", "voice_level",
    ]

    def __init__(self, server_sio: socketio.AsyncServer, loop: asyncio.AbstractEventLoop):
        self.server_sio = server_sio  # The server-side Socket.IO instance
        self.loop = loop
        self.client = None
        self._connected = False
        self._stop_event = threading.Event()
        self._thread = None

    def start(self):
        """Start the relay in a background thread."""
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        """Stop the relay."""
        self._stop_event.set()
        if self.client:
            try:
                self.client.disconnect()
            except Exception:
                pass
        self._connected = False
        self.client = None

    def _run(self):
        """Background thread: connect to agent and relay events."""
        import socketio as sio_client_lib

        # Wait for agent's server to be ready (up to 30s)
        for _ in range(60):
            if self._stop_event.is_set():
                return
            try:
                r = http_requests.get(f"{AGENT_BASE}/health", timeout=2)
                if r.status_code == 200:
                    break
            except Exception:
                pass
            time.sleep(0.5)
        else:
            logger.warning("Agent server didn't become ready in 30s, relay not started")
            return

        # Create a sync Socket.IO client
        client = sio_client_lib.Client(reconnection=True, reconnection_delay=1)

        # Register relay handlers for each event
        for event_name in self.RELAY_EVENTS:
            self._register_handler(client, event_name)

        @client.event
        def connect():
            logger.info("Relay connected to agent")
            self._connected = True

        @client.event
        def disconnect():
            logger.info("Relay disconnected from agent")
            self._connected = False

        # Retry connection up to 10 times (agent Socket.IO may lag behind HTTP)
        max_retries = 10
        for attempt in range(1, max_retries + 1):
            if self._stop_event.is_set():
                return
            try:
                client.connect(AGENT_BASE, transports=["websocket"], wait_timeout=10)
                self.client = client
                logger.info(f"Relay connected to agent (attempt {attempt})")
                # Block until stop is requested
                while not self._stop_event.is_set():
                    time.sleep(0.5)
                    if not client.connected:
                        break
                break  # Clean exit from retry loop
            except Exception as e:
                logger.warning(f"Relay connection attempt {attempt}/{max_retries} failed: {e}")
                if attempt < max_retries:
                    time.sleep(3)
                else:
                    logger.error("Relay gave up after all retries")

        # Cleanup
        try:
            if client.connected:
                client.disconnect()
        except Exception:
            pass
        self._connected = False
        self.client = None

    def _register_handler(self, client, event_name: str):
        """Register a handler that rebroadcasts an event from agent → mobile clients."""
        @client.on(event_name)
        def handler(data):
            # Log first few events for debugging
            if event_name != 'frame':
                logger.debug(f"Relay received '{event_name}' from agent")
            # Rebroadcast to all mobile clients via the server
            try:
                asyncio.run_coroutine_threadsafe(
                    self.server_sio.emit(event_name, data),
                    self.loop
                )
            except Exception as e:
                logger.error(f"Relay emit failed for '{event_name}': {e}")


# ─── Gateway Server ───
class RinServiceServer:
    """
    Always-on gateway server. Serves on port 8000.
    When agent is running, proxies REST calls to port 8001 and relays Socket.IO events.
    When agent is stopped, returns sensible offline responses.
    """

    # Endpoints served directly by the service (never proxied)
    OWN_ENDPOINTS = {"/health", "/agent/status", "/agent/start", "/agent/stop", "/agent/restart",
                     "/mobile/version", "/mobile/apk", "/mobile/token"}

    # Endpoints that should be proxied to the agent
    PROXY_GET = ["/state", "/config", "/models", "/model/active", "/chat/history",
                 "/frame/latest", "/wake-word/status"]
    PROXY_POST = ["/task", "/steer", "/stop", "/pause", "/resume",
                  "/chat/send", "/stream/start", "/stream/stop",
                  "/model/switch", "/wake-word/enable", "/wake-word/disable",
                  "/restart"]

    def __init__(self, host="0.0.0.0", port=SERVICE_PORT):
        self.host = host
        self.port = port
        self.agent = AgentProcessManager()
        self.relay: SocketRelay = None
        self._loop: asyncio.AbstractEventLoop = None

        # Chat history cache (persists across agent restarts)
        self._chat_history = []

        self.app = FastAPI(title="Rin Service")
        
        # CORS: permissive origins — API key auth middleware is the real security layer.
        # Restrictive CORS blocks legitimate phone/LAN connections without adding security
        # (native apps bypass CORS, and auth is what actually protects endpoints).
        self.sio = socketio.AsyncServer(async_mode="asgi", cors_allowed_origins='*')
        self.socket_app = socketio.ASGIApp(self.sio, self.app)

        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=get_allowed_origins(),
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

        # Security middleware (API key auth, rate limiting, body size)
        self._api_key = setup_security(self.app)

        self._setup_routes()

    # ═══════════════════════════════════════════════════
    # Routes
    # ═══════════════════════════════════════════════════

    def _setup_routes(self):

        # ── Health (always available) ──
        @self.app.get("/health")
        async def health():
            agent_st = self.agent.get_status()
            result = {
                "service": "running",
                "status": "ok",
                "agent_running": agent_st["running"],
            }
            # If agent is running, try to include its health info
            if agent_st["running"]:
                try:
                    r = http_requests.get(f"{AGENT_BASE}/health", timeout=2)
                    if r.status_code == 200:
                        data = r.json()
                        result["vlm_status"] = data.get("vlm_status", "OFFLINE")
                        result["agent_status"] = data.get("agent_status", "idle")
                except Exception:
                    result["vlm_status"] = "OFFLINE"
                    result["agent_status"] = "unknown"
            else:
                result["vlm_status"] = "OFFLINE"
                result["agent_status"] = "idle"

            # Include crash history and circuit breaker state
            result["recent_crashes"] = RinServiceServer._read_crash_log(5)
            if hasattr(self, 'guardian'):
                result["circuit_breaker"] = {
                    "open": self.guardian.circuit_open,
                    "recent_count": len(self.guardian._crash_times),
                }
            return result

        # ── Agent Lifecycle ──
        @self.app.get("/agent/status")
        async def agent_status():
            st = self.agent.get_status()
            # Enrich with agent's own status if running
            if st["running"]:
                try:
                    r = http_requests.get(f"{AGENT_BASE}/state", timeout=2)
                    if r.status_code == 200:
                        data = r.json()
                        st["status"] = data.get("status", "idle")
                        st["vlm_status"] = data.get("vlm_status", "OFFLINE")
                except Exception:
                    st["status"] = "running"
                    st["vlm_status"] = "UNKNOWN"
            else:
                st["status"] = "idle"
                st["vlm_status"] = "OFFLINE"
            return st

        @self.app.post("/agent/start")
        async def agent_start():
            # Circuit breaker: refuse start if too many recent crashes
            if hasattr(self, 'guardian') and self.guardian.circuit_open:
                return JSONResponse(
                    {"status": "blocked", "reason": "Too many crashes — wait 5 min or restart the service"},
                    status_code=503,
                )

            # Memory check: refuse start if system is critically low
            mem = self.SystemGuardian.check_memory()
            if not mem["ok"]:
                return JSONResponse(
                    {"status": "blocked", "reason": f"Low memory ({mem['available_mb']}MB free, need {self.SystemGuardian.MIN_FREE_MB}MB)"},
                    status_code=503,
                )

            result = self.agent.start()
            if result.get("status") in ("started", "already_running"):
                # Start the Socket.IO relay to forward events
                self._start_relay()
                # Track start time for uptime in crash logs
                if hasattr(self, 'guardian'):
                    self.guardian._agent_start_time = time.time()
            return result

        @self.app.post("/agent/stop")
        async def agent_stop():
            self._stop_relay()
            result = self.agent.stop()
            # Kill any orphaned VLM processes left behind
            self.SystemGuardian._kill_by_cmdline("llama-server")
            # Broadcast idle status to all mobile clients so UI updates immediately
            await self.sio.emit("status", {
                "state": "idle",
                "details": None,
                "vlm_status": "OFFLINE",
            })
            return result

        @self.app.post("/agent/restart")
        async def agent_restart():
            self._stop_relay()
            # User-initiated restart resets the circuit breaker
            if hasattr(self, 'guardian'):
                self.guardian.reset_circuit()
            # Kill orphaned VLM before restart
            self.SystemGuardian._kill_by_cmdline("llama-server")
            # Broadcast idle status during restart
            await self.sio.emit("status", {
                "state": "idle",
                "details": "Restarting...",
                "vlm_status": "OFFLINE",
            })
            result = self.agent.restart()
            if result.get("status") in ("started", "already_running"):
                self._start_relay()
            return result

        # ── Mobile App Update ──
        @self.app.get("/mobile/version")
        async def mobile_version():
            info = get_mobile_version()
            apk_path = os.path.join(MOBILE_APK_DIR, "Rin.apk")
            info["apk_available"] = os.path.isfile(apk_path)
            if info["apk_available"]:
                info["apk_size"] = os.path.getsize(apk_path)
            return info

        @self.app.get("/mobile/apk")
        async def mobile_apk():
            apk_path = os.path.join(MOBILE_APK_DIR, "Rin.apk")
            if not os.path.isfile(apk_path):
                return JSONResponse({"error": "APK not found"}, status_code=404)
            return FileResponse(
                apk_path,
                media_type="application/vnd.android.package-archive",
                filename="Rin.apk",
            )

        # ── Mobile Token Management (localhost-only) ──
        @self.app.get("/mobile/token")
        async def mobile_token_get(request: Request):
            """Return the current API key. Localhost-only for security."""
            client_ip = request.client.host if request.client else "unknown"
            if client_ip not in LOCAL_IPS:
                return JSONResponse(
                    {"status": "error", "message": "Token endpoint is localhost-only"},
                    status_code=403,
                )
            return {
                "token": self._api_key,
                "token_preview": self._api_key[:8] + "..." if self._api_key else "",
                "length": len(self._api_key) if self._api_key else 0,
                "valid": validate_api_key(self._api_key) if self._api_key else False,
            }

        @self.app.post("/mobile/token")
        async def mobile_token_post(request: Request):
            """Regenerate the API key. Localhost-only.
            Body: {"regenerate": true}
            """
            client_ip = request.client.host if request.client else "unknown"
            if client_ip not in LOCAL_IPS:
                return JSONResponse(
                    {"status": "error", "message": "Token endpoint is localhost-only"},
                    status_code=403,
                )
            try:
                body = await request.json()
            except Exception:
                body = {}

            if not body.get("regenerate"):
                return JSONResponse(
                    {"status": "error", "message": "Send {\"regenerate\": true} to create a new token"},
                    status_code=400,
                )

            new_key = regenerate_api_key()
            self._api_key = new_key

            # Update the middleware's in-memory key reference
            for middleware in self.app.user_middleware:
                if hasattr(middleware, 'kwargs') and 'api_key' in middleware.kwargs:
                    middleware.kwargs['api_key'] = new_key

            logger.info(f"API key regenerated via /mobile/token from {client_ip}")
            return {
                "status": "ok",
                "token": new_key,
                "token_preview": new_key[:8] + "...",
                "message": "API key regenerated. Update your mobile app settings.",
            }

        # ── Proxy GET endpoints ──
        for path in self.PROXY_GET:
            self._add_proxy_get(path)

        # ── Proxy POST endpoints ──
        for path in self.PROXY_POST:
            self._add_proxy_post(path)

    def _add_proxy_get(self, path: str):
        """Register a GET endpoint that proxies to the agent."""
        @self.app.get(path, name=f"proxy_get_{path.replace('/', '_')}")
        async def proxy_get(request: Request, _path=path):
            if not self.agent.running:
                return self._offline_response(_path)
            try:
                r = http_requests.get(f"{AGENT_BASE}{_path}", timeout=10)
                return JSONResponse(content=r.json(), status_code=r.status_code)
            except Exception as e:
                logger.error(f"Proxy GET {_path} failed: {e}")
                return JSONResponse(
                    content={"status": "error", "message": "Agent unreachable"},
                    status_code=502
                )

    def _add_proxy_post(self, path: str):
        """Register a POST endpoint that proxies to the agent."""
        @self.app.post(path, name=f"proxy_post_{path.replace('/', '_')}")
        async def proxy_post(request: Request, _path=path):
            if not self.agent.running:
                return self._offline_response(_path)
            try:
                body = await request.body()
                headers = {"Content-Type": "application/json"}
                r = http_requests.post(
                    f"{AGENT_BASE}{_path}",
                    data=body, headers=headers, timeout=10
                )
                result = r.json()

                # Safety net: on task-stop commands, also broadcast idle from service
                # so mobile clients get the update even if relay is slow
                if _path in ("/stop", "/restart") and result.get("status") == "stopped":
                    await self.sio.emit("status", {
                        "state": "idle",
                        "details": "Task stopped",
                        "vlm_status": "STANDBY",
                    })

                return JSONResponse(content=result, status_code=r.status_code)
            except Exception as e:
                logger.error(f"Proxy POST {_path} failed: {e}")
                return JSONResponse(
                    content={"status": "error", "message": "Agent unreachable"},
                    status_code=502
                )

    def _offline_response(self, path: str) -> JSONResponse:
        """Return a sensible response when the agent is not running."""
        fallbacks = {
            "/state": {"status": "idle", "details": None, "vlm_status": "OFFLINE",
                       "last_thought": "Agent not running.", "current_action": None},
            "/config": {"error": "Agent not running"},
            "/models": {"models": []},
            "/model/active": {"error": "Agent not running"},
            "/chat/history": {"messages": self._chat_history},
            "/frame/latest": {"frame": None, "timestamp": time.time()},
            "/wake-word/status": {"wake_word_enabled": False},
        }
        if path in fallbacks:
            return JSONResponse(content=fallbacks[path])

        return JSONResponse(
            content={"status": "error", "message": "Agent not running. Start it from Dashboard."},
            status_code=503
        )

    # ═══════════════════════════════════════════════════
    # Relay Management
    # ═══════════════════════════════════════════════════

    def _start_relay(self):
        """Start the Socket.IO relay to forward events from agent to mobile clients."""
        if self.relay:
            self.relay.stop()

        if self._loop:
            self.relay = SocketRelay(self.sio, self._loop)
            self.relay.start()
            logger.info("Socket.IO relay started")

    def _stop_relay(self):
        """Stop the Socket.IO relay."""
        if self.relay:
            self.relay.stop()
            self.relay = None
            logger.info("Socket.IO relay stopped")

    # ═══════════════════════════════════════════════════
    # Socket.IO Server Events
    # ═══════════════════════════════════════════════════

    def _setup_socket_handlers(self):
        @self.sio.event
        async def connect(sid, environ, auth=None):
            # Verify Socket.IO auth token for non-local connections
            client_ip = environ.get("REMOTE_ADDR", "")
            if client_ip not in LOCAL_IPS:
                import hmac
                token = None
                if auth and isinstance(auth, dict):
                    token = auth.get("token", "")
                if not token or not hmac.compare_digest(token, self._api_key):
                    logger.warning(f"Socket.IO auth rejected from {client_ip}")
                    raise ConnectionRefusedError("Authentication required")

            logger.info(f"Mobile client connected: {sid} ({client_ip})")
            # Send initial state push
            agent_st = self.agent.get_status()
            status = "idle"
            vlm = "OFFLINE"
            if agent_st["running"]:
                try:
                    r = http_requests.get(f"{AGENT_BASE}/state", timeout=2)
                    if r.status_code == 200:
                        data = r.json()
                        status = data.get("status", "idle")
                        vlm = data.get("vlm_status", "OFFLINE")
                except Exception:
                    pass

            await self.sio.emit("status", {
                "state": status,
                "details": None,
                "vlm_status": vlm,
            }, to=sid)

        @self.sio.event
        async def disconnect(sid):
            logger.info(f"Mobile client disconnected: {sid}")

    # ═══════════════════════════════════════════════════
    # Persistent Crash Log
    # ═══════════════════════════════════════════════════

    CRASH_LOG_FILE = os.path.join(LOG_DIR, "crashes.jsonl")
    CRASH_LOG_MAX_ENTRIES = 100

    @classmethod
    def _log_crash(cls, exit_code: int, uptime_secs: float = 0, cleanup: dict = None):
        """Append a crash record to the persistent crash log."""
        record = {
            "timestamp": datetime.now().isoformat(),
            "exit_code": exit_code,
            "uptime_secs": round(uptime_secs, 1),
            "cleanup": cleanup or {},
        }
        try:
            with open(cls.CRASH_LOG_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(record) + "\n")
            # Rotate if too large
            cls._rotate_crash_log()
        except Exception as e:
            logger.error(f"Failed to write crash log: {e}")

    @classmethod
    def _rotate_crash_log(cls):
        """Keep only the last N crash entries."""
        try:
            with open(cls.CRASH_LOG_FILE, "r", encoding="utf-8") as f:
                lines = f.readlines()
            if len(lines) > cls.CRASH_LOG_MAX_ENTRIES:
                with open(cls.CRASH_LOG_FILE, "w", encoding="utf-8") as f:
                    f.writelines(lines[-cls.CRASH_LOG_MAX_ENTRIES:])
        except (FileNotFoundError, PermissionError):
            pass

    @classmethod
    def _read_crash_log(cls, count: int = 10) -> list:
        """Read the last N crash records."""
        try:
            with open(cls.CRASH_LOG_FILE, "r", encoding="utf-8") as f:
                lines = f.readlines()
            records = []
            for line in lines[-count:]:
                try:
                    records.append(json.loads(line.strip()))
                except json.JSONDecodeError:
                    pass
            return records
        except FileNotFoundError:
            return []

    @classmethod
    def _load_recent_crash_times(cls, window_secs: int = 300) -> list:
        """Load crash timestamps from log that are within the circuit breaker window.
        This restores circuit breaker state after a service restart."""
        cutoff = datetime.now().timestamp() - window_secs
        times = []
        try:
            with open(cls.CRASH_LOG_FILE, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        record = json.loads(line.strip())
                        ts = datetime.fromisoformat(record["timestamp"]).timestamp()
                        if ts > cutoff:
                            times.append(ts)
                    except (json.JSONDecodeError, KeyError, ValueError):
                        pass
        except FileNotFoundError:
            pass
        return times

    # ═══════════════════════════════════════════════════
    # System Guardian — Smart Process Manager
    # ═══════════════════════════════════════════════════

    class SystemGuardian:
        """
        Comprehensive process guardian that runs as a background thread.
        Handles:
          - Startup orphan sweep (stale main.py, llama-server, overlay)
          - Continuous PID monitoring with mobile crash notification
          - Child process cleanup (VLM, overlay) when agent dies
          - Port health checks (reclaim zombie-held ports)
          - Circuit breaker (prevent restart loops)
          - Resource awareness (memory checks)
        """

        # Ports the system uses
        AGENT_PORT = 8001
        VLM_PORT = 8080
        MANAGED_PORTS = [8001, 8080]

        # Process signatures to detect orphans
        ORPHAN_SIGNATURES = {
            "agent":   "main.py --service-managed",
            "vlm":     "llama-server",
        }

        # Circuit breaker settings
        MAX_CRASHES_WINDOW = 3       # crashes
        CRASH_WINDOW_SECS = 300      # seconds (5 min)
        MIN_FREE_MB = 500            # minimum free RAM to allow agent start

        def __init__(self, server: "RinServiceServer"):
            self.server = server
            # Restore crash times from persistent log (circuit breaker survives restarts)
            self._crash_times: list[float] = RinServiceServer._load_recent_crash_times(
                self.CRASH_WINDOW_SECS
            )
            if self._crash_times:
                logger.info(
                    f"SystemGuardian: restored {len(self._crash_times)} recent crash(es) from log"
                )
            self._stop_event = threading.Event()
            self._thread = None
            self._agent_start_time: float = 0  # Track uptime for crash logs

        # ── Lifecycle ──

        def start(self):
            """Start the guardian background thread."""
            self._stop_event.clear()
            self._thread = threading.Thread(target=self._run, daemon=True, name="SystemGuardian")
            self._thread.start()
            logger.info("SystemGuardian started")

        def stop(self):
            self._stop_event.set()

        # ── Startup Sweep ──

        def startup_sweep(self):
            """Kill any orphan processes left from a previous session."""
            logger.info("SystemGuardian: performing startup sweep...")
            orphans_killed = 0

            # 1. Kill orphan main.py --service-managed
            orphans_killed += self._kill_by_cmdline(self.ORPHAN_SIGNATURES["agent"])

            # 2. Kill orphan llama-server
            orphans_killed += self._kill_by_cmdline(self.ORPHAN_SIGNATURES["vlm"])

            # 3. Reclaim any blocked ports
            for port in self.MANAGED_PORTS:
                freed = self._kill_port_holder(port)
                if freed:
                    orphans_killed += 1

            # 4. Clean stale lock files
            for lock_pattern in ["rin_agent_*.lock"]:
                self._clean_stale_locks(lock_pattern)

            if orphans_killed:
                logger.info(f"SystemGuardian: startup sweep killed {orphans_killed} orphan(s)")
            else:
                logger.info("SystemGuardian: startup sweep — system clean")

        # ── Main Loop ──

        def _run(self):
            """Background loop: monitor processes, ports, resources."""
            tick = 0
            while not self._stop_event.is_set():
                time.sleep(5)
                tick += 1

                # ── Every 5s: check if agent process died ──
                self._check_agent_alive()

                # ── Every 30s: port health + orphan VLM check ──
                if tick % 6 == 0:
                    self._check_port_health()
                    self._check_orphan_vlm()

        # ── Agent PID Monitoring ──

        def _check_agent_alive(self):
            """Check if the agent subprocess is still alive. Clean up if dead."""
            proc = self.server.agent.process
            if proc is None:
                return  # Agent not running, nothing to check

            rc = proc.poll()
            if rc is None:
                return  # Still alive

            # Agent died
            exit_code = proc.returncode
            uptime = time.time() - self._agent_start_time if self._agent_start_time else 0
            logger.warning(f"SystemGuardian: agent died (exit code {exit_code}, uptime {uptime:.0f}s)")

            # Record crash time for circuit breaker
            self._crash_times.append(time.time())
            # Keep only recent crashes
            cutoff = time.time() - self.CRASH_WINDOW_SECS
            self._crash_times = [t for t in self._crash_times if t > cutoff]

            # Clean up agent handle + log file
            self.server.agent.process = None
            if self.server.agent.log_file:
                try:
                    self.server.agent.log_file.close()
                except Exception:
                    pass
                self.server.agent.log_file = None

            # Stop the Socket.IO relay
            self.server._stop_relay()

            # Kill orphaned child processes (VLM, etc.)
            cleanup = {}
            vlm_killed = self._kill_by_cmdline(self.ORPHAN_SIGNATURES["vlm"])
            if vlm_killed:
                cleanup["vlm_killed"] = vlm_killed
            port_freed = self._kill_port_holder(self.AGENT_PORT)
            if port_freed:
                cleanup["port_freed"] = self.AGENT_PORT

            # Write persistent crash log
            RinServiceServer._log_crash(exit_code, uptime, cleanup)

            # Notify mobile clients immediately
            self._notify_crash(exit_code)

            if len(self._crash_times) >= self.MAX_CRASHES_WINDOW:
                logger.error(
                    f"SystemGuardian: CIRCUIT BREAKER — {len(self._crash_times)} crashes "
                    f"in {self.CRASH_WINDOW_SECS}s, will not auto-restart"
                )

        def _cleanup_agent_children(self):
            """After agent dies, kill its orphaned children (llama-server, etc.)."""
            killed = self._kill_by_cmdline(self.ORPHAN_SIGNATURES["vlm"])
            if killed:
                logger.info(f"SystemGuardian: killed {killed} orphaned VLM process(es)")

            # Also reclaim agent port
            self._kill_port_holder(self.AGENT_PORT)

        def _notify_crash(self, exit_code: int):
            """Broadcast crash notification to all mobile clients."""
            if not self.server._loop:
                return
            try:
                asyncio.run_coroutine_threadsafe(
                    self.server.sio.emit("status", {
                        "state": "idle",
                        "details": f"Agent crashed (exit {exit_code})",
                        "vlm_status": "OFFLINE",
                    }),
                    self.server._loop,
                )
            except Exception as e:
                logger.error(f"SystemGuardian: failed to notify clients: {e}")

        # ── Port Health ──

        def _check_port_health(self):
            """Verify managed ports aren't held by zombie processes."""
            if self.server.agent.running:
                return  # Agent is alive — ports are legitimately in use

            for port in self.MANAGED_PORTS:
                pid = self._get_port_pid(port)
                if pid and pid != os.getpid():
                    logger.warning(f"SystemGuardian: port {port} held by zombie PID {pid}, reclaiming")
                    self._kill_port_holder(port)

        def _check_orphan_vlm(self):
            """Kill orphaned llama-server if agent is not running."""
            if self.server.agent.running:
                return
            killed = self._kill_by_cmdline(self.ORPHAN_SIGNATURES["vlm"])
            if killed:
                logger.info(f"SystemGuardian: killed {killed} orphaned VLM (agent not running)")

        # ── Circuit Breaker ──

        @property
        def circuit_open(self) -> bool:
            """True if too many recent crashes — don't allow agent start."""
            cutoff = time.time() - self.CRASH_WINDOW_SECS
            recent = [t for t in self._crash_times if t > cutoff]
            return len(recent) >= self.MAX_CRASHES_WINDOW

        def reset_circuit(self):
            """Manually reset the circuit breaker (e.g. after user fixes an issue)."""
            self._crash_times.clear()
            logger.info("SystemGuardian: circuit breaker reset")

        # ── Resource Checks ──

        @staticmethod
        def check_memory() -> dict:
            """Check available system memory. Returns dict with total_mb, available_mb, ok."""
            try:
                import ctypes
                class MEMORYSTATUSEX(ctypes.Structure):
                    _fields_ = [
                        ("dwLength", ctypes.c_ulong),
                        ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong),
                        ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong),
                        ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong),
                        ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                    ]
                stat = MEMORYSTATUSEX()
                stat.dwLength = ctypes.sizeof(stat)
                ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
                total_mb = stat.ullTotalPhys // (1024 * 1024)
                avail_mb = stat.ullAvailPhys // (1024 * 1024)
                return {
                    "total_mb": total_mb,
                    "available_mb": avail_mb,
                    "percent_used": stat.dwMemoryLoad,
                    "ok": avail_mb >= SystemGuardian.MIN_FREE_MB,
                }
            except Exception:
                return {"total_mb": 0, "available_mb": 0, "percent_used": 0, "ok": True}

        # ── Low-Level Helpers ──

        @staticmethod
        def _kill_by_cmdline(signature: str) -> int:
            """Kill all processes whose command line contains the given signature.
            Returns number of processes killed."""
            if sys.platform != "win32":
                return 0
            killed = 0
            try:
                # Use WMIC to find matching processes
                sig_escaped = signature.replace("'", "\\'")
                result = subprocess.run(
                    f'wmic process where "CommandLine like \'%{sig_escaped}%\'" get ProcessId /format:list',
                    shell=True, capture_output=True, text=True, timeout=10,
                )
                my_pid = os.getpid()
                for line in result.stdout.strip().split('\n'):
                    line = line.strip()
                    if line.startswith('ProcessId='):
                        pid_str = line.split('=')[1].strip()
                        if pid_str and int(pid_str) != my_pid:
                            subprocess.run(
                                f"taskkill /F /PID {pid_str} /T",
                                shell=True, capture_output=True, timeout=5,
                            )
                            killed += 1
                            logger.info(f"SystemGuardian: killed PID {pid_str} (matched '{signature}')")
            except Exception as e:
                logger.debug(f"SystemGuardian: kill_by_cmdline('{signature}'): {e}")
            return killed

        @staticmethod
        def _get_port_pid(port: int) -> int | None:
            """Get PID of process listening on a port, or None."""
            if sys.platform != "win32":
                return None
            try:
                result = subprocess.run(
                    f"netstat -ano | findstr :{port} | findstr LISTENING",
                    shell=True, capture_output=True, text=True, timeout=5,
                )
                for line in result.stdout.strip().split('\n'):
                    parts = line.split()
                    if len(parts) > 4:
                        return int(parts[-1])
            except Exception:
                pass
            return None

        @staticmethod
        def _kill_port_holder(port: int) -> bool:
            """Kill whatever is holding a port. Returns True if something was killed."""
            pid = RinServiceServer.SystemGuardian._get_port_pid(port)
            if pid and pid != os.getpid():
                try:
                    subprocess.run(f"taskkill /F /PID {pid}", shell=True, capture_output=True, timeout=5)
                    logger.info(f"SystemGuardian: freed port {port} (killed PID {pid})")
                    return True
                except Exception:
                    pass
            return False

        @staticmethod
        def _clean_stale_locks(pattern: str):
            """Remove stale lock files matching a glob pattern from temp dir."""
            import glob
            import tempfile
            lock_dir = tempfile.gettempdir()
            for lock_path in glob.glob(os.path.join(lock_dir, pattern)):
                try:
                    # Read PID from lock file
                    with open(lock_path, 'r') as f:
                        pid_str = f.read().strip()
                    if pid_str:
                        pid = int(pid_str)
                        if _is_pid_alive(pid):
                            continue  # Process still alive, skip
                    os.remove(lock_path)
                    logger.info(f"SystemGuardian: removed stale lock {lock_path}")
                except (ValueError, FileNotFoundError, PermissionError):
                    pass

    # Alias for the nested class
    SystemGuardian = SystemGuardian

    def _start_health_monitor(self):
        """Start the SystemGuardian (replaces old simple health monitor)."""
        self.guardian = self.SystemGuardian(self)
        self.guardian.startup_sweep()
        self.guardian.start()

    # ═══════════════════════════════════════════════════
    # Run
    # ═══════════════════════════════════════════════════

    def run(self):
        """Run the service server (blocking)."""
        self._setup_socket_handlers()

        # We need the event loop for the Socket.IO relay
        loop = asyncio.new_event_loop()
        self._loop = loop

        # Start health monitor
        self._start_health_monitor()

        logger.info(f"Rin Service starting on {self.host}:{self.port}")
        # Display API key on startup for easy mobile pairing
        logger.info(f"API Key for mobile pairing: {self._api_key}")
        print(f"\n{'='*60}")
        print(f"  Rin Service — Mobile API Key")
        print(f"  {self._api_key}")
        print(f"  Enter this key in the mobile app Settings > Key field")
        print(f"{'='*60}\n")

        config = uvicorn.Config(
            self.socket_app,
            host=self.host,
            port=self.port,
            log_level="warning",
            loop="asyncio",
        )
        server = uvicorn.Server(config)

        # Run on our own loop so we have a reference to it
        loop.run_until_complete(server.serve())


# ─── Entry Point ───
def main():
    if not acquire_service_lock():
        print("ERROR: Rin Service is already running!")
        return 1

    server = RinServiceServer()

    def shutdown_handler(sig, frame):
        logger.info("Shutting down Rin Service...")
        if hasattr(server, 'guardian'):
            server.guardian.stop()
        server._stop_relay()
        server.agent.stop()
        # Kill any orphaned VLM/agent processes
        RinServiceServer.SystemGuardian._kill_by_cmdline("llama-server")
        release_service_lock()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown_handler)
    signal.signal(signal.SIGTERM, shutdown_handler)

    try:
        server.run()
    finally:
        if hasattr(server, 'guardian'):
            server.guardian.stop()
        server._stop_relay()
        server.agent.stop()
        # Final cleanup: kill any orphaned children
        RinServiceServer.SystemGuardian._kill_by_cmdline("llama-server")
        release_service_lock()

    return 0


if __name__ == "__main__":
    sys.exit(main())
