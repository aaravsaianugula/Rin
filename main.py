#!/usr/bin/env python3
"""
Qwen3-VL Computer Control System - Main Entry Point

A local, privacy-first computer automation system using Qwen3-VL-4B
vision-language model to control the computer via natural language.
"""

import argparse
import logging
import os
import subprocess
import sys
import time
from pathlib import Path

import yaml
from src.display import ensure_dpi_aware

# Ensure console can handle emojis/UTF-8
if sys.platform == "win32":
    try:
        import codecs
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except (AttributeError, Exception):
        pass

# Ensure UI coordinates match screen pixels for accurate clicking
ensure_dpi_aware()


def setup_logging(level: str = "INFO", log_file: str = None) -> logging.Logger:
    """Configure logging."""
    logger = logging.getLogger("qwen3vl")
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%H:%M:%S"
    )
    
    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    # File handler
    if log_file:
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    
    return logger


def load_config(config_path: str = None) -> dict:
    """Load configuration from YAML file."""
    if config_path is None:
        config_path = Path(__file__).parent / "config" / "settings.yaml"
    
    config_path = Path(config_path)
    
    if not config_path.exists():
        print(f"Warning: Config file not found at {config_path}, using defaults")
        return get_default_config()
    
    with open(config_path, "r") as f:
        return yaml.safe_load(f)


def get_default_config() -> dict:
    """Return default configuration."""
    return {
        "screen": {"width": None, "height": None, "max_image_size": 1080},
        "vlm": {"base_url": "http://127.0.0.1:8080", "timeout": 30, "temperature": 0.0},
        "safety": {
            "confidence_threshold": 0.8,
            "max_iterations": 25,
            "action_delay": 0.0,
            "failsafe_enabled": True,
            "pause_before_action": 0.0,
            "verify_actions": False
        },
        "logging": {"level": "INFO", "file": "logs/actions.log", "console": True}
    }


class VLMManager:
    """Manages the lifecycle of the llama-server process with multi-model support."""
    
    def __init__(self, config: dict, logger: logging.Logger):
        self.config = config
        self.logger = logger
        self.process = None
        self.log_file = None
        self.last_active = 0
        self.idle_timeout = 60  # Keep VLM warm for 60s between tasks
        self._switching = False  # Mutex for model switching
        
    def _get_vlm_executable(self) -> str:
        """Find the llama-server executable."""
        project_root = str(Path(__file__).parent.absolute())
        user_profile = os.environ.get("USERPROFILE", "")
        paths = [
            os.path.join(project_root, "llama.cpp", "build", "bin", "Release", "llama-server.exe"),
            os.path.join(user_profile, "llama.cpp", "build", "bin", "Release", "llama-server.exe"),
            "llama-server.exe", # In PATH
            "llama-server"      # Linux/macOS
        ]
        
        for p in paths:
            if os.path.exists(p):
                return p
        
        # Fallback to just the command name
        return "llama-server"

    def _kill_port_process(self, port: int):
        """Kill any process using the specified port."""
        if sys.platform != "win32": return
        try:
            # Find PID using the port
            cmd = f"netstat -ano | findstr :{port} | findstr LISTENING"
            output = subprocess.check_output(cmd, shell=True).decode()
            for line in output.strip().split('\n'):
                parts = line.split()
                if len(parts) > 4:
                    pid = parts[-1]
                    self.logger.info(f"Killing process {pid} on port {port}")
                    subprocess.run(f"taskkill /F /PID {pid}", shell=True, capture_output=True)
        except Exception:
            pass

    def get_active_profile(self) -> dict:
        """Get the currently active model profile."""
        active_model = self.config.get("active_model", "qwen3-vl-4b")
        profiles = self.config.get("model_profiles", {})
        
        if active_model in profiles:
            profile = profiles[active_model].copy()
            profile["id"] = active_model
            return profile
        
        # Fallback to legacy models config
        models_config = self.config.get("models", {})
        return {
            "id": "qwen3-vl-4b",
            "display_name": "Qwen3-VL 4B",
            "main_model": models_config.get("main_model", "models/Qwen3VL-4B-Instruct-Q4_K_M.gguf"),
            "vision_projector": models_config.get("vision_projector", "models/mmproj-Qwen3VL-4B-Instruct-F16.gguf"),
            "context_size": 8192,
            "gpu_layers": 40,
            "available": True
        }

    def get_available_models(self) -> list:
        """Get list of all model profiles with their status."""
        active_model = self.config.get("active_model", "qwen3-vl-4b")
        profiles = self.config.get("model_profiles", {})
        project_root = str(Path(__file__).parent.absolute())
        
        models = []
        for model_id, profile in profiles.items():
            # Check if files exist on disk
            main_path = os.path.join(project_root, profile.get("main_model", ""))
            files_exist = os.path.exists(main_path)
            
            models.append({
                "id": model_id,
                "display_name": profile.get("display_name", model_id),
                "description": profile.get("description", ""),
                "available": profile.get("available", False),
                "files_exist": files_exist,
                "is_active": model_id == active_model
            })
        
        return models

    def switch_model(self, model_id: str) -> bool:
        """Switch to a different model profile. Stops current VLM and restarts with new model."""
        if self._switching:
            self.logger.warning("Model switch already in progress")
            return False
            
        profiles = self.config.get("model_profiles", {})
        if model_id not in profiles:
            self.logger.error(f"Unknown model profile: {model_id}")
            return False
            
        profile = profiles[model_id]
        if not profile.get("available", False):
            self.logger.error(f"Model {model_id} is not yet available")
            return False
        
        self._switching = True
        try:
            self.logger.info(f"Switching to model: {profile.get('display_name', model_id)}")
            
            # Stop current VLM
            self.stop()
            
            # Update active model in config
            self.config["active_model"] = model_id
            
            # Persist to settings.yaml
            self._save_active_model(model_id)
            
            # Start with new model
            success = self.start()
            
            if success:
                self.logger.info(f"Successfully switched to {model_id}")
            else:
                self.logger.error(f"Failed to start {model_id}")
                
            return success
        finally:
            self._switching = False
    
    def _save_active_model(self, model_id: str):
        """Persist the active model selection to settings.yaml."""
        import yaml
        import os
        config_path = os.path.join(os.path.dirname(__file__), "config", "settings.yaml")
        try:
            with open(config_path, "r") as f:
                full_config = yaml.safe_load(f)
            
            full_config["active_model"] = model_id
            
            with open(config_path, "w") as f:
                yaml.dump(full_config, f, default_flow_style=False, sort_keys=False)
            
            self.logger.info(f"Saved active_model={model_id} to settings.yaml")
        except Exception as e:
            self.logger.error(f"Failed to save active model: {e}")

    def start(self) -> bool:
        """Start the llama-server process with the active model profile."""
        if self.process and self.process.poll() is None:
            self.last_active = time.time()
            return True
            
        executable = self._get_vlm_executable()
        
        # Ensure port is free
        vlm_port = self.config.get("server", {}).get("port", 8080)
        self._kill_port_process(vlm_port)
        
        # Get active model profile
        profile = self.get_active_profile()
        self.logger.info(f"Starting VLM: {profile.get('display_name', 'unknown')} via {executable}")
        
        server_config = self.config.get("server", {})
        project_root = str(Path(__file__).parent.absolute())
        
        def make_abs(p):
            if not p: return ""
            if os.path.isabs(p): return p
            return os.path.join(project_root, p)

        # Use profile settings with fallback to server config
        gpu_layers = profile.get("gpu_layers", server_config.get("gpu_layers", 40))
        context_size = profile.get("context_size", self.config.get("vlm", {}).get("context_size", 8192))
        
        # Build command
        batch_size = server_config.get("batch_size", 2048)
        ubatch_size = server_config.get("ubatch_size", 512)
        cmd = [
            executable,
            "-m", make_abs(profile.get("main_model")),
            "--mmproj", make_abs(profile.get("vision_projector")),
            "-ngl", str(gpu_layers),
            "-c", str(context_size),
            "-b", str(batch_size),
            "-ub", str(ubatch_size),
            "--host", server_config.get("host", "127.0.0.1"),
            "--port", str(vlm_port),
            "-np", str(server_config.get("n_parallel", 1)),
            "--image-min-tokens", str(server_config.get("image_min_tokens", 1024)),
            "-t", str(server_config.get("threads", 8)),
            "--cache-type-k", server_config.get("kv_cache_type", "q8_0"),
            "--cache-type-v", server_config.get("kv_cache_type", "q8_0")
        ]
        if server_config.get("flash_attention"):
            cmd.extend(["--flash-attn", "on"])
        
        try:
            log_dir = os.path.join(project_root, "logs")
            if not os.path.exists(log_dir): os.makedirs(log_dir)
            self.log_file = open(os.path.join(log_dir, "vlm_server.log"), "a")
            self.log_file.write(f"\n--- Starting {profile.get('display_name', 'VLM')} at {time.ctime()} ---\n")
            self.log_file.flush()

            self.process = subprocess.Popen(
                cmd,
                stdout=self.log_file,
                stderr=self.log_file,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
                cwd=project_root
            )
            self.last_active = time.time()
            return True
        except Exception as e:
            self.logger.error(f"Failed to start VLM: {e}")
            return False
            
    def stop(self):
        """Stop the llama-server process."""
        if self.process:
            self.logger.info("Stopping VLM to save resources...")
            try:
                if sys.platform == "win32":
                    subprocess.run(f"taskkill /F /PID {self.process.pid} /T", shell=True, capture_output=True)
                else:
                    self.process.terminate()
                    self.process.wait(timeout=5)
            except Exception as e:
                self.logger.error(f"Error stopping VLM: {e}")
                try: self.process.kill()
                except Exception: pass
            
            self.process = None
            if self.log_file:
                try: self.log_file.close()
                except Exception: pass
                self.log_file = None
            
    def check_idle(self):
        """Stop VLM if idle for too long."""
        if self.process and self.process.poll() is None:
            idle_time = time.time() - self.last_active
            if idle_time > self.idle_timeout:
                self.logger.info(f"VLM idle for {int(idle_time)}s, stopping...")
                self.stop()
        elif self.process:
            # Process died unexpectedly
            self.logger.warning("VLM process found stopped, cleaning up handle.")
            self.stop()

    def update_activity(self):
        """Reset idle timer."""
        self.last_active = time.time()


def create_orchestrator(config: dict, logger: logging.Logger, server=None):
    """Create and configure the orchestrator."""
    from src.capture import ScreenCapture
    from src.inference import VLMClient
    from src.actions import ActionExecutor
    from src.orchestrator import Orchestrator
    
    # Initialize screen capture
    max_size = config.get("screen", {}).get("max_image_size", 1080)
    capture = ScreenCapture(max_size=max_size)
    
    # Get screen dimensions
    screen_width, screen_height = capture.get_screen_size()
    logger.info(f"Screen resolution: {screen_width}x{screen_height}")
    
    # Initialize VLM manager
    vlm_manager = VLMManager(config, logger)
    
    # Initialize VLM client (temperature 0 = greedy, faster)
    vlm_config = config.get("vlm", {})
    vlm = VLMClient(
        base_url=vlm_config.get("base_url", "http://127.0.0.1:8080"),
        timeout=vlm_config.get("timeout", 60),
        logger=logger
    )
    
    # Initialize action executor
    safety_config = config.get("safety", {})
    executor = ActionExecutor(
        screen_width=screen_width,
        screen_height=screen_height,
        confidence_threshold=safety_config.get("confidence_threshold", 0.8),
        action_delay=safety_config.get("action_delay", 0.0),
        pause_before_action=safety_config.get("pause_before_action", 0.0),
        failsafe_enabled=safety_config.get("failsafe_enabled", True),
        logger=logger,
        status_server=server
    )
    
    # Get click offset from config (for calibration)
    coord_config = config.get("coordinates", {})
    click_offset_x = coord_config.get("click_offset_x", 0)
    click_offset_y = coord_config.get("click_offset_y", 0)
    if click_offset_x != 0 or click_offset_y != 0:
        logger.info(f"Using calibrated click offset: ({click_offset_x:+d}, {click_offset_y:+d})")
    
    # Create orchestrator (verify_actions=false speeds up by skipping extra VLM call per action)
    orchestrator = Orchestrator(
        vlm_client=vlm,
        screen_capture=capture,
        action_executor=executor,
        max_iterations=safety_config.get("max_iterations", 10),
        ui_settle_seconds=safety_config.get("ui_settle_seconds", 1.5),
        click_offset_x=click_offset_x,
        click_offset_y=click_offset_y,
        logger=logger,
        status_server=server,
        screen_stability_enabled=safety_config.get("screen_stability_enabled", True),
        screen_stability_max_wait=safety_config.get("screen_stability_max_wait", 3.0)
    )
    
    # Attach manager to orchestrator for automatic lifecycle
    orchestrator.vlm_manager = vlm_manager
    
    # Wire up abort check so VLM client can check if we should abort
    vlm.set_abort_check(lambda: orchestrator.aborted)
    
    return orchestrator


def run_command(orchestrator, command: str, logger: logging.Logger):
    """Execute a single command."""
    logger.info(f"Executing command: {command}")
    
    # Ensure VLM is running
    if not orchestrator.vlm_manager.start():
        logger.error("Could not start VLM")
        return False
        
    # Use timeout from config
    timeout = orchestrator.vlm.timeout
    if not orchestrator.vlm.wait_for_server(max_wait=timeout):
        logger.error("VLM server did not become ready in time")
        return False
    
    orchestrator.vlm_manager.update_activity()
    result = orchestrator.execute_task(command)
    orchestrator.vlm_manager.update_activity()
    
    logger.info(f"Task completed: {result.success}")
    logger.info(f"Message: {result.message}")
    logger.info(f"Steps taken: {result.steps_taken}")
    logger.info(f"Duration: {result.duration_seconds:.2f}s")
    
    if result.error:
        logger.error(f"Error: {result.error}")
    
    return result.success


def async_mode(orchestrator, logger: logging.Logger, task_queue, server):
    """Run in async mode, processing tasks from the queue."""
    logger.info("Ready for tasks from overlay...")
    print("\n" + "="*60)
    print("Qwen3-VL Computer Control System - Overlay Mode")
    print("="*60)
    print("\nWaiting for commands from overlay...\n")
    
    import time
    import queue
    
    last_status_check = 0
    while True:
        try:
            # Check for idle timeout
            orchestrator.vlm_manager.check_idle()
            
            # Periodically update VLM status in server (every 2s)
            current_time = time.time()
            if current_time - last_status_check > 2.0:
                if orchestrator.vlm_manager.process:
                    # Quick health check if we think it's running
                    is_healthy = orchestrator.vlm.check_health()
                    if not is_healthy:
                        server.set_vlm_status("STARTING")
                    else:
                        server.set_vlm_status("ONLINE")
                else:
                    server.set_vlm_status("STANDBY")
                last_status_check = current_time

            # Poll queue with short timeout
            try:
                command = task_queue.get(timeout=0.5)
            except queue.Empty:
                continue
                
            if command:
                logger.info(f"Received task: {command}")
                
                # Update status immediately
                server.set_vlm_status("STARTING")
                server.emit_status("running", f"Starting VLM for: {command}")
                server.emit_thought(f"Waking up the VLM engine for: {command}...")
                
                # Ensure VLM is running before processing
                if not orchestrator.vlm_manager.start():
                    logger.error("Failed to start VLM for task")
                    server.set_vlm_status("ERROR")
                    server.emit_status("error", "Failed to start VLM engine")
                    continue
                
                # Wait for server to be ready
                if not orchestrator.vlm.wait_for_server(max_wait=60):
                    server.set_vlm_status("ERROR")
                    server.emit_status("error", "VLM failed to start in time")
                    continue
                
                server.set_vlm_status("ONLINE")
                # Process the command
                run_command(orchestrator, command, logger)
                
                # Immediately check if we should go to standby
                # We update the last_active time here to now, so it will stop in exactly 20s if no new tasks
                orchestrator.vlm_manager.check_idle()
                
        except KeyboardInterrupt:
            print("\n\nInterrupted. Exiting...")
            orchestrator.vlm_manager.stop()
            break
        except Exception as e:
            logger.error(f"Error in async loop: {e}")
            time.sleep(1)


def test_capture(config: dict, logger: logging.Logger):
    """Test screenshot capture functionality."""
    from src.capture import ScreenCapture
    
    print("\n=== Screenshot Capture Test ===\n")
    
    capture = ScreenCapture(max_size=config.get("screen", {}).get("max_image_size", 1080))
    
    # Test screen size
    width, height = capture.get_screen_size()
    print(f"Screen size: {width}x{height}")
    
    # Test capture
    img = capture.capture_screen()
    print(f"Captured image: {img.size[0]}x{img.size[1]}")
    
    # Benchmark
    avg_time = capture.benchmark_capture(5)
    print(f"Average capture time: {avg_time:.2f}ms")
    
    # Save test screenshot
    test_path = "logs/test_screenshot.png"
    capture.save_screenshot(test_path)
    print(f"Saved test screenshot to: {test_path}")
    
    print("\n[OK] Screenshot capture working\n")


def test_coordinates(logger: logging.Logger):
    """Test coordinate conversion."""
    from src.coordinates import (
        normalized_to_pixels,
        pixels_to_normalized,
        validate_normalized_coordinates,
        validate_pixel_coordinates,
        BoundingBox
    )
    
    print("\n=== Coordinate Conversion Test ===\n")
    
    screen_w, screen_h = 1920, 1080
    
    # Test conversions
    test_cases = [
        (0, 0, 0, 0),
        (500, 500, 960, 540),  # Center
        (1000, 1000, 1920, 1080),  # Bottom-right
        (250, 750, 480, 810),  # Quarter points
    ]
    
    all_passed = True
    for norm_x, norm_y, expected_x, expected_y in test_cases:
        px_x, px_y = normalized_to_pixels(norm_x, norm_y, screen_w, screen_h)
        passed = (px_x == expected_x and px_y == expected_y)
        status = "OK" if passed else "FAIL"
        print(f"  [{status}] ({norm_x}, {norm_y}) -> ({px_x}, {px_y}) [expected: ({expected_x}, {expected_y})]")
        all_passed = all_passed and passed
    
    # Test bbox
    bbox = BoundingBox(100, 200, 300, 400, "test")
    center = bbox.center
    print(f"\n  BoundingBox center: ({center[0]}, {center[1]}) [expected: (200.0, 300.0)]")
    
    if all_passed:
        print("\n[OK] Coordinate conversion working\n")
    else:
        print("\n[FAIL] Some tests failed\n")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Qwen3-VL Computer Control System",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py --interactive
  python main.py --command "Open Notepad and type Hello World"
  python main.py --test-capture
  python main.py --test-coordinates
        """
    )
    
    parser.add_argument(
        "-c", "--command",
        help="Execute a single command and exit"
    )
    parser.add_argument(
        "-i", "--interactive",
        action="store_true",
        help="Run in interactive mode"
    )
    parser.add_argument(
        "--config",
        help="Path to config file (default: config/settings.yaml)"
    )
    parser.add_argument(
        "--test-capture",
        action="store_true",
        help="Test screenshot capture"
    )
    parser.add_argument(
        "--test-coordinates",
        action="store_true",
        help="Test coordinate conversion"
    )
    parser.add_argument(
        "--wait-for-server",
        type=int,
        default=0,
        help="Wait up to N seconds for llama-server to start"
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose (DEBUG) logging"
    )
    parser.add_argument(
        "--service-managed",
        action="store_true",
        help="Run as a child of rin_service.py (port 8001, no overlay, no instance lock)"
    )
    
    args = parser.parse_args()
    
    # Ensure only one instance is running (prevents duplicate Discord bots, etc.)
    # Skip when launched by rin_service.py (it manages our lifecycle)
    if not args.service_managed:
        from src.process_manager import ensure_single_instance, AlreadyRunningError, cleanup_instance
        try:
            ensure_single_instance("Backend")
        except AlreadyRunningError:
            print("ERROR: Rin Agent is already running! Only one instance allowed.")
            return 1
        
        # Register cleanup on exit
        import atexit
        atexit.register(cleanup_instance)
    
    # Load configuration
    config = load_config(args.config)
    
    # Setup logging
    log_level = "DEBUG" if args.verbose else config.get("logging", {}).get("level", "INFO")
    log_file = config.get("logging", {}).get("file")
    logger = setup_logging(log_level, log_file)
    
    # Run tests if requested
    if args.test_capture:
        test_capture(config, logger)
        return 0
    
    if args.test_coordinates:
        test_coordinates(logger)
        return 0
    
    # Initialize and start status server
    # When service-managed, use port 8001 so rin_service.py keeps 8000
    from src.server import StatusServer
    server_port = 8001 if args.service_managed else 8000
    server = StatusServer(port=server_port)
    server.start()
    logger.info(f"Status server started on port {server_port}")
    
    # Auto-launch the overlay app if not already running
    # Skip when service-managed (service or user controls overlay separately)
    if not args.service_managed:
        overlay_exe = Path(__file__).parent / "OverlayApp" / "bin" / "Release" / "net10.0-windows" / "Rin Agent.exe"
        if not overlay_exe.exists():
            overlay_exe = Path(__file__).parent / "OverlayApp" / "bin" / "Debug" / "net10.0-windows" / "Rin Agent.exe"
        
        if overlay_exe.exists():
            # Check if already running
            import subprocess
            check_proc = subprocess.run(
                'tasklist /FI "IMAGENAME eq Rin Agent.exe" /NH',
                shell=True, capture_output=True, text=True
            )
            if "Rin Agent.exe" not in check_proc.stdout:
                logger.info("Launching overlay app...")
                subprocess.Popen(
                    [str(overlay_exe)],
                    creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
                    cwd=str(overlay_exe.parent)
                )
                time.sleep(1)  # Give it time to start
                logger.info("Overlay app launched")
            else:
                logger.info("Overlay app already running")
        else:
            logger.warning(f"Overlay app not found at {overlay_exe}")
    
    # Initialize voice service (optional - graceful if dependencies missing)
    voice_service = None
    voice_config = config.get("voice", {})
    if voice_config.get("enabled", True):  # Default to True for backwards compatibility
        try:
            from src.voice_service import init_voice_service, VoiceConfig
            voice_service = init_voice_service(
                status_server=server,
                config=VoiceConfig(
                    porcupine_model_path=voice_config.get("porcupine_model", "models/porcupine/Hey-Rin_en_windows_v4_0_0.ppn"),
                    moonshine_model=voice_config.get("moonshine_model", "moonshine/base"),
                    silence_timeout=voice_config.get("silence_timeout", 1.5),
                )
            )
            logger.info("Voice service initialized")
        except ImportError as e:
            logger.info(f"Voice service not available (missing dependencies): {e}")
        except Exception as e:
            logger.warning(f"Voice service failed to initialize: {e}")
    else:
        logger.info("Voice service disabled in config")

    # Create orchestrator
    try:
        orchestrator = create_orchestrator(config, logger, server)
    except ImportError as e:
        logger.error(f"Failed to import modules: {e}")
        return 1
    
    # Wire up VLM manager to server for model API endpoints
    server.vlm_manager = orchestrator.vlm_manager
    
    # Wire up orchestrator for steering endpoint
    server.orchestrator = orchestrator
    
    # Wire up stop signal
    server.set_stop_callback(orchestrator.abort)
    
    # Wire up pause/resume signals for interactive control
    if hasattr(orchestrator, 'pause'):
        server.set_pause_callback(orchestrator.pause)
    if hasattr(orchestrator, 'resume'):
        server.set_resume_callback(orchestrator.resume)
    
    # Wait for server if requested
    if args.wait_for_server > 0:
        if not orchestrator.vlm.wait_for_server(args.wait_for_server):
            logger.error("Failed to connect to llama-server")
            return 1
    
    # Execute command or enter interactive mode
    if args.command:
        success = run_command(orchestrator, args.command, logger)
        return 0 if success else 1
    
    # Initialize task queue
    import queue
    task_queue = queue.Queue()
    server.set_task_queue(task_queue)
    
    # Initialize memory service for persistent context
    memory_service = None
    try:
        from src.memory_service import init_memory_service
        memory_config = config.get("memory", {})
        memory_service = init_memory_service(memory_config.get("data_dir"))
        logger.info("Memory service initialized - context persists across sessions")
        # Attach to orchestrator for logging tasks
        orchestrator.memory_service = memory_service
    except Exception as e:
        logger.warning(f"Memory service failed to initialize: {e}")
    
    # Initialize Discord service (optional)
    discord_service = None
    try:
        from src.discord_service import init_discord_service
        discord_service = init_discord_service(config, server)
        if discord_service:
            discord_service.set_task_queue(task_queue)
            discord_service.set_orchestrator(orchestrator)
            if discord_service.start():
                logger.info("Discord service started - message Rin via Discord!")
            else:
                logger.info("Discord service not started (no token configured)")
    except ImportError as e:
        logger.info(f"Discord service not available (missing discord.py): {e}")
    except Exception as e:
        logger.warning(f"Discord service failed to initialize: {e}")
    
    # Initialize heartbeat service for proactive behavior
    heartbeat_service = None
    try:
        from src.heartbeat_service import init_heartbeat_service
        heartbeat_service = init_heartbeat_service(config, server)
        if heartbeat_service:
            heartbeat_service.set_dependencies(
                task_queue=task_queue,
                discord_service=discord_service,
                orchestrator=orchestrator,
            )
            if heartbeat_service.start():
                logger.info("Heartbeat service started - Rin can now be proactive!")
    except Exception as e:
        logger.warning(f"Heartbeat service failed to initialize: {e}")
    
    # Connect voice service to task queue and orchestrator
    if voice_service:
        voice_service.task_queue = task_queue
        
        # Bidirectional wiring for interactive assistant mode
        # Voice service -> Orchestrator: for priority commands (stop/pause/resume)
        voice_service.set_orchestrator(orchestrator)
        # Orchestrator -> Voice service: for continuous listening mode (no wake word during tasks)
        orchestrator.set_voice_service(voice_service)
        
        # Set up prompt injection callback (injects into running task context)
        def inject_prompt(text: str):
            logger.info(f"Voice injection: {text}")
            if hasattr(orchestrator, 'inject_context'):
                orchestrator.inject_context(text)
            else:
                # Fallback: queue as new task if no injection support
                task_queue.put(text)
        voice_service.set_inject_callback(inject_prompt)
        # Start voice listening
        if voice_service.start():
            logger.info("Voice service started - say 'Hey Rin' to activate")
            logger.info("During tasks, speak anytime to steer or interrupt (no wake word needed)")
            # Wire up wake word toggle callbacks
            server.on_wake_word_enable = voice_service.enable_wake_word
            server.on_wake_word_disable = voice_service.disable_wake_word
        else:
            logger.warning("Voice service failed to start")
    
    # Run in async processing mode
    try:
        async_mode(orchestrator, logger, task_queue, server)
    finally:
        # Cleanup all services
        if heartbeat_service:
            heartbeat_service.stop()
        if discord_service:
            discord_service.stop()
        server.stop()
        
    return 0


if __name__ == "__main__":
    sys.exit(main())
