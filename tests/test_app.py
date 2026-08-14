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
        self.assertEqual(loaded.get_json()["type"], "mermaid")
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

    def test_delete_directory_and_all_its_content(self):
        self.upload("folder/README.md", b"# Docs")
        self.upload("folder/nested/item.mmd")
        response = self.client.delete("/api/directory?path=folder")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["deleted"], "folder")
        self.assertFalse((Path(self.temporary.name) / "folder").exists())
        self.assertEqual(self.client.get("/api/files").get_json()["files"], [])

    def test_delete_directory_rejects_root_traversal_and_symlinks(self):
        self.assertEqual(self.client.delete("/api/directory?path=..").status_code, 400)
        folder = Path(self.temporary.name) / "folder"
        folder.mkdir()
        outside = Path(self.temporary.name).parent / "outside-directory-test.txt"
        outside.write_text("keep", encoding="utf-8")
        link = folder / "link"
        try:
            link.symlink_to(outside)
            response = self.client.delete("/api/directory?path=folder")
            self.assertEqual(response.status_code, 400)
            self.assertTrue(folder.exists())
            self.assertEqual(outside.read_text(encoding="utf-8"), "keep")
        finally:
            link.unlink(missing_ok=True)
            outside.unlink(missing_ok=True)

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

    def test_move_file_and_directory_between_folders_and_root(self):
        self.upload("source/item.md", b"# Item")
        self.upload("source/nested/diagram.mmd")
        self.upload("target/keep.mmd")

        moved_file = self.client.patch(
            "/api/path",
            json={"type": "file", "old_path": "source/item.md", "new_path": "target/item.md"},
        )
        moved_directory = self.client.patch(
            "/api/path",
            json={"type": "directory", "old_path": "source/nested", "new_path": "nested"},
        )

        self.assertEqual(moved_file.status_code, 200)
        self.assertEqual(moved_directory.status_code, 200)
        self.assertEqual(
            self.client.get("/api/files").get_json()["files"],
            ["nested/diagram.mmd", "target/item.md", "target/keep.mmd"],
        )

    def test_move_directory_rejects_nested_symlink(self):
        self.upload("source/item.mmd")
        outside = Path(self.temporary.name).parent / "outside-move-test.mmd"
        outside.write_text("keep", encoding="utf-8")
        link = Path(self.temporary.name) / "source" / "link.mmd"
        try:
            link.symlink_to(outside)
            response = self.client.patch(
                "/api/path",
                json={"type": "directory", "old_path": "source", "new_path": "target/source"},
            )
            self.assertEqual(response.status_code, 400)
            self.assertTrue((Path(self.temporary.name) / "source").is_dir())
        finally:
            link.unlink(missing_ok=True)
            outside.unlink(missing_ok=True)

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

    def test_upload_list_read_and_delete_readme(self):
        response = self.upload("docs/README.md", b"# Documentation\n\n```mermaid\ngraph TD; A-->B\n```")
        self.assertEqual(response.status_code, 200)
        listing = self.client.get("/api/files").get_json()
        self.assertEqual(listing, {"files": ["docs/README.md"], "count": 1})
        loaded = self.client.get("/api/file?path=docs/README.md").get_json()
        self.assertEqual(loaded["type"], "markdown")
        self.assertIn("# Documentation", loaded["content"])
        self.assertEqual(self.client.delete("/api/file?path=docs/README.md").status_code, 200)

    def test_all_markdown_names_and_case_variants_are_accepted(self):
        accepted = self.upload("project/readme.MD", b"# Project")
        notes = self.upload("project/notes.md", b"# Notes")
        self.assertEqual(accepted.status_code, 200)
        self.assertEqual(notes.status_code, 200)
        self.assertEqual(
            self.client.get("/api/files").get_json()["files"],
            ["project/notes.md", "project/readme.MD"],
        )

    def test_mixed_mermaid_and_markdown_upload(self):
        response = self.client.post(
            "/api/files",
            data={
                "paths": ["diagram.mmd", "README.md", "notes.md"],
                "files": [
                    (io.BytesIO(b"graph TD; A-->B"), "diagram.mmd"),
                    (io.BytesIO(b"# Read me"), "README.md"),
                    (io.BytesIO(b"# Notes"), "notes.md"),
                ],
            },
            content_type="multipart/form-data",
        )
        body = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(body["accepted"], ["diagram.mmd", "README.md", "notes.md"])
        self.assertEqual(body["rejected"], [])

    def test_rename_markdown_file(self):
        self.upload("docs/notes.md", b"# Notes")
        response = self.client.patch(
            "/api/path",
            json={"type": "file", "old_path": "docs/notes.md", "new_path": "docs/guide.MD"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.get("/api/files").get_json()["files"], ["docs/guide.MD"])

    def test_rename_directory_preserves_readme_and_mermaid(self):
        self.upload("old/README.md", b"# Read me")
        self.upload("old/diagram.mmd")
        response = self.client.patch(
            "/api/path", json={"type": "directory", "old_path": "old", "new_path": "new"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            self.client.get("/api/files").get_json()["files"],
            ["new/diagram.mmd", "new/README.md"],
        )

    def test_update_markdown_task_marker_only(self):
        original = b"# Plano\n\n- [ ] Primeira\n  detalhe preservado\n- [!] Segunda\n"
        self.upload("plan.md", original)

        response = self.client.patch(
            "/api/markdown/task",
            json={"path": "plan.md", "line": 2, "previous_state": " ", "state": "x"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            (Path(self.temporary.name) / "plan.md").read_text(encoding="utf-8"),
            "# Plano\n\n- [x] Primeira\n  detalhe preservado\n- [!] Segunda\n",
        )

    def test_only_one_markdown_task_can_be_in_progress(self):
        self.upload("plan.md", b"- [>] Primeira\n- [ ] Segunda\n- [x] Terceira\n")

        response = self.client.patch(
            "/api/markdown/task",
            json={"path": "plan.md", "line": 1, "previous_state": " ", "state": ">"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["content"], "- [ ] Primeira\n- [>] Segunda\n- [x] Terceira\n")

    def test_update_task_rejects_stale_invalid_and_mermaid_requests(self):
        self.upload("plan.md", b"- [ ] Tarefa\ntexto comum\n")
        self.upload("diagram.mmd")

        stale = self.client.patch(
            "/api/markdown/task",
            json={"path": "plan.md", "line": 0, "previous_state": "x", "state": "!"},
        )
        ordinary_line = self.client.patch(
            "/api/markdown/task",
            json={"path": "plan.md", "line": 1, "previous_state": " ", "state": "x"},
        )
        invalid_state = self.client.patch(
            "/api/markdown/task",
            json={"path": "plan.md", "line": 0, "previous_state": " ", "state": "?"},
        )
        mermaid = self.client.patch(
            "/api/markdown/task",
            json={"path": "diagram.mmd", "line": 0, "previous_state": " ", "state": "x"},
        )

        self.assertEqual(stale.status_code, 409)
        self.assertEqual(ordinary_line.status_code, 409)
        self.assertEqual(invalid_state.status_code, 400)
        self.assertEqual(mermaid.status_code, 400)
        self.assertEqual((Path(self.temporary.name) / "plan.md").read_bytes(), b"- [ ] Tarefa\ntexto comum\n")

    def test_update_task_rejects_marker_inside_code_fence(self):
        self.upload("plan.md", b"```text\n- [ ] Isto e codigo\n```\n- [ ] Tarefa real\n")

        fenced = self.client.patch(
            "/api/markdown/task",
            json={"path": "plan.md", "line": 1, "previous_state": " ", "state": "x"},
        )
        real = self.client.patch(
            "/api/markdown/task",
            json={"path": "plan.md", "line": 3, "previous_state": " ", "state": "x"},
        )

        self.assertEqual(fenced.status_code, 409)
        self.assertEqual(real.status_code, 200)
        self.assertIn("- [ ] Isto e codigo", real.get_json()["content"])

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
