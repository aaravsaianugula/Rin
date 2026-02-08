"""
Process Manager for single-instance enforcement.

Uses Windows named mutexes (primary) with file lock fallback
to ensure only one instance of Rin Agent runs at a time.
"""
import os
import sys
import logging
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

# Unique identifier for Rin Agent
RIN_AGENT_GUID = "7a1b2c3d-4e5f-6789-abcd-ef0123456789"


class AlreadyRunningError(Exception):
    """Raised when another instance is already running."""
    pass


class ProcessManager:
    """
    Manages single-instance enforcement for Rin Agent.
    
    Uses a Windows named mutex for reliable cross-process synchronization,
    with a PID file fallback for stale lock detection.
    """
    
    def __init__(self, component_name: str = "Backend"):
        """
        Initialize and acquire the singleton lock.
        
        Args:
            component_name: Name of component (e.g., "Backend", "Overlay")
            
        Raises:
            AlreadyRunningError: If another instance is already running
        """
        self.component_name = component_name
        self.mutex_name = f"Global\\RinAgent{component_name}-{RIN_AGENT_GUID}"
        self.lock_file = Path(tempfile.gettempdir()) / f"rin_agent_{component_name.lower()}.lock"
        
        self._mutex = None
        self._file_handle = None
        self._owns_lock = False
        
        # Try to acquire lock
        if not self._acquire_lock():
            raise AlreadyRunningError(
                f"Another instance of Rin Agent ({component_name}) is already running"
            )
    
    def _acquire_lock(self) -> bool:
        """
        Attempt to acquire the singleton lock.
        
        Returns:
            True if lock acquired, False if another instance running
        """
        # Try Windows mutex first (most reliable on Windows)
        if sys.platform == "win32":
            try:
                import win32event
                import win32api
                import winerror
                
                self._mutex = win32event.CreateMutex(None, True, self.mutex_name)
                last_error = win32api.GetLastError()
                
                if last_error == winerror.ERROR_ALREADY_EXISTS:
                    logger.warning(f"Mutex already exists: {self.mutex_name}")
                    self._mutex = None
                    return False
                
                logger.info(f"Acquired mutex: {self.mutex_name}")
                self._owns_lock = True
                
                # Also write PID file for debugging/monitoring
                self._write_pid_file()
                return True
                
            except ImportError:
                logger.debug("pywin32 not available, falling back to file lock")
            except Exception as e:
                logger.warning(f"Mutex creation failed: {e}, falling back to file lock")
        
        # Fallback: File-based lock with PID tracking
        return self._acquire_file_lock()
    
    def _acquire_file_lock(self) -> bool:
        """
        Acquire lock using file-based mechanism with stale lock detection.
        """
        try:
            # Check for stale lock first
            if self.lock_file.exists():
                if self._is_stale_lock():
                    logger.info("Found stale lock file, cleaning up")
                    self._cleanup_stale_lock()
                else:
                    logger.warning(f"Lock file exists and process is alive: {self.lock_file}")
                    return False
            
            # Try to create lock file exclusively
            if sys.platform == "win32":
                import msvcrt
                self._file_handle = open(self.lock_file, 'w')
                try:
                    msvcrt.locking(self._file_handle.fileno(), msvcrt.LK_NBLCK, 1)
                except IOError:
                    self._file_handle.close()
                    self._file_handle = None
                    return False
            else:
                import fcntl
                self._file_handle = open(self.lock_file, 'w')
                try:
                    fcntl.flock(self._file_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except IOError:
                    self._file_handle.close()
                    self._file_handle = None
                    return False
            
            # Write PID to lock file
            self._write_pid_file()
            self._owns_lock = True
            logger.info(f"Acquired file lock: {self.lock_file}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to acquire file lock: {e}")
            return False
    
    def _write_pid_file(self):
        """Write current PID to lock file."""
        try:
            with open(self.lock_file, 'w') as f:
                f.write(str(os.getpid()))
        except Exception as e:
            logger.debug(f"Failed to write PID file: {e}")
    
    def _is_stale_lock(self) -> bool:
        """Check if lock file is from a dead process."""
        try:
            with open(self.lock_file, 'r') as f:
                pid_str = f.read().strip()
                if not pid_str:
                    return True
                pid = int(pid_str)
            
            # Check if process is still running
            return not self._is_process_alive(pid)
            
        except (ValueError, FileNotFoundError):
            return True
    
    def _is_process_alive(self, pid: int) -> bool:
        """Check if a process with given PID is still running."""
        if sys.platform == "win32":
            try:
                import ctypes
                kernel32 = ctypes.windll.kernel32
                SYNCHRONIZE = 0x00100000
                handle = kernel32.OpenProcess(SYNCHRONIZE, False, pid)
                if handle:
                    kernel32.CloseHandle(handle)
                    return True
                return False
            except Exception:
                return False
        else:
            try:
                os.kill(pid, 0)
                return True
            except OSError:
                return False
    
    def _cleanup_stale_lock(self):
        """Remove stale lock file."""
        try:
            self.lock_file.unlink(missing_ok=True)
        except Exception as e:
            logger.debug(f"Failed to cleanup stale lock: {e}")
    
    def cleanup(self):
        """Release all locks and cleanup."""
        if not self._owns_lock:
            return
        
        # Release Windows mutex
        if self._mutex:
            try:
                import win32event
                win32event.ReleaseMutex(self._mutex)
                self._mutex = None
                logger.info("Released mutex")
            except Exception as e:
                logger.debug(f"Failed to release mutex: {e}")
        
        # Release file lock
        if self._file_handle:
            try:
                if sys.platform == "win32":
                    import msvcrt
                    msvcrt.locking(self._file_handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(self._file_handle.fileno(), fcntl.LOCK_UN)
                self._file_handle.close()
                self._file_handle = None
            except Exception as e:
                logger.debug(f"Failed to release file lock: {e}")
        
        # Remove lock file
        try:
            self.lock_file.unlink(missing_ok=True)
            logger.info("Cleaned up lock file")
        except Exception:
            pass
        
        self._owns_lock = False
    
    def __del__(self):
        """Cleanup on garbage collection."""
        self.cleanup()
    
    def __enter__(self):
        return self
    
    def __exit__(self, *args):
        self.cleanup()


# Global instance for the backend
_process_manager = None


def ensure_single_instance(component_name: str = "Backend") -> ProcessManager:
    """
    Ensure only one instance is running.
    
    Args:
        component_name: Name of component
        
    Returns:
        ProcessManager instance
        
    Raises:
        AlreadyRunningError: If another instance is already running
    """
    global _process_manager
    if _process_manager is None:
        _process_manager = ProcessManager(component_name)
    return _process_manager


def cleanup_instance():
    """Cleanup the global instance."""
    global _process_manager
    if _process_manager:
        _process_manager.cleanup()
        _process_manager = None
