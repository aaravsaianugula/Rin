"""
Tests for coordinate conversion module.
"""

import pytest
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.coordinates import (
    NORMALIZED_MAX,
    BoundingBox,
    PixelBoundingBox,
    Point,
    normalized_to_pixels,
    normalized_to_pixels_x,
    normalized_to_pixels_y,
    pixels_to_normalized,
    bbox_center,
    validate_normalized_coordinates,
    validate_pixel_coordinates,
    clamp_to_screen,
    parse_bbox_json,
    parse_multiple_bboxes,
    extract_coordinates_from_text,
)


class TestNormalizedToPixels:
    """Test normalized to pixel coordinate conversion."""
    
    def test_origin(self):
        """Test (0, 0) maps to (0, 0)."""
        x, y = normalized_to_pixels(0, 0, 1920, 1080)
        assert x == 0
        assert y == 0
    
    def test_max_corner(self):
        """Test (1000, 1000) maps to screen dimensions."""
        x, y = normalized_to_pixels(1000, 1000, 1920, 1080)
        assert x == 1920
        assert y == 1080
    
    def test_center(self):
        """Test (500, 500) maps to screen center."""
        x, y = normalized_to_pixels(500, 500, 1920, 1080)
        assert x == 960
        assert y == 540
    
    def test_quarter_points(self):
        """Test quarter points."""
        # Top-left quarter
        x, y = normalized_to_pixels(250, 250, 1920, 1080)
        assert x == 480
        assert y == 270
        
        # Bottom-right quarter
        x, y = normalized_to_pixels(750, 750, 1920, 1080)
        assert x == 1440
        assert y == 810


class TestPixelsToNormalized:
    """Test pixel to normalized coordinate conversion."""
    
    def test_origin(self):
        """Test (0, 0) maps to (0, 0)."""
        x, y = pixels_to_normalized(0, 0, 1920, 1080)
        assert x == 0
        assert y == 0
    
    def test_max_corner(self):
        """Test screen max maps to (1000, 1000)."""
        x, y = pixels_to_normalized(1920, 1080, 1920, 1080)
        assert x == 1000
        assert y == 1000
    
    def test_center(self):
        """Test screen center maps to (500, 500)."""
        x, y = pixels_to_normalized(960, 540, 1920, 1080)
        assert x == 500
        assert y == 500
    
    def test_roundtrip(self):
        """Test conversion roundtrip."""
        norm_x, norm_y = 333, 666
        px_x, px_y = normalized_to_pixels(norm_x, norm_y, 1920, 1080)
        back_x, back_y = pixels_to_normalized(px_x, px_y, 1920, 1080)
        
        # Allow small floating point differences
        assert abs(back_x - norm_x) < 1
        assert abs(back_y - norm_y) < 1


class TestBBoxCenter:
    """Test bounding box center calculation."""
    
    def test_simple_bbox(self):
        """Test simple bounding box center."""
        cx, cy = bbox_center(0, 0, 100, 100)
        assert cx == 50
        assert cy == 50
    
    def test_offset_bbox(self):
        """Test offset bounding box."""
        cx, cy = bbox_center(100, 200, 300, 400)
        assert cx == 200
        assert cy == 300


class TestValidation:
    """Test coordinate validation."""
    
    def test_valid_normalized(self):
        """Test valid normalized coordinates."""
        assert validate_normalized_coordinates(0, 0) == True
        assert validate_normalized_coordinates(500, 500) == True
        assert validate_normalized_coordinates(1000, 1000) == True
    
    def test_invalid_normalized(self):
        """Test invalid normalized coordinates."""
        assert validate_normalized_coordinates(-1, 0) == False
        assert validate_normalized_coordinates(0, -1) == False
        assert validate_normalized_coordinates(1001, 0) == False
        assert validate_normalized_coordinates(0, 1001) == False
    
    def test_valid_pixels(self):
        """Test valid pixel coordinates."""
        assert validate_pixel_coordinates(0, 0, 1920, 1080) == True
        assert validate_pixel_coordinates(960, 540, 1920, 1080) == True
        assert validate_pixel_coordinates(1919, 1079, 1920, 1080) == True
    
    def test_invalid_pixels(self):
        """Test invalid pixel coordinates."""
        assert validate_pixel_coordinates(-1, 0, 1920, 1080) == False
        assert validate_pixel_coordinates(0, -1, 1920, 1080) == False
        assert validate_pixel_coordinates(1920, 0, 1920, 1080) == False
        assert validate_pixel_coordinates(0, 1080, 1920, 1080) == False


class TestClampToScreen:
    """Test coordinate clamping."""
    
    def test_valid_coords_unchanged(self):
        """Valid coordinates should be unchanged."""
        x, y = clamp_to_screen(500, 500, 1920, 1080)
        assert x == 500
        assert y == 500
    
    def test_negative_clamped(self):
        """Negative coordinates should be clamped to 0."""
        x, y = clamp_to_screen(-100, -50, 1920, 1080)
        assert x == 0
        assert y == 0
    
    def test_overflow_clamped(self):
        """Overflow coordinates should be clamped to max."""
        x, y = clamp_to_screen(2000, 1200, 1920, 1080)
        assert x == 1919
        assert y == 1079


class TestParseBBoxJson:
    """Test bounding box JSON parsing."""
    
    def test_valid_bbox(self):
        """Test parsing valid bbox JSON."""
        json_str = '{"bbox_2d": [100, 200, 300, 400], "label": "button"}'
        bbox = parse_bbox_json(json_str)
        
        assert bbox is not None
        assert bbox.x1 == 100
        assert bbox.y1 == 200
        assert bbox.x2 == 300
        assert bbox.y2 == 400
        assert bbox.label == "button"
    
    def test_invalid_json(self):
        """Test parsing invalid JSON returns None."""
        assert parse_bbox_json("not json") is None
        assert parse_bbox_json("{}") is None
        assert parse_bbox_json('{"bbox_2d": [1, 2]}') is None  # Too few coords


class TestBoundingBoxClass:
    """Test BoundingBox dataclass."""
    
    def test_center_property(self):
        """Test center calculation."""
        bbox = BoundingBox(0, 0, 200, 100, "test")
        cx, cy = bbox.center
        assert cx == 100
        assert cy == 50
    
    def test_dimensions(self):
        """Test width/height calculation."""
        bbox = BoundingBox(100, 200, 400, 500, "test")
        assert bbox.width == 300
        assert bbox.height == 300
    
    def test_to_pixels(self):
        """Test conversion to pixel bbox."""
        bbox = BoundingBox(0, 0, 500, 500, "test")
        pixel_bbox = bbox.to_pixels(1920, 1080)
        
        assert isinstance(pixel_bbox, PixelBoundingBox)
        assert pixel_bbox.x1 == 0
        assert pixel_bbox.y1 == 0
        assert pixel_bbox.x2 == 960
        assert pixel_bbox.y2 == 540


class TestExtractCoordinates:
    """Test coordinate extraction from text."""
    
    def test_json_format(self):
        """Test extracting JSON-style coordinates."""
        text = 'The button is at "coordinates": {"x": 450, "y": 320}.'
        coords = extract_coordinates_from_text(text)
        assert coords == (450.0, 320.0)
    
    def test_tuple_format(self):
        """Test extracting tuple-style coordinates."""
        text = "Click at position (600, 400)"
        coords = extract_coordinates_from_text(text)
        assert coords == (600.0, 400.0)
    
    def test_xy_format(self):
        """Test extracting x: y: format."""
        text = "Located at x: 123, y: 456"
        coords = extract_coordinates_from_text(text)
        assert coords == (123.0, 456.0)
    
    def test_no_coords(self):
        """Test text with no coordinates."""
        text = "There are no coordinates here."
        assert extract_coordinates_from_text(text) is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
