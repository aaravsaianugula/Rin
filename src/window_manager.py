"""
Window management utilities for Qwen3-VL Computer Control System.

Provides Windows-specific window control functions via ctypes:
- Find windows by title
- Focus/activate windows
- Minimize/maximize/close windows
- Wait for window to appear
- Check if window is responding

All functions use ctypes to avoid external dependencies.
"""

import ctypes
import time
from ctypes import wintypes
from dataclasses import dataclass
from typing import Callable, List, Optional
import re


# Windows constants
SW_HIDE = 0
SW_SHOWNORMAL = 1
SW_SHOWMINIMIZED = 2
SW_SHOWMAXIMIZED = 3
SW_MAXIMIZE = 3
SW_SHOWNOACTIVATE = 4
SW_SHOW = 5
SW_MINIMIZE = 6
SW_SHOWMINNOACTIVE = 7
SW_SHOWNA = 8
SW_RESTORE = 9
SW_SHOWDEFAULT = 10
SW_FORCEMINIMIZE = 11

GW_OWNER = 4
GWL_STYLE = -16
WS_VISIBLE = 0x10000000
WS_MINIMIZE = 0x20000000
WS_MAXIMIZE = 0x01000000

WM_CLOSE = 0x0010

SMTO_ABORTIFHUNG = 0x0002
SMTO_BLOCK = 0x0001


@dataclass
class WindowInfo:
    """Information about a window."""
    handle: int
    title: str
    class_name: str
    is_visible: bool
    is_minimized: bool
    is_maximized: bool
    rect: tuple  # (left, top, right, bottom)
    
    @property
    def width(self) -> int:
        return self.rect[2] - self.rect[0]
    
    @property
    def height(self) -> int:
        return self.rect[3] - self.rect[1]
    
    @property
    def center(self) -> tuple:
        return (
            (self.rect[0] + self.rect[2]) // 2,
            (self.rect[1] + self.rect[3]) // 2
        )


# Load Windows DLLs
user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32


# Define callback type for EnumWindows
WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", wintypes.LONG),
        ("top", wintypes.LONG),
        ("right", wintypes.LONG),
        ("bottom", wintypes.LONG),
    ]


def get_window_title(hwnd: int) -> str:
    """Get the title of a window."""
    length = user32.GetWindowTextLengthW(hwnd)
    if length == 0:
        return ""
    buffer = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buffer, length + 1)
    return buffer.value


def get_window_class(hwnd: int) -> str:
    """Get the class name of a window."""
    buffer = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buffer, 256)
    return buffer.value


def get_window_rect(hwnd: int) -> tuple:
    """Get the bounding rectangle of a window."""
    rect = RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    return (rect.left, rect.top, rect.right, rect.bottom)


def is_window_visible(hwnd: int) -> bool:
    """Check if window is visible."""
    return bool(user32.IsWindowVisible(hwnd))


def is_window_minimized(hwnd: int) -> bool:
    """Check if window is minimized."""
    return bool(user32.IsIconic(hwnd))


def is_window_maximized(hwnd: int) -> bool:
    """Check if window is maximized."""
    return bool(user32.IsZoomed(hwnd))


def get_window_info(hwnd: int) -> WindowInfo:
    """Get complete information about a window."""
    return WindowInfo(
        handle=hwnd,
        title=get_window_title(hwnd),
        class_name=get_window_class(hwnd),
        is_visible=is_window_visible(hwnd),
        is_minimized=is_window_minimized(hwnd),
        is_maximized=is_window_maximized(hwnd),
        rect=get_window_rect(hwnd)
    )


def list_windows(visible_only: bool = True, with_title_only: bool = True) -> List[WindowInfo]:
    """
    List all top-level windows.
    
    Args:
        visible_only: Only include visible windows
        with_title_only: Only include windows with a title
    
    Returns:
        List of WindowInfo objects
    """
    windows = []
    
    def callback(hwnd, lparam):
        if visible_only and not is_window_visible(hwnd):
            return True
        
        title = get_window_title(hwnd)
        if with_title_only and not title:
            return True
        
        # Skip windows owned by other windows (child windows)
        if user32.GetWindow(hwnd, GW_OWNER) != 0:
            return True
        
        windows.append(get_window_info(hwnd))
        return True
    
    callback_func = WNDENUMPROC(callback)
    user32.EnumWindows(callback_func, 0)
    
    return windows


def find_window(title_pattern: str, exact: bool = False) -> Optional[WindowInfo]:
    """
    Find a window by title.
    
    Args:
        title_pattern: Window title to search for (substring or regex)
        exact: If True, require exact match; if False, use substring/regex
    
    Returns:
        WindowInfo if found, None otherwise
    """
    windows = list_windows(visible_only=True, with_title_only=True)
    
    for window in windows:
        if exact:
            if window.title == title_pattern:
                return window
        else:
            # Try substring match first
            if title_pattern.lower() in window.title.lower():
                return window
            # Try regex match
            try:
                if re.search(title_pattern, window.title, re.IGNORECASE):
                    return window
            except re.error:
                pass
    
    return None


def find_windows(title_pattern: str) -> List[WindowInfo]:
    """
    Find all windows matching a title pattern.
    
    Args:
        title_pattern: Window title substring or regex
    
    Returns:
        List of matching WindowInfo objects
    """
    windows = list_windows(visible_only=True, with_title_only=True)
    matches = []
    
    for window in windows:
        if title_pattern.lower() in window.title.lower():
            matches.append(window)
            continue
        try:
            if re.search(title_pattern, window.title, re.IGNORECASE):
                matches.append(window)
        except re.error:
            pass
    
    return matches


def focus_window(hwnd: int) -> bool:
    """
    Bring a window to the foreground and focus it.
    
    Args:
        hwnd: Window handle
    
    Returns:
        True if successful
    """
    # Restore if minimized
    if is_window_minimized(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)
    
    # Bring to foreground
    # First, get the current foreground thread
    foreground_hwnd = user32.GetForegroundWindow()
    foreground_thread = user32.GetWindowThreadProcessId(foreground_hwnd, None)
    current_thread = kernel32.GetCurrentThreadId()
    
    # Attach input threads to allow SetForegroundWindow
    if foreground_thread != current_thread:
        user32.AttachThreadInput(current_thread, foreground_thread, True)
    
    result = user32.SetForegroundWindow(hwnd)
    user32.BringWindowToTop(hwnd)
    user32.SetFocus(hwnd)
    
    # Detach input threads
    if foreground_thread != current_thread:
        user32.AttachThreadInput(current_thread, foreground_thread, False)
    
    return bool(result)


def focus_window_by_title(title_pattern: str) -> bool:
    """
    Find and focus a window by title.
    
    Args:
        title_pattern: Window title substring
    
    Returns:
        True if window found and focused
    """
    window = find_window(title_pattern)
    if window:
        return focus_window(window.handle)
    return False


def minimize_window(hwnd: int) -> bool:
    """Minimize a window."""
    return bool(user32.ShowWindow(hwnd, SW_MINIMIZE))


def maximize_window(hwnd: int) -> bool:
    """Maximize a window."""
    return bool(user32.ShowWindow(hwnd, SW_MAXIMIZE))


def restore_window(hwnd: int) -> bool:
    """Restore a window from minimized/maximized state."""
    return bool(user32.ShowWindow(hwnd, SW_RESTORE))


def close_window(hwnd: int) -> bool:
    """
    Send close message to a window.
    
    Args:
        hwnd: Window handle
    
    Returns:
        True if message was sent
    """
    return bool(user32.PostMessageW(hwnd, WM_CLOSE, 0, 0))


def is_window_responding(hwnd: int, timeout_ms: int = 1000) -> bool:
    """
    Check if a window is responding to messages.
    
    Args:
        hwnd: Window handle
        timeout_ms: Timeout in milliseconds
    
    Returns:
        True if window is responding
    """
    result = wintypes.DWORD()
    success = user32.SendMessageTimeoutW(
        hwnd,
        0,  # WM_NULL
        0,
        0,
        SMTO_ABORTIFHUNG,
        timeout_ms,
        ctypes.byref(result)
    )
    return bool(success)


def wait_for_window(
    title_pattern: str,
    timeout_seconds: float = 10.0,
    poll_interval: float = 0.5
) -> Optional[WindowInfo]:
    """
    Wait for a window with matching title to appear.
    
    Args:
        title_pattern: Window title substring
        timeout_seconds: Maximum time to wait
        poll_interval: Time between checks
    
    Returns:
        WindowInfo if window appeared, None if timeout
    """
    start_time = time.time()
    
    while time.time() - start_time < timeout_seconds:
        window = find_window(title_pattern)
        if window:
            return window
        time.sleep(poll_interval)
    
    return None


def get_foreground_window() -> Optional[WindowInfo]:
    """Get info about the currently focused window."""
    hwnd = user32.GetForegroundWindow()
    if hwnd:
        return get_window_info(hwnd)
    return None


def get_window_at_point(x: int, y: int) -> Optional[WindowInfo]:
    """
    Get the window at a specific screen point.
    
    Args:
        x, y: Screen coordinates
    
    Returns:
        WindowInfo of window at point, or None
    """
    pt = wintypes.POINT(x, y)
    hwnd = user32.WindowFromPoint(pt)
    if hwnd:
        # Get the top-level parent window
        root = user32.GetAncestor(hwnd, 2)  # GA_ROOT = 2
        if root:
            return get_window_info(root)
        return get_window_info(hwnd)
    return None


def set_window_position(hwnd: int, x: int, y: int, width: int = 0, height: int = 0) -> bool:
    """
    Move and optionally resize a window.
    
    Args:
        hwnd: Window handle
        x, y: New position
        width, height: New size (0 to keep current)
    
    Returns:
        True if successful
    """
    flags = 0x0004  # SWP_NOZORDER
    if width == 0 or height == 0:
        flags |= 0x0001  # SWP_NOSIZE
        width = 0
        height = 0
    

def get_active_window_context() -> str:
    """
    Get a context string describing the current window state for the AI.
    
    Returns lists of windows in Z-order (top to bottom) to help the AI 
    understand which windows are covering others.
    """
    foreground = get_foreground_window()
    foreground_title = foreground.title if foreground else "None"
    
    # EnumWindows returns windows in Z-order (top to bottom)
    windows = list_windows(visible_only=True, with_title_only=True)
    
    # Limit to top 5 visible windows to avoid clutter
    top_windows = windows[:5]
    
    context = [f"Foreground Window: '{foreground_title}'"]
    context.append("Visible Windows (Top-most first):")
    
    for i, win in enumerate(top_windows, 1):
        status = " (ACTIVE)" if foreground and win.handle == foreground.handle else ""
        context.append(f"{i}. '{win.title}' {status} - Bounds: {win.rect}")
        
    return "\n".join(context)
