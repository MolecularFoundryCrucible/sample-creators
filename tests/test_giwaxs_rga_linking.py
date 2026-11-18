import os
import types
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("CRUCIBLE_API_KEY", "test-api-key")

try:
    from tests import fake_crucible  # noqa: E402
except ImportError:
    import fake_crucible  # noqa: E402
from app import create_app  # noqa: E402
from crucible import Dataset, Sample  # noqa: E402
from routes import giwaxs, rga  # noqa: E402
from routes.shared import cruc_client  # noqa: E402


class GiwaxsRgaAndFormLinkingTests(unittest.TestCase):
    def setUp(self):
        self.store, restore = fake_crucible.install(cruc_client)
        self.addCleanup(restore)
        giwaxs._pending_uploads.clear()
        rga._pending_uploads.clear()
        self.addCleanup(giwaxs._pending_uploads.clear)
        self.addCleanup(rga._pending_uploads.clear)

        app = create_app()
        app.config.update(TESTING=True, SECRET_KEY="test")
        self.client = app.test_client()
        self.user = {
            "orcid": "0000-0001-2345-6789",
            "projects": ["proj-1"],
            "selected_project": "proj-1",
        }
        with self.client.session_transaction() as sess:
            sess["user"] = dict(self.user)

    def test_giwaxs_scan_tray_filters_non_thin_film_children_and_upload_links_by_mfid(self):
        tray = cruc_client.samples.create(Sample(
            sample_name="TRAY-01", sample_type="tray", project_id="proj-1"
        ))
        tf2 = cruc_client.samples.create(Sample(
            sample_name="TF-02", sample_type="thin film", project_id="proj-1"
        ))
        tf1 = cruc_client.samples.create(Sample(
            sample_name="TF-01", sample_type="thin film", project_id="proj-1"
        ))
        substrate = cruc_client.samples.create(Sample(
            sample_name="SUB-99", sample_type="substrate", project_id="proj-1"
        ))
        wafer = cruc_client.samples.create(Sample(
            sample_name="WFR-01", sample_type="wafer", project_id="proj-1"
        ))
        untyped = cruc_client.samples.create(Sample(
            sample_name="UNTYPED-01", sample_type=None, project_id="proj-1"
        ))
        for child in (tf2, tf1, substrate, wafer, untyped):
            cruc_client.samples.link(parent_mfid=tray["unique_id"], child_mfid=child["unique_id"])

        # Confirm FakeSamples.list_children mirrors crucible-api v4.0.0 by ignoring sample_type.
        raw_children = cruc_client.samples.list_children(tray["unique_id"], sample_type="thin film")
        self.assertEqual(len(raw_children), 5)

        scan = self.client.post("/giwaxs/api/scan-tray", json={"tray_uuid": tray["unique_id"]})
        self.assertEqual(scan.status_code, 200, scan.get_data(as_text=True))
        self.assertEqual(scan.get_json(), {"tray_name": "TRAY-01", "thin_films": ["TF-01", "TF-02"]})

        bar = cruc_client.samples.create(Sample(
            sample_name="GWBAR000001", sample_type="giwaxs bar", project_id="proj-1"
        ))
        with self.client.session_transaction() as sess:
            sess["_id"] = "giwaxs-sid"
            sess["giwaxs"] = {
                "bar_name": "GWBAR000001",
                "bar_mf_uuid": bar["unique_id"],
                "bar_als_uuid": "als-bar-1",
                "positions": {str(i): ("TF-01" if i == 1 else "") for i in range(1, 12)},
                "offset_mm": 12.0,
                "wafer_width": 15.0,
                "incidence_angle": [0.1, 0.15],
                "esaf": "",
            }
        giwaxs._pending_uploads["giwaxs-sid"] = [{
            "bar_position": 1,
            "tf_name": "TF-01",
            "tf_mfid": tf1["unique_id"],
            "tf_descrip": "perovskite film",
            "sample_parameters": {"mfid": tf1["unique_id"], "sample_center_position": 12.0},
        }]

        fake_als = MagicMock()
        fake_als.sample_create.return_value = types.SimpleNamespace(slug="als-samp-1")
        with patch("routes.giwaxs.als_sc_client", fake_als):
            up = self.client.post("/giwaxs/api/upload")
        self.assertEqual(up.status_code, 200, up.get_data(as_text=True))
        self.assertIn((bar["unique_id"], tf1["unique_id"]), self.store["links"])

    def test_rga_scan_carrier_filters_non_thin_film_children_and_upload_links_by_mfid(self):
        carrier_tray = cruc_client.samples.create(Sample(
            sample_name="CARRIER-01", sample_type="tray", project_id="proj-1"
        ))
        tf_a = cruc_client.samples.create(Sample(
            sample_name="RGA-TF-A", sample_type="thin film", project_id="proj-1"
        ))
        chip_x = cruc_client.samples.create(Sample(
            sample_name="CHIP-X", sample_type="chip", project_id="proj-1"
        ))
        untyped_rga = cruc_client.samples.create(Sample(
            sample_name="UNTYPED-RGA", sample_type=None, project_id="proj-1"
        ))
        cruc_client.samples.link(parent_mfid=carrier_tray["unique_id"], child_mfid=tf_a["unique_id"])
        cruc_client.samples.link(parent_mfid=carrier_tray["unique_id"], child_mfid=chip_x["unique_id"])
        cruc_client.samples.link(parent_mfid=carrier_tray["unique_id"], child_mfid=untyped_rga["unique_id"])

        scan = self.client.post("/rga/api/scan-carrier", json={"carrier_uuid": carrier_tray["unique_id"]})
        self.assertEqual(scan.status_code, 200, scan.get_data(as_text=True))
        self.assertEqual(scan.get_json(), {"carrier_name": "CARRIER-01", "thin_films": ["RGA-TF-A"]})

        rga_carrier = cruc_client.samples.create(Sample(
            sample_name="RGA000001", sample_type="rga carrier", project_id="proj-1"
        ))
        with self.client.session_transaction() as sess:
            sess["_id"] = "rga-sid"
            sess["rga"] = {
                "rga_name": "RGA000001",
                "rga_mf_uuid": rga_carrier["unique_id"],
                "rga_als_uuid": "als-rga-1",
                "positions": {},
                "shutter_open_s": 5,
                "mass_range_amu": 100,
                "esaf": "",
            }
        rga._pending_uploads["rga-sid"] = [{
            "rga_position": "A1",
            "tf_name": "RGA-TF-A",
            "tf_mfid": tf_a["unique_id"],
            "tf_descrip": "film A",
            "sample_parameters": {"mfid": tf_a["unique_id"]},
        }]

        fake_als = MagicMock()
        fake_als.sample_create.return_value = types.SimpleNamespace(slug="als-rga-samp-1")
        with patch("routes.rga.als_sc_client", fake_als):
            up = self.client.post("/rga/api/upload")
        self.assertEqual(up.status_code, 200, up.get_data(as_text=True))
        self.assertIn((rga_carrier["unique_id"], tf_a["unique_id"]), self.store["links"])

    def test_electrolyte_and_schema_forms_end_to_end_with_fake_crucible(self):
        el = self.client.post("/electrolyte/api/create", json={
            "name": "LiPF6-EC-DMC",
            "preparation_date": "2026-10-15",
            "concentration": "1.0 M",
            "ph": 7.0,
            "ingredients": [{"type": "LiPF6", "amount": "1.0 M"}],
        })
        self.assertEqual(el.status_code, 201, el.get_data(as_text=True))
        el_body = el.get_json()
        self.assertIn((el_body["unique_id"], el_body["dataset_id"]), self.store["sample_datasets"])

        schema_res = self.client.post("/schema-forms/api/schemas", json={
            "name": "Hall Measurement",
            "fields": [{"name": "mobility_cm2_Vs", "type": "number", "required": True}],
        })
        self.assertEqual(schema_res.status_code, 201, schema_res.get_data(as_text=True))
        schema_id = schema_res.get_json()["id"]

        sample_res = self.client.post("/schema-forms/api/samples", json={
            "sample_name": "HALL-01",
            "sample_type": "thin film",
            "timestamp": "2026-10-15T14:30",
        })
        self.assertEqual(sample_res.status_code, 201, sample_res.get_data(as_text=True))
        sample_id = sample_res.get_json()["unique_id"]

        ds_res = self.client.post("/schema-forms/api/datasets", json={
            "schema_id": schema_id,
            "sample_id": sample_id,
            "dataset_name": "HALL-01 Run 1",
            "values": {"mobility_cm2_Vs": "42.5"},
        })
        self.assertEqual(ds_res.status_code, 201, ds_res.get_data(as_text=True))
        ds_body = ds_res.get_json()
        self.assertIn((sample_id, ds_body["dataset_id"]), self.store["sample_datasets"])
        self.assertEqual(ds_body["metadata"], {"mobility_cm2_Vs": 42.5})


if __name__ == "__main__":
    unittest.main()
