"""
Backup agent.

Reads a file and uploads it to the central backup server at a configured
interval.

Run the agent with::

    python backup_plugin.py

Use ``--once`` to perform a single backup and exit, which is useful for cron
jobs, Windows Task Scheduler, or a quick manual test::

    python backup_plugin.py --once
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

import requests
import schedule

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG_PATH = BASE_DIR / "config.json"
DEFAULT_INTERVAL_MINUTES = 60
DEFAULT_TIMEOUT_SECONDS = 30

logger = logging.getLogger("backup_plugin")


class ConfigError(ValueError):
    """Raised when the configuration cannot be loaded or is invalid."""


def load_config(config_path: str | os.PathLike[str] = DEFAULT_CONFIG_PATH) -> dict[str, Any]:
    """Load and validate the JSON configuration file."""
    path = Path(config_path)
    try:
        with path.open("r", encoding="utf-8-sig") as config_file:
            config = json.load(config_file)
    except FileNotFoundError as exc:
        raise ConfigError(f"Configuration file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigError(f"Invalid JSON in {path}: {exc}") from exc

    if not isinstance(config, dict):
        raise ConfigError("The configuration file must contain a JSON object.")
    return config


def _resolve_from(base_dir: Path, raw_path: str | os.PathLike[str]) -> Path:
    """Resolve a relative path against the configuration file's folder."""
    path = Path(raw_path).expanduser()
    if not path.is_absolute():
        path = base_dir / path
    return path.resolve()


def _positive_number(value: Any, name: str) -> float:
    """Validate a positive numeric configuration value."""
    if isinstance(value, bool):
        raise ConfigError(f"'{name}' must be a number greater than zero.")

    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"'{name}' must be a number greater than zero.") from exc

    if number <= 0:
        raise ConfigError(f"'{name}' must be a number greater than zero.")
    return number


def build_upload_url(server_url: Any) -> str:
    """Return the upload endpoint, adding ``/upload`` only when needed."""
    if not isinstance(server_url, str) or not server_url.strip():
        raise ConfigError("'server_url' must be a non-empty HTTP(S) URL.")

    url = server_url.strip().rstrip("/")
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ConfigError("'server_url' must be a valid HTTP(S) URL.")

    if not parsed.path.rstrip("/").endswith("/upload"):
        parsed = parsed._replace(path=f"{parsed.path.rstrip('/')}/upload")
        url = parsed.geturl()
    return url


def get_file_path(config: dict[str, Any], config_dir: Path) -> Path:
    """Return the configured file path, resolved against the config folder."""
    raw_path = config.get("file_path")
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise ConfigError("'file_path' must be a non-empty path string.")
    return _resolve_from(config_dir, raw_path)


def read_file(file_path: str | os.PathLike[str]) -> bytes:
    """Read and return the content of ``file_path``."""
    path = Path(file_path)
    if not path.is_file():
        raise FileNotFoundError(f"The file {path} does not exist.")
    return path.read_bytes()


def send_to_server(
    file_path: str | os.PathLike[str],
    server_url: str,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> bool:
    """Upload one file to the backup server.

    Returns ``True`` on success and ``False`` when the file is missing or the
    upload fails. Errors are logged instead of raised so a single failed
    backup does not stop the scheduler.
    """
    path = Path(file_path)
    if not path.is_file():
        logger.error("Backup file does not exist: %s", path)
        return False

    try:
        size = path.stat().st_size
        with path.open("rb") as file_handle:
            files = {"file": (path.name, file_handle)}
            response = requests.post(server_url, files=files, timeout=timeout)
        response.raise_for_status()
    except requests.HTTPError as exc:
        status_code = exc.response.status_code if exc.response is not None else "unknown"
        body = exc.response.text[:300].strip() if exc.response is not None else ""
        logger.error("Server rejected %s (HTTP %s): %s", path.name, status_code, body)
        return False
    except requests.RequestException as exc:
        logger.error("Could not upload %s to %s: %s", path.name, server_url, exc)
        return False
    except OSError as exc:
        logger.error("Could not read %s: %s", path, exc)
        return False

    logger.info("Backed up %s (%d bytes) to %s", path.name, size, server_url)
    return True


def backup_file(
    file_path: str | os.PathLike[str],
    server_url: str,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> bool:
    """Backwards-compatible wrapper around :func:`send_to_server`."""
    return send_to_server(file_path, server_url, timeout)


def schedule_backup(
    file_path: str | os.PathLike[str],
    server_url: str,
    interval_minutes: float,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    run_on_start: bool = True,
) -> None:
    """Run one optional backup, then schedule backups until interrupted."""
    if interval_minutes <= 0:
        raise ConfigError("'interval_minutes' must be greater than zero.")

    def run_backup() -> None:
        try:
            backup_file(file_path, server_url, timeout)
        except Exception:
            # Keep the scheduler alive even if an unexpected error occurs.
            logger.exception("Unexpected error while backing up %s", file_path)

    if run_on_start:
        logger.info("Running initial backup ...")
        run_backup()

    schedule.every(interval_minutes).minutes.do(run_backup)
    logger.info(
        "Backups scheduled every %g minute(s). Press Ctrl+C to stop.",
        interval_minutes,
    )

    try:
        while True:
            schedule.run_pending()
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Backup agent stopped.")
        schedule.clear()


def configure_logging(log_path: Path) -> None:
    """Log to both the console and a file, regardless of the working folder."""
    log_path.parent.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    logger.setLevel(logging.INFO)
    logger.propagate = False

    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(formatter)

    logger.addHandler(console_handler)
    logger.addHandler(file_handler)


def main(argv: Optional[list[str]] = None) -> int:
    """Load the configuration and start the backup agent."""
    parser = argparse.ArgumentParser(description="Upload a file to the backup server on a schedule.")
    parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG_PATH),
        help="Path to the JSON configuration file (default: config.json).",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Upload the file once and exit instead of scheduling backups.",
    )
    args = parser.parse_args(argv)

    config_path = Path(args.config).expanduser().resolve()

    try:
        config = load_config(config_path)
        config_dir = config_path.parent
        file_path = get_file_path(config, config_dir)
        server_url = build_upload_url(config.get("server_url"))
        interval_minutes = _positive_number(
            config.get("interval_minutes", DEFAULT_INTERVAL_MINUTES),
            "interval_minutes",
        )
        timeout = _positive_number(
            config.get("request_timeout_seconds", DEFAULT_TIMEOUT_SECONDS),
            "request_timeout_seconds",
        )

        raw_log_file = config.get("log_file", "backup.log")
        if not isinstance(raw_log_file, str) or not raw_log_file.strip():
            raise ConfigError("'log_file' must be a non-empty path string.")
        log_path = _resolve_from(config_dir, raw_log_file)

        run_on_start = config.get("run_on_start", True)
        if not isinstance(run_on_start, bool):
            raise ConfigError("'run_on_start' must be true or false.")
    except (ConfigError, OSError) as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 1

    try:
        configure_logging(log_path)
    except OSError as exc:
        print(f"Could not set up logging: {exc}", file=sys.stderr)
        return 1

    logger.info("Backup agent started (config: %s)", config_path)
    logger.info("Watching: %s", file_path)
    logger.info("Server: %s", server_url)

    if not file_path.is_file():
        logger.warning("Backup file does not exist yet: %s", file_path)

    if args.once:
        return 0 if backup_file(file_path, server_url, timeout) else 1

    schedule_backup(
        file_path=file_path,
        server_url=server_url,
        interval_minutes=interval_minutes,
        timeout=timeout,
        run_on_start=run_on_start,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
