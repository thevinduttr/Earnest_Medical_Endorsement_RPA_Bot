import logging
import shutil
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Optional

# Paths
LOGS_BASE = Path(__file__).resolve().parent.parent.parent / "data" / "logs"
ERROR_SHOTS = Path(__file__).resolve().parent.parent.parent / "data" / "outputs" / "error_screenshots"

# Default retention (days)
DEFAULT_RETENTION_DAYS = 7

def _safe_component(value: str, default: str) -> str:
	"""Sanitize a name component (bot_id / request_id). Allow only alnum, underscore and hyphen."""
	if not value:
		value = default
	# replace spaces and disallowed chars with '-'
	return re.sub(r"[^A-Za-z0-9_-]", "-", value)

def make_run_id(bot_id: Optional[str] = None, request_id: Optional[str] = None, ts: Optional[datetime] = None) -> str:
    """
    Create a two-level run id:
      - day folder: run_YYYY-MM-DD
      - nested folder: bot_{bot_id}-req_{request_id}
    All requests for same day go in same day folder.
    """
    ts = ts or datetime.now()
    date_part = ts.strftime("%Y-%m-%d")
    safe_bot = _safe_component(bot_id, "bot")
    safe_req = _safe_component(request_id, "req")
    return f"run_{date_part}/bot_{safe_bot}-req_{safe_req}"

def _get_next_try_folder(base_path: Path) -> Path:
    """Find next available try folder by checking existing ones."""
    if not base_path.exists():
        return base_path
    
    # Check if base exists, then look for try folders
    if base_path.exists():
        # Look for existing try folders
        parent = base_path.parent
        base_name = base_path.name
        
        i = 2
        while True:
            try_path = parent / f"{base_name} (try - {i})"
            if not try_path.exists():
                return try_path
            i += 1
    
    return base_path

def _ensure_dirs(run_id: str) -> Path:
    """Ensure per-run log directory exists."""
    parts = str(run_id).split("/")
    if len(parts) != 2:
        raise ValueError(f"Invalid run_id format (expected day/bot-req): {run_id}")
    
    day_part, sub_part = parts

    # Validate day folder format
    if not re.fullmatch(r"run_\d{4}-\d{2}-\d{2}", day_part):
        raise ValueError(f"Invalid day folder format in run_id: {day_part}")

    # Validate bot-req folder format 
    if not re.fullmatch(r"bot_[A-Za-z0-9_-]+-req_[A-Za-z0-9_-]+", sub_part):
        raise ValueError(f"Invalid bot-req folder format in run_id: {sub_part}")

    # Get base path and find next available try folder
    base_path = LOGS_BASE / day_part / sub_part
    run_dir = _get_next_try_folder(base_path)
    
    # Create directories
    run_dir.mkdir(parents=True, exist_ok=True)
    ERROR_SHOTS.mkdir(parents=True, exist_ok=True)
    return run_dir

def _build_logger(name: str, logfile: Path, bot_id: str, request_id: str, level: int = logging.INFO, to_console: bool = True) -> logging.Logger:
    """Build a logger for a specific process writing to 'logfile'."""
    logger = logging.getLogger(name)

    # Reconfigure existing named loggers for each run so handlers point to the current run's file.
    if logger.handlers:
        for handler in list(logger.handlers):
            logger.removeHandler(handler)
            try:
                handler.close()
            except Exception:
                pass

    if logger.filters:
        for log_filter in list(logger.filters):
            logger.removeFilter(log_filter)

    logger.setLevel(level)

    # Custom formatter with simplified path and no request_id in message
    fmt = logging.Formatter(
        fmt='[%(asctime)s] [%(bot_id)s] - [%(levelname)s] - [%(name)s] - [%(relative_path)s:%(lineno)d] - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # Add custom filter to inject bot_id and convert paths
    class ContextFilter(logging.Filter):
        def filter(self, record):
            record.bot_id = bot_id
            # Convert absolute path to relative
            try:
                full_path = Path(record.pathname)
                record.relative_path = full_path.name
            except:
                record.relative_path = record.pathname
            return True

    logger.addFilter(ContextFilter())

    fh = logging.FileHandler(str(logfile), encoding="utf-8")
    fh.setLevel(level)
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    if to_console:
        ch = logging.StreamHandler()
        ch.setLevel(level)
        ch.setFormatter(fmt)
        logger.addHandler(ch)

    logger.propagate = False
    return logger

def init_run_loggers(run_id: Optional[str] = None, bot_id: str = "UNKNOWN", 
                    request_id: str = "UNKNOWN", debug: bool = False,
                    retention_days: int = DEFAULT_RETENTION_DAYS) -> Dict[str, logging.Logger]:
    """Initialize loggers with bot_id and request_id context."""
    run_id = run_id or make_run_id(bot_id=bot_id, request_id=request_id)
    run_dir = _ensure_dirs(run_id)
    
    level = logging.DEBUG if debug else logging.INFO
    process_logfile = run_dir / "process.log"

    loggers = {
        "main": _build_logger("main_process", process_logfile, bot_id, request_id, level=level),
        "client": _build_logger("client_process", process_logfile, bot_id, request_id, level=level),
        "lead": _build_logger("lead_process", process_logfile, bot_id, request_id, level=level),
        "prospect": _build_logger("prospect_process", process_logfile, bot_id, request_id, level=level),
    }

    # Cleanup old runs (best-effort)
    # try:
    #     cleanup_old_logs(retention_days=retention_days)
    # except (OSError, PermissionError) as e:
    #     loggers["main"].warning(f"Log cleanup skipped: {e}")
    # except Exception as e:
    #     loggers["main"].error(f"Unexpected error during log cleanup: {e}")

    return loggers

def get_process_logger(run_id: str, process_basename: str, bot_id: str, request_id: str, debug: bool = False) -> logging.Logger:
    """Create/return a logger for an arbitrary process with bot_id and request_id context."""
    run_dir = _ensure_dirs(run_id)
    process_logfile = run_dir / "process.log"
    level = logging.DEBUG if debug else logging.INFO
    return _build_logger(f"{process_basename}_process", process_logfile, bot_id, request_id, level=level)

def cleanup_old_logs(retention_days: int = DEFAULT_RETENTION_DAYS) -> None:
	"""Remove per-day log folders older than 'retention_days'."""
	if not LOGS_BASE.exists():
		return
	cutoff = datetime.now() - timedelta(days=retention_days)
	# LOGS_BASE contains day folders like run_YYYY-MM-DD
	for folder in LOGS_BASE.glob("run_*"):
		try:
			mtime = datetime.fromtimestamp(folder.stat().st_mtime)
			if mtime < cutoff:
				shutil.rmtree(folder, ignore_errors=True)
		except Exception:
			pass
