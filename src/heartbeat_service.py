"""
Heartbeat Service for Rin Agent.

Enables proactive, autonomous behavior - Rin can reach out without prompting.
Scheduled wake-ups check HEARTBEAT.md items and take action if needed.

Inspired by OpenClaw's heartbeat system.
"""

import asyncio
import logging
import re
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, List, Optional, Tuple

logger = logging.getLogger("qwen3vl.heartbeat")


@dataclass
class HeartbeatConfig:
    """Configuration for heartbeat service."""
    enabled: bool = True
    interval_minutes: int = 30
    active_hours_start: int = 9   # 9 AM
    active_hours_end: int = 23    # 11 PM
    use_vlm_for_decisions: bool = True  # Use VLM to evaluate conditions


@dataclass 
class HeartbeatItem:
    """A single item from HEARTBEAT.md checklist."""
    title: str
    description: str
    enabled: bool
    raw_line: str


class HeartbeatService:
    """
    Proactive behavior service for Rin.
    
    Periodically wakes up, checks HEARTBEAT.md items, and takes action
    if any conditions are met. Can send proactive messages via Discord.
    """
    
    def __init__(
        self,
        config: HeartbeatConfig,
        data_dir: Optional[Path] = None,
        status_server=None,
    ):
        """
        Initialize heartbeat service.
        
        Args:
            config: Heartbeat configuration
            data_dir: Path to data directory with HEARTBEAT.md
            status_server: Optional status server for state broadcasting
        """
        self.config = config
        self.status_server = status_server
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        
        # Dependencies (set externally)
        self.task_queue = None
        self.discord_service = None
        self.orchestrator = None
        self.vlm_client = None
        
        # Data directory
        if data_dir is None:
            project_root = Path(__file__).parent.parent
            data_dir = project_root / "data"
        self.data_dir = Path(data_dir)
        self.heartbeat_path = self.data_dir / "HEARTBEAT.md"
        
        # State tracking
        self._last_heartbeat: Optional[datetime] = None
        self._heartbeat_count = 0
        
        logger.info(f"Heartbeat service initialized (interval: {config.interval_minutes}m)")
    
    # -------------------------------------------------------------------------
    # Checklist Parsing
    # -------------------------------------------------------------------------
    
    def parse_heartbeat_file(self) -> List[HeartbeatItem]:
        """Parse HEARTBEAT.md to extract checklist items."""
        items = []
        
        if not self.heartbeat_path.exists():
            logger.warning("HEARTBEAT.md not found")
            return items
        
        try:
            content = self.heartbeat_path.read_text(encoding='utf-8')
            
            # Find enabled items: - [ ] **Title**: Description
            enabled_pattern = r'- \[ \] \*\*(.+?)\*\*:\s*(.+)'
            for match in re.finditer(enabled_pattern, content):
                items.append(HeartbeatItem(
                    title=match.group(1).strip(),
                    description=match.group(2).strip(),
                    enabled=True,
                    raw_line=match.group(0)
                ))
            
            # Find disabled items (commented out)
            disabled_pattern = r'<!--\s*- \[ \] \*\*(.+?)\*\*:\s*(.+?)\s*-->'
            for match in re.finditer(disabled_pattern, content, re.DOTALL):
                items.append(HeartbeatItem(
                    title=match.group(1).strip(),
                    description=match.group(2).strip(),
                    enabled=False,
                    raw_line=match.group(0)
                ))
            
            logger.debug(f"Parsed {len([i for i in items if i.enabled])} enabled heartbeat items")
            
        except Exception as e:
            logger.error(f"Failed to parse HEARTBEAT.md: {e}")
        
        return items
    
    # -------------------------------------------------------------------------
    # Condition Evaluation
    # -------------------------------------------------------------------------
    
    def is_within_active_hours(self) -> bool:
        """Check if current time is within configured active hours."""
        current_hour = datetime.now().hour
        return self.config.active_hours_start <= current_hour < self.config.active_hours_end
    
    def evaluate_condition(self, item: HeartbeatItem) -> Tuple[bool, str]:
        """
        Evaluate if a heartbeat item's condition is met.
        
        Returns:
            Tuple of (should_trigger, message)
        """
        description = item.description.lower()
        now = datetime.now()
        
        # Built-in condition handlers
        
        # Time-based: "If it's after Xpm" or "at Xpm"
        time_match = re.search(r'(?:after|at)\s+(\d{1,2})\s*(?:pm|am)?', description)
        if time_match:
            target_hour = int(time_match.group(1))
            if 'pm' in description and target_hour < 12:
                target_hour += 12
            
            if now.hour >= target_hour:
                return True, f"It's {now.strftime('%I:%M %p')}. {item.title}"
        
        # Duration-based: "working for X+ hours"
        duration_match = re.search(r'(\d+)\+?\s*hours?\s*(?:straight)?', description)
        if duration_match:
            # This would need session tracking - simplified for now
            # Could integrate with memory service to check last activity
            pass
        
        # End of day summary
        if 'end of day' in description or 'summary' in description:
            if now.hour == self.config.active_hours_end - 1:  # 1 hour before end
                return True, "End of day approaching. Would you like a summary?"
        
        # If using VLM for evaluation
        if self.config.use_vlm_for_decisions and self.vlm_client:
            return self._evaluate_with_vlm(item)
        
        return False, ""
    
    def _evaluate_with_vlm(self, item: HeartbeatItem) -> Tuple[bool, str]:
        """Use VLM to evaluate if a condition is met."""
        # This would send a lightweight prompt to the VLM
        # For now, return False to avoid unnecessary VLM calls
        return False, ""
    
    # -------------------------------------------------------------------------
    # Heartbeat Execution
    # -------------------------------------------------------------------------
    
    def run_heartbeat(self) -> str:
        """
        Execute a heartbeat check. Called on schedule.
        
        Returns:
            "HEARTBEAT_OK" if nothing needs attention, or a message describing actions taken.
        """
        self._heartbeat_count += 1
        self._last_heartbeat = datetime.now()
        
        logger.info(f"💓 Heartbeat #{self._heartbeat_count}")
        
        # Check active hours
        if not self.is_within_active_hours():
            logger.debug("Outside active hours, skipping heartbeat checks")
            return "HEARTBEAT_OK (outside active hours)"
        
        # Parse checklist
        items = self.parse_heartbeat_file()
        enabled_items = [i for i in items if i.enabled]
        
        if not enabled_items:
            logger.debug("No enabled heartbeat items")
            return "HEARTBEAT_OK (no items)"
        
        # Evaluate each item
        triggered_items = []
        for item in enabled_items:
            should_trigger, message = self.evaluate_condition(item)
            if should_trigger:
                triggered_items.append((item, message))
                logger.info(f"Heartbeat triggered: {item.title}")
        
        if not triggered_items:
            logger.debug("All checks passed, nothing needs attention")
            return "HEARTBEAT_OK"
        
        # Take action on triggered items
        actions_taken = []
        for item, message in triggered_items:
            action_result = self._take_action(item, message)
            actions_taken.append(action_result)
        
        return f"Heartbeat actions: {', '.join(actions_taken)}"
    
    def _take_action(self, item: HeartbeatItem, message: str) -> str:
        """Take action for a triggered heartbeat item."""
        # Send via Discord if available
        if self.discord_service:
            # Get primary user ID from config
            allowed_users = getattr(self.discord_service.config, 'allowed_users', set())
            if allowed_users:
                primary_user = next(iter(allowed_users))
                asyncio.run_coroutine_threadsafe(
                    self.discord_service.send_proactive_message(primary_user, message),
                    self.discord_service._loop
                )
                return f"Discord message: {item.title}"
        
        # Log to memory if Discord not available
        try:
            from .memory_service import get_memory_service
            memory = get_memory_service()
            memory.append_to_daily_log(f"Heartbeat: {message}", "system")
        except Exception:
            pass
        
        return f"Logged: {item.title}"
    
    # -------------------------------------------------------------------------
    # Background Loop
    # -------------------------------------------------------------------------
    
    def _heartbeat_loop(self):
        """Background thread loop that runs heartbeats on schedule."""
        interval_seconds = self.config.interval_minutes * 60
        
        logger.info(f"Heartbeat loop started (every {self.config.interval_minutes} minutes)")
        
        while not self._stop_event.is_set():
            try:
                result = self.run_heartbeat()
                logger.debug(f"Heartbeat result: {result}")
            except Exception as e:
                logger.error(f"Heartbeat error: {e}")
            
            # Wait for next interval (or stop signal)
            self._stop_event.wait(interval_seconds)
        
        logger.info("Heartbeat loop stopped")
    
    # -------------------------------------------------------------------------
    # Lifecycle
    # -------------------------------------------------------------------------
    
    def set_dependencies(
        self,
        task_queue=None,
        discord_service=None,
        orchestrator=None,
        vlm_client=None,
    ):
        """Set external dependencies."""
        if task_queue:
            self.task_queue = task_queue
        if discord_service:
            self.discord_service = discord_service
        if orchestrator:
            self.orchestrator = orchestrator
        if vlm_client:
            self.vlm_client = vlm_client
    
    def start(self) -> bool:
        """Start the heartbeat service in a background thread."""
        if not self.config.enabled:
            logger.info("Heartbeat service disabled")
            return False
        
        if self._running:
            return True
        
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._heartbeat_loop, daemon=True)
        self._thread.start()
        self._running = True
        
        logger.info("Heartbeat service started")
        return True
    
    def stop(self):
        """Stop the heartbeat service."""
        if not self._running:
            return
        
        self._running = False
        self._stop_event.set()
        
        if self._thread:
            self._thread.join(timeout=5)
        
        logger.info("Heartbeat service stopped")
    
    def trigger_now(self) -> str:
        """Manually trigger a heartbeat (for testing)."""
        return self.run_heartbeat()


def load_heartbeat_config(config: dict) -> HeartbeatConfig:
    """Load heartbeat configuration from settings dict."""
    hb_cfg = config.get("heartbeat", {})
    
    return HeartbeatConfig(
        enabled=hb_cfg.get("enabled", False),  # Disabled by default
        interval_minutes=hb_cfg.get("interval_minutes", 30),
        active_hours_start=hb_cfg.get("active_hours_start", 9),
        active_hours_end=hb_cfg.get("active_hours_end", 23),
        use_vlm_for_decisions=hb_cfg.get("use_vlm_for_decisions", False),
    )


def init_heartbeat_service(config: dict, status_server=None) -> Optional[HeartbeatService]:
    """Initialize heartbeat service from config."""
    try:
        hb_config = load_heartbeat_config(config)
        if not hb_config.enabled:
            logger.info("Heartbeat service disabled in config")
            return None
        
        service = HeartbeatService(hb_config, status_server=status_server)
        return service
    except Exception as e:
        logger.error(f"Failed to initialize heartbeat service: {e}")
        return None
