import os
import unittest
from unittest.mock import patch

os.environ.setdefault("CRUCIBLE_API_KEY", "test-api-key")

from app import create_app  # noqa: E402
from config import B30_XPS_CONFIG  # noqa: E402
from routes.b30_xps import _dataset_to_row as xps_row  # noqa: E402
import routes.b30_xps  # noqa: E402
import tools.b30_xps  # noqa: E402

DATASET = "0tkn2knjast3h0008nyq9zps2c"


class XpsPageTests(unittest.TestCase):
    def setUp(self):
        app = create_app()
        app.config.update(TESTING=True, SECRET_KEY="test")
        self.client = app.test_client()
        with self.client.session_transaction() as sess:
            sess["user"] = {"orcid": "0000-0001-2345-6789", "selected_project": "p1", "projects": ["p1"]}
            sess["b30_xps"] = {
                "sample_unique_id": "sample-1",
                "sample_name": "film",
                "sample_type": "wafer",
                "sample_description": "",
            }

    def test_routes_alias(self):
        self.assertIs(routes.b30_xps, tools.b30_xps)

    def test_page_renders_with_shared_scripts_and_fields(self):
        html = self.client.get("/b30-xps/").get_data(as_text=True)
        self.assertIn('id="xps-files"', html)
        self.assertIn('data-key="anode_material"', html)
        self.assertIn('data-key="photon_energy_eV"', html)
        self.assertIn('data-key="anode_voltage_V"', html)
        self.assertIn('data-key="emission_current_A"', html)
        self.assertIn('data-key="stage_position_name"', html)
        self.assertIn('data-key="technique"', html)
        self.assertIn('data-key="comment"', html)
        self.assertIn("js/instrument_page.js", html)
        self.assertIn("js/b30_xps.js", html)

    def test_dataset_upload_creates_dataset_with_typed_fields_and_links_sample(self):
        with patch("routes.shared.cruc_client.datasets.create", return_value={"dataset_mfid": DATASET}) as create, \
             patch("routes.shared.cruc_client.datasets.link_sample") as link_sample:
            r = self.client.post("/b30-xps/api/upload-dataset", json={
                "anode_material": "Al Mono",
                "photon_energy_eV": "1486.69",
                "anode_voltage_V": "15000",
                "emission_current_A": "0.005",
                "stage_position_name": "S37",
                "technique": "XPS",
                "comment": "test comment",
            })
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        ds = create.call_args.args[0]
        self.assertEqual(ds.instrument_mfid, "0tqx1eq8b5t8h000y3zm23mwmw")
        self.assertEqual(ds.instrument_mfid, B30_XPS_CONFIG["instrument_mfid"])
        self.assertEqual(ds.measurement, "XPS")
        self.assertEqual(ds.data_type, "XPS Spectrum")
        self.assertIn("_XPS_on_film", ds.dataset_name)
        self.assertEqual(create.call_args.kwargs["scientific_metadata"], {
            "anode_material": "Al Mono",
            "photon_energy_eV": 1486.69,
            "anode_voltage_V": 15000.0,
            "emission_current_A": 0.005,
            "stage_position_name": "S37",
            "technique": "XPS",
            "comment": "test comment",
        })
        link_sample.assert_called_once_with(dataset_mfid=DATASET, sample_mfid="sample-1")

    def test_dataset_to_row_formats_all_columns(self):
        details = {
            "unique_id": "ds-001",
            "timestamp": "2026-06-18T11:02:18",
            "owner": {"unique_id": "u1", "first_name": "Jane", "last_name": "Doe"},
            "owner_orcid": "0000-0002-1825-0097",
            "scientific_metadata": {
                "anode_material": "Al Mono",
                "photon_energy_eV": 1486.69,
                "anode_voltage_V": 15000,
                "emission_current_A": 0.005,
                "stage_position_name": "S37",
                "total_spectra": 2,
                "spectra": [
                    {"region": "Survey"},
                    {"region": "C 1s"},
                ],
                "comment": "spectrum comment",
            },
        }
        row = xps_row(details)
        self.assertEqual(row["Date"], "2026-06-18 11:02")
        self.assertIn("Jane Doe", row["User"])
        self.assertEqual(row["Anode"], "Al Mono")
        self.assertEqual(row["Photon (eV)"], "1486.69")
        self.assertEqual(row["Voltage (V)"], "15000")
        self.assertEqual(row["Current (A)"], "0.005")
        self.assertEqual(row["Position"], "S37")
        self.assertEqual(row["Spectra"], "2")
        self.assertEqual(row["Regions"], "Survey, C 1s")
        self.assertEqual(row["Comment"], "spectrum comment")

    def test_dataset_to_row_comment_fallback(self):
        details = {
            "timestamp": "2026-06-18T11:02:18",
            "scientific_metadata": {
                "dataset_comment": "fallback comment",
                "spectra": [{"region": "Survey"}, {"region": "Survey"}],
            },
        }
        row = xps_row(details)
        self.assertEqual(row["Comment"], "fallback comment")
        self.assertEqual(row["Spectra"], "2")
        self.assertEqual(row["Regions"], "Survey")


if __name__ == "__main__":
    unittest.main()
