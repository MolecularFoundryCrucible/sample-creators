import json
import os
import tempfile
import unittest

os.environ.setdefault("CRUCIBLE_API_KEY", "test-api-key")

from flask import render_template_string

from app import create_app


class ViteEntryTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.static = tempfile.TemporaryDirectory()
        self.addCleanup(self.static.cleanup)
        self.app.static_folder = self.static.name

    def render(self):
        with self.app.test_request_context("/"):
            return render_template_string("{{ vite_entry('upload') }}")

    def test_renders_script_and_css_for_built_entry(self):
        os.makedirs(os.path.join(self.static.name, "dist", ".vite"))
        manifest = {"src/upload/index.ts": {"file": "assets/upload-abc.js", "name": "upload", "isEntry": True,
                                            "css": ["assets/upload-abc.css"]}}
        with open(os.path.join(self.static.name, "dist", ".vite", "manifest.json"), "w") as f:
            json.dump(manifest, f)
        html = self.render()
        self.assertIn('<script type="module" src="/static/dist/assets/upload-abc.js', html)
        self.assertIn('<link rel="stylesheet" href="/static/dist/assets/upload-abc.css', html)

    def test_missing_build_renders_a_comment(self):
        self.assertEqual(self.render(), "<!-- vite entry upload missing -->")


if __name__ == "__main__":
    unittest.main()
