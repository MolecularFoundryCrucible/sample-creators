import os
import sys
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("CRUCIBLE_API_KEY", "test-api-key")

from app import create_app
import tools
import tools.registry as reg


class ToolPluginRegistryTests(unittest.TestCase):
    def test_discover_tools_order_and_count(self):
        mods = reg.discover_tools(force_reload=True)
        expected_plugins = [
            ("giwaxs", 10, "als"),
            ("rga", 20, "als"),
            ("b30_sputter", 100, "b30"),
            ("b30_ebeam", 110, "b30"),
            ("b30_sem", 120, "b30"),
            ("b30_raman", 130, "b30"),
            ("b30_xps", 132, "b30"),
            ("b30_gc_ec", 135, "b30"),
            ("electrolyte", 140, "b30"),
            ("schema_forms", 150, "b30"),
            ("print_only", 160, "b30"),
            ("synthesis", 200, "b67"),
            ("nirvana", 210, "b67"),
            ("spinbot_spinrun", 220, "b67"),
            ("spinbot_photobox", 230, "b67"),
            ("inorganic_xrd", 240, "b67"),
            ("insitu_pl", 250, "b67"),
            ("dfs_microscope", 260, "b67"),
            ("fabrication", 270, "b67"),
            ("hip_microscope", 280, "b67"),
            ("tem_sessions", 290, "ncem"),
        ]
        self.assertEqual(len(mods), len(expected_plugins))
        actual = [(m.NAME, m.ORDER, m.DIVISION) for m in mods]
        self.assertEqual(actual, expected_plugins)

    def test_lookup_dicts(self):
        reg.discover_tools(force_reload=True)
        self.assertEqual(
            list(reg.TOOL_MODULES.keys()),
            [
                "giwaxs", "rga", "b30_sputter", "b30_ebeam", "b30_sem",
                "b30_raman", "b30_xps", "b30_gc_ec", "electrolyte", "schema_forms",
                "print_only", "synthesis", "nirvana", "spinbot_spinrun",
                "spinbot_photobox", "inorganic_xrd", "insitu_pl",
                "dfs_microscope", "fabrication", "hip_microscope", "tem_sessions",
            ],
        )
        self.assertEqual(
            reg.INSTRUMENT_MFIDS,
            {
                "b30_ebeam": "0tkvnttwxntbz000bzd7s875j0",
                "b30_sem": "0tkadnh6g9zys00089c7g5ycmg",
                "b30_raman": "0tqp46b2ess53000qg1b1t4scm",
                "b30_xps": "0tqx1eq8b5t8h000y3zm23mwmw",
                "b30_gc_ec": "0tmfg17radzgf000w544pxmwer",
                "insitu_pl": "0t0nah22xxxjd000gy940mm9d8",
                "dfs_microscope": "0tmz428dmnrf3000128mhfcmdg",
                "hip_microscope": "0sh6zrzxhxybd000wwyrkcn2cw",
                "inorganic_xrd": "0tmz7j9xmsrvn000tbs1zjwgpr",
                "spinbot_spinrun": "0sh6zrzxhxsa100089bznryq88",
                "spinbot_photobox": "0t4ptyzswnyps0006tqctfjbpr",
                "nirvana": "0t8vneqh81rbz000b41bdw6adw",
                "m3_microscope": "0tmz7kb6qdwfs000cyevpp43vc",
                "team05": "0szb5en16nxdk000dcd8a1wt2w",
                "team1": "0tbrbfgg2sstf000jk1bwhcvw8",
                "themis": "0t6k7ms7r5zak000bwynwcfacr",
                "titanx": "0sh6zrzxhnz8k000k7pwq0s2t8",
                "f200": "0tkkpbc07sv6z000x7b2f1bgs0",
                "spectre": "0tf06pwcg9ymf00014jzj3rzs8",
            },
        )
        self.assertEqual(
            reg.INGESTORS,
            {
                "b30_raman": "HoribaNgsIngestor",
                "b30_xps": "KratosXpsIngestor",
                "insitu_pl": "InSituPlIngestor",
                "dfs_microscope": "SingleSpecScopeFoundryH5Ingestor",
                "hip_microscope": "SingleSpecScopeFoundryH5Ingestor",
                "inorganic_xrd": "InorganicXRDIngestor",
                "spinbot_spinrun": "SpinbotSpinRunIngestor",
                "nirvana": "NirvanaMultiPosLineScanIngestor",
            },
        )
        self.assertEqual(reg.INSTRUMENT_IDS["insitu_pl"], "in-situ-pl")
        expected_tem_ids = {
            "m3_microscope": "m3-microscope",
            "team05": "team05",
            "team1": "team01",
            "themis": "themis",
            "titanx": "titanx",
            "f200": "f200",
            "spectre": "spectre",
        }
        for key, expected_id in expected_tem_ids.items():
            self.assertEqual(reg.INSTRUMENT_IDS[key], expected_id)
            self.assertEqual(reg.UI_MODES[key], "session")
            self.assertNotIn(key, reg.INGESTORS)
            self.assertNotIn(key, reg.POST_PROCESSING_STEPS)

    def test_module_aliases_and_mocking(self):
        import routes.giwaxs
        import tools.giwaxs
        self.assertIs(routes.giwaxs, tools.giwaxs)

        import routes.rga
        import tools.rga
        self.assertIs(routes.rga, tools.rga)

        import routes.b30_sputter
        import tools.b30_sputter
        self.assertIs(routes.b30_sputter, tools.b30_sputter)

        import routes.b30_ebeam
        import tools.b30_ebeam
        self.assertIs(routes.b30_ebeam, tools.b30_ebeam)

        import routes.b30_sem
        import tools.b30_sem
        self.assertIs(routes.b30_sem, tools.b30_sem)

        import routes.b30_raman
        import tools.b30_raman
        self.assertIs(routes.b30_raman, tools.b30_raman)

        import routes.b30_xps
        import tools.b30_xps
        self.assertIs(routes.b30_xps, tools.b30_xps)

        import routes.electrolyte
        import tools.electrolyte
        self.assertIs(routes.electrolyte, tools.electrolyte)

        import routes.schema_forms
        import tools.schema_forms
        self.assertIs(routes.schema_forms, tools.schema_forms)

        import routes.print_only
        import tools.print_only
        self.assertIs(routes.print_only, tools.print_only)

        import routes.synthesis
        import tools.synthesis
        self.assertIs(routes.synthesis, tools.synthesis)

        import routes.fabrication
        import tools.fabrication
        self.assertIs(routes.fabrication, tools.fabrication)

        import routes.chip_maps
        import tools.fabrication.chip_maps
        self.assertIs(routes.chip_maps, tools.fabrication.chip_maps)

        sentinel = object()
        with patch("routes.b30_sputter.cruc_client", sentinel):
            self.assertIs(tools.b30_sputter.cruc_client, sentinel)

        with patch("routes.giwaxs.cruc_client", sentinel):
            self.assertIs(tools.giwaxs.cruc_client, sentinel)

        from routes.chip_maps import chip_maps_bp
        self.assertIs(chip_maps_bp, tools.fabrication.chip_maps.chip_maps_bp)

    def test_dynamic_plugin_registration(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            plugin_dir = os.path.join(tmpdir, "dynamic_tool")
            os.makedirs(plugin_dir)
            with open(os.path.join(plugin_dir, "__init__.py"), "w") as f:
                f.write("""
from flask import Blueprint

dynamic_bp = Blueprint("dynamic_tool", __name__)

@dynamic_bp.route("/")
def page():
    return "Dynamic Tool OK"

NAME = "dynamic_tool"
DIVISION = "b30"
ORDER = 175
BLUEPRINT = dynamic_bp
URL_PREFIX = "/b30-dynamic"
KEY = "dynamic_tool"
ENDPOINT = "dynamic_tool.page"
NAV_LABEL = "Dynamic Tool"
CARD_TITLE = "Dynamic Tool Card"
CARD_DESCRIPTION = "A dynamically loaded tool"
""")
            original_path = list(tools.__path__)
            tools.__path__.append(tmpdir)
            try:
                mods = reg.discover_tools(force_reload=True)
                self.assertTrue(any(m.NAME == "dynamic_tool" for m in mods))

                app = create_app()
                app.config.update(TESTING=True, SECRET_KEY="test")
                client = app.test_client()

                resp = client.get("/b30-dynamic/")
                self.assertEqual(resp.status_code, 200)
                self.assertEqual(resp.data, b"Dynamic Tool OK")

                html = client.get("/division/b30").get_data(as_text=True)
                self.assertIn('href="/b30-dynamic/"', html)
                self.assertIn("Dynamic Tool Card", html)
            finally:
                tools.__path__ = original_path
                sys.modules.pop("tools.dynamic_tool", None)
                reg.discover_tools(force_reload=True)

    def test_populate_dicts_multi_tool_instruments(self):
        from types import SimpleNamespace

        fake_mod = SimpleNamespace(
            NAME="multi_fake",
            UI_MODE="session",
            INSTRUMENTS={
                "inst_a": {
                    "instrument_id": "inst-a",
                    "instrument_mfid": "0" + "a" * 25,
                    "ingestor": "FakeIngestor",
                    "ui_mode": "session",
                    "post_processing": ["step_one"],
                },
                "inst_b": {
                    "instrument_id": "inst-b",
                    "instrument_mfid": "0" + "b" * 25,
                    "ingestor": "",
                    "ui_mode": "session",
                    "post_processing": [],
                },
            },
        )
        try:
            reg._populate_dicts([fake_mod])
            self.assertEqual(reg.INSTRUMENT_IDS["inst_a"], "inst-a")
            self.assertEqual(reg.INSTRUMENT_MFIDS["inst_a"], "0" + "a" * 25)
            self.assertEqual(reg.INGESTORS["inst_a"], "FakeIngestor")
            self.assertEqual(reg.UI_MODES["inst_a"], "session")
            self.assertEqual(reg.POST_PROCESSING_STEPS["inst_a"], ["step_one"])

            self.assertEqual(reg.INSTRUMENT_IDS["inst_b"], "inst-b")
            self.assertEqual(reg.INSTRUMENT_MFIDS["inst_b"], "0" + "b" * 25)
            self.assertEqual(reg.UI_MODES["inst_b"], "session")
            self.assertNotIn("inst_b", reg.INGESTORS)
            self.assertNotIn("inst_b", reg.POST_PROCESSING_STEPS)
        finally:
            reg.discover_tools(force_reload=True)


if __name__ == "__main__":
    unittest.main()
