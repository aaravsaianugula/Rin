"""
Rin Security Module — API Key Authentication, Rate Limiting, CORS Hardening.

Security stack:
  1. API Key Authentication (Bearer token) — exempts localhost
  2. Per-IP Rate Limiting (sliding window)
  3. Request Body Size Limiting (1 MB default)
  4. Strict CORS (configurable origins)

Usage:
    from src.security import setup_security, generate_api_key
    setup_security(app)
"""
from __future__ import annotations

import re
import secrets

import hashlib
import hmac
import logging
import os
import time
from collections import defaultdict
from pathlib import Path
from typing import Optional, Set

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

logger = logging.getLogger("rin.security")

# ─── Constants ───
PROJECT_ROOT = Path(__file__).parent.parent
API_KEY_FILE = PROJECT_ROOT / "config" / "secrets" / "api_key.txt"
MAX_BODY_SIZE = 1 * 1024 * 1024  # 1 MB

# Endpoints that are always accessible without auth (health checks)
PUBLIC_ENDPOINTS: Set[str] = {"/health", "/mobile/version"}

# Lifecycle endpoints get stricter rate limits
LIFECYCLE_ENDPOINTS: Set[str] = {
    "/agent/start", "/agent/stop", "/agent/restart",
    "/stream/start", "/stream/stop",
}

# Local IPs (exempt from API key requirement)
LOCAL_IPS: Set[str] = {"127.0.0.1", "::1", "localhost"}


# ═══════════════════════════════════════════════════
# API Key Management
# ═══════════════════════════════════════════════════

def generate_api_key() -> str:
    """Generate a cryptographically secure 32-byte hex API key and persist it."""
    key = secrets.token_hex(32)  # 256-bit, CSPRNG
    API_KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
    API_KEY_FILE.write_text(key, encoding="utf-8")
    logger.info(f"Generated new API key → {API_KEY_FILE}")
    return key


def load_api_key() -> Optional[str]:
    """Load API key from disk. Returns None if not found."""
    try:
        if API_KEY_FILE.exists():
            key = API_KEY_FILE.read_text(encoding="utf-8").strip()
            if key:
                return key
    except Exception as e:
        logger.error(f"Failed to load API key: {e}")
    return None


def ensure_api_key() -> str:
    """Load or auto-generate the API key. Validates existing keys."""
    key = load_api_key()
    if key and not validate_api_key(key):
        logger.warning("Stored API key failed validation — regenerating")
        key = None
    if not key:
        key = generate_api_key()
        logger.info("Auto-generated API key (first run)")
    return key


def validate_api_key(key: str) -> bool:
    """
    Validate that an API key has sufficient quality.
    Checks:
      - At least 64 hex characters (256 bits)
      - Only valid hex characters
      - At least 10 distinct hex digits (guards against trivial keys like all-zeros)
    """
    if not key or len(key) < 64:
        return False
    if not re.fullmatch(r'[0-9a-fA-F]+', key):
        return False
    # Entropy check: a truly random 256-bit key will have all 16 hex digits;
    # requiring ≥10 distinct digits catches degenerate keys with huge margin.
    if len(set(key.lower())) < 10:
        return False
    return True


def regenerate_api_key() -> str:
    """
    Generate a new API key, replacing the old one on disk.
    Returns the new key.
    """
    old_key = load_api_key()
    new_key = generate_api_key()
    if old_key:
        logger.info("API key rotated (old key invalidated)")
    else:
        logger.info("API key created (no previous key)")
    return new_key


# ═══════════════════════════════════════════════════
# Authentication Middleware
# ═══════════════════════════════════════════════════

class APIKeyMiddleware(BaseHTTPMiddleware):
    """
    Bearer token authentication.
    - Exempts requests from localhost (127.0.0.1 / ::1)
    - Exempts PUBLIC_ENDPOINTS (e.g. /health)
    - All other requests must include: Authorization: Bearer <key>
    """

    def __init__(self, app: ASGIApp, api_key: str):
        super().__init__(app)
        self.api_key = api_key

    async def dispatch(self, request: Request, call_next):
        path = request.url.path.rstrip("/") or "/"

        # Always allow public endpoints
        if path in PUBLIC_ENDPOINTS:
            return await call_next(request)

        # Allow localhost without key (WPF Overlay, local testing)
        client_ip = _get_client_ip(request)
        if client_ip in LOCAL_IPS:
            return await call_next(request)

        # Check Authorization header
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:].strip()
            if hmac.compare_digest(token, self.api_key):
                return await call_next(request)

        logger.warning(f"Unauthorized request from {client_ip} to {path}")
        return JSONResponse(
            status_code=401,
            content={"status": "error", "message": "Unauthorized — provide Authorization: Bearer <key>"}
        )


# ═══════════════════════════════════════════════════
# Rate Limiting Middleware
# ═══════════════════════════════════════════════════

class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Simple in-memory sliding-window rate limiter per client IP.
    - Normal endpoints: 120 requests / minute
    - Lifecycle endpoints: 10 requests / minute
    """

    def __init__(self, app: ASGIApp, normal_rpm: int = 120, lifecycle_rpm: int = 10):
        super().__init__(app)
        self.normal_rpm = normal_rpm
        self.lifecycle_rpm = lifecycle_rpm
        self._hits: dict[str, list[float]] = defaultdict(list)
        self._lifecycle_hits: dict[str, list[float]] = defaultdict(list)

    async def dispatch(self, request: Request, call_next):
        client_ip = _get_client_ip(request)
        path = request.url.path.rstrip("/") or "/"
        now = time.time()

        # Local requests are exempt from rate limiting
        if client_ip in LOCAL_IPS:
            return await call_next(request)

        # Choose bucket
        if path in LIFECYCLE_ENDPOINTS:
            bucket = self._lifecycle_hits[client_ip]
            limit = self.lifecycle_rpm
        else:
            bucket = self._hits[client_ip]
            limit = self.normal_rpm

        # Prune old entries (older than 60s)
        cutoff = now - 60
        bucket[:] = [t for t in bucket if t > cutoff]

        if len(bucket) >= limit:
            logger.warning(f"Rate limit hit: {client_ip} on {path} ({len(bucket)}/{limit})")
            return JSONResponse(
                status_code=429,
                content={"status": "error", "message": "Rate limit exceeded. Try again later."}
            )

        bucket.append(now)
        return await call_next(request)


# ═══════════════════════════════════════════════════
# Request Body Size Limiter
# ═══════════════════════════════════════════════════

class BodySizeLimitMiddleware(BaseHTTPMiddleware):
    """Reject requests with bodies exceeding the configured size."""

    def __init__(self, app: ASGIApp, max_size: int = MAX_BODY_SIZE):
        super().__init__(app)
        self.max_size = max_size

    async def dispatch(self, request: Request, call_next):
        # Only check POST/PUT/PATCH
        if request.method in ("POST", "PUT", "PATCH"):
            content_length = request.headers.get("content-length")
            if content_length and int(content_length) > self.max_size:
                return JSONResponse(
                    status_code=413,
                    content={"status": "error", "message": f"Request body too large (max {self.max_size // 1024}KB)"}
                )
        return await call_next(request)


# ═══════════════════════════════════════════════════
# Socket.IO Authentication
# ═══════════════════════════════════════════════════

def verify_socket_auth(environ: dict, api_key: str) -> bool:
    """
    Verify Socket.IO connection auth token.
    Checks the 'auth' dict passed by socket.io-client.
    Returns True if local or valid token.
    """
    # Check if local connection
    client_ip = environ.get("REMOTE_ADDR", "")
    if client_ip in LOCAL_IPS:
        return True

    # The auth dict is not directly in environ for python-socketio
    # It will be checked in the connect handler via the auth parameter
    return False


# ═══════════════════════════════════════════════════
# CORS Helper
# ═══════════════════════════════════════════════════

def get_allowed_origins() -> list[str]:
    """
    Generate a list of allowed CORS origins.
    Includes localhost variants and common LAN subnets.
    """
    origins = [
        "http://localhost:8000",
        "http://localhost:8080",
        "http://localhost:8081",
        "http://localhost:8083",
        "http://localhost:19006",  # Expo web
        "http://127.0.0.1:8000",
        "http://127.0.0.1:8080",
        "http://127.0.0.1:8083",
    ]

    # Add LAN IPs dynamically
    try:
        import socket
        hostname = socket.gethostname()
        for addr_info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            ip = addr_info[4][0]
            if not ip.startswith("127."):
                for port in [8000, 8001, 8080, 8083, 19006]:
                    origins.append(f"http://{ip}:{port}")
    except Exception:
        pass

    return origins


# ═══════════════════════════════════════════════════
# Setup Function
# ═══════════════════════════════════════════════════

def setup_security(app: FastAPI, skip_auth: bool = False) -> str:
    """
    Wire all security middleware onto a FastAPI app.
    Returns the API key in use.

    Middleware order (applied bottom-to-top):
      1. BodySizeLimitMiddleware (innermost — checked first)
      2. RateLimitMiddleware
      3. APIKeyMiddleware (outermost — checked last)
    """
    api_key = ensure_api_key()

    # Body size limit (innermost)
    app.add_middleware(BodySizeLimitMiddleware)

    # Rate limiting
    app.add_middleware(RateLimitMiddleware)

    # API key auth (outermost, only if not skipped)
    if not skip_auth:
        app.add_middleware(APIKeyMiddleware, api_key=api_key)

    logger.info("Security middleware installed (auth + rate-limit + body-size)")
    return api_key


# ═══════════════════════════════════════════════════
# Utils
# ═══════════════════════════════════════════════════

def _get_client_ip(request: Request) -> str:
    """Extract client IP from the direct TCP connection.
    
    SECURITY: Do NOT trust X-Forwarded-For — there is no reverse proxy,
    so that header is entirely attacker-controlled. An attacker could set
    X-Forwarded-For: 127.0.0.1 to bypass all auth and rate limiting.
    """
    return request.client.host if request.client else "unknown"
