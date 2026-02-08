"""
Tests for screenshot capture module.
"""

import pytest
import sys
import base64
from pathlib import Path
from unittest.mock import MagicMock, patch

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))


class TestScreenCapture:
    """Test ScreenCapture class."""
    
    def test_import(self):
        """Test module can be imported."""
        from src.capture import ScreenCapture, capture_screen, get_screen_size
        assert ScreenCapture is not None
    
    def test_screen_size(self):
        """Test screen size detection."""
        from src.capture import ScreenCapture
        
        with ScreenCapture() as sc:
            width, height = sc.get_screen_size()
            
            # Should return reasonable values
            assert width > 0
            assert height > 0
            assert width >= 640  # Minimum reasonable width
            assert height >= 480  # Minimum reasonable height
    
    def test_capture_returns_image(self):
        """Test capture returns a PIL Image."""
        from src.capture import ScreenCapture
        from PIL import Image
        
        with ScreenCapture() as sc:
            img = sc.capture_screen()
            
            assert isinstance(img, Image.Image)
            assert img.size[0] > 0
            assert img.size[1] > 0
    
    def test_capture_with_max_size(self):
        """Test capture respects max_size."""
        from src.capture import ScreenCapture
        
        max_size = 720
        with ScreenCapture(max_size=max_size) as sc:
            img = sc.capture_screen()
            
            # Largest dimension should be <= max_size
            assert max(img.size) <= max_size
    
    def test_base64_output(self):
        """Test base64 screenshot output."""
        from src.capture import ScreenCapture
        
        with ScreenCapture() as sc:
            b64_str, size = sc.get_base64_screenshot()
            
            # Should be valid base64
            assert isinstance(b64_str, str)
            assert len(b64_str) > 0
            
            # Should decode without error
            decoded = base64.b64decode(b64_str)
            assert len(decoded) > 0
            
            # Size should be tuple of ints
            assert isinstance(size, tuple)
            assert len(size) == 2
            assert all(isinstance(x, int) for x in size)
    
    def test_benchmark_capture(self):
        """Test capture benchmark function."""
        from src.capture import ScreenCapture
        
        with ScreenCapture() as sc:
            avg_time = sc.benchmark_capture(iterations=3)
            
            # Should return positive number in milliseconds
            assert avg_time > 0
            # Should be reasonably fast (under 500ms)
            assert avg_time < 500
    
    def test_context_manager(self):
        """Test context manager cleanup."""
        from src.capture import ScreenCapture
        
        sc = ScreenCapture()
        with sc:
            _ = sc.capture_screen()
        
        # After exit, internal sct should be closed
        assert sc._sct is None


class TestConvenienceFunctions:
    """Test module-level convenience functions."""
    
    def test_capture_screen_function(self):
        """Test standalone capture_screen function."""
        from src.capture import capture_screen
        from PIL import Image
        
        img = capture_screen()
        assert isinstance(img, Image.Image)
    
    def test_get_screen_size_function(self):
        """Test standalone get_screen_size function."""
        from src.capture import get_screen_size
        
        width, height = get_screen_size()
        assert width > 0
        assert height > 0
    
    def test_capture_to_base64_function(self):
        """Test standalone capture_to_base64 function."""
        from src.capture import capture_to_base64
        
        b64_str, size = capture_to_base64()
        assert isinstance(b64_str, str)
        assert len(b64_str) > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
