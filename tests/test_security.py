"""
Tests for Rin Security Module — verifies auth, rate limiting, and body size enforcement.
"""
import os
import sys
import pytest

# Ensure project root is on path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi import FastAPI
from fastapi.testclient import TestClient
from src.security import (
    APIKeyMiddleware,
    RateLimitMiddleware,
    BodySizeLimitMiddleware,
    setup_security,
    generate_api_key,
    load_api_key,
    ensure_api_key,
    validate_api_key,
    regenerate_api_key,
    API_KEY_FILE,
)


TEST_KEY = "test_api_key_abc123"


def _make_app(api_key=TEST_KEY):
    """Create a minimal FastAPI app with security middleware."""
    app = FastAPI()

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.get("/state")
    async def state():
        return {"status": "idle"}

    @app.post("/agent/start")
    async def agent_start():
        return {"status": "started"}

    @app.post("/task")
    async def submit_task():
        return {"status": "queued"}

    # Wire security
    app.add_middleware(BodySizeLimitMiddleware)
    app.add_middleware(RateLimitMiddleware, normal_rpm=5, lifecycle_rpm=2)
    app.add_middleware(APIKeyMiddleware, api_key=api_key)

    return app


# ═══════════════════════════════════════════════════
# Auth Tests
# ═══════════════════════════════════════════════════

class TestAPIKeyAuth:
    """Verify that API key authentication actually blocks/allows requests."""

    def setup_method(self):
        self.app = _make_app()
        self.client = TestClient(self.app)

    def test_health_is_public(self):
        """Health endpoint should always be accessible without a key."""
        r = self.client.get("/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

    def test_protected_endpoint_without_key_returns_401(self):
        """Requests to protected endpoints without key should get 401."""
        # TestClient uses 'testclient' as the host, not 127.0.0.1,
        # so it won't be treated as localhost
        r = self.client.get("/state", headers={"X-Forwarded-For": "192.168.1.50"})
        assert r.status_code == 401
        assert "Unauthorized" in r.json()["message"]

    def test_protected_endpoint_with_wrong_key_returns_401(self):
        """Requests with an incorrect key should get 401."""
        r = self.client.get(
            "/state",
            headers={
                "Authorization": "Bearer wrong_key",
                "X-Forwarded-For": "192.168.1.50",
            },
        )
        assert r.status_code == 401

    def test_protected_endpoint_with_correct_key_passes(self):
        """Requests with the correct key should succeed."""
        r = self.client.get(
            "/state",
            headers={
                "Authorization": f"Bearer {TEST_KEY}",
                "X-Forwarded-For": "192.168.1.50",
            },
        )
        assert r.status_code == 200
        assert r.json()["status"] == "idle"

    def test_post_endpoint_with_correct_key_passes(self):
        """POST endpoints should also pass with correct key."""
        r = self.client.post(
            "/agent/start",
            headers={
                "Authorization": f"Bearer {TEST_KEY}",
                "X-Forwarded-For": "192.168.1.50",
            },
        )
        assert r.status_code == 200
        assert r.json()["status"] == "started"

    @pytest.mark.skip(reason="TestClient uses 'testclient' as client.host; X-Forwarded-For deliberately untrusted")
    def test_localhost_bypasses_auth(self):
        """Requests from localhost should pass without any key.
        NOTE: This cannot be tested with TestClient — it requires a real
        loopback connection where request.client.host == '127.0.0.1'.
        """
        r = self.client.get(
            "/state",
            headers={"X-Forwarded-For": "127.0.0.1"},
        )
        assert r.status_code == 200


# ═══════════════════════════════════════════════════
# Rate Limit Tests
# ═══════════════════════════════════════════════════

class TestRateLimiting:
    """Verify rate limiting actually blocks after threshold."""

    def setup_method(self):
        self.app = _make_app()
        self.client = TestClient(self.app)
        self.auth = {
            "Authorization": f"Bearer {TEST_KEY}",
            "X-Forwarded-For": "10.0.0.99",
        }

    def test_rate_limit_blocks_after_threshold(self):
        """Normal endpoints should block after 5 requests (configured above)."""
        # First 5 requests should pass
        for i in range(5):
            r = self.client.get("/state", headers=self.auth)
            assert r.status_code == 200, f"Request {i+1} should pass"

        # 6th request should be rate limited
        r = self.client.get("/state", headers=self.auth)
        assert r.status_code == 429
        assert "Rate limit" in r.json()["message"]

    def test_lifecycle_rate_limit_is_stricter(self):
        """Lifecycle endpoints should block after 2 requests (configured above)."""
        for i in range(2):
            r = self.client.post("/agent/start", headers=self.auth)
            assert r.status_code == 200, f"Request {i+1} should pass"

        # 3rd request should be blocked
        r = self.client.post("/agent/start", headers=self.auth)
        assert r.status_code == 429

    @pytest.mark.skip(reason="TestClient uses 'testclient' as client.host; X-Forwarded-For deliberately untrusted")
    def test_localhost_exempt_from_rate_limit(self):
        """Localhost requests should never be rate limited.
        NOTE: This cannot be tested with TestClient — requires real loopback.
        """
        headers = {"X-Forwarded-For": "127.0.0.1"}
        for _ in range(20):
            r = self.client.get("/state", headers=headers)
            assert r.status_code == 200


# ═══════════════════════════════════════════════════
# Body Size Tests
# ═══════════════════════════════════════════════════

class TestBodySizeLimit:
    """Verify body size limiter blocks oversized requests."""

    def setup_method(self):
        self.app = _make_app()
        self.client = TestClient(self.app)
        self.auth = {
            "Authorization": f"Bearer {TEST_KEY}",
            "X-Forwarded-For": "10.0.0.99",
        }

    def test_small_body_passes(self):
        """Normal-sized POST body should pass."""
        r = self.client.post(
            "/task",
            json={"command": "hello"},
            headers=self.auth,
        )
        assert r.status_code == 200

    def test_oversized_body_rejected(self):
        """Bodies over 1MB should be rejected with 413."""
        oversized = "x" * (1024 * 1024 + 1)  # Just over 1MB
        r = self.client.post(
            "/task",
            content=oversized,
            headers={
                **self.auth,
                "Content-Type": "application/json",
                "Content-Length": str(len(oversized)),
            },
        )
        assert r.status_code == 413


# ═══════════════════════════════════════════════════
# Key Management Tests
# ═══════════════════════════════════════════════════

class TestKeyManagement:
    """Verify API key generation and loading."""

    def test_generate_and_load_key(self, tmp_path):
        """Generated key should be loadable from disk."""
        import src.security as sec
        # Temporarily redirect key file
        original = sec.API_KEY_FILE
        sec.API_KEY_FILE = tmp_path / "api_key.txt"
        try:
            key = generate_api_key()
            assert len(key) == 64  # 32 bytes hex = 64 chars
            loaded = load_api_key()
            assert loaded == key
        finally:
            sec.API_KEY_FILE = original

    def test_ensure_key_creates_if_missing(self, tmp_path):
        """ensure_api_key should auto-generate when no key file exists."""
        import src.security as sec
        original = sec.API_KEY_FILE
        sec.API_KEY_FILE = tmp_path / "api_key.txt"
        try:
            key = ensure_api_key()
            assert len(key) == 64
            assert (tmp_path / "api_key.txt").exists()
        finally:
            sec.API_KEY_FILE = original


# ═══════════════════════════════════════════════════
# Token Security Tests
# ═══════════════════════════════════════════════════

class TestTokenSecurity:
    """Verify token generation quality, validation, and regeneration."""

    def test_token_is_64_hex_chars(self, tmp_path):
        """Generated token must be exactly 64 hex characters (256 bits)."""
        import src.security as sec
        original = sec.API_KEY_FILE
        sec.API_KEY_FILE = tmp_path / "api_key.txt"
        try:
            key = generate_api_key()
            assert len(key) == 64, f"Expected 64 chars, got {len(key)}"
            # Must be valid hex
            int(key, 16)
        finally:
            sec.API_KEY_FILE = original

    def test_token_is_unique_across_generations(self, tmp_path):
        """100 generated tokens should all be unique."""
        import src.security as sec
        original = sec.API_KEY_FILE
        sec.API_KEY_FILE = tmp_path / "api_key.txt"
        try:
            keys = set()
            for _ in range(100):
                key = generate_api_key()
                keys.add(key)
            assert len(keys) == 100, "Generated keys are not unique"
        finally:
            sec.API_KEY_FILE = original

    def test_token_has_sufficient_entropy(self, tmp_path):
        """Each generated token should use at least 10 distinct hex digits."""
        import src.security as sec
        original = sec.API_KEY_FILE
        sec.API_KEY_FILE = tmp_path / "api_key.txt"
        try:
            for _ in range(50):
                key = generate_api_key()
                distinct = len(set(key.lower()))
                assert distinct >= 10, (
                    f"Key has only {distinct} distinct hex digits: {key}"
                )
        finally:
            sec.API_KEY_FILE = original

    def test_validate_rejects_weak_keys(self):
        """validate_api_key should reject keys that are too short, non-hex, or trivial."""
        # Too short
        assert not validate_api_key("")
        assert not validate_api_key("abcd1234")
        assert not validate_api_key("a" * 63)

        # Non-hex characters
        assert not validate_api_key("g" * 64)
        assert not validate_api_key("xyz!" * 16)

        # All same character (low entropy — only 1 distinct digit)
        assert not validate_api_key("0" * 64)
        assert not validate_api_key("a" * 64)
        assert not validate_api_key("f" * 64)

        # Only a few distinct digits
        assert not validate_api_key("01" * 32)  # 2 distinct
        assert not validate_api_key("0123" * 16)  # 4 distinct

    def test_validate_accepts_good_keys(self, tmp_path):
        """validate_api_key should accept properly generated keys."""
        import src.security as sec
        original = sec.API_KEY_FILE
        sec.API_KEY_FILE = tmp_path / "api_key.txt"
        try:
            for _ in range(20):
                key = generate_api_key()
                assert validate_api_key(key), f"Valid key rejected: {key}"
        finally:
            sec.API_KEY_FILE = original

    def test_regenerate_produces_different_key(self, tmp_path):
        """regenerate_api_key must produce a different key than the current one."""
        import src.security as sec
        original = sec.API_KEY_FILE
        sec.API_KEY_FILE = tmp_path / "api_key.txt"
        try:
            old_key = generate_api_key()
            new_key = regenerate_api_key()
            assert old_key != new_key, "Regenerated key is identical to old key"
            assert len(new_key) == 64
            # New key should be on disk
            loaded = load_api_key()
            assert loaded == new_key
        finally:
            sec.API_KEY_FILE = original

    def test_ensure_regenerates_weak_stored_key(self, tmp_path):
        """ensure_api_key should replace a weak key found on disk."""
        import src.security as sec
        original = sec.API_KEY_FILE
        sec.API_KEY_FILE = tmp_path / "api_key.txt"
        try:
            # Write a weak key
            (tmp_path / "api_key.txt").write_text("0" * 64, encoding="utf-8")
            key = ensure_api_key()
            # Should have regenerated
            assert key != "0" * 64
            assert validate_api_key(key)
        finally:
            sec.API_KEY_FILE = original

    def test_validate_rejects_none_and_empty(self):
        """validate_api_key should handle None and empty string gracefully."""
        assert not validate_api_key(None)
        assert not validate_api_key("")
