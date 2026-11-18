"""Unit tests for Group 2 migrated uploaders:
- inorganic_xrd
- spinbot_spinrun
- spinbot_photobox
- nirvana
"""
from __future__ import annotations

import os
import unittest

os.environ.setdefault("CRUCIBLE_API_KEY", "test-api-key")

from app import create_app
from crucible import Dataset, Sample
from routes.shared import cruc_client
from tests import fake_crucible


class MigratedUploadersGroup2Tests(unittest.TestCase):
    def setUp(self):
        self.store, restore = fake_crucible.install(cruc_client)
        self.addCleanup(restore)

        app = create_app()
        app.config.update(TESTING=True, SECRET_KEY="test-secret")
        self.client = app.test_client()

        self.orcid = "0000-0001-2345-6789"
        self.project_id = "test-project"

        # Pre-seed user in session
        with self.client.session_transaction() as sess:
            sess["user"] = {
                "orcid": self.orcid,
                "selected_project": self.project_id,
                "projects": [self.project_id],
                "user_name": "Test User",
            }

    # 1. Page GET returns 200 for all 4 tools
    def test_pages_render_successfully(self):
        for route in ("/inorganic-xrd/", "/spinbot-spinrun/", "/spinbot-photobox/", "/nirvana/"):
            res = self.client.get(route)
            self.assertEqual(res.status_code, 200, f"Failed GET {route}: {res.get_data(as_text=True)}")

    # 2. inorganic_xrd tests
    def test_inorganic_xrd_single_mode(self):
        # Create a sample to link
        sample_res = cruc_client.samples.create(
            Sample(sample_name="TF_001", project_id=self.project_id, owner=self.orcid)
        )
        sample_uuid = sample_res["unique_id"]

        res = self.client.post(
            "/inorganic-xrd/api/create-uploads",
            json={
                "mode": "single",
                "files": [
                    {
                        "filename": "sample_scan.txt",
                        "sha256": "hash123",
                        "sample_uuid": sample_uuid,
                    }
                ],
                "comments": "Single mode test",
            },
        )
        self.assertEqual(res.status_code, 200, res.get_data(as_text=True))
        data = res.get_json()
        self.assertEqual(len(data["uploads"]), 1)
        dsid = data["uploads"][0]["dataset_mfid"]

        # Verify dataset created and linked
        self.assertIn(dsid, self.store["datasets"])
        ds = self.store["datasets"][dsid]
        self.assertEqual(ds["instrument_mfid"], "0tmz7j9xmsrvn000tbs1zjwgpr")
        self.assertIsNone(ds["measurement"])
        self.assertNotIn("upload_mode", ds["scientific_metadata"])
        self.assertIn((sample_uuid, dsid), self.store["sample_datasets"])

    def test_inorganic_xrd_flat_multi_mode(self):
        # Create 2 samples
        s1 = cruc_client.samples.create(Sample(sample_name="TF_A", project_id=self.project_id, owner=self.orcid))["unique_id"]
        s2 = cruc_client.samples.create(Sample(sample_name="TF_B", project_id=self.project_id, owner=self.orcid))["unique_id"]

        res = self.client.post(
            "/inorganic-xrd/api/create-uploads",
            json={
                "mode": "flat_multi",
                "filename": "combined_run.txt",
                "samples": [
                    {"position": "S01", "sample_name": "TF_A", "sample_uuid": s1},
                    {"position": "S02", "sample_name": "TF_B", "sample_uuid": s2},
                ],
                "comments": "Flat multi test",
            },
        )
        self.assertEqual(res.status_code, 200, res.get_data(as_text=True))
        data = res.get_json()
        uploads = data["uploads"]
        self.assertEqual(len(uploads), 2)

        for u, expected_s, expected_pos in zip(uploads, [s1, s2], ["S01", "S02"]):
            dsid = u["dataset_mfid"]
            self.assertIn(dsid, self.store["datasets"])
            self.assertIn((expected_s, dsid), self.store["sample_datasets"])
            ds = self.store["datasets"][dsid]
            self.assertIsNone(ds["measurement"])
            self.assertEqual(ds["scientific_metadata"]["position"], expected_pos)
            self.assertNotIn("upload_mode", ds["scientific_metadata"])

    def test_inorganic_xrd_parent_child_mode(self):
        # Create parent and child samples
        parent = cruc_client.samples.create(Sample(sample_name="Parent_Tray", project_id=self.project_id, owner=self.orcid))["unique_id"]
        c1 = cruc_client.samples.create(Sample(sample_name="Child_01", project_id=self.project_id, owner=self.orcid))["unique_id"]
        c2 = cruc_client.samples.create(Sample(sample_name="Child_02", project_id=self.project_id, owner=self.orcid))["unique_id"]
        cruc_client.samples.link(parent, c1)
        cruc_client.samples.link(parent, c2)

        # 1. resolve-children endpoint
        res_resolve = self.client.post(
            "/inorganic-xrd/api/resolve-children",
            json={"sample_uuid": parent},
        )
        self.assertEqual(res_resolve.status_code, 200)
        children = res_resolve.get_json()["children"]
        self.assertEqual(len(children), 2)
        self.assertEqual([c["unique_id"] for c in children], [c1, c2])

        # 2. create-uploads in parent_child mode
        res_upload = self.client.post(
            "/inorganic-xrd/api/create-uploads",
            json={
                "mode": "parent_child",
                "filename": "multi_xrd.txt",
                "parent_uuid": parent,
                "child_uuids": [c1, c2],
                "comments": "Parent child XRD test",
            },
        )
        self.assertEqual(res_upload.status_code, 200, res_upload.get_data(as_text=True))
        data = res_upload.get_json()
        parent_dsid = data["parent_dataset_mfid"]
        child_entries = data["children"]
        self.assertEqual(len(child_entries), 2)

        # Parent dataset assertions
        self.assertIn((parent, parent_dsid), self.store["sample_datasets"])
        p_ds = self.store["datasets"][parent_dsid]
        self.assertEqual(p_ds["scientific_metadata"]["upload_mode"], "parent")
        self.assertIsNone(p_ds["measurement"])

        # Child dataset assertions
        for idx, ch_entry in enumerate(child_entries):
            ch_dsid = ch_entry["child_dataset_mfid"]
            ch_sample_uuid = ch_entry["sample_uuid"]
            # Linked to parent dataset in store["dataset_links"]
            self.assertIn((parent_dsid, ch_dsid), self.store["dataset_links"])
            # Linked to respective child sample in store["sample_datasets"]
            self.assertIn((ch_sample_uuid, ch_dsid), self.store["sample_datasets"])
            ch_ds = self.store["datasets"][ch_dsid]
            self.assertIsNone(ch_ds["measurement"])
            self.assertEqual(ch_ds["scientific_metadata"]["position"], f"S{idx + 1:02d}")
            self.assertNotIn("upload_mode", ch_ds["scientific_metadata"])

        # Verify parent_child preserves position (e.g. S02) when an earlier child is omitted
        res_upload_s02 = self.client.post(
            "/inorganic-xrd/api/create-uploads",
            json={
                "mode": "parent_child",
                "filename": "multi_xrd_sparse.txt",
                "parent_uuid": parent,
                "children": [{"uuid": c2, "position": "S02", "name": "Child_02"}],
                "comments": "Sparse children",
            },
        )
        self.assertEqual(res_upload_s02.status_code, 200)
        sparse_ch_dsid = res_upload_s02.get_json()["children"][0]["child_dataset_mfid"]
        sparse_ch_ds = self.store["datasets"][sparse_ch_dsid]
        self.assertEqual(sparse_ch_ds["scientific_metadata"]["position"], "S02")

    # 3. spinbot_spinrun tests
    def test_spinbot_spinrun_create_upload_and_print_trays(self):
        embedded_dsid = "0sh6rwn0000000000000000001"

        # 1. First upload creates dataset with embedded run_id
        res1 = self.client.post(
            "/spinbot-spinrun/api/create-upload",
            json={
                "filename": "run_test.h5",
                "yaml_filename": "run_test.yaml",
                "embedded_dsid": embedded_dsid,
                "comments": "First run upload",
            },
        )
        self.assertEqual(res1.status_code, 200, res1.get_data(as_text=True))
        data1 = res1.get_json()
        self.assertEqual(data1["dataset_mfid"], embedded_dsid)
        self.assertFalse(data1["is_existing"])

        # 2. Re-uploading existing run_id updates rather than 409-conflicting
        res2 = self.client.post(
            "/spinbot-spinrun/api/create-upload",
            json={
                "filename": "run_test.h5",
                "yaml_filename": "run_test.yaml",
                "embedded_dsid": embedded_dsid,
                "comments": "Updated run comments",
            },
        )
        self.assertEqual(res2.status_code, 200, res2.get_data(as_text=True))
        data2 = res2.get_json()
        self.assertEqual(data2["dataset_mfid"], embedded_dsid)
        self.assertTrue(data2["is_existing"])

        # Check updated comments
        ds = self.store["datasets"][embedded_dsid]
        self.assertEqual(ds["scientific_metadata"]["comments"], "Updated run comments")
        self.assertEqual(ds["scientific_metadata"]["yaml_companion"], "run_test.yaml")
        self.assertEqual(ds["instrument_mfid"], "0sh6zrzxhxsa100089bznryq88")

        # 3. Print tray barcodes
        tray_mfid_1 = "0sh6tray000000000000000001"
        tray_mfid_2 = "0sh6tray000000000000000002"
        res_print = self.client.post(
            "/spinbot-spinrun/api/print-trays",
            json={
                "printer_id": "b30-113",
                "trays": [
                    {"mfid": tray_mfid_1, "name": "Tray_Alpha"},
                    {"mfid": tray_mfid_2, "name": "Tray_Beta"},
                ],
            },
        )
        self.assertEqual(res_print.status_code, 200)
        self.assertEqual(res_print.get_json()["count"], 2)
        self.assertIn(("b30-113", tray_mfid_1, "Tray_Alpha"), self.store["prints"])
        self.assertIn(("b30-113", tray_mfid_2, "Tray_Beta"), self.store["prints"])

    # 4. spinbot_photobox tests
    def test_spinbot_photobox_workflow(self):
        # 1. next-carrier-name generation
        # With no existing carriers, returns CAR000001
        res_name1 = self.client.get(f"/spinbot-photobox/api/next-carrier-name?project_id={self.project_id}")
        self.assertEqual(res_name1.status_code, 200)
        self.assertEqual(res_name1.get_json()["sample_name"], "CAR000001")

        # Create CAR000001 and a non-CAR sample
        cruc_client.samples.create(Sample(sample_name="CAR000001", sample_type="thin film carrier", project_id=self.project_id, owner=self.orcid))
        cruc_client.samples.create(Sample(sample_name="OTHER_SAMPLE", sample_type="thin film carrier", project_id=self.project_id, owner=self.orcid))

        # Next carrier should safely ignore OTHER_SAMPLE and return CAR000002
        res_name2 = self.client.get(f"/spinbot-photobox/api/next-carrier-name?project_id={self.project_id}")
        self.assertEqual(res_name2.status_code, 200)
        self.assertEqual(res_name2.get_json()["sample_name"], "CAR000002")

        # Create two trays to link
        tray1 = cruc_client.samples.create(Sample(sample_name="Tray_1", project_id=self.project_id, owner=self.orcid))["unique_id"]
        tray2 = cruc_client.samples.create(Sample(sample_name="Tray_2", project_id=self.project_id, owner=self.orcid))["unique_id"]

        # 2. prepare-upload with pending_new_carrier=True
        positions = {"A1": "tf_01", "A2": "tf_02", "C1": "tf_03"}
        res_prep = self.client.post(
            "/spinbot-photobox/api/prepare-upload",
            json={
                "pending_new_carrier": True,
                "carrier_name": "CAR000002",
                "tray1_uuid": tray1,
                "tray2_uuid": tray2,
                "sample_positions": positions,
                "filename": "carrier_run_42.png",
                "comments": "Photobox test",
            },
        )
        self.assertEqual(res_prep.status_code, 200, res_prep.get_data(as_text=True))
        prep_data = res_prep.get_json()
        carrier_uuid = prep_data["carrier_uuid"]
        dsid = prep_data["dataset_mfid"]

        # Verify carrier created and linked to Tray 1 & Tray 2
        self.assertIn(carrier_uuid, self.store["samples"])
        self.assertIn((carrier_uuid, tray1), self.store["links"])
        self.assertIn((carrier_uuid, tray2), self.store["links"])

        # Verify dataset created and linked to carrier, tray1, tray2
        ds = self.store["datasets"][dsid]
        self.assertEqual(ds["measurement"], "thin film carrier image")
        self.assertIsNone(ds["data_type"])
        self.assertEqual(ds["dataset_name"], "carrier_run_42 Carrier Image")
        self.assertEqual(ds["scientific_metadata"]["sample_positions"], positions)
        self.assertIn((carrier_uuid, dsid), self.store["sample_datasets"])
        self.assertIn((tray1, dsid), self.store["sample_datasets"])
        self.assertIn((tray2, dsid), self.store["sample_datasets"])

        # 3. Postprocess carrier_segmentation
        res_post = self.client.post(
            "/spinbot-photobox/api/postprocess",
            json={"dataset_id": dsid},
        )
        self.assertEqual(res_post.status_code, 200)
        self.assertEqual(len(self.store["postprocessing"]), 1)
        self.assertEqual(self.store["postprocessing"][0]["dataset_mfid"], dsid)
        self.assertEqual(self.store["postprocessing"][0]["pipeline"], "carrier_segmentation")

        # 4. Cross-project postprocess guard returns 403
        other_ds = cruc_client.datasets.create(Dataset(
            dataset_name="Foreign DS", project_id="proj-other", owner="someone-else",
            instrument_mfid="0t4ptyzswnyps0006tqctfjbpr"
        ))
        res_cross = self.client.post(
            "/spinbot-photobox/api/postprocess",
            json={"dataset_id": other_ds["dataset_mfid"]},
        )
        self.assertEqual(res_cross.status_code, 403)
        self.assertIn("does not belong", res_cross.get_json()["error"])

    # 5. nirvana tests
    def test_nirvana_resolve_holders_and_prepare_upload(self):
        # Create Tray A with 2 children and Tray B with 1 child
        tray_a = cruc_client.samples.create(Sample(sample_name="Tray_A", project_id=self.project_id, owner=self.orcid))["unique_id"]
        ta_c1 = cruc_client.samples.create(Sample(sample_name="A_Film_1", project_id=self.project_id, owner=self.orcid))["unique_id"]
        ta_c2 = cruc_client.samples.create(Sample(sample_name="A_Film_2", project_id=self.project_id, owner=self.orcid))["unique_id"]
        cruc_client.samples.link(tray_a, ta_c1)
        cruc_client.samples.link(tray_a, ta_c2)

        tray_b = cruc_client.samples.create(Sample(sample_name="Tray_B", project_id=self.project_id, owner=self.orcid))["unique_id"]
        tb_c1 = cruc_client.samples.create(Sample(sample_name="B_Film_1", project_id=self.project_id, owner=self.orcid))["unique_id"]
        cruc_client.samples.link(tray_b, tb_c1)

        # 1. resolve-holders: maps Tray A (S01..S08) and Tray B (S09..S16)
        res_res = self.client.post(
            "/nirvana/api/resolve-holders",
            json={"holder_uuids": [tray_a, tray_b]},
        )
        self.assertEqual(res_res.status_code, 200, res_res.get_data(as_text=True))
        holders_data = res_res.get_json()
        samples = holders_data["samples"]
        self.assertEqual(len(samples), 16)
        # S01, S02 populated from Tray A
        self.assertEqual(samples[0]["position"], "S01")
        self.assertEqual(samples[0]["uuid"], ta_c1)
        self.assertEqual(samples[1]["position"], "S02")
        self.assertEqual(samples[1]["uuid"], ta_c2)
        # S03..S08 padded empty
        for i in range(2, 8):
            self.assertEqual(samples[i]["uuid"], "")
        # S09 populated from Tray B
        self.assertEqual(samples[8]["position"], "S09")
        self.assertEqual(samples[8]["uuid"], tb_c1)
        # S10..S16 padded empty
        for i in range(9, 16):
            self.assertEqual(samples[i]["uuid"], "")

        # 2. prepare-upload in "From file" mode
        res_file_upload = self.client.post(
            "/nirvana/api/prepare-upload",
            json={
                "source": "file",
                "filename": "scan_sample.h5",
                "excluded_positions": ["S03"],
                "excluded_uuids": ["tf_excluded_uuid"],
                "comments": "From file mode",
            },
        )
        self.assertEqual(res_file_upload.status_code, 200)
        dsid_f = res_file_upload.get_json()["dataset_mfid"]
        ds_f = self.store["datasets"][dsid_f]
        self.assertEqual(ds_f["instrument_mfid"], "0t8vneqh81rbz000b41bdw6adw")
        self.assertIsNone(ds_f["measurement"])
        self.assertIsNone(ds_f["data_type"])
        self.assertEqual(ds_f["scientific_metadata"]["skipped thin films"], ["tf_excluded_uuid"])
        self.assertEqual(ds_f["scientific_metadata"]["skipped_positions"], ["S03"])
        # From file mode does NOT link thin-film samples directly to parent dataset
        self.assertNotIn((ta_c1, dsid_f), self.store["sample_datasets"])

        # 3. prepare-upload in "From holders" mode
        sample_positions_map = {
            "S01": {"sample_uuid": ta_c1, "sample_name": "A_Film_1", "tray_uuid": tray_a, "tray_name": "Tray_A"},
            "S09": {"sample_uuid": tb_c1, "sample_name": "B_Film_1", "tray_uuid": tray_b, "tray_name": "Tray_B"},
        }
        res_holder_upload = self.client.post(
            "/nirvana/api/prepare-upload",
            json={
                "source": "holders",
                "filename": "scan_holders.h5",
                "sample_positions": sample_positions_map,
                "tray_uuids": [tray_a, tray_b],
                "trays": holders_data["trays"],
                "excluded_positions": ["S02"],
                "comments": "From holders mode",
            },
        )
        self.assertEqual(res_holder_upload.status_code, 200)
        dsid_h = res_holder_upload.get_json()["dataset_mfid"]
        ds_h = self.store["datasets"][dsid_h]
        self.assertEqual(ds_h["instrument_mfid"], "0t8vneqh81rbz000b41bdw6adw")
        self.assertEqual(ds_h["scientific_metadata"]["sample_positions"], sample_positions_map)
        self.assertEqual(ds_h["scientific_metadata"]["tray_uuids"], [tray_a, tray_b])
        self.assertEqual(ds_h["scientific_metadata"]["skipped_positions"], ["S02"])
        # Trays linked to dataset
        self.assertIn((tray_a, dsid_h), self.store["sample_datasets"])
        self.assertIn((tray_b, dsid_h), self.store["sample_datasets"])

    def test_group2_print_endpoints_require_authentication(self):
        # Clear session
        with self.client.session_transaction() as sess:
            sess.clear()

        # SpinBot Photobox print carrier
        res1 = self.client.post("/spinbot-photobox/api/print-carrier", json={"carrier_uuid": "c1"})
        self.assertEqual(res1.status_code, 401)
        self.assertIn("Not authenticated", res1.get_json()["error"])

        # SpinBot SpinRun print trays
        res2 = self.client.post("/spinbot-spinrun/api/print-trays", json={"trays": [{"mfid": "t1"}]})
        self.assertEqual(res2.status_code, 401)
        self.assertIn("Not authenticated", res2.get_json()["error"])

    def test_spinbot_photobox_next_carrier_name_cross_project_guard(self):
        # User is in "test-project", attempting to access "unauthorized-project"
        res = self.client.get("/spinbot-photobox/api/next-carrier-name?project_id=unauthorized-project")
        self.assertEqual(res.status_code, 403)
        self.assertIn("Project access denied", res.get_json()["error"])

    def test_spinbot_spinrun_batch_limit_and_timeout(self):
        # Test > 50 trays batch rejection
        trays = [{"mfid": f"tray_{i}", "name": f"Tray {i}"} for i in range(51)]
        res = self.client.post("/spinbot-spinrun/api/print-trays", json={"trays": trays})
        self.assertEqual(res.status_code, 400)
        self.assertIn("Too many trays", res.get_json()["error"])

    def test_group2_cross_project_sample_and_dataset_guards(self):
        # Create a sample and dataset in a different project
        other_project = "other-project"
        other_sample = cruc_client.samples.create(
            Sample(sample_name="OtherProjSample", project_id=other_project, owner="other-user")
        )["unique_id"]
        other_ds = cruc_client.datasets.create(
            Dataset(dataset_name="OtherProjDS", project_id=other_project, owner="other-user", instrument_mfid="0tmz7j9xmsrvn000tbs1zjwgpr")
        )["dataset_mfid"]

        # 1. Inorganic XRD single mode linking sample from other project -> 403
        res1 = self.client.post("/inorganic-xrd/api/create-uploads", json={
            "mode": "single",
            "files": [{"filename": "xrd.txt", "sample_uuid": other_sample}],
        })
        self.assertEqual(res1.status_code, 403)
        self.assertIn("belongs to project", res1.get_json()["error"])

        # 2. SpinBot SpinRun linking sample from other project -> 403
        res2 = self.client.post("/spinbot-spinrun/api/create-upload", json={
            "filename": "run.h5",
            "sample_uuid": other_sample,
        })
        self.assertEqual(res2.status_code, 403)
        self.assertIn("belongs to project", res2.get_json()["error"])

        # 3. SpinBot Photobox lookup_carrier with sample from other project -> 403
        res3 = self.client.post("/spinbot-photobox/api/lookup-carrier", json={
            "sample_unique_id": other_sample,
        })
        self.assertEqual(res3.status_code, 403)
        self.assertIn("belongs to project", res3.get_json()["error"])

        # 4. SpinBot Photobox resolve-children with tray from other project -> 403
        res4 = self.client.post("/spinbot-photobox/api/resolve-children", json={
            "sample_uuid": other_sample,
        })
        self.assertEqual(res4.status_code, 403)
        self.assertIn("belongs to project", res4.get_json()["error"])

        # 5. Nirvana resolve-holders with holder from other project -> 403
        res5 = self.client.post("/nirvana/api/resolve-holders", json={
            "holder_uuids": [other_sample],
        })
        self.assertEqual(res5.status_code, 403)
        self.assertIn("belongs to project", res5.get_json()["error"])

        # 6. SpinBot SpinRun attempting to overwrite dataset from other project -> 403
        res6 = self.client.post("/spinbot-spinrun/api/create-upload", json={
            "filename": "run.h5",
            "embedded_dsid": other_ds,
        })
        self.assertEqual(res6.status_code, 403)
        self.assertIn("belongs to project", res6.get_json()["error"])


if __name__ == "__main__":
    unittest.main()
