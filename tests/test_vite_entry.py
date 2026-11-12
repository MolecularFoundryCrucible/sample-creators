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

    def test_includes_css_and_preloads_from_shared_imported_chunks(self):
        os.makedirs(os.path.join(self.static.name, "dist", ".vite"))
        manifest = {
            "_shared.js": {"file": "assets/shared-1.js", "css": ["assets/shared-1.css"], "imports": ["_react.js"]},
            "_react.js": {"file": "assets/react-1.js"},
            "src/traveler.jsx": {"file": "assets/traveler-1.js", "name": "traveler", "isEntry": True,
                                 "imports": ["_shared.js", "_react.js"]},
        }
        with open(os.path.join(self.static.name, "dist", ".vite", "manifest.json"), "w") as f:
            json.dump(manifest, f)
        with self.app.test_request_context("/"):
            html = render_template_string("{{ vite_entry('traveler') }}")
        self.assertIn('rel="stylesheet" href="/static/dist/assets/shared-1.css', html)
        self.assertEqual(html.count("react-1.js"), 1)
        self.assertIn('rel="modulepreload" href="/static/dist/assets/shared-1.js', html)
        self.assertIn('<script type="module" src="/static/dist/assets/traveler-1.js', html)

    def test_missing_build_renders_a_comment(self):
        self.assertEqual(self.render(), "<!-- vite entry upload missing -->")


if __name__ == "__main__":
    unittest.main()
