import asyncio
import base64
import hmac
import io
import logging
import threading
import time
from typing import Optional
from datetime import datetime

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import socketio

from src.security import setup_security, get_allowed_origins, load_api_key, ensure_api_key, LOCAL_IPS

# Configure logging
logger = logging.getLogger("qwen3vl.server")

class StatusServer:
    """
    WebSocket server to broadcast agent status to the overlay.
    Uses FastAPI and python-socketio.
    """
    
    def __init__(self, host: str = "0.0.0.0", port: int = 8000):
        self.host = host
        self.port = port
        self.app = FastAPI()
        
        # Security: use hardened CORS origins for REST API
        allowed_origins = get_allowed_origins()
        # Socket.IO allows all origins — server.py is internal (port 8001)
        # behind rin_service gateway. Auth middleware is the real security layer.
        self.sio = socketio.AsyncServer(async_mode='asgi', cors_allowed_origins='*')
        self.socket_app = socketio.ASGIApp(self.sio, self.app)
        
        # Configure CORS with explicit origins
        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=allowed_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
        
        # Security middleware (API key auth, rate limiting, body size)
        self._api_key = setup_security(self.app)
        
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.thread: Optional[threading.Thread] = None
        self.should_exit = False
        self.task_queue = None  # To be set by main.py
        
        # Chat history for mobile app
        self.chat_history = []  # [{role, content, timestamp}]
        self._chat_history_max = 200
        
        # Screen streaming for mobile app
        self._streaming = False
        self._stream_thread: Optional[threading.Thread] = None
        self._latest_frame: Optional[str] = None  # base64 JPEG
        self._stream_fps = 10
        
        # Current state storage
        self.state = {
            "status": "idle",
            "details": None,
            "last_thought": "Waiting for input...",
            "current_action": None,
            "vlm_status": "OFFLINE",
            # Voice state
            "voice_state": "idle",
            "voice_partial": "",
            "voice_level": 0.0,
            "wake_word_enabled": True
        }

        self._setup_routes()
        self._register_handlers()

    def _setup_routes(self):
        # Orchestrator reference for steering (set by main.py)
        self.orchestrator = None
        
        @self.app.post("/task")
        async def submit_task(task_data: dict):
            command = task_data.get("command")
            if not command:
                return {"status": "error", "message": "No command provided"}
            
            # Input validation
            command = str(command).strip()
            if not command:
                return {"status": "error", "message": "Command cannot be empty"}
            if len(command) > 10000:
                return {"status": "error", "message": "Command too long (max 10,000 characters)"}
            
            # Smart routing: steer if busy, queue if idle
            # Check current state - "running", "loading", "THINKING", etc. indicate active task
            current_status = self.state.get("status", "idle")
            is_busy = current_status not in ("idle", "COMPLETE", "ERROR", "ABORTED")
            
            if is_busy and self.orchestrator:
                # Agent is busy - inject as steering context
                self.orchestrator.inject_context(command)
                logger.info(f"Steering active task: {command[:100]}")
                return {"status": "steering", "message": "Injected into active task"}
            
            # No active task - queue normally
            if self.task_queue:
                logger.info(f"Received task via API: {command[:100]}")
                self.task_queue.put(command)
                return {"status": "queued"}
            return {"status": "error", "message": "System not ready"}
        
        @self.app.post("/steer")
        async def steer_task(steer_data: dict):
            """Inject steering context into the currently active task."""
            context = steer_data.get("context") or steer_data.get("command")
            if not context:
                return {"status": "error", "message": "No context provided"}
            
            # Input validation
            context = str(context).strip()
            if not context:
                return {"status": "error", "message": "Context cannot be empty"}
            if len(context) > 5000:
                return {"status": "error", "message": "Context too long (max 5,000 characters)"}
            
            if not self.orchestrator:
                return {"status": "error", "message": "Orchestrator not initialized"}
            
            self.orchestrator.inject_context(context)
            logger.info(f"Steering context injected: {context[:50]}...")
            return {"status": "ok", "message": "Context injected"}

        # Callbacks
        self.on_stop_callback = None

        @self.app.post("/stop")
        async def stop_agent():
            """Stop the current agent task."""
            self.state["status"] = "idle"
            self.state["details"] = "Task cancelled by user"
            self.state["current_action"] = ""
            self.state["last_thought"] = "Task cancelled."
            
            # Trigger callback if registered
            if self.on_stop_callback:
                self.on_stop_callback()

            # Broadcast idle status so mobile clients see the change immediately
            if self.loop:
                try:
                    asyncio.run_coroutine_threadsafe(
                        self.sio.emit('status', {
                            'state': 'idle',
                            'details': 'Task cancelled by user',
                            'vlm_status': self.state.get('vlm_status', 'STANDBY'),
                        }),
                        self.loop
                    )
                except Exception:
                    pass

            return {"status": "stopped"}

        # Pause/resume callbacks for interactive control
        self.on_pause_callback = None
        self.on_resume_callback = None

        @self.app.post("/pause")
        async def pause_agent():
            """Pause the current agent task."""
            self.state["status"] = "paused"
            self.state["details"] = "Task paused by user"
            self.state["last_thought"] = "⏸️ Paused - say 'resume' to continue"
            
            if self.on_pause_callback:
                self.on_pause_callback()
                
            return {"status": "paused"}

        @self.app.post("/resume")
        async def resume_agent():
            """Resume a paused agent task."""
            self.state["status"] = "running"
            self.state["details"] = "Task resumed by user"
            self.state["last_thought"] = "▶️ Resuming..."
            
            if self.on_resume_callback:
                self.on_resume_callback()
                
            return {"status": "resumed"}

        @self.app.get("/state")
        async def get_state():
            """Return the current agent state."""
            return self.state

        @self.app.get("/health")
        async def health_check():
            """Health check endpoint for the frontend."""
            return {
                "status": "ok",
                "vlm_status": self.state.get("vlm_status", "OFFLINE"),
                "agent_status": self.state.get("status", "idle")
            }

        @self.app.post("/restart")
        async def restart_services():
            """Restart VLM services."""
            # This will be handled by the orchestrator's VLM manager
            logger.info("Restart services requested")
            return {"status": "restart_requested"}

        @self.app.get("/config")
        async def get_config():
            """Return current configuration for UI display."""
            import yaml
            import os
            config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config", "settings.yaml")
            try:
                with open(config_path, "r") as f:
                    config = yaml.safe_load(f)
                
                # Get active model info from profiles
                active_model_id = config.get("active_model", "qwen3-vl-4b")
                profiles = config.get("model_profiles", {})
                active_profile = profiles.get(active_model_id, {})
                vlm_model = active_profile.get("main_model", config.get("models", {}).get("main_model", "Unknown"))
                gpu_layers = active_profile.get("gpu_layers", config.get("server", {}).get("gpu_layers", 0))
                context_size = active_profile.get("context_size", config.get("vlm", {}).get("context_size", 8192))
                
                return {
                    "backend_port": 8000,
                    "vlm_port": config.get("server", {}).get("port", 8080),
                    "vlm_model": vlm_model,
                    "gpu_layers": gpu_layers,
                    "context_size": context_size,
                    "max_iterations": config.get("safety", {}).get("max_iterations", 25),
                    "action_delay": config.get("safety", {}).get("action_delay", 0.1),
                    "failsafe_enabled": config.get("safety", {}).get("failsafe_enabled", True),
                    "wake_word_enabled": self.state.get("wake_word_enabled", True)
                }
            except Exception as e:
                logger.error(f"Failed to load config: {e}")
                return {"error": "Failed to load configuration"}

        # Wake word callbacks
        self.on_wake_word_enable = None
        self.on_wake_word_disable = None

        @self.app.post("/wake-word/enable")
        async def enable_wake_word():
            """Enable wake word detection."""
            self.state["wake_word_enabled"] = True
            if self.on_wake_word_enable:
                self.on_wake_word_enable()
            logger.info("Wake word detection ENABLED")
            return {"status": "enabled", "wake_word_enabled": True}

        @self.app.post("/wake-word/disable")
        async def disable_wake_word():
            """Disable wake word detection."""
            self.state["wake_word_enabled"] = False
            if self.on_wake_word_disable:
                self.on_wake_word_disable()
            logger.info("Wake word detection DISABLED")
            return {"status": "disabled", "wake_word_enabled": False}

        @self.app.get("/wake-word/status")
        async def wake_word_status():
            """Get current wake word status."""
            return {"wake_word_enabled": self.state.get("wake_word_enabled", True)}

        # VLM Manager reference (set by main.py)
        self.vlm_manager = None

        @self.app.get("/models")
        async def get_models():
            """Get list of available models."""
            if not self.vlm_manager:
                return {"error": "VLM manager not initialized", "models": []}
            
            models = self.vlm_manager.get_available_models()
            return {"models": models}

        @self.app.post("/model/switch")
        async def switch_model(data: dict):
            """Switch to a different model."""
            if not self.vlm_manager:
                return {"status": "error", "message": "VLM manager not initialized"}
            
            model_id = data.get("model_id")
            if not model_id:
                return {"status": "error", "message": "model_id required"}
            
            # Check if model is available
            profiles = self.vlm_manager.config.get("model_profiles", {})
            if model_id not in profiles:
                return {"status": "error", "message": f"Unknown model: {model_id}"}
            
            profile = profiles[model_id]
            if not profile.get("available", False):
                return {"status": "error", "message": f"Model not yet available: {profile.get('display_name', model_id)}"}
            
            # Perform the switch
            logger.info(f"Switching model to: {model_id}")
            success = self.vlm_manager.switch_model(model_id)
            
            if success:
                return {"status": "ok", "model_id": model_id, "display_name": profile.get("display_name")}
            else:
                return {"status": "error", "message": "Failed to switch model"}

        @self.app.get("/model/active")
        async def get_active_model():
            """Get the currently active model."""
            if not self.vlm_manager:
                return {"error": "VLM manager not initialized"}
            
            profile = self.vlm_manager.get_active_profile()
            return {
                "model_id": profile.get("id"),
                "display_name": profile.get("display_name"),
                "description": profile.get("description", "")
            }

        # ========== Mobile App Endpoints ==========

        @self.app.get("/chat/history")
        async def get_chat_history():
            """Return recent chat messages for mobile app."""
            return {"messages": self.chat_history[-100:]}

        @self.app.post("/chat/send")
        async def send_chat(data: dict):
            """Send a message from the mobile app."""
            message = data.get("message", "").strip()
            if not message:
                return {"status": "error", "message": "No message provided"}
            if len(message) > 10000:
                return {"status": "error", "message": "Message too long"}

            # Store user message
            self._add_chat_message("user", message)

            # Smart routing: steer if busy, queue if idle
            current_status = self.state.get("status", "idle")
            is_busy = current_status not in ("idle", "COMPLETE", "ERROR", "ABORTED")

            if is_busy and self.orchestrator:
                self.orchestrator.inject_context(message)
                logger.info(f"Mobile steering: {message[:100]}")
                return {"status": "steering", "message": "Injected into active task"}

            if self.task_queue:
                logger.info(f"Mobile task: {message[:100]}")
                self.task_queue.put(message)
                return {"status": "queued"}
            return {"status": "error", "message": "System not ready"}

        @self.app.post("/stream/start")
        async def start_stream():
            """Start continuous screen streaming for mobile monitor."""
            if self._streaming:
                return {"status": "already_streaming"}
            self._start_screen_stream()
            return {"status": "streaming"}

        @self.app.post("/stream/stop")
        async def stop_stream():
            """Stop continuous screen streaming."""
            self._stop_screen_stream()
            return {"status": "stopped"}

        @self.app.get("/frame/latest")
        async def get_latest_frame():
            """Return the most recent screen frame as base64 JPEG."""
            if self._latest_frame:
                return {"frame": self._latest_frame, "timestamp": time.time()}
            return {"frame": None, "timestamp": time.time()}

        # ========== Agent Lifecycle Endpoints (Mobile Dashboard) ==========

        @self.app.get("/agent/status")
        async def agent_status():
            """Return whether the agent is currently running."""
            current = self.state.get("status", "idle")
            running = current not in ("idle", "COMPLETE", "ERROR", "ABORTED")
            return {
                "running": running,
                "status": current,
                "vlm_status": self.state.get("vlm_status", "OFFLINE"),
            }

        @self.app.post("/agent/start")
        async def agent_start():
            """Start the agent (queue a wake-up if idle)."""
            if self.task_queue:
                self.task_queue.put("__START__")
                return {"status": "ok", "message": "Agent start requested"}
            return {"status": "error", "message": "System not ready"}

        @self.app.post("/agent/stop")
        async def agent_stop():
            """Stop the running agent."""
            if hasattr(self, 'on_stop_callback') and self.on_stop_callback:
                self.on_stop_callback()
                return {"status": "ok", "message": "Stop signal sent"}
            return {"status": "error", "message": "No stop handler registered"}

        @self.app.post("/agent/restart")
        async def agent_restart():
            """Restart the agent — stop then start."""
            if hasattr(self, 'on_stop_callback') and self.on_stop_callback:
                self.on_stop_callback()
            await asyncio.sleep(1)
            if self.task_queue:
                self.task_queue.put("__START__")
                return {"status": "ok", "message": "Restart initiated"}
            return {"status": "error", "message": "System not ready"}

        # ========== Mobile OTA Update Endpoints ==========

        @self.app.get("/mobile/version")
        async def mobile_version():
            """Return current mobile app version info for OTA checks."""
            import json, os
            version_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "mobile", "version.json")
            try:
                with open(version_path, "r") as f:
                    info = json.load(f)
                # Check if APK exists
                apk_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "mobile", "builds")
                apk_path = os.path.join(apk_dir, "rin-release.apk")
                info["apk_available"] = os.path.exists(apk_path)
                if info["apk_available"]:
                    info["apk_size"] = os.path.getsize(apk_path)
                return info
            except FileNotFoundError:
                return {"error": "Version info not available", "version": "0.0.0", "versionCode": 0}
            except Exception as e:
                logger.error(f"Failed to read version info: {e}")
                return {"error": str(e)}

        @self.app.get("/mobile/apk")
        async def mobile_apk():
            """Serve the latest APK for OTA download."""
            import os
            from fastapi.responses import FileResponse
            apk_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "mobile", "builds")
            apk_path = os.path.join(apk_dir, "rin-release.apk")
            if not os.path.exists(apk_path):
                return {"status": "error", "message": "No APK available"}
            return FileResponse(
                apk_path,
                media_type="application/vnd.android.package-archive",
                filename="rin-release.apk"
            )


    def set_vlm_status(self, status: str):
        """Update VLM health status."""
        self.state["vlm_status"] = status

    def set_task_queue(self, queue):
        """Set the queue to submit tasks to."""
        self.task_queue = queue

    def set_stop_callback(self, callback):
        """Set the callback to run when stop is requested."""
        self.on_stop_callback = callback
    
    def set_pause_callback(self, callback):
        """Set the callback to run when pause is requested."""
        self.on_pause_callback = callback
    
    def set_resume_callback(self, callback):
        """Set the callback to run when resume is requested."""
        self.on_resume_callback = callback
        
    def _register_handlers(self):
        @self.sio.event
        async def connect(sid, environ, auth=None):
            # Verify Socket.IO auth token for non-local connections
            client_ip = environ.get("REMOTE_ADDR", "")
            if client_ip not in LOCAL_IPS:
                token = None
                if auth and isinstance(auth, dict):
                    token = auth.get("token", "")
                if not token or not hmac.compare_digest(token, self._api_key):
                    logger.warning(f"Socket.IO auth failed from {client_ip}")
                    raise ConnectionRefusedError("Authentication required")
            
            logger.info(f"Client connected: {sid} ({client_ip})")
            
            # Send initial state push to new client
            await self.sio.emit('status', {
                'state': self.state.get('status', 'idle'),
                'details': self.state.get('details'),
                'vlm_status': self.state.get('vlm_status', 'OFFLINE'),
                'wake_word_enabled': self.state.get('wake_word_enabled', True),
            }, to=sid)
            
        @self.sio.event
        async def disconnect(sid):
            logger.info(f"Client disconnected: {sid}")
            
    def start(self):
        """Start the server in a separate thread."""
        logger.info(f"Starting Status Server on {self.host}:{self.port}")
        self.thread = threading.Thread(target=self._run_server, daemon=True)
        self.thread.start()
        
    def _run_server(self):
        # Create a new event loop for this thread
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        
        config = uvicorn.Config(
            self.socket_app, 
            host=self.host, 
            port=self.port, 
            log_level="error",
            loop="asyncio"
        )
        server = uvicorn.Server(config)
        
        self.loop.run_until_complete(server.serve())
        
    def stop(self):
        """Stop the server."""
        self.should_exit = True
        # Note: Uvicorn doesn't have a clean thread-safe stop from outside, 
        # but since it's a daemon thread it will die with the main process.
        
    def emit_status(self, status: str, details: Optional[str] = None):
        """Broadcast status update."""
        self.state["status"] = status
        self.state["details"] = details
        
        if not self.loop:
            return
            
        future = asyncio.run_coroutine_threadsafe(
            self.sio.emit('status', {'state': status, 'details': details}),
            self.loop
        )
        
    def emit_thought(self, thought: str):
        """Broadcast agent thinking."""
        self.state["last_thought"] = thought
        
        # Record to chat history for mobile app
        if thought and thought != "Waiting for input...":
            self._add_chat_message("agent", thought)
        
        if not self.loop:
            return
            
        future = asyncio.run_coroutine_threadsafe(
            self.sio.emit('thought', {'text': thought}),
            self.loop
        )
        
    def emit_action(self, action_type: str, description: str):
        """Broadcast action execution."""
        self.state["current_action"] = f"[{action_type}] {description}"
        
        if not self.loop:
            return
            
        future = asyncio.run_coroutine_threadsafe(
            self.sio.emit('action', {'type': action_type, 'description': description}),
            self.loop
        )

    def emit_frame(self, base64_frame: str):
        """Broadcast screen frame."""
        self._latest_frame = base64_frame  # Cache for REST fallback
        
        if not self.loop:
            return
            
        # Fire and forget - don't wait for result to avoid blocking capture loop
        asyncio.run_coroutine_threadsafe(
            self.sio.emit('frame', {'image': base64_frame}),
            self.loop
        )

    # === Chat History ===

    def _add_chat_message(self, role: str, content: str):
        """Add a message to chat history."""
        self.chat_history.append({
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat()
        })
        # Cap history
        if len(self.chat_history) > self._chat_history_max:
            self.chat_history = self.chat_history[-self._chat_history_max:]
        
        # Broadcast to connected mobile clients
        if self.loop:
            asyncio.run_coroutine_threadsafe(
                self.sio.emit('chat_message', self.chat_history[-1]),
                self.loop
            )

    # === Screen Streaming ===

    def _start_screen_stream(self):
        """Start continuous screen capture streaming."""
        if self._streaming:
            return
        self._streaming = True
        self._stream_thread = threading.Thread(target=self._stream_loop, daemon=True)
        self._stream_thread.start()
        logger.info(f"Screen streaming started at {self._stream_fps}fps")

    def _stop_screen_stream(self):
        """Stop screen streaming."""
        self._streaming = False
        logger.info("Screen streaming stopped")

    def _stream_loop(self):
        """Continuous screen capture loop for mobile streaming."""
        try:
            import mss
            from PIL import Image
            
            sct = mss.mss()
            interval = 1.0 / self._stream_fps
            
            while self._streaming:
                start = time.time()
                try:
                    # Capture primary monitor
                    monitor = sct.monitors[1]  # Primary monitor
                    screenshot = sct.grab(monitor)
                    
                    # Convert to PIL, resize for mobile bandwidth
                    img = Image.frombytes('RGB', screenshot.size, screenshot.bgra, 'raw', 'BGRX')
                    # Scale to max 720p width for mobile
                    max_w = 720
                    if img.width > max_w:
                        ratio = max_w / img.width
                        img = img.resize((max_w, int(img.height * ratio)), Image.LANCZOS)
                    
                    # Compress to JPEG
                    buffer = io.BytesIO()
                    img.save(buffer, format='JPEG', quality=55)
                    frame_b64 = base64.b64encode(buffer.getvalue()).decode('utf-8')
                    
                    self._latest_frame = frame_b64
                    
                    # Emit via Socket.IO
                    if self.loop:
                        asyncio.run_coroutine_threadsafe(
                            self.sio.emit('frame', {'image': frame_b64}),
                            self.loop
                        )
                except Exception as e:
                    logger.error(f"Stream frame error: {e}")
                
                # Maintain target FPS
                elapsed = time.time() - start
                sleep_time = max(0, interval - elapsed)
                time.sleep(sleep_time)
        except ImportError:
            logger.error("mss/PIL not available for screen streaming")
        except Exception as e:
            logger.error(f"Stream loop error: {e}")
        finally:
            self._streaming = False

    # === Voice State Emissions ===
    
    def emit_voice_state(self, state: str, partial: str = ""):
        """Broadcast voice state change (idle, listening, processing)."""
        self.state["voice_state"] = state
        self.state["voice_partial"] = partial
        
        if not self.loop:
            return
            
        asyncio.run_coroutine_threadsafe(
            self.sio.emit('voice_state', {'state': state, 'partial': partial}),
            self.loop
        )
    
    def emit_voice_partial(self, text: str):
        """Broadcast partial transcription for real-time display."""
        self.state["voice_partial"] = text
        
        if not self.loop:
            return
            
        asyncio.run_coroutine_threadsafe(
            self.sio.emit('voice_partial', {'text': text}),
            self.loop
        )
    
    def emit_voice_level(self, level: float):
        """Broadcast audio level (0.0-1.0) for visualization."""
        self.state["voice_level"] = level
        
        if not self.loop:
            return
            
        # High frequency - fire and forget without storing future
        asyncio.run_coroutine_threadsafe(
            self.sio.emit('voice_level', {'level': level}),
            self.loop
        )
