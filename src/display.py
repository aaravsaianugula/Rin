"""
Windows display utilities for Qwen3-VL Computer Control System.

Provides Windows-specific APIs via ctypes for:
- True primary monitor detection
- DPI scaling awareness
- Work area (screen minus taskbar) calculation
- Window focus detection

All functions are Windows-only and use ctypes to avoid external dependencies.
"""

import ctypes
from ctypes import wintypes
from dataclasses import dataclass
from typing import List, Optional, Tuple

# Windows API constants
MONITOR_DEFAULTTOPRIMARY = 1
MONITOR_DEFAULTTONEAREST = 2

SM_CXSCREEN = 0
SM_CYSCREEN = 1
SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79

PROCESS_DPI_UNAWARE = 0
PROCESS_SYSTEM_DPI_AWARE = 1
PROCESS_PER_MONITOR_DPI_AWARE = 2

# DPI awareness context values (Windows 10 1607+)
DPI_AWARENESS_CONTEXT_UNAWARE = -1
DPI_AWARENESS_CONTEXT_SYSTEM_AWARE = -2
DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE = -3
DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = -4


@dataclass
class MonitorRect:
    """Rectangle representing monitor bounds."""
    left: int
    top: int
    right: int
    bottom: int
    
    @property
    def width(self) -> int:
        return self.right - self.left
    
    @property
    def height(self) -> int:
        return self.bottom - self.top
    
    @property
    def center(self) -> Tuple[int, int]:
        return ((self.left + self.right) // 2, (self.top + self.bottom) // 2)
    
    def contains(self, x: int, y: int) -> bool:
        """Check if point is within this rectangle."""
        return self.left <= x < self.right and self.top <= y < self.bottom


@dataclass
class MonitorInfo:
    """Complete information about a display monitor."""
    handle: int
    monitor_rect: MonitorRect
    work_rect: MonitorRect
    is_primary: bool
    device_name: str
    dpi_x: int = 96
    dpi_y: int = 96
    
    @property
    def dpi_scale(self) -> float:
        """Get DPI scaling factor (1.0 = 100%, 1.5 = 150%, etc.)."""
        return self.dpi_x / 96.0


# Load Windows DLLs
user32 = ctypes.windll.user32
shcore = None  # Loaded on demand for DPI functions
kernel32 = ctypes.windll.kernel32

# Define Windows structures
class RECT(ctypes.Structure):
    _fields_ = [
        ("left", wintypes.LONG),
        ("top", wintypes.LONG),
        ("right", wintypes.LONG),
        ("bottom", wintypes.LONG),
    ]


class MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", RECT),
        ("rcWork", RECT),
        ("dwFlags", wintypes.DWORD),
    ]


class MONITORINFOEX(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", RECT),
        ("rcWork", RECT),
        ("dwFlags", wintypes.DWORD),
        ("szDevice", wintypes.WCHAR * 32),
    ]


# Monitor enumeration callback type
MONITORENUMPROC = ctypes.WINFUNCTYPE(
    wintypes.BOOL,
    wintypes.HMONITOR,
    wintypes.HDC,
    ctypes.POINTER(RECT),
    wintypes.LPARAM
)


def _load_shcore():
    """Load shcore.dll for DPI functions (Windows 8.1+)."""
    global shcore
    if shcore is None:
        try:
            shcore = ctypes.windll.shcore
        except OSError:
            pass  # Not available on older Windows
    return shcore


def set_dpi_awareness() -> bool:
    """
    Set process DPI awareness to get accurate screen coordinates.
    
    Should be called once at application startup, before any GUI operations.
    
    Returns:
        True if DPI awareness was set successfully
    """
    try:
        # Try Windows 10 1703+ API first (best support)
        user32.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
        user32.SetProcessDpiAwarenessContext.restype = wintypes.BOOL
        if user32.SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2):
            return True
    except (AttributeError, OSError, Exception):
        pass
    
    try:
        # Try Windows 8.1+ API
        shcore = _load_shcore()
        if shcore:
            shcore.SetProcessDpiAwareness.argtypes = [ctypes.c_int]
            shcore.SetProcessDpiAwareness.restype = ctypes.HRESULT
            result = shcore.SetProcessDpiAwareness(PROCESS_PER_MONITOR_DPI_AWARE)
            if result == 0:  # S_OK
                return True
    except (AttributeError, OSError, Exception):
        pass
    
    try:
        # Fallback to Vista+ API
        user32.SetProcessDPIAware.restype = wintypes.BOOL
        return bool(user32.SetProcessDPIAware())
    except (AttributeError, OSError, Exception):
        pass
    
    return False


def get_primary_monitor_handle() -> int:
    """Get handle to the primary monitor."""
    # Get a point on the primary monitor (0,0 is always on primary)
    pt = wintypes.POINT(0, 0)
    return user32.MonitorFromPoint(pt, MONITOR_DEFAULTTOPRIMARY)


def get_monitor_info(handle: int) -> Optional[MonitorInfo]:
    """
    Get detailed information about a monitor.
    
    Args:
        handle: Monitor handle from MonitorFromPoint or enumeration
    
    Returns:
        MonitorInfo object or None if failed
    """
    info = MONITORINFOEX()
    info.cbSize = ctypes.sizeof(MONITORINFOEX)
    
    if not user32.GetMonitorInfoW(handle, ctypes.byref(info)):
        return None
    
    monitor_rect = MonitorRect(
        left=info.rcMonitor.left,
        top=info.rcMonitor.top,
        right=info.rcMonitor.right,
        bottom=info.rcMonitor.bottom
    )
    
    work_rect = MonitorRect(
        left=info.rcWork.left,
        top=info.rcWork.top,
        right=info.rcWork.right,
        bottom=info.rcWork.bottom
    )
    
    # Flag 0x1 means primary monitor
    is_primary = bool(info.dwFlags & 0x1)
    device_name = info.szDevice
    
    # Get DPI for this monitor
    dpi_x, dpi_y = get_monitor_dpi(handle)
    
    return MonitorInfo(
        handle=handle,
        monitor_rect=monitor_rect,
        work_rect=work_rect,
        is_primary=is_primary,
        device_name=device_name,
        dpi_x=dpi_x,
        dpi_y=dpi_y
    )


def get_monitor_dpi(handle: int) -> Tuple[int, int]:
    """
    Get DPI for a specific monitor.
    
    Args:
        handle: Monitor handle
    
    Returns:
        Tuple of (dpi_x, dpi_y), defaults to (96, 96) if unavailable
    """
    shcore = _load_shcore()
    if not shcore:
        return (96, 96)
    
    try:
        dpi_x = wintypes.UINT()
        dpi_y = wintypes.UINT()
        
        # MDT_EFFECTIVE_DPI = 0
        shcore.GetDpiForMonitor.argtypes = [
            wintypes.HMONITOR, 
            ctypes.c_int,
            ctypes.POINTER(wintypes.UINT),
            ctypes.POINTER(wintypes.UINT)
        ]
        shcore.GetDpiForMonitor.restype = ctypes.HRESULT
        
        result = shcore.GetDpiForMonitor(handle, 0, ctypes.byref(dpi_x), ctypes.byref(dpi_y))
        if result == 0:  # S_OK
            return (dpi_x.value, dpi_y.value)
    except (AttributeError, OSError):
        pass
    
    return (96, 96)


def get_primary_monitor_info() -> Optional[MonitorInfo]:
    """
    Get information about the primary monitor.
    
    Returns:
        MonitorInfo for primary monitor, or None if failed
    """
    handle = get_primary_monitor_handle()
    return get_monitor_info(handle)


def get_all_monitors() -> List[MonitorInfo]:
    """
    Enumerate all connected monitors.
    
    Returns:
        List of MonitorInfo objects for all monitors
    """
    monitors = []
    
    def callback(hMonitor, hdcMonitor, lprcMonitor, dwData):
        info = get_monitor_info(hMonitor)
        if info:
            monitors.append(info)
        return True  # Continue enumeration
    
    callback_func = MONITORENUMPROC(callback)
    user32.EnumDisplayMonitors(None, None, callback_func, 0)
    
    return monitors


def get_screen_size() -> Tuple[int, int]:
    """
    Get the primary monitor's resolution.
    
    This is DPI-aware if set_dpi_awareness was called.
    
    Returns:
        Tuple of (width, height) in pixels
    """
    width = user32.GetSystemMetrics(SM_CXSCREEN)
    height = user32.GetSystemMetrics(SM_CYSCREEN)
    return (width, height)


def get_virtual_screen_bounds() -> MonitorRect:
    """
    Get the bounding rectangle of all monitors combined.
    
    Returns:
        MonitorRect covering all monitors
    """
    x = user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
    y = user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
    width = user32.GetSystemMetrics(SM_CXVIRTUALSCREEN)
    height = user32.GetSystemMetrics(SM_CYVIRTUALSCREEN)
    
    return MonitorRect(left=x, top=y, right=x + width, bottom=y + height)


def get_work_area() -> MonitorRect:
    """
    Get the work area of the primary monitor (excludes taskbar).
    
    Returns:
        MonitorRect representing usable screen area
    """
    info = get_primary_monitor_info()
    if info:
        return info.work_rect
    
    # Fallback: use SystemParametersInfo
    rect = RECT()
    user32.SystemParametersInfoW(48, 0, ctypes.byref(rect), 0)  # SPI_GETWORKAREA = 48
    return MonitorRect(left=rect.left, top=rect.top, right=rect.right, bottom=rect.bottom)


def get_dpi_scale() -> float:
    """
    Get the DPI scaling factor for the primary monitor.
    
    Returns:
        Scale factor (1.0 = 100%, 1.25 = 125%, 1.5 = 150%, etc.)
    """
    info = get_primary_monitor_info()
    if info:
        return info.dpi_scale
    return 1.0


def is_point_on_primary(x: int, y: int) -> bool:
    """
    Check if a point is on the primary monitor.
    
    Args:
        x, y: Screen coordinates
    
    Returns:
        True if point is within primary monitor bounds
    """
    info = get_primary_monitor_info()
    if info:
        return info.monitor_rect.contains(x, y)
    return True  # Assume yes if can't determine


def get_foreground_window() -> int:
    """Get handle of the currently focused window."""
    return user32.GetForegroundWindow()


def get_window_title(hwnd: int) -> str:
    """
    Get the title of a window.
    
    Args:
        hwnd: Window handle
    
    Returns:
        Window title string
    """
    length = user32.GetWindowTextLengthW(hwnd)
    if length == 0:
        return ""
    
    buffer = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buffer, length + 1)
    return buffer.value


def get_foreground_window_title() -> str:
    """Get the title of the currently focused window."""
    hwnd = get_foreground_window()
    return get_window_title(hwnd)


def is_window_focused(title_substring: str) -> bool:
    """
    Check if a window with the given title substring is currently focused.
    
    Args:
        title_substring: Part of the window title to match (case-insensitive)
    
    Returns:
        True if matching window is focused
    """
    current_title = get_foreground_window_title().lower()
    return title_substring.lower() in current_title


# Initialize DPI awareness when module is imported
_dpi_initialized = False

def ensure_dpi_aware():
    """Ensure DPI awareness is set (call this before any screen operations)."""
    global _dpi_initialized
    if not _dpi_initialized:
        try:
            set_dpi_awareness()
        except Exception:
            pass  # Ignore any errors, DPI awareness is optional
        _dpi_initialized = True


# NOTE: Do NOT auto-initialize on import - causes permission errors in test contexts
# Call ensure_dpi_aware() explicitly when needed from capture.py or main.py
