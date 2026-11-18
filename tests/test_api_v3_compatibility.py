import os
import unittest
from unittest.mock import patch

os.environ.setdefault("CRUCIBLE_API_KEY", "test-api-key")

from app import create_app
from config import B30_EBEAM_CONFIG, B30_SEM_CONFIG, SPUTTER_TOOLS
from routes.b30_sputter import _get_filtered_dataset_summaries

DATASET_MFID = "0tkn2knjast3h0008nyq9zps2c"


class ApiV3PayloadTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config.update(TESTING=True, SECRET_KEY="test")
        self.client = self.app.test_client()
        self.user = {
            "orcid": "0000-0001-2345-6789",
            "selected_project": "test-project",
        }

    def set_session(self, key, state):
        with self.client.session_transaction() as flask_session:
            flask_session["user"] = self.user
            flask_session[key] = state

    def set_user(self):
        with self.client.session_transaction() as flask_session:
            flask_session["user"] = self.user

    def dataset_post_payload(self, request):
        for call in request.call_args_list:
            if call.args[:2] == ("post", "/datasets"):
                return call.kwargs["json"]
        self.fail("POST /datasets was not requested")

    def assert_v3_dataset(self, payload, expected_data_type, expected_instrument):
        self.assertEqual(payload["data_type"], expected_data_type)
        self.assertEqual(payload["instrument_mfid"], expected_instrument)
        self.assertNotIn("instrument_name", payload)
        self.assertEqual(payload["owner_ref"], self.user["orcid"])
        self.assertNotIn("owner", payload)
        self.assertNotIn("dataset_type", payload)
        self.assertNotIn("owner_orcid", payload)

    def assert_v3_sample(self, sample, expected_name, expected_type):
        payload = sample.model_dump(exclude_none=True)
        self.assertEqual(payload["sample_name"], expected_name)
        self.assertEqual(payload["sample_type"], expected_type)
        self.assertEqual(payload["project_id"], self.user["selected_project"])
        self.assertEqual(payload["owner"], self.user["orcid"])
        self.assertNotIn("owner_orcid", payload)

    def test_sputter_dataset_uses_v3_fields(self):
        self.set_session("b30_sputter_aja", {
            "run_samples": [{"unique_id": "sample-1", "sample_name": "sample"}],
        })
        created = {"unique_id": DATASET_MFID}

        with patch("routes.b30_sputter.cruc_client.datasets._request", return_value=created) as request, \
             patch("routes.b30_sputter.link_samples_to_dataset", return_value=([], [])):
            response = self.client.post("/b30-aja-sputter/api/create-dataset", json={})

        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        tool = SPUTTER_TOOLS["aja"]
        self.assert_v3_dataset(
            self.dataset_post_payload(request),
            tool["dataset_type"],
            tool["instrument_mfid"],
        )

    def test_sputter_calibration_filter_uses_top_level_dataset_links(self):
        calibration_sample = "0tgfny1b35rwd000x35nr7a9d8"
        datasets = [
            {
                "unique_id": "calibration-dataset",
                "timestamp": "2026-09-01T10:00:00Z",
                "links": [{
                    "unique_id": calibration_sample,
                    "resource_type": "sample",
                    "relationship": "associated",
                }],
            },
            {
                "unique_id": "deposition-dataset",
                "timestamp": "2026-09-01T11:00:00Z",
                "links": [],
            },
        ]

        with patch("routes.b30_sputter.cruc_client.datasets.list", return_value=datasets) as list_datasets:
            result = _get_filtered_dataset_summaries(
                "test-project",
                "0tfn1vtxesrdn000waaft9ntrg",
                calibration_sample,
                "Calibration only",
            )

        self.assertEqual([dataset["unique_id"] for dataset in result], ["calibration-dataset"])
        list_datasets.assert_called_once_with(
            project_id="test-project",
            instrument_mfid="0tfn1vtxesrdn000waaft9ntrg",
            include_links=True,
            limit=2000,
        )

    def test_ebeam_dataset_uses_v3_fields(self):
        self.set_session("b30_ebeam", {
            "run_samples": [{"unique_id": "sample-1", "sample_name": "sample"}],
        })
        created = {"unique_id": DATASET_MFID}

        with patch("routes.b30_ebeam.cruc_client.datasets._request", return_value=created) as request, \
             patch("routes.b30_ebeam.link_samples_to_dataset", return_value=([], [])):
            response = self.client.post("/b30-ebeam/api/upload-dataset", json={})

        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        self.assert_v3_dataset(
            self.dataset_post_payload(request),
            B30_EBEAM_CONFIG["dataset_type"],
            B30_EBEAM_CONFIG["instrument_mfid"],
        )

    def test_sem_dataset_uses_v3_fields_and_canonical_link_arguments(self):
        self.set_session("b30_sem", {
            "sample_unique_id": "sample-1",
            "sample_name": "sample",
            "sample_type": "film",
            "sample_description": "",
        })
        created = {"unique_id": DATASET_MFID}

        with patch("routes.shared.cruc_client.datasets._request", return_value=created) as request, \
             patch("routes.shared.cruc_client.datasets.link_sample") as link_sample:
            response = self.client.post("/b30-sem/api/upload-dataset", json={})

        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        self.assert_v3_dataset(
            self.dataset_post_payload(request),
            B30_SEM_CONFIG["dataset_type"],
            B30_SEM_CONFIG["instrument_mfid"],
        )
        link_sample.assert_called_once_with(
            dataset_mfid=DATASET_MFID,
            sample_mfid="sample-1",
        )

    def test_deposition_sample_uses_sample_model_and_owner(self):
        self.set_user()
        created = {"unique_id": "sample-1", "sample_name": "film"}

        with patch("routes.deposition_common.cruc_client.samples.list", return_value=[]), \
             patch("routes.deposition_common.cruc_client.samples.create", return_value=created) as create:
            response = self.client.post("/b30-ebeam/api/create-sample", json={
                "sample_name": "film",
                "sample_type": "thin film",
                "description": "test",
            })

        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        self.assert_v3_sample(create.call_args.args[0], "film", "thin film")

    def test_sem_sample_uses_sample_model_and_owner(self):
        self.set_user()
        created = {"unique_id": "sample-1", "sample_name": "film"}

        with patch("routes.shared.cruc_client.samples.create", return_value=created) as create:
            response = self.client.post("/b30-sem/api/create-sample", json={
                "sample_name": "film",
                "sample_type": "thin film",
            })

        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        self.assert_v3_sample(create.call_args.args[0], "film", "thin film")

    def test_giwaxs_sample_uses_sample_model_and_owner(self):
        self.set_user()
        created = {"unique_id": "sample-1", "sample_name": "GWBAR000001"}

        with patch("routes.giwaxs.cruc_client.samples.list", return_value=[]), \
             patch("routes.giwaxs.cruc_client.samples.create", return_value=created) as create:
            response = self.client.post("/giwaxs/api/register-crucible", json={
                "bar_name": "GWBAR000001",
            })

        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        self.assert_v3_sample(create.call_args.args[0], "GWBAR000001", "giwaxs bar")

    def test_rga_sample_uses_sample_model_and_owner(self):
        self.set_user()
        created = {"unique_id": "sample-1", "sample_name": "RGA000001"}

        with patch("routes.rga.cruc_client.samples.list", return_value=[]), \
             patch("routes.rga.cruc_client.samples.create", return_value=created) as create:
            response = self.client.post("/rga/api/register-crucible", json={
                "rga_name": "RGA000001",
            })

        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        self.assert_v3_sample(create.call_args.args[0], "RGA000001", "rga carrier")

    def test_sample_create_posts_owner_ref_wire_payload(self):
        self.set_user()
        created = {"unique_id": "0tkn2knjast3h0008nyq9zps2s", "sample_name": "film"}

        with patch("routes.shared.cruc_client.samples._request", return_value=created) as request:
            response = self.client.post("/b30-sem/api/create-sample", json={
                "sample_name": "film",
                "sample_type": "thin film",
            })

        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        self.assertEqual(request.call_args.args[:2], ("post", "/samples"))
        payload = request.call_args.kwargs["json"]
        self.assertEqual(payload["owner_ref"], self.user["orcid"])
        self.assertNotIn("owner", payload)
        self.assertNotIn("owner_orcid", payload)

    def test_electrolyte_create_uses_link_sample_and_owner_ref(self):
        self.set_user()
        created_sample = {"unique_id": "0tkn2knjast3h0008nyq9zps2s", "sample_name": "EL-1"}
        created_ds = {"unique_id": DATASET_MFID, "dataset_name": "EL-1 electrolyte preparation 2026-10-15"}

        with patch("routes.electrolyte.cruc_client.samples.list", return_value=[]), \
             patch("routes.electrolyte.cruc_client.samples.create", return_value=created_sample), \
             patch("routes.electrolyte.cruc_client.datasets._request", return_value=created_ds) as ds_req, \
             patch("routes.electrolyte.cruc_client.datasets.link_sample") as link_sample:
            response = self.client.post("/electrolyte/api/create", json={
                "name": "EL-1",
                "preparation_date": "2026-10-15",
                "concentration": "1.0 M",
                "ph": 7.0,
                "ingredients": [{"type": "LiPF6", "amount": "1.0 M"}],
            })

        self.assertEqual(response.status_code, 201, response.get_data(as_text=True))
        payload = self.dataset_post_payload(ds_req)
        self.assertEqual(payload["owner_ref"], self.user["orcid"])
        self.assertNotIn("owner", payload)
        link_sample.assert_called_once_with(
            dataset_mfid=DATASET_MFID,
            sample_mfid="0tkn2knjast3h0008nyq9zps2s",
        )

    def test_schema_forms_create_dataset_uses_link_sample_and_owner_ref(self):
        self.set_user()
        schema_ds = {
            "unique_id": "schema-1",
            "dataset_name": "Custom XRD",
            "scientific_metadata": {"fields": [{"name": "angle", "type": "number", "required": True}]},
        }
        created_ds = {"unique_id": DATASET_MFID, "dataset_name": "Run 1"}

        with patch("routes.schema_forms.cruc_client.datasets.list", return_value=[schema_ds]), \
             patch("routes.schema_forms.cruc_client.datasets._request", return_value=created_ds) as ds_req, \
             patch("routes.schema_forms.cruc_client.datasets.link_sample") as link_sample:
            response = self.client.post("/schema-forms/api/datasets", json={
                "schema_id": "schema-1",
                "sample_id": "sample-1",
                "dataset_name": "Run 1",
                "values": {"angle": 32.5},
            })

        self.assertEqual(response.status_code, 201, response.get_data(as_text=True))
        payload = self.dataset_post_payload(ds_req)
        self.assertEqual(payload["owner_ref"], self.user["orcid"])
        self.assertNotIn("owner", payload)
        link_sample.assert_called_once_with(
            dataset_mfid=DATASET_MFID,
            sample_mfid="sample-1",
        )


if __name__ == "__main__":
    unittest.main()
