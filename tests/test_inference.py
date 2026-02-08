"""
Tests for VLM inference client (no live server required).
"""

import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.inference import VLMClient, MockVLMClient, VLMResponse


class TestVLMClient:
    """Test VLMClient behavior (session, defaults)."""

    def test_client_has_session(self):
        """Client uses a persistent session for connection reuse."""
        client = VLMClient(base_url="http://127.0.0.1:8080")
        assert hasattr(client, "_session")
        assert client._session is not None

    def test_default_max_tokens_in_send_request(self):
        """Default max_tokens is 512 for faster completion."""
        import inspect
        sig = inspect.signature(VLMClient.send_request)
        assert sig.parameters["max_tokens"].default == 1024


class TestMockVLMClient:
    """Test MockVLMClient for offline validation."""

    def test_mock_returns_added_response(self):
        """Mock returns queued response."""
        client = MockVLMClient()
        client.add_mock_response({"action": "CLICK", "confidence": 0.9})
        resp = client.send_request("test", image_base64="dGVzdA==")
        assert resp.success
        assert resp.parsed_json["action"] == "CLICK"
        assert resp.parsed_json["confidence"] == 0.9

    def test_mock_health_always_ok(self):
        """Mock health check always passes."""
        client = MockVLMClient()
        assert client.check_health() is True

    def test_analyze_screenshot_mock(self):
        """analyze_screenshot with mock returns parsed action."""
        client = MockVLMClient()
        client.add_mock_response({
            "thought": "Found button",
            "action": "CLICK",
            "coordinates": {"x": 500, "y": 300},
            "confidence": 0.95,
            "task_complete": False
        })
        parsed, raw = client.analyze_screenshot("dGVzdA==", "Click the submit button")
        assert parsed is not None
        assert parsed["action"] == "CLICK"
        assert parsed["confidence"] == 0.95


class TestVLMAbortCheck:
    """Test VLM abort check mechanism for stop button."""

    def test_abort_check_default_none(self):
        """abort_check callback is None by default."""
        client = VLMClient()
        assert client._abort_check is None
        assert client._should_abort() is False

    def test_set_abort_check_callback(self):
        """set_abort_check stores the callback."""
        client = VLMClient()
        client.set_abort_check(lambda: True)
        assert client._abort_check is not None
        assert client._should_abort() is True

    def test_should_abort_returns_callback_result(self):
        """_should_abort returns the callback result."""
        client = VLMClient()
        flag = [False]
        client.set_abort_check(lambda: flag[0])
        
        assert client._should_abort() is False
        flag[0] = True
        assert client._should_abort() is True

    def test_mock_client_respects_abort(self):
        """MockVLMClient also has abort check capability."""
        client = MockVLMClient()
        client.set_abort_check(lambda: True)
        assert client._should_abort() is True

