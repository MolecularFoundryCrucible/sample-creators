import os
import unittest
from unittest.mock import patch

os.environ.setdefault("CRUCIBLE_API_KEY", "test-api-key")

from app import create_app  # noqa: E402
from config import B30_RAMAN_CONFIG  # noqa: E402
from routes.b30_raman import _dataset_to_row as raman_row  # noqa: E402
from routes.instrument_page import form_metadata  # noqa: E402

DATASET = "0tkn2knjast3h0008nyq9zps2c"
FIELDS = [
    {"key": "comment", "type": "text"},
    {"key": "spot_size", "type": "number"},
    {"key": "laser_wavelength_nm", "type": "number", "as_number": True},
    {"key": "raman_shift_range_cm-1", "type": "range"},
]


class FormMetadataTests(unittest.TestCase):
    def test_types_follow_the_field_config(self):
        out = form_metadata(FIELDS, {"comment": "  hi ", "spot_size": "3", "laser_wavelength_nm": "532.06",
                                     "raman_shift_range_cm-1": [150, "1500"], "unknown": "x"})
        self.assertEqual(out, {"comment": "hi", "spot_size": "3", "laser_wavelength_nm": 532.06,
                               "raman_shift_range_cm-1": [150.0, 1500.0]})

    def test_empty_and_invalid_values_are_left_out(self):
        out = form_metadata(FIELDS, {"comment": " ", "laser_wavelength_nm": "abc", "raman_shift_range_cm-1": [150]})
        self.assertEqual(out, {})


class RamanPageTests(unittest.TestCase):
    def setUp(self):
        app = create_app()
        app.config.update(TESTING=True, SECRET_KEY="test")
        self.client = app.test_client()
        with self.client.session_transaction() as sess:
            sess["user"] = {"orcid": "0000-0001-2345-6789", "selected_project": "p1", "projects": ["p1"]}
            sess["b30_raman"] = {"sample_unique_id": "sample-1", "sample_name": "film", "sample_type": "t",
                                 "sample_description": ""}

    def test_page_renders_with_shared_scripts(self):
        html = self.client.get("/b30-raman/").get_data(as_text=True)
        self.assertIn('id="raman-files"', html)
        self.assertIn('data-key="raman_shift_range_cm-1" data-range-index="1"', html)
        self.assertIn("js/instrument_page.js", html)
        self.assertIn("js/b30_raman.js", html)

    def test_dataset_uses_raman_instrument_and_typed_fields(self):
        with patch("routes.shared.cruc_client.datasets.create", return_value={"dataset_mfid": DATASET}) as create, \
             patch("routes.shared.cruc_client.datasets.add_sample") as add_sample:
            r = self.client.post("/b30-raman/api/upload-dataset", json={
                "laser_wavelength_nm": "532.06", "exposure_time_s": "60", "accumulation": "1 x 9",
                "raman_shift_range_cm-1": [150, 1500], "comment": "c"})
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        ds = create.call_args.args[0]
        self.assertEqual(ds.instrument_mfid, B30_RAMAN_CONFIG["instrument_mfid"])
        self.assertEqual(ds.measurement, "Raman spectroscopy")
        self.assertEqual(ds.data_type, "Raman Spectrum")
        self.assertIn("_Raman_on_film", ds.dataset_name)
        self.assertEqual(create.call_args.kwargs["scientific_metadata"], {
            "laser_wavelength_nm": 532.06, "exposure_time_s": 60.0, "accumulation": "1 x 9",
            "raman_shift_range_cm-1": [150.0, 1500.0], "comment": "c"})
        add_sample.assert_called_once_with(dataset_mfid=DATASET, sample_mfid="sample-1")

    def test_logbook_row(self):
        row = raman_row({"timestamp": "2026-06-18T11:02:18", "scientific_metadata": {
            "laser_wavelength_nm": 532.06, "exposure_time_s": 60.0, "accumulation": "1 x 9", "grating": "1800",
            "objective": "x50", "raman_shift_range_cm-1": [150.0, 1500.0], "raman_spectra": {"a.ngs": {}, "b.ngs": {}}}})
        self.assertEqual((row["Date"], row["Laser (nm)"], row["Exposure (s)"], row["Range (1/cm)"], row["Spectra"]),
                         ("2026-06-18 11:02", "532.06", "60", "150–1500", "2"))


if __name__ == "__main__":
    unittest.main()
