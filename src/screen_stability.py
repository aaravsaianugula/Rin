"""
Screen stability detection for Qwen3-VL Computer Control System.

Waits for screen to stop changing before taking actions,
replacing static delays with dynamic screenshot comparison.
"""

import time
import logging
from typing import Optional, Tuple
from PIL import Image
import numpy as np


def calculate_image_difference(img1: Image.Image, img2: Image.Image) -> float:
    """
    Calculate the percentage of pixels that differ between two images.
    
    Args:
        img1: First PIL Image
        img2: Second PIL Image
        
    Returns:
        Float between 0.0 (identical) and 1.0 (completely different)
    """
    # Resize to same dimensions if needed
    if img1.size != img2.size:
        img2 = img2.resize(img1.size, Image.Resampling.LANCZOS)
    
    # Convert to numpy arrays
    arr1 = np.asarray(img1.convert('RGB'), dtype=np.int16)
    arr2 = np.asarray(img2.convert('RGB'), dtype=np.int16)
    
    # Calculate absolute difference per pixel
    diff = np.abs(arr1 - arr2)
    
    # A pixel is "different" if any channel differs by more than threshold
    pixel_threshold = 10  # Allow small color variations (compression artifacts, etc.)
    different_pixels = np.any(diff > pixel_threshold, axis=2)
    
    # Return percentage of different pixels
    return float(np.mean(different_pixels))


def wait_for_screen_stable(
    capture,
    threshold: float = 0.02,
    max_wait: float = 3.0,
    check_interval: float = 0.15,
    min_stable_frames: int = 2,
    logger: Optional[logging.Logger] = None
) -> Tuple[bool, float]:
    """
    Wait until the screen stops changing.
    
    Args:
        capture: ScreenCapture instance with capture_screen() method
        threshold: Maximum pixel difference percentage to consider "stable" (0.02 = 2%)
        max_wait: Maximum seconds to wait before giving up
        check_interval: Seconds between screenshot comparisons
        min_stable_frames: Number of consecutive stable frames required
        logger: Optional logger instance
        
    Returns:
        Tuple of (is_stable: bool, elapsed_time: float)
    """
    log = logger or logging.getLogger(__name__)
    
    start_time = time.time()
    stable_count = 0
    prev_image: Optional[Image.Image] = None
    
    while (elapsed := time.time() - start_time) < max_wait:
        # Capture current screen
        current_image = capture.capture_screen()
        
        if prev_image is not None:
            # Compare with previous frame
            diff = calculate_image_difference(prev_image, current_image)
            
            if diff <= threshold:
                stable_count += 1
                log.debug(f"Screen stable (diff={diff:.3%}, count={stable_count}/{min_stable_frames})")
                
                if stable_count >= min_stable_frames:
                    log.info(f"Screen stabilized after {elapsed:.2f}s (diff={diff:.3%})")
                    return True, elapsed
            else:
                stable_count = 0
                log.debug(f"Screen changing (diff={diff:.3%})")
        
        prev_image = current_image
        time.sleep(check_interval)
    
    log.warning(f"Screen did not stabilize within {max_wait}s")
    return False, max_wait


def is_loading_cursor_visible() -> bool:
    """
    Check if the Windows loading cursor (spinner) is currently visible.
    
    Returns:
        True if a loading cursor is detected
        
    Note: This is a Windows-specific implementation using ctypes.
    """
    try:
        import ctypes
        from ctypes import wintypes
        
        # Get current cursor info
        class CURSORINFO(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.DWORD),
                ("flags", wintypes.DWORD),
                ("hCursor", wintypes.HANDLE),
                ("ptScreenPos", wintypes.POINT),
            ]
        
        cursor_info = CURSORINFO()
        cursor_info.cbSize = ctypes.sizeof(CURSORINFO)
        
        if ctypes.windll.user32.GetCursorInfo(ctypes.byref(cursor_info)):
            # Loading cursors have specific handles
            # IDC_WAIT = 32514, IDC_APPSTARTING = 32650
            wait_cursor = ctypes.windll.user32.LoadCursorW(0, 32514)
            appstart_cursor = ctypes.windll.user32.LoadCursorW(0, 32650)
            
            return cursor_info.hCursor in (wait_cursor, appstart_cursor)
    except Exception:
        pass
    
    return False


def wait_for_ready(
    capture,
    stability_threshold: float = 0.02,
    max_wait: float = 3.0,
    check_cursor: bool = True,
    logger: Optional[logging.Logger] = None
) -> Tuple[bool, str]:
    """
    High-level function to wait until the screen is ready for input.
    
    Combines screen stability detection and optional cursor checking.
    
    Args:
        capture: ScreenCapture instance
        stability_threshold: Max pixel difference for stability
        max_wait: Maximum wait time in seconds
        check_cursor: Whether to also check for loading cursor
        logger: Optional logger
        
    Returns:
        Tuple of (ready: bool, reason: str)
    """
    log = logger or logging.getLogger(__name__)
    
    # First check for loading cursor
    if check_cursor and is_loading_cursor_visible():
        log.debug("Loading cursor detected, waiting...")
        cursor_wait_start = time.time()
        while time.time() - cursor_wait_start < max_wait:
            if not is_loading_cursor_visible():
                break
            time.sleep(0.1)
        else:
            return False, "Loading cursor timeout"
    
    # Then wait for screen stability
    stable, elapsed = wait_for_screen_stable(
        capture,
        threshold=stability_threshold,
        max_wait=max_wait,
        logger=log
    )
    
    if stable:
        return True, f"Ready after {elapsed:.2f}s"
    else:
        return False, "Screen did not stabilize"
