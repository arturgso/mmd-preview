import io
import tempfile
import unittest
from pathlib import Path

from app import create_app


class MermaidViewerTestCase(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.app = create_app(self.temporary.name)
        self.app.config.update(TESTING=True)
        self.client = self.app.test_client()

    def tearDown(self):
        self.temporary.cleanup()

    def upload(self, path="diagram.mmd", content=b"flowchart LR\nA-->B"):
        return self.client.post(
            "/api/files",
            data={"paths": path, "files": (io.BytesIO(content), Path(path).name)},
            content_type="multipart/form-data",
        )

    def test_upload_list_and_read_nested_file(self):
        response = self.upload("architecture/system.mmd")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["accepted"], ["architecture/system.mmd"])

        listing = self.client.get("/api/files").get_json()
        self.assertEqual(listing, {"files": ["architecture/system.mmd"], "count": 1})

        loaded = self.client.get("/api/file?path=architecture/system.mmd")
        self.assertEqual(loaded.status_code, 200)
        self.assertIn("A-->B", loaded.get_json()["content"])

    def test_existing_file_is_replaced(self):
        self.upload(content=b"flowchart LR\nA-->B")
        response = self.upload(content=b"flowchart LR\nB-->C")
        self.assertEqual(response.get_json()["replaced"], ["diagram.mmd"])
        self.assertIn("B-->C", self.client.get("/api/file?path=diagram.mmd").get_json()["content"])

    def test_rejects_wrong_extension_traversal_and_invalid_utf8(self):
        for path, content in (("notes.txt", b"hello"), ("../escape.mmd", b"ok"), ("bad.mmd", b"\xff")):
            with self.subTest(path=path):
                response = self.upload(path, content)
                self.assertEqual(response.status_code, 400)
                self.assertTrue(response.get_json()["rejected"])
        self.assertFalse((Path(self.temporary.name).parent / "escape.mmd").exists())

    def test_partial_upload_reports_rejection(self):
        response = self.client.post(
            "/api/files",
            data={
                "paths": ["good.mmd", "bad.txt"],
                "files": [(io.BytesIO(b"graph TD; A-->B"), "good.mmd"), (io.BytesIO(b"no"), "bad.txt")],
            },
            content_type="multipart/form-data",
        )
        body = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(body["accepted"], ["good.mmd"])
        self.assertEqual(len(body["rejected"]), 1)

    def test_delete_file_and_empty_parent(self):
        self.upload("folder/item.mmd")
        response = self.client.delete("/api/file?path=folder/item.mmd")
        self.assertEqual(response.status_code, 200)
        self.assertFalse((Path(self.temporary.name) / "folder").exists())

    def test_rename_file_and_directory(self):
        self.upload("old-folder/old.mmd")
        file_response = self.client.patch(
            "/api/path",
            json={"type": "file", "old_path": "old-folder/old.mmd", "new_path": "old-folder/new.mmd"},
        )
        self.assertEqual(file_response.status_code, 200)
        directory_response = self.client.patch(
            "/api/path",
            json={"type": "directory", "old_path": "old-folder", "new_path": "new-folder"},
        )
        self.assertEqual(directory_response.status_code, 200)
        self.assertEqual(self.client.get("/api/files").get_json()["files"], ["new-folder/new.mmd"])

    def test_rename_rejects_collision_and_invalid_extension(self):
        self.upload("one.mmd")
        self.upload("two.mmd")
        collision = self.client.patch(
            "/api/path", json={"type": "file", "old_path": "one.mmd", "new_path": "two.mmd"}
        )
        invalid = self.client.patch(
            "/api/path", json={"type": "file", "old_path": "one.mmd", "new_path": "one.txt"}
        )
        self.assertEqual(collision.status_code, 409)
        self.assertEqual(invalid.status_code, 400)

    def test_symlinks_are_not_listed_or_read(self):
        outside = Path(self.temporary.name).parent / "outside-test.mmd"
        outside.write_text("graph TD; X-->Y", encoding="utf-8")
        link = Path(self.temporary.name) / "link.mmd"
        try:
            link.symlink_to(outside)
            self.assertEqual(self.client.get("/api/files").get_json()["files"], [])
            self.assertEqual(self.client.get("/api/file?path=link.mmd").status_code, 400)
        finally:
            link.unlink(missing_ok=True)
            outside.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
