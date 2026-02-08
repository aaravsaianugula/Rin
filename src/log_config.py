"""
Structured logging configuration for Rin Agent.

Provides:
- JSON structured logs for machine parsing
- Log rotation to prevent disk space issues
- Sensitive data sanitization
- Correlation IDs for request tracing
"""

import logging
import logging.handlers
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Optional
import threading

# Thread-local storage for correlation IDs
_context = threading.local()


def get_correlation_id() -> Optional[str]:
    """Get the current correlation ID for this thread."""
    return getattr(_context, 'correlation_id', None)


def set_correlation_id(correlation_id: str):
    """Set the correlation ID for this thread."""
    _context.correlation_id = correlation_id


def clear_correlation_id():
    """Clear the correlation ID for this thread."""
    _context.correlation_id = None


# Patterns for sensitive data sanitization
SENSITIVE_PATTERNS = [
    (re.compile(r'(token["\']?\s*[:=]\s*["\']?)([a-zA-Z0-9._-]+)(["\']?)', re.IGNORECASE), r'\1***REDACTED***\3'),
    (re.compile(r'(password["\']?\s*[:=]\s*["\']?)([^"\']+)(["\']?)', re.IGNORECASE), r'\1***REDACTED***\3'),
    (re.compile(r'(api[_-]?key["\']?\s*[:=]\s*["\']?)([a-zA-Z0-9._-]+)(["\']?)', re.IGNORECASE), r'\1***REDACTED***\3'),
    (re.compile(r'(secret["\']?\s*[:=]\s*["\']?)([^"\']+)(["\']?)', re.IGNORECASE), r'\1***REDACTED***\3'),
]


def sanitize_message(message: str) -> str:
    """Remove sensitive data from log messages."""
    for pattern, replacement in SENSITIVE_PATTERNS:
        message = pattern.sub(replacement, message)
    return message


class StructuredFormatter(logging.Formatter):
    """JSON formatter for structured logging."""
    
    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": sanitize_message(record.getMessage()),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }
        
        # Add correlation ID if present
        correlation_id = get_correlation_id()
        if correlation_id:
            log_data["correlation_id"] = correlation_id
        
        # Add exception info if present
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)
        
        # Add any extra fields
        if hasattr(record, 'extra_fields'):
            log_data.update(record.extra_fields)
        
        return json.dumps(log_data, default=str)


class ConsoleFormatter(logging.Formatter):
    """Human-readable console formatter with colors."""
    
    COLORS = {
        'DEBUG': '\033[36m',     # Cyan
        'INFO': '\033[32m',      # Green
        'WARNING': '\033[33m',   # Yellow
        'ERROR': '\033[31m',     # Red
        'CRITICAL': '\033[35m',  # Magenta
    }
    RESET = '\033[0m'
    
    def format(self, record: logging.LogRecord) -> str:
        color = self.COLORS.get(record.levelname, self.RESET)
        time_str = datetime.now().strftime("%H:%M:%S")
        
        # Add correlation ID prefix if present
        correlation_id = get_correlation_id()
        prefix = f"[{correlation_id[:8]}] " if correlation_id else ""
        
        message = sanitize_message(record.getMessage())
        formatted = f"{color}{time_str} [{record.levelname[0]}]{self.RESET} {prefix}{message}"
        
        if record.exc_info:
            formatted += "\n" + self.formatException(record.exc_info)
        
        return formatted


def configure_logging(
    log_dir: str = "logs",
    log_level: str = "INFO",
    max_bytes: int = 10 * 1024 * 1024,  # 10 MB
    backup_count: int = 5,
    console_output: bool = True,
    json_file: bool = True,
) -> logging.Logger:
    """
    Configure structured logging for the application.
    
    Args:
        log_dir: Directory for log files
        log_level: Minimum log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        max_bytes: Maximum size per log file before rotation
        backup_count: Number of backup files to keep
        console_output: Enable console logging
        json_file: Enable JSON structured file logging
    
    Returns:
        Root logger instance
    """
    # Ensure log directory exists
    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)
    
    # Get root logger for qwen3vl namespace
    root_logger = logging.getLogger("qwen3vl")
    root_logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))
    
    # Clear existing handlers
    root_logger.handlers.clear()
    
    # Console handler with human-readable format
    if console_output:
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(ConsoleFormatter())
        console_handler.setLevel(logging.DEBUG)
        root_logger.addHandler(console_handler)
    
    # Rotating file handler with JSON format
    if json_file:
        file_handler = logging.handlers.RotatingFileHandler(
            log_path / "rin.log",
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        file_handler.setFormatter(StructuredFormatter())
        file_handler.setLevel(logging.DEBUG)
        root_logger.addHandler(file_handler)
    
    # Also configure the requests library to be less verbose
    logging.getLogger("requests").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    
    root_logger.info("Logging configured", extra={
        "extra_fields": {
            "log_dir": str(log_path),
            "level": log_level,
            "console": console_output,
            "json_file": json_file,
        }
    })
    
    return root_logger
