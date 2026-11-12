import os
import re
import unittest

os.environ.setdefault("CRUCIBLE_API_KEY", "test-api-key")

from app import create_app
from tool_registry import divisions_with_tools, validate_registry

DIVISIONS = [{"key": "b30", "label": "B30", "description": "Building 30"}]
TOOL = {"key": "sem", "division": "b30", "endpoint": "b30_sem.page",
        "nav_label": "SEM", "card_title": "SEM", "card_description": "SEM data entry"}


class RegistryValidationTests(unittest.TestCase):
    def test_valid_registry_passes(self):
        validate_registry(DIVISIONS, [TOOL], {"b30_sem.page"})

    def test_reports_every_problem(self):
        bad = [
            {**TOOL, "division": "nowhere"},
            {**TOOL, "endpoint": "missing.page"},
            {"key": "partial", "division": "b30"},
        ]
        with self.assertRaises(ValueError) as ctx:
            validate_registry(DIVISIONS, bad, {"b30_sem.page"})
        message = str(ctx.exception)
        self.assertIn("unknown division 'nowhere'", message)
        self.assertIn("unregistered endpoint 'missing.page'", message)
        self.assertIn("duplicate tool key sem", message)
        self.assertIn("tool partial is missing", message)

    def test_divisions_without_tools_are_dropped(self):
        divisions = DIVISIONS + [{"key": "b67", "label": "B67", "description": "Building 67"}]
        result = divisions_with_tools(divisions, [TOOL])
        self.assertEqual([d["key"] for d in result], ["b30"])


class DivisionPagesTests(unittest.TestCase):
    def setUp(self):
        app = create_app()
        app.config.update(TESTING=True, SECRET_KEY="test")
        self.client = app.test_client()

    def test_home_lists_divisions_with_tools(self):
        html = self.client.get("/").get_data(as_text=True)
        self.assertIn('href="/division/als"', html)
        self.assertIn('href="/division/b30"', html)
        self.assertIn('href="/division/b67"', html)

    def test_b67_lists_synthesis_upload(self):
        html = self.client.get("/division/b67").get_data(as_text=True).split('<main class="container">', 1)[1]
        self.assertIn('href="/synthesis/"', html)
        self.assertIn('href="/fabrication/"', html)

    def test_division_page_lists_its_tools(self):
        html = self.client.get("/division/b30").get_data(as_text=True)
        html = html.split('<main class="container">', 1)[1]  # skip the nav, which links every tool
        for path in ("/b30-aja-sputter/", "/b30-kjlesker-sputter/", "/b30-ebeam/", "/b30-sem/",
                     "/electrolyte/", "/schema-forms/", "/print/"):
            self.assertIn(f'href="{path}"', html)
        self.assertNotIn('href="/giwaxs/"', html)

    def test_unknown_division_is_404(self):
        self.assertEqual(self.client.get("/division/nope").status_code, 404)

    def test_every_nav_link_resolves(self):
        html = self.client.get("/").get_data(as_text=True)
        nav = html.split('<div class="nav-links">', 1)[1].split('<div class="nav-user"', 1)[0]
        links = set(re.findall(r'href="([^"]+)"', nav))
        self.assertIn("/b30-sem/", links)
        for link in links:
            with self.subTest(link=link):
                self.assertEqual(self.client.get(link).status_code, 200)


if __name__ == "__main__":
    unittest.main()
