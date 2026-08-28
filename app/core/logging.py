import logging
import os
import sys
import json
import time
from contextvars import ContextVar
from typing import Optional, Dict, Any
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from app.common.enums import AuditAction

# Context variable to hold the active request ID across async tasks
request_id_ctx: ContextVar[str] = ContextVar("request_id_ctx", default="-")

def get_request_id() -> str:
    return request_id_ctx.get()

def set_request_id(req_id: str) -> None:
    request_id_ctx.set(req_id)

class RequestIDFilter(logging.Filter):
    """
    Injects request_id from contextvar into every log record.
    """
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = get_request_id()
        return True

class JSONLogFormatter(logging.Formatter):
    """
    Formats log records into structured JSON objects suitable for 
    cloud log collectors (ELK, Datadog, CloudWatch, Loki).
    """
    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
            "location": f"{record.filename}:{record.lineno}",
            "function": record.funcName,
        }
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)
        if hasattr(record, "extra_data") and isinstance(record.extra_data, dict):
            log_entry["data"] = record.extra_data
        return json.dumps(log_entry, default=str)

class ConsoleColorFormatter(logging.Formatter):
    """
    Color-coded console formatter for readable development output.
    """
    COLOR_MAP = {
        logging.DEBUG: "\033[36m",    # Cyan
        logging.INFO: "\033[32m",     # Green
        logging.WARNING: "\033[33m",  # Yellow
        logging.ERROR: "\033[31m",    # Red
        logging.CRITICAL: "\033[35m", # Magenta
    }
    RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        color = self.COLOR_MAP.get(record.levelno, self.RESET)
        req_id = getattr(record, "request_id", "-")
        req_prefix = f"[{req_id}] " if req_id != "-" else ""
        time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_line = f"{color}{time_str} [{record.levelname:<7}]{self.RESET} {req_prefix}[{record.name}] {record.getMessage()}"
        if record.exc_info:
            log_line += f"\n{self.formatException(record.exc_info)}"
        return log_line

def setup_logging(
    log_level: int = logging.INFO,
    log_dir: str = "logs",
    json_format: bool = False
) -> logging.Logger:
    """
    Initializes root and app loggers with rotating file handlers and console output.
    """
    os.makedirs(log_dir, exist_ok=True)
    req_filter = RequestIDFilter()

    # 1. Console Handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)
    console_handler.addFilter(req_filter)
    if json_format:
        console_handler.setFormatter(JSONLogFormatter())
    else:
        console_handler.setFormatter(ConsoleColorFormatter())

    # 2. Main App Log File (Rotating, max 10MB x 5 backups)
    app_file_handler = RotatingFileHandler(
        filename=os.path.join(log_dir, "app.log"),
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8"
    )
    app_file_handler.setLevel(log_level)
    app_file_handler.addFilter(req_filter)
    app_file_handler.setFormatter(JSONLogFormatter())

    # 3. Error Log File (Rotating, max 10MB x 5 backups)
    error_file_handler = RotatingFileHandler(
        filename=os.path.join(log_dir, "error.log"),
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8"
    )
    error_file_handler.setLevel(logging.ERROR)
    error_file_handler.addFilter(req_filter)
    error_file_handler.setFormatter(JSONLogFormatter())

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    # Remove default handlers to avoid duplicates
    root_logger.handlers.clear()
    root_logger.addHandler(console_handler)
    root_logger.addHandler(app_file_handler)
    root_logger.addHandler(error_file_handler)

    # Configure app logger
    app_logger = logging.getLogger("meditouch")
    app_logger.setLevel(log_level)

    # Silence overly noisy third-party loggers
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("motor").setLevel(logging.WARNING)
    logging.getLogger("pymongo").setLevel(logging.WARNING)

    app_logger.info(f"Logging initialized. Level={logging.getLevelName(log_level)}, Dir={log_dir}")
    return app_logger

# Default global logger instance
logger = logging.getLogger("meditouch")

async def log_audit_event(
    db,
    user_id: Optional[str],
    action: AuditAction,
    target_type: str,
    target_id: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
    ip_address: Optional[str] = None
) -> None:
    """
    Persists an audit event to MongoDB audit_logs and records a structured audit log line.
    """
    try:
        action_val = action.value if isinstance(action, AuditAction) else str(action)
        audit_doc = {
            "user_id": user_id,
            "action": action_val,
            "target_type": target_type,
            "target_id": target_id,
            "details": details or {},
            "ip_address": ip_address,
            "created_at": datetime.now(timezone.utc)
        }
        if db is not None:
            await db.audit_logs.insert_one(audit_doc)

        logger.info(
            f"AUDIT_EVENT: action={action_val} user_id={user_id} target={target_type}:{target_id}",
            extra={"extra_data": audit_doc}
        )
    except Exception as e:
        logger.error(f"Failed to record audit log: {e}", exc_info=True)
