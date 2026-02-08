"""
Action executor module for Qwen3-VL Computer Control System.

Wraps PyAutoGUI with safety checks, coordinate validation,
and configurable delays.
"""

import logging
import time
from dataclasses import dataclass
from enum import Enum
from typing import List, Optional, Tuple, Union

import pyautogui

from .coordinates import validate_pixel_coordinates, clamp_to_screen
from .server import StatusServer


# Configure PyAutoGUI safety settings
pyautogui.FAILSAFE = True  # Move mouse to corner to abort
pyautogui.PAUSE = 0.01  # Minimum pause


class ActionType(Enum):
    """Supported action types."""
    # Mouse actions
    CLICK = "CLICK"
    DOUBLE_CLICK = "DOUBLE_CLICK"
    RIGHT_CLICK = "RIGHT_CLICK"
    TRIPLE_CLICK = "TRIPLE_CLICK"  # Select entire line
    MOVE = "MOVE"
    DRAG = "DRAG"
    SCROLL = "SCROLL"
    
    # Keyboard actions
    TYPE = "TYPE"
    PRESS = "PRESS"
    HOTKEY = "HOTKEY"
    
    # Clipboard actions
    COPY = "COPY"           # Ctrl+C
    PASTE = "PASTE"         # Ctrl+V
    CUT = "CUT"             # Ctrl+X
    SELECT_ALL = "SELECT_ALL"  # Ctrl+A
    
    # Window management
    FOCUS_WINDOW = "FOCUS_WINDOW"
    MINIMIZE = "MINIMIZE"
    MAXIMIZE = "MAXIMIZE"
    CLOSE_WINDOW = "CLOSE_WINDOW"
    
    # Application control
    LAUNCH_APP = "LAUNCH_APP"
    OPEN_URL = "OPEN_URL"
    
    # Control flow
    WAIT = "WAIT"


@dataclass
class Action:
    """Represents an action to be executed."""
    action_type: ActionType
    x: Optional[int] = None
    y: Optional[int] = None
    text: Optional[str] = None
    key: Optional[str] = None
    keys: Optional[List[str]] = None
    scroll_amount: Optional[int] = None
    end_x: Optional[int] = None
    end_y: Optional[int] = None
    duration: Optional[float] = None
    confidence: float = 1.0
    target_description: str = ""
    thought: str = ""


class ActionError(Exception):
    """Raised when an action cannot be executed."""
    pass


class ActionExecutor:
    """
    Executes mouse and keyboard actions with safety checks.
    
    All coordinate parameters are expected to be in pixel values.
    Use the coordinates module to convert from normalized coordinates first.
    """
    
    def __init__(
        self,
        screen_width: int,
        screen_height: int,
        confidence_threshold: float = 0.8,
        action_delay: float = 0.5,
        pause_before_action: float = 0.1,
        failsafe_enabled: bool = True,
        logger: Optional[logging.Logger] = None,
        status_server: Optional[StatusServer] = None
    ):
        """
        Initialize the action executor.
        
        Args:
            screen_width: Screen width in pixels
            screen_height: Screen height in pixels
            confidence_threshold: Minimum confidence to execute (0.0-1.0)
            action_delay: Delay between actions in seconds
            pause_before_action: Pause before each action for human override
            failsafe_enabled: Enable PyAutoGUI failsafe (corner abort)
            logger: Optional logger instance
            status_server: Optional status server for overlay
        """
        self.screen_width = screen_width
        self.screen_height = screen_height
        self.confidence_threshold = confidence_threshold
        self.action_delay = action_delay
        self.pause_before_action = pause_before_action
        self.logger = logger or logging.getLogger(__name__)
        self.server = status_server
        
        # Configure PyAutoGUI
        pyautogui.FAILSAFE = failsafe_enabled
        pyautogui.PAUSE = pause_before_action
        
        self.action_history: List[Action] = []
    
    def _validate_coordinates(self, x: int, y: int) -> Tuple[int, int]:
        """Validate and optionally clamp coordinates to screen bounds."""
        if x is None or y is None:
            raise ActionError("Missing coordinates for action requiring them")
            
        if not validate_pixel_coordinates(x, y, self.screen_width, self.screen_height):
            cx, cy = clamp_to_screen(x, y, self.screen_width, self.screen_height)
            self.logger.warning(
                f"Coordinates ({x}, {y}) out of bounds for screen "
                f"({self.screen_width}x{self.screen_height}). "
                f"Clamping to ({cx}, {cy})."
            )
            return (cx, cy)
        return (x, y)
    
    def _check_confidence(self, action: Action) -> bool:
        """Check if action confidence meets threshold."""
        if action.confidence < self.confidence_threshold:
            self.logger.warning(
                f"Action confidence {action.confidence:.2f} below threshold "
                f"{self.confidence_threshold:.2f}. Skipping action."
            )
            return False
        return True
    
    def _log_action(self, action: Action):
        """Log action to history and logger."""
        self.action_history.append(action)
        self.logger.info(
            f"Executing {action.action_type.value}: "
            f"target='{action.target_description}' "
            f"coords=({action.x}, {action.y}) "
            f"confidence={action.confidence:.2f}"
        )
        
        if self.server:
            self.server.emit_action(action.action_type.value, action.target_description)
    
    def _post_action_delay(self):
        """Wait after action for UI to respond."""
        time.sleep(self.action_delay)
    
    def execute(self, action: Action) -> bool:
        """
        Execute an action.
        
        Args:
            action: Action to execute
        
        Returns:
            True if action was executed, False if skipped
        
        Raises:
            ActionError: If action execution fails
        """
        if not self._check_confidence(action):
            return False
        
        self._log_action(action)
        
        try:
            if action.action_type == ActionType.CLICK:
                return self.click(action.x, action.y)
            elif action.action_type == ActionType.DOUBLE_CLICK:
                return self.double_click(action.x, action.y)
            elif action.action_type == ActionType.RIGHT_CLICK:
                return self.right_click(action.x, action.y)
            elif action.action_type == ActionType.TYPE:
                return self.type_text(action.text, action.x, action.y)
            elif action.action_type == ActionType.PRESS:
                return self.press_key(action.key)
            elif action.action_type == ActionType.HOTKEY:
                return self.hotkey(action.keys)
            elif action.action_type == ActionType.SCROLL:
                return self.scroll(action.scroll_amount, action.x, action.y)
            elif action.action_type == ActionType.DRAG:
                return self.drag(action.x, action.y, action.end_x, action.end_y, action.duration)
            elif action.action_type == ActionType.WAIT:
                return self.wait(action.duration)
            elif action.action_type == ActionType.MOVE:
                return self.move(action.x, action.y)
            # New action types
            elif action.action_type == ActionType.TRIPLE_CLICK:
                return self.triple_click(action.x, action.y)
            elif action.action_type == ActionType.COPY:
                return self.copy()
            elif action.action_type == ActionType.PASTE:
                return self.paste()
            elif action.action_type == ActionType.CUT:
                return self.cut()
            elif action.action_type == ActionType.SELECT_ALL:
                return self.select_all()
            elif action.action_type == ActionType.FOCUS_WINDOW:
                return self.focus_window(action.target_description or action.text)
            elif action.action_type == ActionType.MINIMIZE:
                return self.minimize_window()
            elif action.action_type == ActionType.MAXIMIZE:
                return self.maximize_window()
            elif action.action_type == ActionType.CLOSE_WINDOW:
                return self.close_window()
            elif action.action_type == ActionType.LAUNCH_APP:
                return self.launch_app(action.text or action.target_description)
            elif action.action_type == ActionType.OPEN_URL:
                return self.open_url(action.text)
            else:
                raise ActionError(f"Unknown action type: {action.action_type}")
        except pyautogui.FailSafeException:
            self.logger.error("FAILSAFE TRIGGERED - Mouse moved to corner. Aborting.")
            raise ActionError("Failsafe triggered")
    
    def click(self, x: int, y: int) -> bool:
        """
        Perform a single left click.
        
        Args:
            x: Pixel X coordinate
            y: Pixel Y coordinate
        
        Returns:
            True on success
        """
        x, y = self._validate_coordinates(x, y)
        # Direct click - no redundant moveTo; pyautogui.click already moves
        pyautogui.click(x, y)
        self._post_action_delay()
        return True
    
    def double_click(self, x: int, y: int) -> bool:
        """
        Perform a double left click.
        
        Args:
            x: Pixel X coordinate
            y: Pixel Y coordinate
        
        Returns:
            True on success
        """
        x, y = self._validate_coordinates(x, y)
        pyautogui.doubleClick(x, y)
        self._post_action_delay()
        return True
    
    def right_click(self, x: int, y: int) -> bool:
        """
        Perform a right click.
        
        Args:
            x: Pixel X coordinate
            y: Pixel Y coordinate
        
        Returns:
            True on success
        """
        x, y = self._validate_coordinates(x, y)
        pyautogui.rightClick(x, y)
        self._post_action_delay()
        return True
    
    def type_text(self, text: str, x: Optional[int] = None, y: Optional[int] = None, interval: float = 0.01) -> bool:
        """
        Type text using keyboard, optionally clicking first at (x, y).
        
        Args:
            text: Text to type
            x: Optional Pixel X coordinate to click first
            y: Optional Pixel Y coordinate to click first
            interval: Delay between keystrokes
        
        Returns:
            True on success
        """
        if not text:
            self.logger.warning("Empty text provided to type_text")
            return False
            
        if x is not None and y is not None:
            self.click(x, y)
            time.sleep(0.15)  # Brief wait for focus (reduced from 0.75s)
        
        pyautogui.write(text, interval=interval)
        self._post_action_delay()
        return True
    
    def press_key(self, key: str) -> bool:
        """
        Press a special key.
        
        Args:
            key: Key name (enter, esc, tab, space, backspace, etc.)
        
        Returns:
            True on success
        """
        if not key:
            self.logger.warning("Empty key provided to press_key")
            return False
        
        pyautogui.press(key)
        self._post_action_delay()
        return True
    
    def hotkey(self, keys: List[str]) -> bool:
        """
        Press a keyboard shortcut.
        
        Args:
            keys: List of keys to press together (e.g., ['ctrl', 'c'])
        
        Returns:
            True on success
        """
        if not keys:
            self.logger.warning("Empty keys provided to hotkey")
            return False
        
        pyautogui.hotkey(*keys)
        self._post_action_delay()
        return True
    
    def scroll(self, clicks: int, x: Optional[int] = None, y: Optional[int] = None) -> bool:
        """
        Scroll the mouse wheel.
        
        Args:
            clicks: Number of scroll clicks (positive=up, negative=down)
            x: Optional X coordinate to scroll at
            y: Optional Y coordinate to scroll at
        
        Returns:
            True on success
        """
        if x is not None and y is not None:
            x, y = self._validate_coordinates(x, y)
            pyautogui.scroll(clicks, x, y)
        else:
            pyautogui.scroll(clicks)
        
        self._post_action_delay()
        return True
    
    def drag(
        self, 
        start_x: int, 
        start_y: int, 
        end_x: int, 
        end_y: int, 
        duration: float = 0.5
    ) -> bool:
        """
        Click and drag from start to end position.
        
        Args:
            start_x: Starting X coordinate
            start_y: Starting Y coordinate
            end_x: Ending X coordinate
            end_y: Ending Y coordinate
            duration: Drag duration in seconds
        
        Returns:
            True on success
        """
        start_x, start_y = self._validate_coordinates(start_x, start_y)
        end_x, end_y = self._validate_coordinates(end_x, end_y)
        
        # Move to start position
        pyautogui.moveTo(start_x, start_y)
        
        # Calculate delta
        dx = end_x - start_x
        dy = end_y - start_y
        
        # Perform drag
        pyautogui.drag(dx, dy, duration=duration)
        self._post_action_delay()
        return True
    
    def move(self, x: int, y: int, duration: float = 0.25) -> bool:
        """
        Move mouse to position without clicking.
        
        Args:
            x: Target X coordinate
            y: Target Y coordinate
            duration: Movement duration
        
        Returns:
            True on success
        """
        x, y = self._validate_coordinates(x, y)
        pyautogui.moveTo(x, y, duration=duration)
        return True
    
    def wait(self, seconds: float) -> bool:
        """
        Pause execution.
        
        Args:
            seconds: Duration to wait
        
        Returns:
            True on success
        """
        if seconds <= 0:
            return True
        
        time.sleep(seconds)
        return True
    
    def get_mouse_position(self) -> Tuple[int, int]:
        """Get current mouse position."""
        return pyautogui.position()
    
    def get_action_history(self) -> List[Action]:
        """Get list of executed actions."""
        return self.action_history.copy()
    
    def clear_history(self):
        """Clear action history."""
        self.action_history.clear()
    
    def triple_click(self, x: int, y: int) -> bool:
        """
        Perform a triple click to select entire line.
        
        Args:
            x: Pixel X coordinate
            y: Pixel Y coordinate
        
        Returns:
            True on success
        """
        x, y = self._validate_coordinates(x, y)
        pyautogui.click(x, y, clicks=3)
        self._post_action_delay()
        return True
    
    def copy(self) -> bool:
        """
        Copy selected content to clipboard (Ctrl+C).
        
        Returns:
            True on success
        """
        pyautogui.hotkey('ctrl', 'c')
        self._post_action_delay()
        return True
    
    def paste(self) -> bool:
        """
        Paste clipboard content (Ctrl+V).
        
        Returns:
            True on success
        """
        pyautogui.hotkey('ctrl', 'v')
        self._post_action_delay()
        return True
    
    def cut(self) -> bool:
        """
        Cut selected content (Ctrl+X).
        
        Returns:
            True on success
        """
        pyautogui.hotkey('ctrl', 'x')
        self._post_action_delay()
        return True
    
    def select_all(self) -> bool:
        """
        Select all content (Ctrl+A).
        
        Returns:
            True on success
        """
        pyautogui.hotkey('ctrl', 'a')
        self._post_action_delay()
        return True
    
    def focus_window(self, title_pattern: str) -> bool:
        """
        Focus a window by title pattern.
        
        Args:
            title_pattern: Window title substring to match
        
        Returns:
            True if window found and focused
        """
        try:
            from .window_manager import focus_window_by_title
            result = focus_window_by_title(title_pattern)
            self._post_action_delay()
            return result
        except ImportError:
            self.logger.warning("window_manager module not available")
            return False
    
    def minimize_window(self) -> bool:
        """
        Minimize the current window.
        
        Returns:
            True on success
        """
        try:
            from .window_manager import get_foreground_window, minimize_window
            window = get_foreground_window()
            if window:
                result = minimize_window(window.handle)
                self._post_action_delay()
                return result
            return False
        except ImportError:
            # Fallback to keyboard shortcut
            pyautogui.hotkey('win', 'down')
            self._post_action_delay()
            return True
    
    def maximize_window(self) -> bool:
        """
        Maximize the current window.
        
        Returns:
            True on success
        """
        try:
            from .window_manager import get_foreground_window, maximize_window
            window = get_foreground_window()
            if window:
                result = maximize_window(window.handle)
                self._post_action_delay()
                return result
            return False
        except ImportError:
            # Fallback to keyboard shortcut
            pyautogui.hotkey('win', 'up')
            self._post_action_delay()
            return True
    
    def close_window(self) -> bool:
        """
        Close the current window (Alt+F4).
        
        Returns:
            True on success
        """
        pyautogui.hotkey('alt', 'F4')
        self._post_action_delay()
        return True
    
    def launch_app(self, app_name: str) -> bool:
        """
        Launch an application by name.
        
        Args:
            app_name: Name of the application to launch
        
        Returns:
            True if launch was attempted
        """
        try:
            from .app_launcher import launch_app
            result = launch_app(app_name)
            time.sleep(1.0)  # Wait for app to start
            return result
        except ImportError:
            self.logger.warning("app_launcher module not available")
            return False
    
    def open_url(self, url: str) -> bool:
        """
        Open a URL in the default browser.
        
        Args:
            url: URL to open
        
        Returns:
            True if URL was opened
        """
        try:
            from .app_launcher import open_url
            result = open_url(url)
            time.sleep(1.0)  # Wait for browser
            return result
        except ImportError:
            self.logger.warning("app_launcher module not available")
            return False


def create_action_from_dict(data: dict) -> Action:
    """
    Create an Action from a dictionary (e.g., from VLM JSON output).
    """
    action_type_str = data.get("action", "").upper()
    
    try:
        action_type = ActionType(action_type_str)
    except ValueError:
        raise ActionError(f"Invalid action type: {action_type_str}")
    
    # Handle coordinates (could be top level or nested)
    coords = data.get("coordinates") or {}
    x = data.get("x") if data.get("x") is not None else coords.get("x")
    y = data.get("y") if data.get("y") is not None else coords.get("y")
    
    # CRITICAL: Validate coordinates for actions that REQUIRE them
    if action_type in [ActionType.CLICK, ActionType.DOUBLE_CLICK, ActionType.RIGHT_CLICK, ActionType.TRIPLE_CLICK]:
        if x is None or y is None:
            target = data.get("target", "unknown element")
            raise ActionError(f"CRITICAL: Model failed to provide coordinates for CLICK on '{target}'. Check vision and prompts.")
    
    # Handle PRESS key
    key = data.get("key")
    
    # Handle HOTKEY keys
    keys = data.get("keys")

    # Handle LAUNCH_APP text or other value fields
    text = data.get("value") or data.get("text") or data.get("url") or data.get("app_name")
    
    return Action(
        action_type=action_type,
        x=int(x) if x is not None else None,
        y=int(y) if y is not None else None,
        text=text,
        key=key,
        keys=keys,
        scroll_amount=data.get("scroll") or data.get("scroll_amount"),
        end_x=data.get("end_x") or (data.get("end_coordinates", {}) or {}).get("x"),
        end_y=data.get("end_y") or (data.get("end_coordinates", {}) or {}).get("y"),
        duration=data.get("duration", 0.5),
        confidence=float(data.get("confidence", 1.0)),
        target_description=data.get("target", ""),
        thought=data.get("thought", "")
    )
