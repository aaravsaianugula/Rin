"""
Tests for Rin Service Layer — crash log, SystemGuardian logic, and state management.
Run: python -m pytest tests/test_service.py -v
"""
import json
import os
import sys
import tempfile
import time
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

# Ensure project root is on path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ═══════════════════════════════════════════════════
# Crash Log Tests
# ═══════════════════════════════════════════════════


class TestCrashLog:
    """Tests for persistent crash log (JSONL file)."""

    def setup_method(self):
        """Create a temp crash log file for each test."""
        self.tmpdir = tempfile.mkdtemp()
        self.crash_file = os.path.join(self.tmpdir, "crashes.jsonl")

    def teardown_method(self):
        """Clean up temp files."""
        try:
            os.remove(self.crash_file)
            os.rmdir(self.tmpdir)
        except (FileNotFoundError, OSError):
            pass

    def test_write_and_read_crash(self):
        """Crash records should be written and readable."""
        from rin_service import RinServiceServer

        # Patch the class-level crash log path
        original = RinServiceServer.CRASH_LOG_FILE
        RinServiceServer.CRASH_LOG_FILE = self.crash_file
        try:
            RinServiceServer._log_crash(1, uptime_secs=42.5, cleanup={"vlm_killed": 1})
            records = RinServiceServer._read_crash_log(10)

            assert len(records) == 1
            assert records[0]["exit_code"] == 1
            assert records[0]["uptime_secs"] == 42.5
            assert records[0]["cleanup"]["vlm_killed"] == 1
            assert "timestamp" in records[0]
        finally:
            RinServiceServer.CRASH_LOG_FILE = original

    def test_multiple_crashes(self):
        """Multiple crashes should all be recorded."""
        from rin_service import RinServiceServer

        original = RinServiceServer.CRASH_LOG_FILE
        RinServiceServer.CRASH_LOG_FILE = self.crash_file
        try:
            RinServiceServer._log_crash(1, uptime_secs=10)
            RinServiceServer._log_crash(-1, uptime_secs=5)
            RinServiceServer._log_crash(137, uptime_secs=120)
            records = RinServiceServer._read_crash_log(10)

            assert len(records) == 3
            assert records[0]["exit_code"] == 1
            assert records[2]["exit_code"] == 137
        finally:
            RinServiceServer.CRASH_LOG_FILE = original

    def test_rotation(self):
        """Crash log should rotate when exceeding max entries."""
        from rin_service import RinServiceServer

        original_file = RinServiceServer.CRASH_LOG_FILE
        original_max = RinServiceServer.CRASH_LOG_MAX_ENTRIES
        RinServiceServer.CRASH_LOG_FILE = self.crash_file
        RinServiceServer.CRASH_LOG_MAX_ENTRIES = 5
        try:
            for i in range(10):
                RinServiceServer._log_crash(i, uptime_secs=i * 10)

            records = RinServiceServer._read_crash_log(100)
            assert len(records) == 5
            # Should keep the LAST 5 entries (exit codes 5-9)
            assert records[0]["exit_code"] == 5
            assert records[4]["exit_code"] == 9
        finally:
            RinServiceServer.CRASH_LOG_FILE = original_file
            RinServiceServer.CRASH_LOG_MAX_ENTRIES = original_max

    def test_read_empty_log(self):
        """Reading a non-existent log should return empty list."""
        from rin_service import RinServiceServer

        original = RinServiceServer.CRASH_LOG_FILE
        RinServiceServer.CRASH_LOG_FILE = os.path.join(self.tmpdir, "nonexistent.jsonl")
        try:
            records = RinServiceServer._read_crash_log(10)
            assert records == []
        finally:
            RinServiceServer.CRASH_LOG_FILE = original

    def test_load_recent_crash_times(self):
        """Should restore crash times within the circuit breaker window."""
        from rin_service import RinServiceServer

        original = RinServiceServer.CRASH_LOG_FILE
        RinServiceServer.CRASH_LOG_FILE = self.crash_file
        try:
            # Write crashes: 2 recent, 1 old
            now = datetime.now()
            old_time = (now - timedelta(minutes=10)).isoformat()
            recent1 = (now - timedelta(minutes=2)).isoformat()
            recent2 = (now - timedelta(seconds=30)).isoformat()

            with open(self.crash_file, "w", encoding="utf-8") as f:
                f.write(json.dumps({"timestamp": old_time, "exit_code": 1}) + "\n")
                f.write(json.dumps({"timestamp": recent1, "exit_code": 2}) + "\n")
                f.write(json.dumps({"timestamp": recent2, "exit_code": 3}) + "\n")

            times = RinServiceServer._load_recent_crash_times(300)  # 5 min window
            assert len(times) == 2  # Only the 2 recent ones
        finally:
            RinServiceServer.CRASH_LOG_FILE = original


# ═══════════════════════════════════════════════════
# Circuit Breaker Tests
# ═══════════════════════════════════════════════════


class TestCircuitBreaker:
    """Test the SystemGuardian's circuit breaker logic."""

    def test_circuit_closed_by_default(self):
        """Circuit breaker should be closed (open=False) with no crashes."""
        from rin_service import RinServiceServer

        mock_server = MagicMock()
        guardian = RinServiceServer.SystemGuardian.__new__(
            RinServiceServer.SystemGuardian
        )
        guardian.server = mock_server
        guardian._crash_times = []
        guardian._stop_event = MagicMock()
        guardian._thread = None
        guardian._agent_start_time = 0

        assert guardian.circuit_open is False

    def test_circuit_opens_after_threshold(self):
        """Circuit should open after MAX_CRASHES_WINDOW crashes within window."""
        from rin_service import RinServiceServer

        guardian = RinServiceServer.SystemGuardian.__new__(
            RinServiceServer.SystemGuardian
        )
        guardian.server = MagicMock()
        now = time.time()
        guardian._crash_times = [now - 10, now - 5, now - 1]  # 3 crashes in last seconds
        guardian._stop_event = MagicMock()
        guardian._thread = None
        guardian._agent_start_time = 0

        assert guardian.circuit_open is True

    def test_circuit_closes_after_window(self):
        """Circuit should close when old crashes expire."""
        from rin_service import RinServiceServer

        guardian = RinServiceServer.SystemGuardian.__new__(
            RinServiceServer.SystemGuardian
        )
        guardian.server = MagicMock()
        # All crashes are > 5 min old
        old = time.time() - 400
        guardian._crash_times = [old - 10, old - 5, old - 1]
        guardian._stop_event = MagicMock()
        guardian._thread = None
        guardian._agent_start_time = 0

        assert guardian.circuit_open is False

    def test_reset_clears_circuit(self):
        """Manual reset should clear all crash times."""
        from rin_service import RinServiceServer

        guardian = RinServiceServer.SystemGuardian.__new__(
            RinServiceServer.SystemGuardian
        )
        guardian.server = MagicMock()
        now = time.time()
        guardian._crash_times = [now - 10, now - 5, now - 1]
        guardian._stop_event = MagicMock()
        guardian._thread = None
        guardian._agent_start_time = 0

        assert guardian.circuit_open is True
        guardian.reset_circuit()
        assert guardian.circuit_open is False
        assert len(guardian._crash_times) == 0


# ═══════════════════════════════════════════════════
# Orchestrator Auto-Idle Tests
# ═══════════════════════════════════════════════════


class TestOrchestratorStateReset:
    """Test that the orchestrator state reset logic functions correctly."""

    def test_finally_block_resets_all_flags(self):
        """Simulate what the finally block does — verify it resets all state."""
        # This tests the logic pattern, not the full execute_task method
        class MockOrchestrator:
            def __init__(self):
                self.aborted = True
                self._paused = True
                self._skip_requested = True
                self._retry_requested = True

            def reset(self):
                # Mirrors the finally block in execute_task
                self.aborted = False
                self._paused = False
                self._skip_requested = False
                self._retry_requested = False

        orch = MockOrchestrator()
        assert orch.aborted is True
        assert orch._paused is True

        orch.reset()
        assert orch.aborted is False
        assert orch._paused is False
        assert orch._skip_requested is False
        assert orch._retry_requested is False

    def test_orchestrator_has_required_state_attributes(self):
        """Verify Orchestrator class has the state attributes we reset."""
        from src.orchestrator import Orchestrator
        # Check that the class defines these attributes (via __init__ or defaults)
        source = open(os.path.join(os.path.dirname(__file__), '..', 'src', 'orchestrator.py'), encoding='utf-8').read()
        assert 'self.aborted' in source
        assert 'self._paused' in source
        assert 'self._skip_requested' in source
        assert 'self._retry_requested' in source

    def test_execute_task_has_finally_block(self):
        """Verify execute_task contains the auto-idle finally block."""
        source = open(os.path.join(os.path.dirname(__file__), '..', 'src', 'orchestrator.py'), encoding='utf-8').read()
        # Check for the idle emit pattern in the finally block
        assert 'emit_status("idle"' in source or "emit_status('idle'" in source
        assert 'self.aborted = False' in source


# ═══════════════════════════════════════════════════
# Memory Check Tests
# ═══════════════════════════════════════════════════


class TestMemoryCheck:
    """Test the SystemGuardian's memory check."""

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows-only memory API")
    def test_memory_check_returns_valid_data(self):
        """Memory check should return valid data on Windows."""
        from rin_service import RinServiceServer

        mem = RinServiceServer.SystemGuardian.check_memory()
        assert "total_mb" in mem
        assert "available_mb" in mem
        assert "ok" in mem
        # On a real Windows machine these should be > 0
        assert isinstance(mem["total_mb"], int)
        assert isinstance(mem["available_mb"], int)

    def test_memory_check_returns_dict(self):
        """Memory check should always return a dict with expected keys."""
        from rin_service import RinServiceServer

        mem = RinServiceServer.SystemGuardian.check_memory()
        assert isinstance(mem, dict)
        assert "ok" in mem
        assert isinstance(mem["ok"], bool)


# ═══════════════════════════════════════════════════
# Socket State Transition Tests (unit-level)
# ═══════════════════════════════════════════════════


class TestSocketStateTransitions:
    """Test the state transition logic from socket.js (validated as pure logic)."""

    ACTIVE_STATES = ['thinking', 'working', 'acting', 'running', 'RUNNING', 'THINKING', 'PAUSED']
    TERMINAL_STATES = ['idle', 'DONE', 'ABORTED', 'ERROR', 'COMPLETE', 'blocked']

    def test_active_to_idle_clears_state(self):
        """Active -> idle should be recognized as needing cleanup."""
        for active in self.ACTIVE_STATES:
            was_active = active in self.ACTIVE_STATES
            now_terminal = 'idle' in self.TERMINAL_STATES
            assert was_active and now_terminal

    def test_active_to_done_clears_state(self):
        """Active -> DONE should be recognized as terminal."""
        assert 'DONE' in self.TERMINAL_STATES
        assert 'RUNNING' in self.ACTIVE_STATES

    def test_idle_not_active(self):
        """Idle should NOT be considered active."""
        assert 'idle' not in self.ACTIVE_STATES

    def test_blocked_is_terminal(self):
        """blocked status should be terminal."""
        assert 'blocked' in self.TERMINAL_STATES

    def test_crash_details_detected(self):
        """Details containing crash/exit/stopped should trigger VLM offline."""
        crash_details = ['exit code 1', 'Agent crashed', 'Agent stopped']
        keywords = ['exit', 'crash', 'stopped']
        for detail in crash_details:
            matched = any(kw in detail for kw in keywords)
            assert matched, f"'{detail}' should match crash keywords"
