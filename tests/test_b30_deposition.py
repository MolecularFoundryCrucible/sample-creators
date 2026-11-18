import csv
import io
import os
import unittest
import warnings
from unittest.mock import patch

os.environ.setdefault("CRUCIBLE_API_KEY", "test-api-key")

try:
    from tests import fake_crucible  # noqa: E402
except ImportError:
    import fake_crucible  # noqa: E402
from app import create_app  # noqa: E402
from config import B30_EBEAM_CONFIG, SPUTTER_TOOLS  # noqa: E402
from crucible import Dataset, Sample  # noqa: E402
from routes import b30_sputter, deposition_common  # noqa: E402
from routes.shared import cruc_client  # noqa: E402


class B30EbeamEndToEndTests(unittest.TestCase):
    def setUp(self):
        deposition_common._INCREMENTAL_CACHE.clear()
        self.addCleanup(deposition_common._INCREMENTAL_CACHE.clear)
        self.store, restore = fake_crucible.install(cruc_client)
        self.addCleanup(restore)

        app = create_app()
        app.config.update(TESTING=True, SECRET_KEY="test")
        self.client = app.test_client()
        self.user = {
            "orcid": "0000-0001-2345-6789",
            "username": "firstlast",
            "first_name": "First",
            "last_name": "Lastname",
            "projects": ["proj-ebeam"],
            "selected_project": "proj-ebeam",
        }
        self.store["users"][self.user["orcid"]] = dict(self.user)
        with self.client.session_transaction() as sess:
            sess["user"] = dict(self.user)

    def test_upload_recent_datasets_target_options_and_csv_export(self):
        created_sample = self.client.post("/b30-ebeam/api/create-sample", json={
            "sample_name": "EB-SAMP-01",
            "sample_type": "thin film",
            "description": "e-beam substrate",
        })
        self.assertEqual(created_sample.status_code, 200, created_sample.get_data(as_text=True))
        sample_id = created_sample.get_json()["unique_id"]

        with patch("routes.b30_ebeam.get_tz_isoformat", return_value="2026-10-01T09:00:00-07:00"):
            up_au = self.client.post("/b30-ebeam/api/upload-dataset", json={
                "01_target_material": "Au",
                "02_power_W": "120",
                "03_rate_A_s": "1.5",
                "04_base_pressure_mTorr": "1e-6",
                "05_deposition_pressure_mTorr": "2e-6",
                "06_comment": "gold layer",
            })
        self.assertEqual(up_au.status_code, 200, up_au.get_data(as_text=True))
        ds_au = up_au.get_json()["dataset_id"]
        self.assertIn((sample_id, ds_au), self.store["sample_datasets"])

        with patch("routes.b30_ebeam.get_tz_isoformat", return_value="2026-10-01T10:30:00-07:00"):
            up_ti = self.client.post("/b30-ebeam/api/upload-dataset", json={
                "01_target_material": "Ti",
                "02_power_W": "80",
                "03_rate_A_s": "0.5",
                "06_comment": "adhesion layer",
            })
        self.assertEqual(up_ti.status_code, 200, up_ti.get_data(as_text=True))
        ds_ti = up_ti.get_json()["dataset_id"]
        self.assertIn((sample_id, ds_ti), self.store["sample_datasets"])

        recent = self.client.get("/b30-ebeam/api/recent-datasets")
        self.assertEqual(recent.status_code, 200, recent.get_data(as_text=True))
        recent_body = recent.get_json()
        self.assertEqual(recent_body["count"], 2)
        self.assertEqual([r["Target"] for r in recent_body["rows"]], ["Ti", "Au"])
        for r in recent_body["rows"]:
            self.assertNotIn("_target_1", r)

        au_only = self.client.get("/b30-ebeam/api/recent-datasets?target=Au")
        self.assertEqual(au_only.status_code, 200)
        self.assertEqual(au_only.get_json()["count"], 1)
        self.assertEqual(au_only.get_json()["rows"][0]["Target"], "Au")

        opts = self.client.get("/b30-ebeam/api/recent-target-options")
        self.assertEqual(opts.status_code, 200, opts.get_data(as_text=True))
        self.assertEqual(opts.get_json(), {"options": ["All", "Au", "Ti"]})

        csv_res = self.client.get("/b30-ebeam/api/recent-datasets/b30_ebeam_recent_datasets.csv")
        self.assertEqual(csv_res.status_code, 200)
        self.assertIn("text/csv", csv_res.mimetype)
        parsed = list(csv.reader(io.StringIO(csv_res.get_data().decode("utf-8-sig"))))
        self.assertEqual(
            parsed[0],
            ["Date", "User", "Target", "Power (W)", "Rate (Å/s)",
             "Base press. (mTorr)", "Dep. press. (mTorr)", "Comment"],
        )
        self.assertEqual([row[2] for row in parsed[1:]], ["Ti", "Au"])
        self.assertEqual(
            self.store["datasets"][ds_au]["instrument_mfid"],
            B30_EBEAM_CONFIG["instrument_mfid"],
        )

    def test_recent_endpoints_require_login_and_selected_project(self):
        with self.client.session_transaction() as sess:
            sess["user"] = {**self.user, "selected_project": ""}
        self.assertEqual(self.client.get("/b30-ebeam/api/recent-datasets").status_code, 400)

        with self.client.session_transaction() as sess:
            sess.pop("user", None)
        self.assertEqual(self.client.get("/b30-ebeam/api/recent-datasets").status_code, 401)


class B30SputterEndToEndTests(unittest.TestCase):
    def setUp(self):
        b30_sputter._RATE_INDEXES.clear()
        deposition_common._INCREMENTAL_CACHE.clear()
        self.addCleanup(b30_sputter._RATE_INDEXES.clear)
        self.addCleanup(deposition_common._INCREMENTAL_CACHE.clear)
        self.store, restore = fake_crucible.install(cruc_client)
        self.addCleanup(restore)

        self.app = create_app()
        self.app.config.update(TESTING=True, SECRET_KEY="test")
        self.client = self.app.test_client()
        self.user = {
            "orcid": "0000-0001-2345-6789",
            "projects": ["proj-sputter"],
            "selected_project": "proj-sputter",
        }
        with self.client.session_transaction() as sess:
            sess["user"] = dict(self.user)

    def test_rate_index_lookup_and_reload_without_deprecation_warnings(self):
        ref_sample = SPUTTER_TOOLS["aja"]["calibration_sample_id"]
        self.store["samples"][ref_sample] = {
            "unique_id": ref_sample,
            "sample_name": "AJA_CALIBRATION",
            "sample_type": "reference",
            "project_id": "proj-sputter",
        }

        common_sci = {
            "09_target_material": "Pt",
            "03_gas1": "Ar",
            "04_gas1_pc": "100",
            "11_power_W": "100",
            "07_pressure_mTorr": "3.0",
            "10_power_source": "DC",
        }
        older = cruc_client.datasets.create(
            Dataset(
                dataset_name="Calib Older",
                project_id="proj-sputter",
                instrument_mfid=SPUTTER_TOOLS["aja"]["instrument_mfid"],
                timestamp="2026-10-01T10:00:00-07:00",
            ),
            scientific_metadata={**common_sci, "19_rate_A_s": 1.25},
        )["dataset_mfid"]
        newer = cruc_client.datasets.create(
            Dataset(
                dataset_name="Calib Newer",
                project_id="proj-sputter",
                instrument_mfid=SPUTTER_TOOLS["aja"]["instrument_mfid"],
                timestamp="2026-10-02T10:00:00-07:00",
            ),
            scientific_metadata={**common_sci, "19_rate_A_s": 1.55},
        )["dataset_mfid"]
        # Unlinked dataset with a newer timestamp must NOT pollute the calibration sample rate index.
        cruc_client.datasets.create(
            Dataset(
                dataset_name="Unlinked Deposition",
                project_id="proj-sputter",
                instrument_mfid=SPUTTER_TOOLS["aja"]["instrument_mfid"],
                timestamp="2026-10-03T10:00:00-07:00",
            ),
            scientific_metadata={**common_sci, "19_rate_A_s": 9.99},
        )
        cruc_client.datasets.link_sample(older, ref_sample)
        cruc_client.datasets.link_sample(newer, ref_sample)

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", DeprecationWarning)
            reloaded = self.client.post("/b30-aja-sputter/api/reload-rate-index")
            self.assertEqual(reloaded.status_code, 200, reloaded.get_data(as_text=True))
            self.assertEqual(reloaded.get_json()["count"], 1)

            looked_up = self.client.post("/b30-aja-sputter/api/lookup-rate", json=common_sci)
            self.assertEqual(looked_up.status_code, 200, looked_up.get_data(as_text=True))
            body = looked_up.get_json()
            self.assertTrue(body["found"])
            self.assertEqual(body["19_rate_A_s"], 1.55)
            self.assertEqual(body["dataset_id"], newer)

        dep_warnings = [w for w in caught if issubclass(w.category, DeprecationWarning)]
        self.assertEqual(dep_warnings, [])

    def test_rate_index_falls_back_cleanly_for_shallow_dataset_stubs(self):
        ref_sample = "0tgfny1b35rwd000x35nr7a9d8"
        ds_id = "0tkn2knjast3h0008nyq9zps2c"
        sci = {
            "09_target_material": "SiO2",
            "03_gas1": "Ar",
            "04_gas1_pc": "100",
            "11_power_W": "150",
            "07_pressure_mTorr": "5",
            "10_power_source": "RF",
            "19_rate_A_s": "0.85",
        }
        for shallow_item in (
            {"unique_id": ds_id},
            {"unique_id": ds_id, "scientific_metadata": None, "timestamp": None},
        ):
            with self.subTest(shallow_item=shallow_item):
                with self.app.app_context(), \
                     patch("routes.b30_sputter.cruc_client.datasets.list", return_value=[shallow_item]), \
                     patch("routes.b30_sputter.cruc_client.datasets.get_scientific_metadata",
                           return_value={"unique_id": ds_id, "scientific_metadata": sci}) as get_md, \
                     patch("routes.b30_sputter.cruc_client.datasets.get",
                           return_value={"unique_id": ds_id, "timestamp": "2026-10-05T12:00:00-07:00"}) as get_ds:
                    idx = b30_sputter._build_rate_index_from_reference_sample(ref_sample)

                self.assertEqual(len(idx), 1)
                entry = next(iter(idx.values()))
                self.assertEqual(entry["19_rate_A_s"], 0.85)
                self.assertEqual(entry["timestamp"], "2026-10-05T12:00:00-07:00")
                get_md.assert_called_once_with(ds_id)
                get_ds.assert_called_once_with(ds_id)

    def test_create_and_update_sputter_dataset_against_fake_crucible(self):
        s1 = cruc_client.samples.create(Sample(
            sample_name="SP-SUB-1", sample_type="thin film", project_id="proj-sputter"
        ))
        s2 = cruc_client.samples.create(Sample(
            sample_name="SP-SUB-2", sample_type="thin film", project_id="proj-sputter"
        ))
        with self.client.session_transaction() as sess:
            sess["b30_sputter_aja"] = {"run_samples": [s1]}

        created = self.client.post("/b30-aja-sputter/api/create-dataset", json={
            "09_target_material": "Pt",
            "11_power_W": "100",
        })
        self.assertEqual(created.status_code, 200, created.get_data(as_text=True))
        c_body = created.get_json()
        ds_id = c_body["dataset_id"]
        self.assertIn((s1["unique_id"], ds_id), self.store["sample_datasets"])

        with self.client.session_transaction() as sess:
            sess["b30_sputter_aja"] = {"run_samples": [s1, s2]}

        updated = self.client.post("/b30-aja-sputter/api/update-dataset", json={
            "dataset_id": ds_id,
            "dataset_name": c_body["dataset_name"],
            "09_target_material": "Pt",
            "11_power_W": "125",
        })
        self.assertEqual(updated.status_code, 200, updated.get_data(as_text=True))
        self.assertIn((s2["unique_id"], ds_id), self.store["sample_datasets"])
        self.assertEqual(self.store["datasets"][ds_id]["scientific_metadata"]["11_power_W"], "125")


if __name__ == "__main__":
    unittest.main()
