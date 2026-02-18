import logging
import os
from pathlib import Path
from logging.handlers import RotatingFileHandler


def _parse_int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        val = int(raw)
        if val < 1:
            return default
        return val
    except ValueError:
        return default


def _parse_level(level_name: str, default: int) -> int:
    return getattr(logging, level_name.upper(), default)


def _apply_module_levels(root_logger: logging.Logger, default_level: int) -> None:
    """
    Apply per-module log levels from env var:
    HIRESTI_LOG_MODULE_LEVELS="audio_player=DEBUG,tidal_backend=INFO"
    """
    raw = os.getenv("HIRESTI_LOG_MODULE_LEVELS", "").strip()
    if not raw:
        return

    for item in raw.split(","):
        entry = item.strip()
        if not entry or "=" not in entry:
            root_logger.warning("Invalid module-level logging entry: %s", entry)
            continue

        module_name, level_name = entry.split("=", 1)
        module_name = module_name.strip()
        level_name = level_name.strip()
        if not module_name or not level_name:
            root_logger.warning("Invalid module-level logging entry: %s", entry)
            continue

        level = _parse_level(level_name, default_level)
        logging.getLogger(module_name).setLevel(level)
        root_logger.info("Log level override: %s=%s", module_name, logging.getLevelName(level))


def setup_logging() -> None:
    """
    Configure application-wide logging once.

    Env vars:
    - HIRESTI_LOG_LEVEL: DEBUG/INFO/WARNING/ERROR (default: INFO)
    - HIRESTI_LOG_FILE: optional path to a log file
    - HIRESTI_LOG_ROTATE_BYTES: max file size before rotation (default: 5242880)
    - HIRESTI_LOG_BACKUP_COUNT: number of rotated files to keep (default: 3)
    - HIRESTI_LOG_MODULE_LEVELS: comma-separated module overrides
      e.g. "audio_player=DEBUG,tidal_backend=INFO"
    """
    level_name = os.getenv("HIRESTI_LOG_LEVEL", "INFO").upper()
    level = _parse_level(level_name, logging.INFO)

    root = logging.getLogger()
    root.setLevel(level)

    # Reset handlers to avoid duplicated logs on repeated setup.
    root.handlers.clear()

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )

    console = logging.StreamHandler()
    console.setLevel(level)
    console.setFormatter(formatter)
    root.addHandler(console)

    log_file = os.getenv("HIRESTI_LOG_FILE")
    if log_file:
        path = Path(log_file).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        rotate_bytes = _parse_int_env("HIRESTI_LOG_ROTATE_BYTES", 5 * 1024 * 1024)
        backup_count = _parse_int_env("HIRESTI_LOG_BACKUP_COUNT", 3)
        file_handler = RotatingFileHandler(
            path,
            maxBytes=rotate_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)

    _apply_module_levels(root, level)
