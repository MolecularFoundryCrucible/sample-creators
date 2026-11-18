import os
import tempfile
import unittest
import warnings

os.environ.setdefault("CRUCIBLE_API_KEY", "test-api-key")

try:
    from tests import fake_crucible  # noqa: E402
except ImportError:
    import fake_crucible  # noqa: E402
from crucible import Dataset, Sample  # noqa: E402
from crucible.errors import CrucibleAPIError, RemovedError  # noqa: E402
from crucible.utils.identifiers import IdentifierNotFoundError  # noqa: E402
from routes.shared import cruc_client, DEFAULT_CRUCIBLE_API_URL  # noqa: E402


class FakeCrucibleContractTests(unittest.TestCase):
    def setUp(self):
        self.store, restore = fake_crucible.install(cruc_client)
        self.addCleanup(restore)

    def test_enforces_removed_methods_parameters_and_model_fields(self):
        sid = cruc_client.samples.create(Sample(
            sample_name="S1", sample_type="wafer", project_id="p1", owner="0000-0001-2345-6789"
        ))["unique_id"]
        ds_res = cruc_client.datasets.create(
            Dataset(dataset_name="D1", project_id="p1", instrument_mfid="s0000000000000000000000001"),
            scientific_metadata={"k": "v"},
        )
        self.assertIn("dataset_mfid", ds_res)
        self.assertNotIn("dsid", ds_res)
        did = ds_res["dataset_mfid"]

        with tempfile.NamedTemporaryFile("wb", delete=False) as fh:
            fh.write(b"abc")
            tmp_path = fh.name
        self.addCleanup(lambda: os.path.exists(tmp_path) and os.unlink(tmp_path))

        removed_calls = [
            lambda: cruc_client.samples.create(sample_name="S2", project_id="p1"),
            lambda: cruc_client.samples.create(Sample(sample_name="S2", owner_orcid="0000-0001-2345-6789")),
            lambda: cruc_client.samples.get(sample_id=sid),
            lambda: cruc_client.samples.list(unique_id=sid),
            lambda: cruc_client.samples.list(offset=5),
            lambda: cruc_client.samples.list(owner_orcid="0000-0001-2345-6789"),
            lambda: cruc_client.samples.list(include_datasets=True),
            lambda: cruc_client.samples.link(parent_id=sid, child_id=sid),
            lambda: cruc_client.samples.update(sid, owner_orcid="0000-0001-2345-6789"),
            lambda: cruc_client.samples.update(sid, public=True),
            lambda: cruc_client.samples.add_dataset(sid, did),
            lambda: cruc_client.datasets.create(Dataset(dataset_name="D2", owner_orcid="0000-0001-2345-6789")),
            lambda: cruc_client.datasets.create(Dataset(dataset_name="D2", instrument_name="SEM")),
            lambda: cruc_client.datasets.create(Dataset(dataset_name="D2"), files_to_upload=[]),
            lambda: cruc_client.datasets.list(instrument_name="SEM"),
            lambda: cruc_client.datasets.list(unique_id=did),
            lambda: cruc_client.datasets.list(offset=10),
            lambda: cruc_client.datasets.list(sample_id=sid),
            lambda: cruc_client.datasets.update(did, public=True),
            lambda: cruc_client.datasets.update(did, instrument_name="SEM"),
            lambda: cruc_client.datasets.add_sample(did, sid),
            lambda: cruc_client.datasets.add_file_to_dataset(did, tmp_path),
            lambda: cruc_client.datasets.add_file(did, tmp_path, multipart=True),
            lambda: cruc_client.datasets.add_file(did, tmp_path, chunk_size_mb=8),
            lambda: cruc_client.datasets.add_file(did, tmp_path, upload_protocol="gcs"),
            lambda: cruc_client.projects.list(orcid="0000-0001-2345-6789"),
            lambda: cruc_client.users.get(orcid="0000-0001-2345-6789"),
            lambda: cruc_client.users.list_projects(orcid="0000-0001-2345-6789"),
        ]
        for idx, fn in enumerate(removed_calls):
            with self.subTest(call_index=idx):
                with self.assertRaises(RemovedError):
                    fn()

    def test_enforces_v4_envelopes_deprecations_and_search_minimum(self):
        sid = cruc_client.samples.create(
            Sample(sample_name="AlphaBeta", sample_type="wafer", project_id="p1"),
            scientific_metadata={"thickness_nm": 100},
        )["unique_id"]
        did = cruc_client.datasets.create(
            Dataset(dataset_name="D1", project_id="p1"),
            scientific_metadata={"temp_c": 25},
        )["dataset_mfid"]
        cruc_client.datasets.link_sample(did, sid)

        with warnings.catch_warnings(record=True) as w_clean:
            warnings.simplefilter("always", DeprecationWarning)
            sample_default = cruc_client.samples.get(sid)
        self.assertIsNone(sample_default["datasets"])
        self.assertNotIn("scientific_metadata", sample_default)
        self.assertEqual([w for w in w_clean if issubclass(w.category, DeprecationWarning)], [])

        with self.assertWarns(DeprecationWarning):
            sample_with_ds = cruc_client.samples.get(sid, include_datasets=True)
        self.assertEqual([d["unique_id"] for d in sample_with_ds["datasets"]], [did])

        self.assertEqual(
            cruc_client.datasets.get_scientific_metadata(did),
            {"unique_id": did, "scientific_metadata": {"temp_c": 25}},
        )

        with self.assertWarns(DeprecationWarning):
            cruc_client.users.list_projects(user_unique_id="0000-0001-2345-6789")

        with self.assertRaises(CrucibleAPIError) as ctx:
            cruc_client.samples.search("ab")
        self.assertEqual(ctx.exception.status, 422)

        with self.assertRaises(IdentifierNotFoundError):
            cruc_client.users.get("nobody@lbl.gov")
        with self.assertRaises(CrucibleAPIError) as u_ctx:
            cruc_client.users.get("0000-0001-2345-6789")
        self.assertEqual(u_ctx.exception.status, 404)

    def test_mfid_validation_and_project_offset_and_owner_fallbacks(self):
        with self.assertRaises(ValueError):
            cruc_client.samples.get("invalid-short-id")
        with self.assertRaises(ValueError):
            cruc_client.datasets.get("invalid-short-id")
        with self.assertRaises(ValueError):
            cruc_client.print.barcode("b30-113", "invalid-short-id", "name")

        self.store["projects"] = {
            f"p{i}": {"project_id": f"p{i}"} for i in range(5)
        }
        res = cruc_client.projects.list(offset=2, limit=2)
        self.assertEqual(len(res), 2)
        self.assertEqual([p["project_id"] for p in res], ["p2", "p3"])

        s = cruc_client.samples.create(Sample(
            sample_name="FallbackOwnerSample", project_id="p1", owner="unknown-user-id"
        ))
        self.assertEqual(s["owner"], {"unique_id": "unknown-user-id", "first_name": "", "last_name": ""})
        d = cruc_client.datasets.create(Dataset(
            dataset_name="FallbackOwnerDataset", project_id="p1", owner="unknown-user-id"
        ))
        d_record = self.store["datasets"][d["dataset_mfid"]]
        self.assertEqual(d_record["owner"], {"unique_id": "unknown-user-id", "first_name": "", "last_name": ""})

    def test_v4_0_1_dict_create_and_default_v4_url(self):
        s = cruc_client.samples.create({"sample_name": "DictSample", "sample_type": "wafer", "project_id": "p1"})
        self.assertIn("unique_id", s)
        self.assertEqual(s["sample_name"], "DictSample")

        d = cruc_client.datasets.create({"dataset_name": "DictDataset", "project_id": "p1", "instrument_mfid": "s0000000000000000000000001"})
        self.assertIn("dataset_mfid", d)
        self.assertEqual(d["created_record"]["dataset_name"], "DictDataset")

        self.assertEqual(DEFAULT_CRUCIBLE_API_URL, "https://crucible.lbl.gov/api/v4")


if __name__ == "__main__":
    unittest.main()
