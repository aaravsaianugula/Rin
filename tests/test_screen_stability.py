"""
Tests for screen stability detection.
"""

import pytest
from unittest.mock import MagicMock, patch
from PIL import Image
import numpy as np


class TestImageDifference:
    """Test the image difference calculation."""
    
    def test_identical_images_have_zero_diff(self):
        from src.screen_stability import calculate_image_difference
        
        # Create two identical images
        img = Image.fromarray(np.zeros((100, 100, 3), dtype=np.uint8))
        
        diff = calculate_image_difference(img, img)
        assert diff == 0.0
    
    def test_completely_different_images(self):
        from src.screen_stability import calculate_image_difference
        
        # Black and white images
        black = Image.fromarray(np.zeros((100, 100, 3), dtype=np.uint8))
        white = Image.fromarray(np.full((100, 100, 3), 255, dtype=np.uint8))
        
        diff = calculate_image_difference(black, white)
        assert diff == 1.0  # 100% different
    
    def test_partial_difference(self):
        from src.screen_stability import calculate_image_difference
        
        # Create images where exactly half the pixels differ
        arr1 = np.zeros((100, 100, 3), dtype=np.uint8)
        arr2 = np.zeros((100, 100, 3), dtype=np.uint8)
        arr2[50:, :, :] = 255  # Bottom half is white
        
        img1 = Image.fromarray(arr1)
        img2 = Image.fromarray(arr2)
        
        diff = calculate_image_difference(img1, img2)
        assert 0.45 <= diff <= 0.55  # Approximately 50%


class TestScreenStability:
    """Test the screen stability detection logic."""
    
    def test_stable_screen_detected_quickly(self):
        from src.screen_stability import wait_for_screen_stable
        
        # Mock capture that always returns the same image
        mock_capture = MagicMock()
        static_img = Image.fromarray(np.zeros((100, 100, 3), dtype=np.uint8))
        mock_capture.capture_screen.return_value = static_img
        
        stable, elapsed = wait_for_screen_stable(
            mock_capture,
            threshold=0.02,
            max_wait=1.0,
            check_interval=0.05,
            min_stable_frames=2
        )
        
        assert stable is True
        assert elapsed < 0.5  # Should be quick for static screen
    
    def test_changing_screen_times_out(self):
        from src.screen_stability import wait_for_screen_stable
        
        # Mock capture that returns different images each time
        call_count = [0]
        def changing_screen():
            call_count[0] += 1
            # Return completely different image each time
            arr = np.full((100, 100, 3), call_count[0] * 50 % 256, dtype=np.uint8)
            return Image.fromarray(arr)
        
        mock_capture = MagicMock()
        mock_capture.capture_screen.side_effect = changing_screen
        
        stable, elapsed = wait_for_screen_stable(
            mock_capture,
            threshold=0.02,
            max_wait=0.3,  # Short timeout for test
            check_interval=0.05
        )
        
        assert stable is False
        assert elapsed >= 0.3  # Should have waited full duration


class TestWaitForReady:
    """Test the high-level wait_for_ready function."""
    
    def test_ready_when_stable(self):
        from src.screen_stability import wait_for_ready
        
        mock_capture = MagicMock()
        static_img = Image.fromarray(np.zeros((100, 100, 3), dtype=np.uint8))
        mock_capture.capture_screen.return_value = static_img
        
        ready, reason = wait_for_ready(
            mock_capture,
            max_wait=1.0,
            check_cursor=False  # Skip cursor check for test
        )
        
        assert ready is True
        assert "Ready" in reason


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
