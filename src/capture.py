"""
Screenshot capture module for Qwen3-VL Computer Control System.

Provides fast, efficient screen capture using mss library.
Explicitly targets PRIMARY MONITOR ONLY for multi-monitor setups.
Target performance: <50ms for full screen capture.
"""

import base64
import io
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import mss
import mss.tools
from PIL import Image

# Patch mss to ignore "Access is denied" when setting DPI awareness.
# This happens if another part of the app (like display.py) already set it.
try:
    import mss.windows
    _orig_set_dpi = mss.windows.MSS._set_dpi_awareness
    def _patched_set_dpi(self):
        try:
            return _orig_set_dpi(self)
        except Exception as e:
            # WinError -2147024891 is "Access is denied" (already set)
            if "Access is denied" in str(e) or "-2147024891" in str(e):
                return
            raise
    mss.windows.MSS._set_dpi_awareness = _patched_set_dpi
except (ImportError, AttributeError):
    pass


@dataclass
class MonitorInfo:
    """Information about a monitor."""
    index: int
    left: int
    top: int
    width: int
    height: int
    is_primary: bool
    
    @property
    def right(self) -> int:
        return self.left + self.width
    
    @property
    def bottom(self) -> int:
        return self.top + self.height
    
    @property
    def center(self) -> Tuple[int, int]:
        return (self.left + self.width // 2, self.top + self.height // 2)


class ScreenCapture:
    """
    Handles screenshot capture with various output formats.
    
    IMPORTANT: This class explicitly captures ONLY the primary monitor
    to ensure consistent coordinate mapping in multi-monitor setups.
    """
    
    def __init__(self, max_size: Optional[int] = None, primary_only: bool = True):
        """
        Initialize screen capture.
        
        Args:
            max_size: Optional maximum dimension for resizing (maintains aspect ratio)
            primary_only: If True, only capture and work with primary monitor (RECOMMENDED)
        """
        self.max_size = max_size
        self.primary_only = primary_only
        self._sct = None
        self._primary_monitor: Optional[MonitorInfo] = None
        self._all_monitors: List[MonitorInfo] = []
    
    @property
    def sct(self) -> mss.mss:
        """Lazy initialization of mss instance."""
        if self._sct is None:
            self._sct = mss.mss()
            self._detect_monitors()
        return self._sct
    
    def _detect_monitors(self):
        """Detect and cache monitor information using Windows APIs."""
        self._all_monitors = []
        self._dpi_scale = 1.0
        
        # Try to use display.py for accurate primary monitor detection
        primary_rect = None
        try:
            from .display import get_primary_monitor_info, get_dpi_scale, ensure_dpi_aware
            ensure_dpi_aware()
            
            primary_info = get_primary_monitor_info()
            if primary_info:
                self._dpi_scale = primary_info.dpi_scale
                primary_rect = primary_info.monitor_rect
        except Exception:
            pass  # Fall back to mss detection (display.py may fail with permissions)
            
        found_primary = False
        
        for i, mon in enumerate(self._sct.monitors):
            if i == 0:
                # Index 0 is the "all monitors" virtual screen, skip it
                continue
            
            # Determine if this is the primary monitor
            is_primary = False
            
            if primary_rect:
                # Match against display.py accurate info
                # Allow for small 1px differences due to rounding/DPI
                if (abs(mon["left"] - primary_rect.left) <= 1 and 
                    abs(mon["top"] - primary_rect.top) <= 1 and 
                    abs(mon["width"] - primary_rect.width) <= 1 and 
                    abs(mon["height"] - primary_rect.height) <= 1):
                    is_primary = True
                    found_primary = True
            elif i == 1:
                # Fallback: assume index 1 if display.py failed
                is_primary = True
                found_primary = True
            
            info = MonitorInfo(
                index=i,
                left=mon["left"],
                top=mon["top"],
                width=mon["width"],
                height=mon["height"],
                is_primary=is_primary
            )
            self._all_monitors.append(info)
            
            if is_primary:
                self._primary_monitor = info
        
        # Safety fallback: if no primary matched strategy, force index 1
        if not found_primary and len(self._all_monitors) > 0:
            # Look for index 1 in our list (which starts from mss index 1)
            for m in self._all_monitors:
                if m.index == 1:
                    m.is_primary = True
                    self._primary_monitor = m
                    break
            
            # If still nothing (e.g. mss index logic changed?), take the first one
            if not self._primary_monitor and self._all_monitors:
                self._all_monitors[0].is_primary = True
                self._primary_monitor = self._all_monitors[0]
    
    @property
    def dpi_scale(self) -> float:
        """Get DPI scaling factor for coordinate compensation."""
        _ = self.sct  # Ensure monitors are detected
        return getattr(self, '_dpi_scale', 1.0)
    
    @property
    def primary_monitor(self) -> MonitorInfo:
        """Get primary monitor info."""
        _ = self.sct  # Ensure monitors are detected
        return self._primary_monitor
    
    @property
    def all_monitors(self) -> List[MonitorInfo]:
        """Get all monitor info."""
        _ = self.sct  # Ensure monitors are detected
        return self._all_monitors
    
    def get_screen_size(self) -> Tuple[int, int]:
        """Get the primary monitor's resolution."""
        return self.primary_monitor.width, self.primary_monitor.height
    
    def get_screen_offset(self) -> Tuple[int, int]:
        """
        Get the primary monitor's offset from virtual screen origin.
        
        This is crucial for multi-monitor setups where the primary monitor
        may not start at (0, 0) in virtual screen coordinates.
        
        Returns:
            Tuple of (left_offset, top_offset) in virtual screen coordinates
        """
        return self.primary_monitor.left, self.primary_monitor.top
    
    def get_monitor_info(self) -> Dict:
        """Get detailed monitor configuration info."""
        return {
            "primary": {
                "index": self.primary_monitor.index,
                "width": self.primary_monitor.width,
                "height": self.primary_monitor.height,
                "offset": (self.primary_monitor.left, self.primary_monitor.top),
                "center": self.primary_monitor.center
            },
            "total_monitors": len(self._all_monitors),
            "all_monitors": [
                {
                    "index": m.index,
                    "size": (m.width, m.height),
                    "offset": (m.left, m.top),
                    "is_primary": m.is_primary
                }
                for m in self._all_monitors
            ]
        }
    
    def capture_screen(self, use_primary: bool = True) -> Image.Image:
        """
        Capture the primary monitor screen.
        
        Args:
            use_primary: If True (default), capture primary monitor only.
                        If False, capture all monitors combined.
        
        Returns:
            PIL Image of the screenshot
        """
        if use_primary and self.primary_only:
            # Use the detected primary monitor index
            idx = self.primary_monitor.index
            # Ensure index is within bounds (fallback to 1 if something went wrong)
            if idx >= len(self.sct.monitors):
                idx = 1
            monitor = self.sct.monitors[idx]
        else:
            monitor = self.sct.monitors[0]  # All monitors combined
        
        screenshot = self.sct.grab(monitor)
        
        # Convert to PIL Image
        img = Image.frombytes("RGB", screenshot.size, screenshot.bgra, "raw", "BGRX")
        
        # Resize if max_size is set
        if self.max_size:
            img = self._resize_maintain_aspect(img, self.max_size)
        
        return img
    
    def capture_region(self, x: int, y: int, width: int, height: int) -> Image.Image:
        """
        Capture a specific region of the PRIMARY monitor.
        
        Args:
            x: Left coordinate (relative to primary monitor, not virtual screen)
            y: Top coordinate (relative to primary monitor, not virtual screen)
            width: Region width
            height: Region height
        
        Returns:
            PIL Image of the captured region
        """
        # Adjust coordinates to virtual screen if needed
        offset_x, offset_y = self.get_screen_offset()
        
        region = {
            "left": offset_x + x,
            "top": offset_y + y,
            "width": width,
            "height": height
        }
        screenshot = self.sct.grab(region)
        
        img = Image.frombytes("RGB", screenshot.size, screenshot.bgra, "raw", "BGRX")
        
        if self.max_size:
            img = self._resize_maintain_aspect(img, self.max_size)
        
        return img
    
    def virtual_to_primary(self, vx: int, vy: int) -> Tuple[int, int]:
        """
        Convert virtual screen coordinates to primary monitor coordinates.
        
        Args:
            vx, vy: Virtual screen coordinates
        
        Returns:
            Coordinates relative to primary monitor origin
        """
        offset_x, offset_y = self.get_screen_offset()
        return (vx - offset_x, vy - offset_y)
    
    def primary_to_virtual(self, px: int, py: int) -> Tuple[int, int]:
        """
        Convert primary monitor coordinates to virtual screen coordinates.
        
        This is what you need for PyAutoGUI on multi-monitor setups.
        
        Args:
            px, py: Primary monitor relative coordinates
        
        Returns:
            Virtual screen coordinates (for PyAutoGUI)
        """
        offset_x, offset_y = self.get_screen_offset()
        return (offset_x + px, offset_y + py)
    
    def is_on_primary_monitor(self, vx: int, vy: int) -> bool:
        """
        Check if virtual screen coordinates are on the primary monitor.
        
        Args:
            vx, vy: Virtual screen coordinates
        
        Returns:
            True if coordinates are within primary monitor bounds
        """
        pm = self.primary_monitor
        return (pm.left <= vx < pm.right and pm.top <= vy < pm.bottom)
    
    def _resize_maintain_aspect(self, img: Image.Image, max_dim: int) -> Image.Image:
        """Resize image maintaining aspect ratio so largest dimension is max_dim."""
        width, height = img.size
        
        if width <= max_dim and height <= max_dim:
            return img
        
        if width > height:
            new_width = max_dim
            new_height = int(height * (max_dim / width))
        else:
            new_height = max_dim
            new_width = int(width * (max_dim / height))
        
        return img.resize((new_width, new_height), Image.Resampling.LANCZOS) # LANCZOS is better for retaining small UI details during downscaling
    
    def save_screenshot(self, filepath: str) -> str:
        """
        Capture and save screenshot to file.
        
        Args:
            filepath: Path to save the image
        
        Returns:
            Absolute path to saved file
        """
        img = self.capture_screen()
        path = Path(filepath)
        path.parent.mkdir(parents=True, exist_ok=True)
        img.save(str(path))
        return str(path.absolute())
    
    def get_base64_screenshot(self, format: str = "JPEG", quality: int = 80) -> Tuple[str, Tuple[int, int]]:
        """
        Capture PRIMARY monitor and return as base64 string.
        
        Args:
            format: Image format (PNG, JPEG)
        
        Returns:
            Tuple of (base64 string, (width, height) of captured image)
        """
        img = self.capture_screen()
        
        buffer = io.BytesIO()
        if format == "JPEG":
            img.save(buffer, format=format, quality=quality, optimize=True)
        else:
            img.save(buffer, format=format)
        buffer.seek(0)
        
        b64_string = base64.b64encode(buffer.read()).decode("utf-8")
        
        return b64_string, img.size

    def get_base64_from_image(self, img: Image.Image, format: str = "JPEG", quality: int = 80) -> str:
        """Convert a PIL Image to a base64 string without re-capturing."""
        buffer = io.BytesIO()
        if format == "JPEG":
            img.save(buffer, format=format, quality=quality, optimize=True)
        else:
            img.save(buffer, format=format)
        buffer.seek(0)
        return base64.b64encode(buffer.read()).decode("utf-8")
    
    def benchmark_capture(self, iterations: int = 10) -> float:
        """
        Benchmark capture speed.
        
        Args:
            iterations: Number of captures to average
        
        Returns:
            Average capture time in milliseconds
        """
        times = []
        for _ in range(iterations):
            start = time.perf_counter()
            self.capture_screen()
            elapsed = (time.perf_counter() - start) * 1000
            times.append(elapsed)
        
        return sum(times) / len(times)
    
    def close(self):
        """Clean up resources."""
        if self._sct:
            self._sct.close()
            self._sct = None
    
    def __enter__(self):
        return self
    
    def __exit__(self, *args):
        self.close()


# Convenience functions for quick usage
def capture_screen(max_size: Optional[int] = None) -> Image.Image:
    """Quick capture of the primary monitor."""
    with ScreenCapture(max_size=max_size) as sc:
        return sc.capture_screen()


def get_screen_size() -> Tuple[int, int]:
    """Get primary monitor dimensions."""
    with ScreenCapture() as sc:
        return sc.get_screen_size()


def get_screen_offset() -> Tuple[int, int]:
    """Get primary monitor offset for multi-monitor coordinate handling."""
    with ScreenCapture() as sc:
        return sc.get_screen_offset()


def capture_to_base64(max_size: Optional[int] = None) -> Tuple[str, Tuple[int, int]]:
    """Capture primary monitor and return as base64."""
    with ScreenCapture(max_size=max_size) as sc:
        return sc.get_base64_screenshot()


def get_monitor_info() -> Dict:
    """Get complete monitor configuration."""
    with ScreenCapture() as sc:
        return sc.get_monitor_info()
