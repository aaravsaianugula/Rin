"""
Debug logging utilities for the Rin agent.

Provides detailed logging of agent thoughts, actions, and mouse position tracking.
"""

import logging
import time
import os
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List
import pyautogui


class DebugLogger:
    """Enhanced debug logger for agent activity."""
    
    def __init__(
        self,
        log_dir: str = "logs",
        log_level: int = logging.DEBUG,
        track_mouse: bool = True,
        save_screenshots: bool = False
    ):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(exist_ok=True)
        
        self.track_mouse = track_mouse
        self.save_screenshots = save_screenshots
        
        # Create session-specific log file
        self.session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.session_log = self.log_dir / f"debug_{self.session_id}.log"
        
        # Configure file logger
        self.logger = logging.getLogger(f"rin_debug_{self.session_id}")
        self.logger.setLevel(log_level)
        
        # File handler with detailed formatting
        fh = logging.FileHandler(self.session_log, encoding='utf-8')
        fh.setLevel(log_level)
        fh.setFormatter(logging.Formatter(
            '%(asctime)s.%(msecs)03d | %(levelname)-8s | %(message)s',
            datefmt='%H:%M:%S'
        ))
        self.logger.addHandler(fh)
        
        # Console handler for important messages
        ch = logging.StreamHandler()
        ch.setLevel(logging.INFO)
        ch.setFormatter(logging.Formatter(
            '🔍 %(message)s'
        ))
        self.logger.addHandler(ch)
        
        self.step_count = 0
        self.action_log: List[Dict[str, Any]] = []
        
        self.logger.info(f"=== Debug session started: {self.session_id} ===")
        self.logger.info(f"Log file: {self.session_log}")
    
    def log_step_start(self, step: int, task: str):
        """Log the start of a new step."""
        self.step_count = step
        self.logger.info(f"")
        self.logger.info(f"{'='*60}")
        self.logger.info(f"STEP {step}: {task[:80]}")
        self.logger.info(f"{'='*60}")
        
        if self.track_mouse:
            mx, my = pyautogui.position()
            self.logger.debug(f"Mouse position at step start: ({mx}, {my})")
    
    def log_screen_capture(self, width: int, height: int, capture_time_ms: float):
        """Log screen capture details."""
        self.logger.debug(f"📷 Screen captured: {width}x{height} in {capture_time_ms:.1f}ms")
    
    def log_vlm_request(self, prompt_preview: str, has_image: bool):
        """Log VLM request details."""
        self.logger.debug(f"🤖 VLM Request:")
        self.logger.debug(f"   Image attached: {has_image}")
        self.logger.debug(f"   Prompt preview: {prompt_preview[:200]}...")
    
    def log_vlm_response(self, raw_text: str, parse_time_ms: float):
        """Log raw VLM response."""
        self.logger.info(f"📝 VLM Response ({parse_time_ms:.0f}ms):")
        
        # Log the full response for debugging
        for line in raw_text.split('\n'):
            self.logger.debug(f"   | {line}")
    
    def log_observation(self, observation: str):
        """Log what the agent observed on screen."""
        self.logger.info(f"👁️ OBSERVATION:")
        for line in observation.strip().split('\n'):
            self.logger.info(f"   {line.strip()}")
    
    def log_reasoning(self, reasoning: str):
        """Log agent's reasoning process."""
        self.logger.info(f"🧠 REASONING:")
        for line in reasoning.strip().split('\n'):
            self.logger.info(f"   {line.strip()}")
    
    def log_action_planned(self, action_dict: Dict[str, Any]):
        """Log the planned action before execution."""
        self.logger.info(f"📋 PLANNED ACTION:")
        self.logger.info(f"   Action: {action_dict.get('action', 'UNKNOWN')}")
        self.logger.info(f"   Target: {action_dict.get('target', 'N/A')}")
        
        coords = action_dict.get('coordinates', {})
        if coords:
            self.logger.info(f"   Coords (normalized): ({coords.get('x')}, {coords.get('y')})")
        
        if action_dict.get('text'):
            self.logger.info(f"   Text: '{action_dict.get('text')}'")
        if action_dict.get('key'):
            self.logger.info(f"   Key: {action_dict.get('key')}")
        if action_dict.get('keys'):
            self.logger.info(f"   Keys: {action_dict.get('keys')}")
        
        self.logger.info(f"   Thought: {action_dict.get('thought', 'N/A')}")
    
    def log_coordinate_conversion(
        self,
        norm_x: int, norm_y: int,
        pixel_x: int, pixel_y: int,
        screen_w: int, screen_h: int
    ):
        """Log coordinate conversion from normalized to pixels."""
        self.logger.debug(
            f"📍 Coordinate conversion: "
            f"({norm_x}, {norm_y}) → ({pixel_x}, {pixel_y}) "
            f"on {screen_w}x{screen_h} screen"
        )
    
    def log_action_execution(
        self,
        action_type: str,
        target: str,
        pixel_x: Optional[int],
        pixel_y: Optional[int],
        success: bool = True
    ):
        """Log action execution with pixel coordinates."""
        status = "✅" if success else "❌"
        
        coord_str = f"at pixel ({pixel_x}, {pixel_y})" if pixel_x is not None else ""
        self.logger.info(f"{status} EXECUTING: {action_type} on '{target}' {coord_str}")
        
        if self.track_mouse and pixel_x is not None:
            # Log actual mouse position after action
            time.sleep(0.05)  # Brief delay to let mouse settle
            actual_x, actual_y = pyautogui.position()
            self.logger.debug(f"   Mouse now at: ({actual_x}, {actual_y})")
            
            # Check for discrepancy
            if pixel_x is not None and pixel_y is not None:
                dx = abs(actual_x - pixel_x)
                dy = abs(actual_y - pixel_y)
                if dx > 5 or dy > 5:
                    self.logger.warning(
                        f"   ⚠️ Mouse position mismatch! "
                        f"Expected ({pixel_x}, {pixel_y}), got ({actual_x}, {actual_y})"
                    )
        
        # Record action for later analysis
        self.action_log.append({
            'step': self.step_count,
            'action': action_type,
            'target': target,
            'pixel_x': pixel_x,
            'pixel_y': pixel_y,
            'success': success,
            'timestamp': time.time()
        })
    
    def log_action_error(self, action_type: str, error: str):
        """Log action execution error."""
        self.logger.error(f"❌ ACTION FAILED: {action_type}")
        self.logger.error(f"   Error: {error}")
    
    def log_screen_stability(self, stable: bool, wait_time: float, reason: str):
        """Log screen stability check result."""
        status = "stable" if stable else "unstable"
        self.logger.debug(f"⏳ Screen {status} after {wait_time:.2f}s: {reason}")
    
    def log_loop_detection(self, action_type: str, target: str, count: int):
        """Log when loop detection triggers."""
        self.logger.warning(
            f"🔄 LOOP DETECTED: '{action_type}' on '{target}' repeated {count} times"
        )
    
    def log_task_complete(self, success: bool, steps: int, duration: float):
        """Log task completion."""
        status = "SUCCESS" if success else "FAILED"
        self.logger.info(f"")
        self.logger.info(f"{'='*60}")
        self.logger.info(f"TASK {status} after {steps} steps in {duration:.1f}s")
        self.logger.info(f"{'='*60}")
        
        # Summary of actions
        self.logger.info(f"Action summary:")
        action_counts = {}
        for a in self.action_log:
            action_counts[a['action']] = action_counts.get(a['action'], 0) + 1
        for action, count in action_counts.items():
            self.logger.info(f"   {action}: {count}")
    
    def get_session_log_path(self) -> str:
        """Get path to current session log file."""
        return str(self.session_log)


# Global debug logger instance
_debug_logger: Optional[DebugLogger] = None


def get_debug_logger() -> DebugLogger:
    """Get or create the global debug logger."""
    global _debug_logger
    if _debug_logger is None:
        _debug_logger = DebugLogger()
    return _debug_logger


def set_debug_logger(logger: DebugLogger):
    """Set a custom debug logger."""
    global _debug_logger
    _debug_logger = logger
