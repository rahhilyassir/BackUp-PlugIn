"""
Self-test suite for the backup server.

Run it with::

    python serverTest.py

The tests use Flask's built-in test client and a temporary upload folder, so
no running server, network connection, or real backups are required.
"""

from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path

from server import create_app


class BackupServerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.upload_folder = Path(self.temp_dir.name) / "uploads"
        self.app = create_app(
            {
                "UPLOAD_FOLDER": str(self.upload_folder),
                "MAX_FILES": 2,
            }
        )
        self.app.config.update(TESTING=True)
        self.client = self.app.test_client()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def upload(self, content: bytes = b"hello", filename: str = "exampleFile.txt"):
        return self.client.post(
            "/upload",
            data={"file": (io.BytesIO(content), filename)},
            content_type="multipart/form-data",
        )

    def test_health_endpoint(self) -> None:
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["status"], "ok")

    def test_upload_saves_file(self) -> None:
        response = self.upload(b"hello backup")
        self.assertEqual(response.status_code, 201)

        body = response.get_json()
        self.assertIn("filename", body)
        self.assertTrue(body["filename"].startswith("exampleFile_"))
        self.assertTrue(body["filename"].endswith(".txt"))
        self.assertEqual(body["size"], len(b"hello backup"))

        saved_file = self.upload_folder / body["filename"]
        self.assertTrue(saved_file.is_file())
        self.assertEqual(saved_file.read_bytes(), b"hello backup")

    def test_upload_creates_upload_folder(self) -> None:
        self.assertTrue(self.upload_folder.is_dir())

    def test_upload_without_file_is_rejected(self) -> None:
        response = self.client.post("/upload", data={}, content_type="multipart/form-data")
        self.assertEqual(response.status_code, 400)
        self.assertIn("error", response.get_json())

    def test_upload_with_empty_filename_is_rejected(self) -> None:
        response = self.upload(b"", filename="")
        self.assertEqual(response.status_code, 400)
        self.assertIn("error", response.get_json())

    def test_retention_keeps_only_max_files(self) -> None:
        for index in range(3):
            response = self.upload(f"content-{index}".encode(), f"backup-{index}.txt")
            self.assertEqual(response.status_code, 201)

        saved_files = [entry for entry in self.upload_folder.iterdir() if entry.is_file()]
        self.assertEqual(len(saved_files), 2)

    def test_original_filename_is_sanitized(self) -> None:
        response = self.upload(b"malicious", "../../escape.txt")
        self.assertEqual(response.status_code, 201)

        saved_name = response.get_json()["filename"]
        self.assertNotIn("/", saved_name)
        self.assertNotIn("\\", saved_name)

        saved_path = (self.upload_folder / saved_name).resolve()
        self.assertEqual(saved_path.parent, self.upload_folder.resolve())
        self.assertFalse((Path(self.temp_dir.name) / "escape.txt").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
