"""
Main orchestrator for Qwen3-VL Computer Control System.

Enhanced capture -> analyze -> act loop with:
- Screen stability detection (waits for UI to settle)
- Semantic action tracking (prevents loops)
- Action history injection into prompts
- Enhanced debug logging for troubleshooting
"""

import logging
import time
import re
from dataclasses import dataclass
from typing import Any, List, Optional, Dict, Tuple

from .actions import Action, ActionExecutor, create_action_from_dict
from .capture import ScreenCapture
from .inference import VLMClient
from .prompts import plan_action_prompt, recovery_prompt
from .screen_stability import wait_for_ready
from .debug_logger import DebugLogger, get_debug_logger
from .window_manager import get_active_window_context


@dataclass
class TaskResult:
    success: bool
    message: str
    steps_taken: int
    duration_seconds: float = 0.0
    error: Optional[str] = None


@dataclass
class ActionRecord:
    """Record of an action for history tracking."""
    action_type: str
    target: str
    x: Optional[int] = None
    y: Optional[int] = None
    result: str = "executed"  # executed, failed, or skipped
    
    def to_history_str(self) -> str:
        coords = f" at ({self.x}, {self.y})" if self.x is not None else ""
        return f"{self.action_type}: {self.target}{coords} -> {self.result}"


class Orchestrator:
    def __init__(
        self,
        vlm_client: VLMClient,
        screen_capture: ScreenCapture,
        action_executor: ActionExecutor,
        max_iterations: int = 10,
        ui_settle_seconds: float = 1.5,
        click_offset_x: int = 0,
        click_offset_y: int = 0,
        logger: Optional[logging.Logger] = None,
        status_server: Any = None,
        # Screen stability settings
        screen_stability_enabled: bool = True,
        screen_stability_max_wait: float = 3.0,
        # Debug settings
        debug_enabled: bool = True,
    ):
        self.vlm = vlm_client
        self.capture = screen_capture
        self.executor = action_executor
        self.max_iterations = max_iterations
        self.ui_settle_seconds = ui_settle_seconds
        self.click_offset_x = click_offset_x
        self.click_offset_y = click_offset_y
        self.logger = logger or logging.getLogger(__name__)
        self.server = status_server
        self.aborted = False
        
        # Screen stability settings
        self.screen_stability_enabled = screen_stability_enabled
        self.screen_stability_max_wait = screen_stability_max_wait
        
        # Enhanced action tracking for semantic loop detection
        self._action_history: List[ActionRecord] = []
        self._last_error: Optional[str] = None
        
        # Debug logger
        self.debug_enabled = debug_enabled
        self._debug: Optional[DebugLogger] = None
        if debug_enabled:
            try:
                self._debug = get_debug_logger()
            except Exception as e:
                self.logger.warning(f"Could not initialize debug logger: {e}")
        
        # Voice service reference for continuous listening
        self._voice_service = None
        
        # Memory service reference for persistent context
        self.memory_service = None
        
        # Pause/resume state
        self._paused = False
        self._skip_requested = False
        self._retry_requested = False

    def abort(self):
        self.aborted = True
        self._paused = False  # Clear pause on abort
    
    def set_voice_service(self, voice_service):
        """Set voice service reference for bidirectional communication."""
        self._voice_service = voice_service
    
    def pause(self):
        """Pause the current task execution."""
        if not self._paused:
            self._paused = True
            self.logger.info("Task PAUSED by user")
            if self.server:
                self.server.emit_status("PAUSED", "Paused by user")
                self.server.emit_thought("⏸️ Paused. Say 'resume' or 'continue' to proceed.")
    
    def resume(self):
        """Resume a paused task."""
        if self._paused:
            self._paused = False
            self.logger.info("Task RESUMED by user")
            if self.server:
                self.server.emit_status("RUNNING", "Resumed by user")
                self.server.emit_thought("▶️ Resuming...")
    
    def skip_step(self):
        """Skip the current step and move to the next one."""
        self._skip_requested = True
        self.logger.info("Step SKIP requested")
        if self.server:
            self.server.emit_thought("⏭️ Skipping current step...")
    
    def retry_last(self):
        """Retry the last action."""
        self._retry_requested = True
        self.logger.info("RETRY requested")
        if self.server:
            self.server.emit_thought("🔄 Retrying last action...")
    
    def inject_context(self, text: str):
        """
        Inject additional context into the current task.
        Called by voice service to add mid-task commands.
        The injected text will be included in the next VLM prompt.
        """
        if not hasattr(self, '_injected_context'):
            self._injected_context = []
        self._injected_context.append(text)
        self.logger.info(f"Context injected: {text}")
        if self.server:
            self.server.emit_thought(f"🎤 Heard: {text[:50]}...")

    def execute_task(self, task: str) -> TaskResult:
        self.logger.info(f"Starting task: {task}")
        self.aborted = False
        self._paused = False
        self._skip_requested = False
        self._action_history.clear()
        self._last_error = None
        start_time = time.time()

        # Notify voice service we are busy (enables continuous listening)
        if self._voice_service:
            self._voice_service.set_agent_busy(True)

        if self.server:
            self.server.emit_status("RUNNING", f"Task: {task}")
        
        try:
            # True physical screen size (primary monitor) used for click execution
            screen_w, screen_h = self.capture.get_screen_size()
            
            for i in range(self.max_iterations):
                # Check for abort
                if self.aborted:
                    if self.server:
                        self.server.emit_status("ABORTED", "Task aborted")
                        self.server.emit_thought("Aborted.")
                    return TaskResult(False, "Aborted", i, time.time() - start_time, "Aborted")
                
                # Handle pause (blocking wait)
                while self._paused and not self.aborted:
                    time.sleep(0.1)
                
                # Handle skip request (move to next iteration without action)
                if self._skip_requested:
                    self._skip_requested = False
                    self.logger.info(f"Skipping step {i + 1}")
                    continue
                
                step_num = i + 1
                self.logger.info(f"Step {step_num}")
                
                # Debug: Log step start
                if self._debug:
                    self._debug.log_step_start(step_num, task)
                
                # Capture
                capture_start = time.time()
                image = self.capture.capture_screen()
                image_b64 = self.capture.get_base64_from_image(image)
                w, h = image.size  # image size (may be downscaled from screen_w/screen_h)
                capture_time = (time.time() - capture_start) * 1000
                
                # Debug: Log capture
                if self._debug:
                    self._debug.log_screen_capture(w, h, capture_time)
                
                # Update overlay with current view
                if self.server:
                    self.server.emit_frame(image_b64)
                
                # Analyze - Build rich context for VLM
                context_lines = [f"Screen: {w}x{h}", f"Step: {step_num}/{self.max_iterations}"]
                
                # Add active window context for better screen understanding
                try:
                    window_context = get_active_window_context()
                    context_lines.append(window_context)
                except Exception as e:
                    self.logger.debug(f"Could not get window context: {e}")
                
                if self._last_error:
                    context_lines.append(f"⚠️ Previous issue: {self._last_error}")
                
                # Include voice-injected context (mid-task guidance)
                if hasattr(self, '_injected_context') and self._injected_context:
                    for injected in self._injected_context:
                        context_lines.append(f"🎤 User: {injected}")
                    self._injected_context.clear()
                    
                context = "\n".join(context_lines)
                
                # Build action history string for the prompt
                action_history = ""
                if self._action_history:
                    recent = self._action_history[-5:]  # Last 5 actions
                    action_history = "\n".join(f"- {a.to_history_str()}" for a in recent)
                
                prompt = plan_action_prompt(task, context, action_history)
                
                # Debug: Log VLM request
                if self._debug:
                    self._debug.log_vlm_request(prompt[:200], has_image=True)
                
                vlm_start = time.time()
                response = self.vlm.send_request(prompt, image_base64=image_b64)
                vlm_time = (time.time() - vlm_start) * 1000
                
                if not response.success:
                    # Check if this was an abort
                    if response.error == "Aborted" or self.aborted:
                        if self.server:
                            self.server.emit_status("ABORTED", "Task aborted")
                            self.server.emit_thought("Aborted.")
                        return TaskResult(False, "Aborted", i, time.time() - start_time, "Aborted")
                    
                    self.logger.error("VLM failed")
                    self._last_error = response.error or "VLM request failed"
                    continue
                
                # Debug: Log raw VLM response
                if self._debug:
                    self._debug.log_vlm_response(response.raw_text, vlm_time)
                
                # Parse observation and reasoning from VLM response
                observation_match = re.search(r"<observation>(.*?)</observation>", response.raw_text, re.DOTALL)
                reasoning_match = re.search(r"<reasoning>(.*?)</reasoning>", response.raw_text, re.DOTALL)
                
                display_text = ""
                if observation_match:
                    observation = observation_match.group(1).strip()
                    self.logger.info(f"👁️ Observation:\n{observation}")
                    display_text = observation[:150] + "..."
                    # Debug: Log observation
                    if self._debug:
                        self._debug.log_observation(observation)
                
                if reasoning_match:
                    reasoning = reasoning_match.group(1).strip()
                    self.logger.info(f"🧠 Reasoning:\n{reasoning}")
                    if display_text:
                        display_text += "\n" + reasoning[:100]
                    else:
                        display_text = reasoning[:200] + "..."
                    # Debug: Log reasoning
                    if self._debug:
                        self._debug.log_reasoning(reasoning)
                
                if self.server and display_text:
                    self.server.emit_thought(display_text)

                result: Optional[Dict[str, Any]] = response.parsed_json
                if not result:
                    self.logger.error("Invalid JSON from VLM; skipping this step.")
                    self.logger.error(f"Raw response was:\n{response.raw_text[:500]}")
                    self._last_error = "Model did not return valid JSON for an action."
                    continue
                
                # Debug: Log planned action
                if self._debug:
                    self._debug.log_action_planned(result)
                    
                self.logger.info(f"Plan: {result.get('thought')}")
                
                if result.get("task_complete"):
                    if self.server:
                        self.server.emit_status("DONE", "Task complete")
                        self.server.emit_thought("Done.")
                    # Debug: Log completion
                    if self._debug:
                        self._debug.log_task_complete(True, step_num, time.time() - start_time)
                    
                    # Log to persistent memory
                    duration = time.time() - start_time
                    if self.memory_service:
                        try:
                            self.memory_service.log_task(task, "Success", step_num, duration)
                        except Exception as e:
                            self.logger.debug(f"Memory log failed: {e}")
                    
                    return TaskResult(True, "Complete", step_num, duration, None)
                
                # Act
                record = None
                try:
                    action = create_action_from_dict(result)
                    
                    # Store original normalized coords for debug logging
                    orig_x, orig_y = action.x, action.y
                    
                    # Convert VLM's normalized [0-1000] coordinates to actual screen pixels
                    from .coordinates import normalized_to_pixels
                    if action.x is not None and action.y is not None:
                        px_x, px_y = normalized_to_pixels(action.x, action.y, screen_w, screen_h)
                        action.x = px_x + self.click_offset_x
                        action.y = px_y + self.click_offset_y
                        
                        # Debug: Log coordinate conversion
                        if self._debug:
                            self._debug.log_coordinate_conversion(
                                orig_x, orig_y,
                                action.x, action.y,
                                screen_w, screen_h
                            )
                    
                    if action.end_x is not None and action.end_y is not None:
                        end_px_x, end_px_y = normalized_to_pixels(action.end_x, action.end_y, screen_w, screen_h)
                        action.end_x = end_px_x + self.click_offset_x
                        action.end_y = end_px_y + self.click_offset_y
                    
                    if (self.click_offset_x != 0 or self.click_offset_y != 0) and action.x is not None:
                        self.logger.debug(f"Applied offset ({self.click_offset_x:+d}, {self.click_offset_y:+d}) -> final coords: ({action.x}, {action.y})")
                    
                    # Update overlay with action
                    if self.server:
                        self.server.emit_action(action.action_type.value, action.target_description)
                    
                    # Create action record for history
                    record = ActionRecord(
                        action_type=action.action_type.value,
                        target=action.target_description or "unknown",
                        x=action.x,
                        y=action.y,
                        result="pending"
                    )
                    
                    # Aggressive semantic loop detection - triggers after just 1 repeat
                    # Check for repeated action_type + target combinations
                    if len(self._action_history) >= 1:
                        last_action = self._action_history[-1]
                        if last_action.action_type == record.action_type and last_action.target == record.target:
                            # Count how many times this exact action has been repeated
                            repeat_count = 1
                            for prev in reversed(self._action_history):
                                if prev.action_type == record.action_type and prev.target == record.target:
                                    repeat_count += 1
                                else:
                                    break
                            
                            self.logger.warning(
                                f"Detected repeating '{record.action_type}' on '{record.target}' "
                                f"({repeat_count} times) - forcing strategy change"
                            )
                            # Debug: Log loop detection
                            if self._debug:
                                self._debug.log_loop_detection(record.action_type, record.target, repeat_count)
                            
                            # Use recovery prompt for aggressive intervention
                            failed_action = f"{record.action_type} on {record.target}"
                            self._last_error = recovery_prompt(failed_action, repeat_count)
                    
                    # Debug: Log action execution
                    if self._debug:
                        self._debug.log_action_execution(
                            action.action_type.value,
                            action.target_description or "unknown",
                            action.x,
                            action.y
                        )
                    
                    # Execute the action
                    self.executor.execute(action)
                    record.result = "executed"
                    self._action_history.append(record)
                    
                    # Keep history bounded
                    if len(self._action_history) > 10:
                        self._action_history.pop(0)
                    
                    # Clear last_error on successful execution
                    self._last_error = None
                    
                except Exception as e:
                    self.logger.error(f"Action failed: {e}")
                    # Debug: Log error
                    if self._debug:
                        self._debug.log_action_error(
                            record.action_type if record else "UNKNOWN",
                            str(e)
                        )
                    # Record the failure
                    if record:
                        record.result = f"failed: {str(e)[:50]}"
                        self._action_history.append(record)
                    # Surface the failure reason back into the next-step prompt.
                    self._last_error = str(e)

                # Wait for screen to stabilize before next capture
                if self.screen_stability_enabled:
                    stability_start = time.time()
                    ready, reason = wait_for_ready(
                        self.capture,
                        max_wait=self.screen_stability_max_wait,
                        logger=self.logger
                    )
                    stability_time = time.time() - stability_start
                    
                    # Debug: Log stability check
                    if self._debug:
                        self._debug.log_screen_stability(ready, stability_time, reason)
                    
                    if not ready:
                        self.logger.warning(f"Screen stability: {reason}")
                else:
                    # Fallback to fixed delay
                    time.sleep(self.ui_settle_seconds)
            
            # After for loop exits (max iterations reached)
            # Debug: Log task failure
            if self._debug:
                self._debug.log_task_complete(False, self.max_iterations, time.time() - start_time)
            
            # Log failure to persistent memory
            duration = time.time() - start_time
            if self.memory_service:
                try:
                    self.memory_service.log_task(task, "Failed (max steps)", self.max_iterations, duration)
                except Exception as e:
                    self.logger.debug(f"Memory log failed: {e}")
                
            if self.server:
                self.server.emit_status("ERROR", "Max steps reached")
                self.server.emit_thought("Stopped: max steps reached.")
            return TaskResult(False, "Max steps reached", self.max_iterations, duration, "Max steps reached")
        finally:
            # Always notify voice service we're done (disables continuous listening)
            if self._voice_service:
                self._voice_service.set_agent_busy(False)

            # ── Always reset to idle so system is fresh for the next task ──
            self.aborted = False
            self._paused = False
            self._skip_requested = False
            self._retry_requested = False

            # Short delay then emit idle — lets the DONE/ABORTED status
            # display briefly on clients before switching to idle
            import threading
            def _auto_idle():
                time.sleep(3)
                if self.server:
                    self.server.emit_status("idle", None)
            threading.Thread(target=_auto_idle, daemon=True).start()
