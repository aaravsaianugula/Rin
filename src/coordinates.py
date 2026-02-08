"""
Coordinate conversion module for Qwen3-VL Computer Control System.

Handles conversion between Qwen3-VL's normalized [0, 1000] coordinate system
and actual screen pixel coordinates.
"""

import json
import re
from dataclasses import dataclass
from typing import List, Optional, Tuple, Union


# Qwen3-VL uses normalized [0, 1000] range
NORMALIZED_MAX = 1000


@dataclass
class BoundingBox:
    """Represents a bounding box with normalized coordinates."""
    x1: float
    y1: float
    x2: float
    y2: float
    label: str = ""
    
    @property
    def center(self) -> Tuple[float, float]:
        """Get center point of bounding box (normalized)."""
        return ((self.x1 + self.x2) / 2, (self.y1 + self.y2) / 2)
    
    @property
    def width(self) -> float:
        """Get bounding box width (normalized)."""
        return abs(self.x2 - self.x1)
    
    @property
    def height(self) -> float:
        """Get bounding box height (normalized)."""
        return abs(self.y2 - self.y1)
    
    def to_pixels(self, screen_width: int, screen_height: int) -> "PixelBoundingBox":
        """Convert to pixel coordinates."""
        return PixelBoundingBox(
            x1=int(normalized_to_pixels_x(self.x1, screen_width)),
            y1=int(normalized_to_pixels_y(self.y1, screen_height)),
            x2=int(normalized_to_pixels_x(self.x2, screen_width)),
            y2=int(normalized_to_pixels_y(self.y2, screen_height)),
            label=self.label
        )


@dataclass
class PixelBoundingBox:
    """Represents a bounding box with pixel coordinates."""
    x1: int
    y1: int
    x2: int
    y2: int
    label: str = ""
    
    @property
    def center(self) -> Tuple[int, int]:
        """Get center point of bounding box (pixels)."""
        return ((self.x1 + self.x2) // 2, (self.y1 + self.y2) // 2)
    
    @property
    def width(self) -> int:
        """Get bounding box width (pixels)."""
        return abs(self.x2 - self.x1)
    
    @property
    def height(self) -> int:
        """Get bounding box height (pixels)."""
        return abs(self.y2 - self.y1)


@dataclass
class Point:
    """Represents a point coordinate."""
    x: float
    y: float
    is_normalized: bool = True
    
    def to_pixels(self, screen_width: int, screen_height: int) -> Tuple[int, int]:
        """Convert to pixel coordinates."""
        if self.is_normalized:
            return (
                int(normalized_to_pixels_x(self.x, screen_width)),
                int(normalized_to_pixels_y(self.y, screen_height))
            )
        return (int(self.x), int(self.y))


def normalized_to_pixels_x(norm_x: float, screen_width: int) -> float:
    """
    Convert normalized X coordinate to pixel coordinate.
    
    Args:
        norm_x: Normalized X coordinate [0, 1000]
        screen_width: Screen width in pixels
    
    Returns:
        Pixel X coordinate
    """
    return (norm_x / NORMALIZED_MAX) * screen_width


def normalized_to_pixels_y(norm_y: float, screen_height: int) -> float:
    """
    Convert normalized Y coordinate to pixel coordinate.
    
    Args:
        norm_y: Normalized Y coordinate [0, 1000]
        screen_height: Screen height in pixels
    
    Returns:
        Pixel Y coordinate
    """
    return (norm_y / NORMALIZED_MAX) * screen_height


def normalized_to_pixels(
    norm_x: float, 
    norm_y: float, 
    screen_width: int, 
    screen_height: int
) -> Tuple[int, int]:
    """
    Convert normalized coordinates to pixel coordinates.
    
    Args:
        norm_x: Normalized X coordinate [0, 1000]
        norm_y: Normalized Y coordinate [0, 1000]
        screen_width: Screen width in pixels
        screen_height: Screen height in pixels
    
    Returns:
        Tuple of (pixel_x, pixel_y)
    """
    px_x = int(normalized_to_pixels_x(norm_x, screen_width))
    px_y = int(normalized_to_pixels_y(norm_y, screen_height))
    return (px_x, px_y)


def pixels_to_normalized(
    px_x: int, 
    px_y: int, 
    screen_width: int, 
    screen_height: int
) -> Tuple[float, float]:
    """
    Convert pixel coordinates to normalized coordinates.
    
    Args:
        px_x: Pixel X coordinate
        px_y: Pixel Y coordinate
        screen_width: Screen width in pixels
        screen_height: Screen height in pixels
    
    Returns:
        Tuple of (normalized_x, normalized_y)
    """
    norm_x = (px_x / screen_width) * NORMALIZED_MAX
    norm_y = (px_y / screen_height) * NORMALIZED_MAX
    return (norm_x, norm_y)


def bbox_center(x1: float, y1: float, x2: float, y2: float) -> Tuple[float, float]:
    """
    Calculate the center point of a bounding box.
    
    Args:
        x1, y1: Top-left corner
        x2, y2: Bottom-right corner
    
    Returns:
        Tuple of (center_x, center_y)
    """
    return ((x1 + x2) / 2, (y1 + y2) / 2)


def validate_normalized_coordinates(x: float, y: float) -> bool:
    """
    Check if normalized coordinates are within valid range.
    
    Args:
        x: Normalized X coordinate
        y: Normalized Y coordinate
    
    Returns:
        True if valid, False otherwise
    """
    return 0 <= x <= NORMALIZED_MAX and 0 <= y <= NORMALIZED_MAX


def validate_pixel_coordinates(
    x: int, 
    y: int, 
    screen_width: int, 
    screen_height: int
) -> bool:
    """
    Check if pixel coordinates are within screen bounds.
    
    Args:
        x: Pixel X coordinate
        y: Pixel Y coordinate
        screen_width: Screen width in pixels
        screen_height: Screen height in pixels
    
    Returns:
        True if valid, False otherwise
    """
    if x is None or y is None:
        return False
    return 0 <= x < screen_width and 0 <= y < screen_height


def clamp_to_screen(
    x: int, 
    y: int, 
    screen_width: int, 
    screen_height: int
) -> Tuple[int, int]:
    """
    Clamp coordinates to be within screen bounds.
    
    Args:
        x: Pixel X coordinate
        y: Pixel Y coordinate
        screen_width: Screen width
        screen_height: Screen height
    
    Returns:
        Clamped (x, y) tuple
    """
    clamped_x = max(0, min(x, screen_width - 1))
    clamped_y = max(0, min(y, screen_height - 1))
    return (clamped_x, clamped_y)


def parse_bbox_json(json_str: str) -> Optional[BoundingBox]:
    """
    Parse bounding box from Qwen3-VL JSON output.
    
    Expected format: {"bbox_2d": [x1, y1, x2, y2], "label": "element_name"}
    
    Args:
        json_str: JSON string from model output
    
    Returns:
        BoundingBox object or None if parsing fails
    """
    try:
        data = json.loads(json_str)
        
        if "bbox_2d" in data:
            coords = data["bbox_2d"]
            if len(coords) >= 4:
                return BoundingBox(
                    x1=float(coords[0]),
                    y1=float(coords[1]),
                    x2=float(coords[2]),
                    y2=float(coords[3]),
                    label=data.get("label", "")
                )
    except (json.JSONDecodeError, KeyError, IndexError, TypeError):
        pass
    
    return None


def parse_multiple_bboxes(json_str: str) -> List[BoundingBox]:
    """
    Parse multiple bounding boxes from model output.
    
    Handles both single objects and arrays of objects.
    
    Args:
        json_str: JSON string from model output
    
    Returns:
        List of BoundingBox objects
    """
    boxes = []
    
    try:
        data = json.loads(json_str)
        
        # Handle array of bboxes
        if isinstance(data, list):
            for item in data:
                if "bbox_2d" in item:
                    coords = item["bbox_2d"]
                    boxes.append(BoundingBox(
                        x1=float(coords[0]),
                        y1=float(coords[1]),
                        x2=float(coords[2]),
                        y2=float(coords[3]),
                        label=item.get("label", "")
                    ))
        # Handle single bbox
        elif isinstance(data, dict) and "bbox_2d" in data:
            box = parse_bbox_json(json_str)
            if box:
                boxes.append(box)
                
    except (json.JSONDecodeError, KeyError, IndexError, TypeError):
        pass
    
    return boxes


def extract_coordinates_from_text(text: str) -> Optional[Tuple[float, float]]:
    """
    Extract coordinates from text using regex patterns.
    
    Handles formats like:
    - "coordinates": {"x": 450, "y": 320}
    - (450, 320)
    - x: 450, y: 320
    
    Args:
        text: Text potentially containing coordinates
    
    Returns:
        Tuple of (x, y) or None if not found
    """
    # Pattern for JSON-style coordinates
    json_pattern = r'"coordinates"\s*:\s*\{\s*"x"\s*:\s*(\d+(?:\.\d+)?)\s*,\s*"y"\s*:\s*(\d+(?:\.\d+)?)\s*\}'
    match = re.search(json_pattern, text)
    if match:
        return (float(match.group(1)), float(match.group(2)))
    
    # Pattern for tuple-style (x, y)
    tuple_pattern = r'\((\d+(?:\.\d+)?)\s*,\s*(\d+(?:\.\d+)?)\)'
    match = re.search(tuple_pattern, text)
    if match:
        return (float(match.group(1)), float(match.group(2)))
    
    # Pattern for x: N, y: M
    xy_pattern = r'x\s*[:=]\s*(\d+(?:\.\d+)?)\s*[,\s]\s*y\s*[:=]\s*(\d+(?:\.\d+)?)'
    match = re.search(xy_pattern, text, re.IGNORECASE)
    if match:
        return (float(match.group(1)), float(match.group(2)))
    
    return None


def scale_coordinates_for_resized_image(
    norm_x: float,
    norm_y: float,
    original_width: int,
    original_height: int,
    resized_width: int,
    resized_height: int
) -> Tuple[float, float]:
    """
    Handle coordinate scaling when screenshot was resized before VLM processing.
    
    If the screenshot was resized to fit max_size before sending to VLM,
    coordinates are still normalized to [0, 1000] relative to the resized image,
    so they should still map correctly to the original resolution.
    
    This function is provided for edge cases where additional scaling is needed.
    
    Args:
        norm_x, norm_y: Normalized coordinates from VLM
        original_width, original_height: Original screen dimensions
        resized_width, resized_height: Dimensions of image sent to VLM
    
    Returns:
        Adjusted normalized coordinates
    """
    # In most cases with Qwen3-VL, the normalized output [0-1000] should
    # directly map to the full image regardless of resize, so no adjustment needed
    # This function is here for potential edge cases
    return (norm_x, norm_y)
