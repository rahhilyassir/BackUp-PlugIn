"""
Central backup server.

Receives files from the backup agent (``backup_plugin.py``) through
``POST /upload``, stores them in the configured upload folder and keeps only
the newest ``max_files`` backups.

Run the server with::

    python server.py

The server reads ``config.json`` from the same directory as this file unless
another configuration file is supplied with ``--config``.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Optional

from flask import Flask, jsonify, request
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.utils import secure_filename

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG_PATH = BASE_DIR / "config.json"
DEFAULT_UPLOAD_FOLDER = BASE_DIR / "uploads"

logger = logging.getLogger("backup_server")


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


def _resolve_upload_folder(
    raw_folder: str | os.PathLike[str],
    base_dir: Path = BASE_DIR,
) -> Path:
    """Resolve a possibly relative upload folder against a base folder."""
    folder = Path(raw_folder).expanduser()
    if not folder.is_absolute():
        folder = base_dir / folder
    return folder.resolve()


def _coerce_max_files(value: Any) -> Optional[int]:
    """Validate the retention limit. ``None`` means keep every backup."""
    if value is None:
        return None
    if isinstance(value, bool):
        raise ConfigError("'max_files' must be a positive integer or null.")

    try:
        max_files = int(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError("'max_files' must be a positive integer or null.") from exc

    if max_files < 1:
        raise ConfigError("'max_files' must be at least 1 or null.")
    return max_files


def _unique_destination(folder: Path, filename: str) -> Path:
    """Build a timestamped path that cannot overwrite an existing backup."""
    stem, suffix = os.path.splitext(filename)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    candidate = folder / f"{stem}_{timestamp}{suffix}"

    counter = 1
    while candidate.exists():
        candidate = folder / f"{stem}_{timestamp}_{counter}{suffix}"
        counter += 1
    return candidate


def _file_mtime(path: Path) -> int:
    """Return a sortable modification time, tolerating disappearing files."""
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return 0


def _prune_old_files(folder: Path, max_files: Optional[int]) -> None:
    """Delete the oldest backups until at most ``max_files`` remain."""
    if max_files is None:
        return

    files = [entry for entry in folder.iterdir() if entry.is_file()]
    files.sort(key=_file_mtime)

    for old_file in files[: max(0, len(files) - max_files)]:
        try:
            old_file.unlink()
            logger.info("Deleted old backup: %s", old_file.name)
        except OSError as exc:
            logger.warning("Could not delete old backup %s: %s", old_file, exc)


def create_app(config: Optional[Mapping[str, Any]] = None) -> Flask:
    """Create the Flask application.

    ``config`` accepts the same uppercase keys as ``app.config``. Tests can
    therefore use a temporary upload folder and a small retention limit.
    """
    app = Flask(__name__)
    app.config.update(
        UPLOAD_FOLDER=str(DEFAULT_UPLOAD_FOLDER),
        MAX_FILES=None,
        MAX_CONTENT_LENGTH=None,
    )
    if config:
        app.config.update(config)

    upload_folder = _resolve_upload_folder(app.config["UPLOAD_FOLDER"])
    try:
        upload_folder.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ConfigError(f"Could not create upload folder {upload_folder}: {exc}") from exc

    app.config["UPLOAD_FOLDER"] = str(upload_folder)
    max_files = _coerce_max_files(app.config.get("MAX_FILES"))
    app.config["MAX_FILES"] = max_files

    # Uploads are handled by a threaded Flask server. The lock keeps the
    # "save new file + remove old files" operation consistent.
    retention_lock = threading.Lock()

    @app.get("/health")
    def health() -> tuple[Any, int]:
        """Simple endpoint used to check that the server is running."""
        return jsonify({"status": "ok"}), 200

    @app.post("/upload")
    def upload_file() -> tuple[Any, int]:
        """Store one uploaded file and enforce the retention limit."""
        if "file" not in request.files:
            return jsonify({"error": "No file part in the request."}), 400

        uploaded = request.files["file"]
        if not uploaded.filename:
            return jsonify({"error": "No file selected for uploading."}), 400

        # secure_filename strips directory components such as ``..\..\``,
        # preventing uploads from escaping the upload folder.
        safe_name = secure_filename(uploaded.filename)
        if not safe_name:
            safe_name = "backup"

        try:
            with retention_lock:
                upload_folder.mkdir(parents=True, exist_ok=True)
                destination = _unique_destination(upload_folder, safe_name)
                uploaded.save(destination)
                _prune_old_files(upload_folder, max_files)
            size = destination.stat().st_size
        except OSError:
            logger.exception("Could not store uploaded file")
            return jsonify({"error": "Could not store the uploaded file."}), 500

        logger.info("Stored %s (%d bytes)", destination.name, size)
        return (
            jsonify(
                {
                    "message": "File successfully uploaded",
                    "filename": destination.name,
                    "size": size,
                }
            ),
            201,
        )

    @app.errorhandler(RequestEntityTooLarge)
    def handle_too_large(_error: RequestEntityTooLarge) -> tuple[Any, int]:
        return jsonify({"error": "The uploaded file is too large."}), 413

    return app


def main(argv: Optional[list[str]] = None) -> int:
    """Start the backup server from the command line."""
    parser = argparse.ArgumentParser(description="Run the central backup server.")
    parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG_PATH),
        help="Path to the JSON configuration file (default: config.json).",
    )
    parser.add_argument("--host", help="Override the host from the configuration file.")
    parser.add_argument("--port", type=int, help="Override the port from the configuration file.")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
    )

    try:
        config = load_config(args.config)
        config_dir = Path(args.config).expanduser().resolve().parent

        app_config: dict[str, Any] = {
            "UPLOAD_FOLDER": str(
                _resolve_upload_folder(config.get("upload_folder", "uploads"), config_dir)
            ),
            "MAX_FILES": config.get("max_files"),
        }

        max_upload_mb = config.get("max_upload_mb")
        if max_upload_mb is not None:
            if isinstance(max_upload_mb, bool):
                raise ConfigError("'max_upload_mb' must be a positive integer or null.")
            try:
                max_upload_mb = int(max_upload_mb)
            except (TypeError, ValueError) as exc:
                raise ConfigError("'max_upload_mb' must be a positive integer or null.") from exc
            if max_upload_mb < 1:
                raise ConfigError("'max_upload_mb' must be at least 1 or null.")
            app_config["MAX_CONTENT_LENGTH"] = max_upload_mb * 1024 * 1024

        app = create_app(app_config)

        host = args.host or str(config.get("host", "127.0.0.1"))
        port = args.port if args.port is not None else int(config.get("port", 5000))

        debug = config.get("debug", False)
        if not isinstance(debug, bool):
            raise ConfigError("'debug' must be true or false.")
    except (ConfigError, OSError, TypeError, ValueError) as exc:
        logger.error("Server configuration error: %s", exc)
        return 1

    logger.info("Upload folder: %s", app.config["UPLOAD_FOLDER"])
    logger.info("Starting backup server at http://%s:%s", host, port)
    app.run(host=host, port=port, debug=debug)
    return 0


if __name__ == "__main__":
    sys.exit(main())
