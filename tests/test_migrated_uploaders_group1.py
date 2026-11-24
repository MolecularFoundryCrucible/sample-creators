"""Unit tests for Group 1 Migrated Uploaders:
- b30_gc_ec (/b30-gc-ec)
- insitu_pl (/insitu-pl)
- dfs_microscope (/dfs-microscope)
- hip_microscope (/hip-microscope)
"""
import os
import unittest
from unittest.mock import patch

os.environ.setdefault("CRUCIBLE_API_KEY", "test-api-key")

from app import create_app
from crucible import Dataset, Sample
from routes.shared import cruc_client
from routes.uploader_common import list_existing_dataset_filenames, resolve_dsid_for_sha256
from tests import fake_crucible


class MigratedUploadersGroup1Tests(unittest.TestCase):
    def setUp(self):
        self.store, restore = fake_crucible.install(cruc_client)
        self.addCleanup(restore)

        app = create_app()
        app.config.update(TESTING=True, SECRET_KEY="test-secret")
        self.client = app.test_client()

        self.user = {
            "unique_id": "0000-0001-2345-6789",
            "orcid": "0000-0001-2345-6789",
            "username": "tester",
            "first_name": "Test",
            "last_name": "User",
            "email": "test@lbl.gov",
        }
        self.store["users"][self.user["unique_id"]] = dict(self.user)
        self.store["user_projects"][self.user["unique_id"]] = [
            {"project_id": "proj-1"},
            {"project_id": "proj-2"},
        ]

        with self.client.session_transaction() as sess:
            sess["user"] = {
                "orcid": self.user["orcid"],
                "user_name": "Test User (@tester)",
                "projects": ["proj-1", "proj-2"],
                "selected_project": "proj-1",
            }

    # 1. Page GET checks for all 4 uploaders
    def test_pages_render_successfully(self):
        endpoints = [
            ("/b30-gc-ec/", "B30 GC-EC", "gc-files", "gc-anode-mfid"),
            ("/insitu-pl/", "Inorganic - In-Situ PL", "std-files", "std-group-as-one"),
            ("/dfs-microscope/", "Nanofab - DFS-Microscope", "std-files", "std-group-as-one"),
            ("/hip-microscope/", "Imaging - HiP-Microscope", "std-files", "std-group-as-one"),
        ]
        for url, title_snip, file_id, extra_id in endpoints:
            with self.subTest(url=url):
                res = self.client.get(url)
                self.assertEqual(res.status_code, 200)
                html = res.get_data(as_text=True)
                self.assertIn(title_snip, html)
                self.assertIn(file_id, html)
                self.assertIn(extra_id, html)

    # 2. b30_gc_ec tests
    def test_b30_gc_ec_prepare_preview_strictly_read_only(self):
        anode = cruc_client.samples.create(Sample(
            sample_name="Anode-1", sample_type="electrode", project_id="proj-1", owner=self.user["orcid"]
        ))
        cathode = cruc_client.samples.create(Sample(
            sample_name="Cathode-1", sample_type="electrode", project_id="proj-1", owner=self.user["orcid"]
        ))
        electrolyte = cruc_client.samples.create(Sample(
            sample_name="Electrolyte-1", sample_type="electrolyte", project_id="proj-1", owner=self.user["orcid"]
        ))

        initial_dataset_count = len(self.store["datasets"])

        # Call prepare-preview
        res = self.client.post("/b30-gc-ec/api/prepare-preview", json={
            "first_file_sha256": "1" * 64,
            "anode_sample_mfid": anode["unique_id"],
            "cathode_sample_mfid": cathode["unique_id"],
            "electrolyte_sample_mfid": electrolyte["unique_id"],
        })
        self.assertEqual(res.status_code, 200, res.get_data(as_text=True))
        data = res.get_json()
        self.assertFalse(data["reused_dataset"])
        self.assertIsNone(data["dsid"])
        self.assertEqual(data["resolved_materials"]["anode_material"]["sample_name"], "Anode-1")
        self.assertEqual(data["resolved_materials"]["cathode_material"]["sample_name"], "Cathode-1")
        self.assertEqual(data["resolved_materials"]["electrolyte"]["sample_name"], "Electrolyte-1")

        # Verify STRICTLY READ-ONLY in Crucible: zero new datasets
        self.assertEqual(len(self.store["datasets"]), initial_dataset_count)

    def test_b30_gc_ec_prepare_preview_validates_materials_in_project(self):
        # Missing material field
        res = self.client.post("/b30-gc-ec/api/prepare-preview", json={
            "anode_sample_mfid": "something",
            "cathode_sample_mfid": "",
            "electrolyte_sample_mfid": "something",
        })
        self.assertEqual(res.status_code, 400)
        self.assertIn("required", res.get_json()["error"])

        # Sample belonging to another project
        other_sample = cruc_client.samples.create(Sample(
            sample_name="Other-Proj-Sample", sample_type="electrode", project_id="proj-2", owner=self.user["orcid"]
        ))
        res = self.client.post("/b30-gc-ec/api/prepare-preview", json={
            "anode_sample_mfid": other_sample["unique_id"],
            "cathode_sample_mfid": other_sample["unique_id"],
            "electrolyte_sample_mfid": other_sample["unique_id"],
        })
        self.assertEqual(res.status_code, 400)
        self.assertIn("No Anode Material sample found", res.get_json()["error"])

    def test_b30_gc_ec_sha256_dataset_reuse_scoped_to_user_and_project(self):
        sha = "f" * 64
        # Dataset 1: in proj-1, owned by user
        ds1 = cruc_client.datasets.create(Dataset(
            dataset_name="Proj1 Dataset", project_id="proj-1", owner=self.user["orcid"],
            instrument_mfid="0tmfg17radzgf000w544pxmwer",
        ))
        ds1_mfid = ds1["dataset_mfid"]
        self.store["files"][ds1_mfid] = [{
            "mfid": "f" + "1" * 25, "filename": "run.mpt", "sha256_hash": sha
        }]

        # Create valid material samples
        anode = cruc_client.samples.create(Sample(sample_name="A", sample_type="e", project_id="proj-1", owner=self.user["orcid"]))
        cathode = cruc_client.samples.create(Sample(sample_name="C", sample_type="e", project_id="proj-1", owner=self.user["orcid"]))
        electrolyte = cruc_client.samples.create(Sample(sample_name="E", sample_type="el", project_id="proj-1", owner=self.user["orcid"]))

        # prepare-preview in proj-1 detects reuse
        res = self.client.post("/b30-gc-ec/api/prepare-preview", json={
            "first_file_sha256": sha,
            "anode_sample_mfid": anode["unique_id"],
            "cathode_sample_mfid": cathode["unique_id"],
            "electrolyte_sample_mfid": electrolyte["unique_id"],
        })
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["reused_dataset"])
        self.assertEqual(data["dsid"], ds1_mfid)

        # Now test with selected_project = proj-2: should NOT reuse ds1 from proj-1!
        with self.client.session_transaction() as sess:
            sess["user"] = dict(sess["user"], selected_project="proj-2")
            sess.modified = True

        # Create materials in proj-2
        a2 = cruc_client.samples.create(Sample(sample_name="A2", sample_type="e", project_id="proj-2", owner=self.user["orcid"]))
        c2 = cruc_client.samples.create(Sample(sample_name="C2", sample_type="e", project_id="proj-2", owner=self.user["orcid"]))
        e2 = cruc_client.samples.create(Sample(sample_name="E2", sample_type="el", project_id="proj-2", owner=self.user["orcid"]))

        res2 = self.client.post("/b30-gc-ec/api/prepare-preview", json={
            "first_file_sha256": sha,
            "anode_sample_mfid": a2["unique_id"],
            "cathode_sample_mfid": c2["unique_id"],
            "electrolyte_sample_mfid": e2["unique_id"],
        })
        self.assertEqual(res2.status_code, 200)
        data2 = res2.get_json()
        self.assertFalse(data2["reused_dataset"])
        self.assertIsNone(data2["dsid"])

    def test_b30_gc_ec_confirm_upload_creates_and_links(self):
        anode = cruc_client.samples.create(Sample(sample_name="Anode", sample_type="e", project_id="proj-1", owner=self.user["orcid"]))
        cathode = cruc_client.samples.create(Sample(sample_name="Cathode", sample_type="e", project_id="proj-1", owner=self.user["orcid"]))
        electrolyte = cruc_client.samples.create(Sample(sample_name="Electrolyte", sample_type="el", project_id="proj-1", owner=self.user["orcid"]))
        primary = cruc_client.samples.create(Sample(sample_name="Primary", sample_type="device", project_id="proj-1", owner=self.user["orcid"]))

        res = self.client.post("/b30-gc-ec/api/confirm-upload", json={
            "dataset_fields": {
                "dataset_name": "Custom_GC_EC_Run",
                "measurement": "cyclic voltammetry",
                "data_type": "voltammogram",
                "session_name": "Test Session",
            },
            "scientific_metadata": {
                "cell_temperature_C": 25.0,
                "anode_material": {"sample_name": "Anode", "sample_mfid": anode["unique_id"]},
                "cathode_material": {"sample_name": "Cathode", "sample_mfid": cathode["unique_id"]},
                "electrolyte": {"sample_name": "Electrolyte", "sample_mfid": electrolyte["unique_id"]},
                "parse_provenance": {"parsed_locally": True},
            },
            "keywords": ["CO2RR", "test"],
            "sample_unique_id": primary["unique_id"],
            "anode_sample_mfid": anode["unique_id"],
            "cathode_sample_mfid": cathode["unique_id"],
            "electrolyte_sample_mfid": electrolyte["unique_id"],
        })
        self.assertEqual(res.status_code, 200, res.get_data(as_text=True))
        data = res.get_json()
        self.assertTrue(data["ok"])
        dsid = data["dataset_mfid"]
        self.assertFalse(data["reused"])
        self.assertIn(dsid, data["hub_url"])

        # Verify dataset record created in store
        rec = self.store["datasets"][dsid]
        self.assertEqual(rec["dataset_name"], "Custom_GC_EC_Run")
        self.assertEqual(rec["measurement"], "cyclic voltammetry")
        self.assertEqual(rec["instrument_mfid"], "0tmfg17radzgf000w544pxmwer")
        self.assertIn("CO2RR", rec["keywords"])
        self.assertEqual(rec["scientific_metadata"]["cell_temperature_C"], 25.0)
        self.assertTrue(rec["scientific_metadata"]["parse_provenance"]["parsed_locally"])

        # Verify links created for all 4 samples
        linked_samples = {s for s, d in self.store["sample_datasets"] if d == dsid}
        self.assertIn(anode["unique_id"], linked_samples)
        self.assertIn(cathode["unique_id"], linked_samples)
        self.assertIn(electrolyte["unique_id"], linked_samples)
        self.assertIn(primary["unique_id"], linked_samples)

    # 3. Standard uploaders: sample lookup, disambiguation, creation, printing, dataset creation, postprocess
    def test_sample_lookup_by_mfid_and_name_with_disambiguation(self):
        s1 = cruc_client.samples.create(Sample(sample_name="DuplicateName", sample_type="film", project_id="proj-1", owner=self.user["orcid"]))
        s2 = cruc_client.samples.create(Sample(sample_name="DuplicateName", sample_type="substrate", project_id="proj-1", owner=self.user["orcid"]))
        unique_sample = cruc_client.samples.create(Sample(sample_name="SingleSample", sample_type="film", project_id="proj-1", owner=self.user["orcid"]))

        # Lookup by MFID
        res = self.client.post("/insitu-pl/api/lookup-sample", json={"sample_unique_id": unique_sample["unique_id"]})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["sample_name"], "SingleSample")

        # Lookup by unique name
        res = self.client.post("/insitu-pl/api/lookup-sample", json={"sample_name": "SingleSample"})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["unique_id"], unique_sample["unique_id"])

        # Lookup by ambiguous name -> HTTP 409 with candidates
        res = self.client.post("/insitu-pl/api/lookup-sample", json={"sample_name": "DuplicateName"})
        self.assertEqual(res.status_code, 409)
        candidates = res.get_json()["candidates"]
        self.assertEqual(len(candidates), 2)
        candidate_ids = {c["unique_id"] for c in candidates}
        self.assertEqual(candidate_ids, {s1["unique_id"], s2["unique_id"]})

    def test_sample_creation_and_barcode_print(self):
        # Create sample
        res = self.client.post("/dfs-microscope/api/create-sample", json={
            "sample_name": "NewDFS_Sample",
            "sample_type": "nanoparticle",
            "description": "Gold NP on glass",
        })
        self.assertEqual(res.status_code, 200)
        created = res.get_json()
        sample_mfid = created["unique_id"]
        self.assertEqual(created["sample_name"], "NewDFS_Sample")

        # Print barcode
        res = self.client.post("/dfs-microscope/api/print-barcode", json={
            "printer_id": "b67-123",
            "sample_id": sample_mfid,
            "sample_name": "NewDFS_Sample",
        })
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json()["ok"])
        self.assertEqual(self.store["prints"][-1], ("b67-123", sample_mfid, "NewDFS_Sample"))

    def test_standard_dataset_creation_and_instrument_mfids(self):
        configs = [
            ("/insitu-pl/api/create-dataset", "0t0nah22xxxjd000gy940mm9d8"),
            ("/dfs-microscope/api/create-dataset", "0tmz428dmnrf3000128mhfcmdg"),
            ("/hip-microscope/api/create-dataset", "0sh6zrzxhxybd000wwyrkcn2cw"),
        ]
        sample = cruc_client.samples.create(Sample(sample_name="OpticSample", sample_type="film", project_id="proj-1", owner=self.user["orcid"]))

        for url, expected_inst_mfid in configs:
            with self.subTest(url=url):
                res = self.client.post(url, json={
                    "dataset_name": f"Run_{expected_inst_mfid[:6]}",
                    "comments": "Test optics upload",
                    "keywords": ["optics"],
                    "sample_unique_id": sample["unique_id"],
                })
                self.assertEqual(res.status_code, 200, res.get_data(as_text=True))
                data = res.get_json()
                self.assertTrue(data["ok"])
                dsid = data["dataset_mfid"]
                ds_rec = self.store["datasets"][dsid]
                self.assertEqual(ds_rec["instrument_mfid"], expected_inst_mfid)
                self.assertEqual(ds_rec["project_id"], "proj-1")
                # Sample link
                self.assertIn((sample["unique_id"], dsid), self.store["sample_datasets"])

    def test_insitu_pl_postprocess_success_and_cross_project_guard(self):
        # Create dataset in proj-1
        ds = cruc_client.datasets.create(Dataset(
            dataset_name="PL Run", project_id="proj-1", owner=self.user["orcid"],
            instrument_mfid="0t0nah22xxxjd000gy940mm9d8"
        ))
        dsid = ds["dataset_mfid"]

        # POST /insitu-pl/api/postprocess triggers "insitu_aggregation"
        res = self.client.post("/insitu-pl/api/postprocess", json={"dataset_id": dsid})
        self.assertEqual(res.status_code, 200, res.get_data(as_text=True))
        data = res.get_json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["steps"], ["insitu_aggregation"])
        self.assertEqual(len(self.store["postprocessing"]), 1)
        self.assertEqual(self.store["postprocessing"][0]["dataset_mfid"], dsid)
        self.assertEqual(self.store["postprocessing"][0]["pipeline"], "insitu_aggregation")

        # Create dataset in proj-other (not in user's projects)
        other_ds = cruc_client.datasets.create(Dataset(
            dataset_name="Forbidden Run", project_id="proj-other", owner="someone-else",
            instrument_mfid="0t0nah22xxxjd000gy940mm9d8"
        ))
        other_dsid = other_ds["dataset_mfid"]

        # Cross-project guard must return 403 Forbidden
        res_forbidden = self.client.post("/insitu-pl/api/postprocess", json={"dataset_id": other_dsid})
        self.assertEqual(res_forbidden.status_code, 403)
        self.assertIn("does not belong", res_forbidden.get_json()["error"])

    def test_recent_datasets_and_csv_export(self):
        # Create dataset
        ds = cruc_client.datasets.create(Dataset(
            dataset_name="Logbook Dataset", project_id="proj-1", owner=self.user["orcid"],
            instrument_mfid="0t0nah22xxxjd000gy940mm9d8", measurement="in-situ photoluminescence"
        ), scientific_metadata={"comment": "Sample comment"})
        dsid = ds["dataset_mfid"]

        res = self.client.get("/insitu-pl/api/recent-datasets")
        self.assertEqual(res.status_code, 200)
        rows = res.get_json()["rows"]
        self.assertTrue(any(r.get("Dataset ID") == dsid for r in rows))

        # CSV export
        res_csv = self.client.get("/insitu-pl/api/recent-datasets/insitu_pl_recent_datasets.csv")
        self.assertEqual(res_csv.status_code, 200)
        self.assertIn("text/csv", res_csv.headers["Content-Type"])
        csv_text = res_csv.get_data(as_text=True)
        self.assertIn("Dataset Name", csv_text)
        self.assertIn("Logbook Dataset", csv_text)

    def test_print_barcode_requires_authentication(self):
        with self.client.session_transaction() as sess:
            sess.clear()

        res = self.client.post("/insitu-pl/api/print-barcode", json={
            "printer_id": "b30-113",
            "sample_id": "s001",
            "sample_name": "Test",
        })
        self.assertEqual(res.status_code, 401)
        self.assertIn("Not authenticated", res.get_json()["error"])

    def test_group1_cross_project_guards(self):
        other_sample = cruc_client.samples.create(Sample(
            sample_name="ForeignSample", sample_type="film", project_id="proj-2", owner=self.user["orcid"]
        ))["unique_id"]
        other_ds = cruc_client.datasets.create(Dataset(
            dataset_name="ForeignDataset", project_id="proj-2", owner=self.user["orcid"],
            instrument_mfid="0t0nah22xxxjd000gy940mm9d8"
        ))["dataset_mfid"]

        # 1. Standard uploader create-dataset with sample in other project -> 403
        res1 = self.client.post("/insitu-pl/api/create-dataset", json={
            "dataset_name": "Test Run",
            "sample_unique_id": other_sample,
        })
        self.assertEqual(res1.status_code, 403)
        self.assertIn("belongs to project", res1.get_json()["error"])

        # 2. Standard uploader create-dataset with embedded_dsid in other project -> 403
        res2 = self.client.post("/insitu-pl/api/create-dataset", json={
            "dataset_name": "Test Run",
            "embedded_dsid": other_ds,
        })
        self.assertEqual(res2.status_code, 403)
        self.assertIn("belongs to project", res2.get_json()["error"])

        # 3. B30 GC-EC confirm-upload with sample in other project -> 403
        valid_sample = cruc_client.samples.create(Sample(
            sample_name="ValidSample", sample_type="e", project_id="proj-1", owner=self.user["orcid"]
        ))["unique_id"]
        res3 = self.client.post("/b30-gc-ec/api/confirm-upload", json={
            "anode_sample_mfid": other_sample,
            "cathode_sample_mfid": valid_sample,
            "electrolyte_sample_mfid": valid_sample,
        })
        self.assertEqual(res3.status_code, 403)
        self.assertIn("belongs to project", res3.get_json()["error"])

    def test_resolve_dsid_for_sha256_empty_valid_dsids_avoids_files_list(self):
        with patch.object(cruc_client.files, "list", side_effect=AssertionError("files.list should not be called")):
            dsid, reused = resolve_dsid_for_sha256("a" * 64, set())
            self.assertIsNone(dsid)
            self.assertFalse(reused)

    def test_dfs_microscope_create_dataset_existing_filenames_and_sha256_dedup(self):
        # 1. New dataset: not reused, empty existing_filenames
        res1 = self.client.post("/dfs-microscope/api/create-dataset", json={
            "dataset_name": "DFS_Initial_Run",
            "comments": "Initial upload",
        })
        self.assertEqual(res1.status_code, 200, res1.get_data(as_text=True))
        data1 = res1.get_json()
        self.assertTrue(data1["ok"])
        self.assertFalse(data1["reused"])
        self.assertEqual(data1["existing_filenames"], [])
        dsid = data1["dataset_mfid"]

        # 2. Add existing file with sha256 to this dataset
        test_sha = "b" * 64
        self.store["files"][dsid] = [
            {"filename": "scan1.tif", "sha256_hash": test_sha, "size": 2048}
        ]

        # 3. Create dataset with matching sha256: reused = True, returns existing_filenames
        res2 = self.client.post("/dfs-microscope/api/create-dataset", json={
            "dataset_name": "DFS_Resumed_Run",
            "sha256_hash": test_sha,
        })
        self.assertEqual(res2.status_code, 200, res2.get_data(as_text=True))
        data2 = res2.get_json()
        self.assertTrue(data2["ok"])
        self.assertTrue(data2["reused"])
        self.assertEqual(data2["dataset_mfid"], dsid)
        self.assertEqual(data2["existing_filenames"], ["scan1.tif"])

        # 4. Graceful fallback to [] when list_files raises
        with patch.object(cruc_client.datasets, "list_files", side_effect=Exception("list_files error")):
            res3 = self.client.post("/dfs-microscope/api/create-dataset", json={
                "dataset_name": "DFS_Resumed_Error_Run",
                "sha256_hash": test_sha,
            })
            self.assertEqual(res3.status_code, 200)
            data3 = res3.get_json()
            self.assertTrue(data3["reused"])
            self.assertEqual(data3["dataset_mfid"], dsid)
            self.assertEqual(data3["existing_filenames"], [])


if __name__ == "__main__":
    unittest.main()
