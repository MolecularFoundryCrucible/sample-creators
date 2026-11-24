"""Unit tests for the 7 migrated TEM session uploaders and /api/session/* routes."""
import json
import os
import re
import unittest
from unittest.mock import patch

os.environ.setdefault("CRUCIBLE_API_KEY", "test-api-key")

from app import create_app
from config import TEM_ACCEPTABLE_FILE_TYPES, TEM_SESSION_TOOLS
from crucible import Dataset, Sample
from routes.shared import cruc_client
from tests import fake_crucible
import tools.tem_sessions as tem_sessions_mod


EXPECTED_TEM_TOOLS = [
    ("m3_microscope", "b67", "/m3-microscope", "Imaging - m3-Microscope", "m3-microscope", "0tmz7kb6qdwfs000cyevpp43vc"),
    ("team05", "ncem", "/team05", "TEAM 0.5", "team05", "0szb5en16nxdk000dcd8a1wt2w"),
    ("team1", "ncem", "/team1", "TEAM I", "team01", "0tbrbfgg2sstf000jk1bwhcvw8"),
    ("themis", "ncem", "/themis", "ThemIS", "themis", "0t6k7ms7r5zak000bwynwcfacr"),
    ("titanx", "ncem", "/titanx", "TitanX", "titanx", "0sh6zrzxhnz8k000k7pwq0s2t8"),
    ("f200", "ncem", "/f200", "F200", "f200", "0tkkpbc07sv6z000x7b2f1bgs0"),
    ("spectre", "ncem", "/spectre", "Spectre", "spectre", "0tf06pwcg9ymf00014jzj3rzs8"),
]


class TemSessionUploadersTests(unittest.TestCase):
    def setUp(self):
        self.store, restore = fake_crucible.install(cruc_client)
        self.addCleanup(restore)

        self.app = create_app()
        self.app.config.update(TESTING=True, SECRET_KEY="test-secret")
        self.client = self.app.test_client()

        self.user = {
            "unique_id": "0000-0001-2345-6789",
            "orcid": "0000-0001-2345-6789",
            "username": "tester",
            "first_name": "Test",
            "last_name": "User",
            "email": "test@lbl.gov",
        }
        self.other_user = {
            "unique_id": "0000-0009-9999-9999",
            "orcid": "0000-0009-9999-9999",
            "username": "other",
            "first_name": "Other",
            "last_name": "User",
            "email": "other@lbl.gov",
        }
        self.store["users"][self.user["unique_id"]] = dict(self.user)
        self.store["users"][self.other_user["unique_id"]] = dict(self.other_user)
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

    def test_all_seven_tem_tools_registered_with_exact_configs_and_divisions(self):
        self.assertEqual(len(TEM_SESSION_TOOLS), 7)
        self.assertEqual(
            TEM_ACCEPTABLE_FILE_TYPES,
            [
                ".bcf", ".bmp", ".csv", ".dm3", ".dm4", ".emd", ".h5",
                ".jpeg", ".mrc", ".mtd", ".png", ".ser", ".tif", ".txt", ".xls",
            ],
        )

        # Verify home page exposes NCEM division
        home_html = self.client.get("/").get_data(as_text=True)
        self.assertIn('href="/division/ncem"', home_html)

        # Verify m3_microscope appears at the end of B67
        b67_html = self.client.get("/division/b67").get_data(as_text=True)
        b67_main = b67_html.split('<main class="container">', 1)[1]
        b67_titles = re.findall(r"<h2[^>]*>(.*?)</h2>", b67_main)
        self.assertEqual(b67_titles[-1], "Imaging - m3-Microscope")
        self.assertIn('href="/m3-microscope/"', b67_main)

        # Verify all 6 NCEM TEMs appear in order under /division/ncem
        ncem_html = self.client.get("/division/ncem").get_data(as_text=True)
        ncem_main = ncem_html.split('<main class="container">', 1)[1]
        ncem_titles = re.findall(r"<h2[^>]*>(.*?)</h2>", ncem_main)
        self.assertEqual(ncem_titles, ["TEAM 0.5", "TEAM I", "ThemIS", "TitanX", "F200", "Spectre"])

        # Verify each route renders session_uploader.html with complete JSON-serializable tool_config
        required_keys = {
            "name", "key", "division", "order", "url_prefix", "endpoint",
            "nav_label", "card_title", "card_description", "instrument_id",
            "instrument_mfid", "ingestor", "ui_mode", "post_processing",
            "default_printer", "acceptable_file_types",
        }
        for key, division, prefix, title, inst_id, inst_mfid in EXPECTED_TEM_TOOLS:
            with self.subTest(tool=key):
                with patch.object(tem_sessions_mod, "render_template", return_value="rendered-ok") as mock_render:
                    resp = self.client.get(f"{prefix}/")
                self.assertEqual(resp.status_code, 200)
                mock_render.assert_called_once()
                template_name = mock_render.call_args.args[0]
                tool_cfg = mock_render.call_args.kwargs["tool_config"]
                self.assertEqual(template_name, "session_uploader.html")
                self.assertTrue(required_keys.issubset(tool_cfg.keys()))
                self.assertEqual(tool_cfg["name"], key)
                self.assertEqual(tool_cfg["key"], key)
                self.assertEqual(tool_cfg["division"], division)
                self.assertEqual(tool_cfg["url_prefix"], prefix)
                self.assertEqual(tool_cfg["card_title"], title)
                self.assertEqual(tool_cfg["instrument_id"], inst_id)
                self.assertEqual(tool_cfg["instrument_mfid"], inst_mfid)
                self.assertEqual(tool_cfg["ingestor"], "")
                self.assertEqual(tool_cfg["ui_mode"], "session")
                self.assertEqual(tool_cfg["post_processing"], [])
                self.assertEqual(tool_cfg["acceptable_file_types"], TEM_ACCEPTABLE_FILE_TYPES)
                # Ensure tool_config is strictly JSON-serializable for Jinja tojson
                encoded = json.dumps(tool_cfg)
                self.assertEqual(json.loads(encoded)["instrument_mfid"], inst_mfid)

    def test_auth_required_for_session_routes(self):
        with self.client.session_transaction() as sess:
            sess.clear()
        for endpoint in ("/team1/api/session/check", "/team1/api/session/start", "/team1/api/session/prepare-children"):
            res = self.client.post(endpoint, json={})
            self.assertEqual(res.status_code, 401)

    def test_session_check_validates_folder_name(self):
        invalid_names = ["", "   ", ".", "..", "a/b", "a\\b", "../escape", "bad..name", "line\nbreak", "null\x00byte", 123, None]
        for bad in invalid_names:
            with self.subTest(folder_name=bad):
                res = self.client.post("/team1/api/session/check", json={"folder_name": bad})
                self.assertEqual(res.status_code, 400)

        # Single dots inside a normal folder name are allowed
        res = self.client.post("/team05/api/session/check", json={"folder_name": "run_0.5_2026.11.18"})
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["session_name"], "run_0.5_2026.11.18")
        self.assertEqual(data["session_dataset_name"], "team05 session: run_0.5_2026.11.18")
        self.assertEqual(data["matches"], [])

    def test_session_check_matches_owner_project_and_name_only(self):
        # Matching dataset: proj-1, owned by self.user, exact name
        match_ds = cruc_client.datasets.create(Dataset(
            dataset_name="team1 session: 2026-11-18_run",
            project_id="proj-1",
            owner=self.user["orcid"],
            instrument_mfid="0tbrbfgg2sstf000jk1bwhcvw8",
        ))
        match_id = match_ds["dataset_mfid"]
        self.store["datasets"][match_id]["creation_time"] = "2026-11-18T10:00:00Z"
        self.store["datasets"][match_id]["modification_time"] = "2026-11-18T11:00:00Z"

        # Non-matching 1: owned by another user in proj-1
        cruc_client.datasets.create(Dataset(
            dataset_name="team1 session: 2026-11-18_run",
            project_id="proj-1",
            owner=self.other_user["orcid"],
            instrument_mfid="0tbrbfgg2sstf000jk1bwhcvw8",
        ))
        # Non-matching 2: same user and name, different project (proj-2)
        cruc_client.datasets.create(Dataset(
            dataset_name="team1 session: 2026-11-18_run",
            project_id="proj-2",
            owner=self.user["orcid"],
            instrument_mfid="0tbrbfgg2sstf000jk1bwhcvw8",
        ))
        # Non-matching 3: same user and project, different instrument session prefix
        cruc_client.datasets.create(Dataset(
            dataset_name="team05 session: 2026-11-18_run",
            project_id="proj-1",
            owner=self.user["orcid"],
            instrument_mfid="0szb5en16nxdk000dcd8a1wt2w",
        ))

        res = self.client.post("/team1/api/session/check", json={"folder_name": "2026-11-18_run"})
        self.assertEqual(res.status_code, 200, res.get_data(as_text=True))
        data = res.get_json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["session_name"], "2026-11-18_run")
        self.assertEqual(data["session_dataset_name"], "team1 session: 2026-11-18_run")
        self.assertEqual(len(data["matches"]), 1)
        m = data["matches"][0]
        self.assertEqual(m["unique_id"], match_id)
        self.assertEqual(m["dataset_name"], "team1 session: 2026-11-18_run")
        self.assertEqual(m["creation_time"], "2026-11-18T10:00:00Z")
        self.assertEqual(m["modification_time"], "2026-11-18T11:00:00Z")
        self.assertTrue(m["hub_url"].endswith(f"/datasets/{match_id}"))

    def test_session_start_new_and_resume_with_optional_sample_link(self):
        sample = cruc_client.samples.create(Sample(
            sample_name="TEM-Grid-1",
            sample_type="tem grid",
            project_id="proj-1",
            owner=self.user["orcid"],
        ))
        sample_id = sample["unique_id"]

        # 1. Start a brand new session on m3-microscope with sample, comments, keywords
        res = self.client.post("/m3-microscope/api/session/start", json={
            "folder_name": "2026-11-18_grid1",
            "existing_session_dsid": "new",
            "sample_unique_id": sample_id,
            "comments": "Cryo holder run",
            "keywords": ["tem", "cryo"],
        })
        self.assertEqual(res.status_code, 200, res.get_data(as_text=True))
        data = res.get_json()
        self.assertTrue(data["ok"])
        self.assertFalse(data["reused"])
        self.assertEqual(data["session_name"], "2026-11-18_grid1")
        self.assertEqual(data["dataset_name"], "m3_microscope session: 2026-11-18_grid1")
        session_dsid = data["session_dsid"]
        self.assertTrue(data["hub_url"].endswith(f"/datasets/{session_dsid}"))

        stored = self.store["datasets"][session_dsid]
        self.assertEqual(stored["dataset_name"], "m3_microscope session: 2026-11-18_grid1")
        self.assertEqual(stored["measurement"], "full m3_microscope session")
        self.assertEqual(stored["instrument_mfid"], "0tmz7kb6qdwfs000cyevpp43vc")
        self.assertEqual(stored["project_id"], "proj-1")
        self.assertEqual(stored["scientific_metadata"], {"comments": "Cryo holder run"})
        self.assertEqual(stored["keywords"], ["tem", "cryo"])
        self.assertIn((sample_id, session_dsid), self.store["sample_datasets"])

        # 2. Resume the existing session and link a second sample
        sample2 = cruc_client.samples.create(Sample(
            sample_name="TEM-Grid-2",
            sample_type="tem grid",
            project_id="proj-1",
            owner=self.user["orcid"],
        ))
        before_count = len(self.store["datasets"])
        res2 = self.client.post("/m3-microscope/api/session/start", json={
            "folder_name": "2026-11-18_grid1",
            "existing_session_dsid": session_dsid,
            "sample_unique_id": sample2["unique_id"],
        })
        self.assertEqual(res2.status_code, 200, res2.get_data(as_text=True))
        data2 = res2.get_json()
        self.assertTrue(data2["ok"])
        self.assertTrue(data2["reused"])
        self.assertEqual(data2["session_dsid"], session_dsid)
        self.assertEqual(len(self.store["datasets"]), before_count)
        self.assertIn((sample2["unique_id"], session_dsid), self.store["sample_datasets"])

    def test_prepare_children_links_and_session_scoped_sha256_dedup(self):
        sample = cruc_client.samples.create(Sample(
            sample_name="Grid-A",
            sample_type="tem grid",
            project_id="proj-1",
            owner=self.user["orcid"],
        ))
        sample_id = sample["unique_id"]

        # Create target session on themis
        start_res = self.client.post("/themis/api/session/start", json={
            "folder_name": "themis_run_1",
        })
        self.assertEqual(start_res.status_code, 200)
        session_dsid = start_res.get_json()["session_dsid"]

        # Pre-existing child already linked to THIS session with sha_same_session
        sha_same_session = "a" * 64
        existing_child = cruc_client.datasets.create(Dataset(
            dataset_name="img01.dm4",
            project_id="proj-1",
            owner=self.user["orcid"],
            instrument_mfid="0t6k7ms7r5zak000bwynwcfacr",
        ))
        existing_child_id = existing_child["dataset_mfid"]
        cruc_client.datasets.link(session_dsid, existing_child_id)
        self.store["files"][existing_child_id] = [{
            "mfid": "f" + "1" * 25,
            "filename": "img01.dm4",
            "sha256_hash": sha_same_session,
        }]

        # Unrelated standalone dataset in SAME project & owner with sha_unrelated
        sha_unrelated = "b" * 64
        unrelated_ds = cruc_client.datasets.create(Dataset(
            dataset_name="unrelated.dm4",
            project_id="proj-1",
            owner=self.user["orcid"],
            instrument_mfid="0t6k7ms7r5zak000bwynwcfacr",
        ))
        unrelated_ds_id = unrelated_ds["dataset_mfid"]
        self.store["files"][unrelated_ds_id] = [{
            "mfid": "f" + "2" * 25,
            "filename": "unrelated.dm4",
            "sha256_hash": sha_unrelated,
        }]

        # Child of a DIFFERENT session in SAME project & owner with sha_other_session
        sha_other_session = "c" * 64
        other_session = cruc_client.datasets.create(Dataset(
            dataset_name="themis session: other_run",
            project_id="proj-1",
            owner=self.user["orcid"],
            instrument_mfid="0t6k7ms7r5zak000bwynwcfacr",
        ))
        other_session_child = cruc_client.datasets.create(Dataset(
            dataset_name="other_child.ser",
            project_id="proj-1",
            owner=self.user["orcid"],
            instrument_mfid="0t6k7ms7r5zak000bwynwcfacr",
        ))
        other_child_id = other_session_child["dataset_mfid"]
        cruc_client.datasets.link(other_session["dataset_mfid"], other_child_id)
        self.store["files"][other_child_id] = [{
            "mfid": "f" + "3" * 25,
            "filename": "other_child.ser",
            "sha256_hash": sha_other_session,
        }]

        prep_res = self.client.post("/themis/api/session/prepare-children", json={
            "session_dsid": session_dsid,
            "session_name": "themis_run_1",
            "sample_unique_id": sample_id,
            "comments": "Batch 1",
            "keywords": ["stem", "edx"],
            "items": [
                {"client_id": "c1", "dataset_name": "img01.dm4", "sha256_hash": sha_same_session, "data_format": "dm4"},
                {"client_id": "c2", "dataset_name": "img02.dm4", "sha256_hash": sha_unrelated, "data_format": "dm4"},
                {"client_id": "c3", "dataset_name": "img03.ser", "sha256_hash": sha_other_session, "data_format": "ser"},
                {"client_id": "c4", "dataset_name": "big_tomo.mrc", "sha256_hash": None, "data_format": "mrc"},
            ],
        })
        self.assertEqual(prep_res.status_code, 200, prep_res.get_data(as_text=True))
        body = prep_res.get_json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["session_dsid"], session_dsid)
        by_cid = {c["client_id"]: c for c in body["children"]}
        self.assertEqual(set(by_cid.keys()), {"c1", "c2", "c3", "c4"})

        # c1: MUST reuse existing_child_id (same session child), return existing_filenames,
        # and NOT duplicate the parent->child link.
        self.assertTrue(by_cid["c1"]["reused"])
        self.assertEqual(by_cid["c1"]["dataset_mfid"], existing_child_id)
        self.assertEqual(by_cid["c1"]["existing_filenames"], ["img01.dm4"])
        self.assertEqual(self.store["dataset_links"].count((session_dsid, existing_child_id)), 1)

        # c2: MUST NOT reuse unrelated_ds_id (not a child of this session)
        self.assertFalse(by_cid["c2"]["reused"])
        self.assertNotEqual(by_cid["c2"]["dataset_mfid"], unrelated_ds_id)
        self.assertEqual(by_cid["c2"]["existing_filenames"], [])

        # c3: MUST NOT reuse other_child_id (child of a different session)
        self.assertFalse(by_cid["c3"]["reused"])
        self.assertNotEqual(by_cid["c3"]["dataset_mfid"], other_child_id)
        self.assertEqual(by_cid["c3"]["existing_filenames"], [])

        # c4: new dataset with null sha256_hash
        self.assertFalse(by_cid["c4"]["reused"])
        self.assertEqual(by_cid["c4"]["existing_filenames"], [])

        # Every prepared child must be linked to parent session exactly once, linked to sample, and have expected metadata
        for cid, child_info in by_cid.items():
            dsid = child_info["dataset_mfid"]
            self.assertTrue(child_info["hub_url"].endswith(f"/datasets/{dsid}"))
            self.assertEqual(self.store["dataset_links"].count((session_dsid, dsid)), 1)
            self.assertIn((sample_id, dsid), self.store["sample_datasets"])
            ds_rec = self.store["datasets"][dsid]
            self.assertEqual(ds_rec["instrument_mfid"], "0t6k7ms7r5zak000bwynwcfacr")
            self.assertEqual(ds_rec["scientific_metadata"]["comment"], "Batch 1")
            self.assertIn("stem", ds_rec["keywords"])
            self.assertIn("edx", ds_rec["keywords"])

    def test_fail_closed_403_for_cross_project_session_and_sample(self):
        other_proj_session = cruc_client.datasets.create(Dataset(
            dataset_name="titanx session: secret_run",
            project_id="proj-2",
            owner=self.user["orcid"],
            instrument_mfid="0sh6zrzxhnz8k000k7pwq0s2t8",
        ))
        other_proj_session_id = other_proj_session["dataset_mfid"]

        own_proj_session = cruc_client.datasets.create(Dataset(
            dataset_name="titanx session: own_run",
            project_id="proj-1",
            owner=self.user["orcid"],
            instrument_mfid="0sh6zrzxhnz8k000k7pwq0s2t8",
        ))
        own_proj_session_id = own_proj_session["dataset_mfid"]

        other_proj_sample = cruc_client.samples.create(Sample(
            sample_name="Secret-Sample",
            sample_type="tem grid",
            project_id="proj-2",
            owner=self.user["orcid"],
        ))
        other_proj_sample_id = other_proj_sample["unique_id"]

        # 1. /api/session/start with cross-project existing_session_dsid -> 403
        res = self.client.post("/titanx/api/session/start", json={
            "folder_name": "secret_run",
            "existing_session_dsid": other_proj_session_id,
        })
        self.assertEqual(res.status_code, 403)

        # 2. /api/session/start with cross-project sample_unique_id -> 403
        res = self.client.post("/titanx/api/session/start", json={
            "folder_name": "new_run",
            "sample_unique_id": other_proj_sample_id,
        })
        self.assertEqual(res.status_code, 403)

        # 3. /api/session/prepare-children with cross-project session_dsid -> 403
        res = self.client.post("/titanx/api/session/prepare-children", json={
            "session_dsid": other_proj_session_id,
            "items": [{"client_id": "c1", "dataset_name": "a.dm4"}],
        })
        self.assertEqual(res.status_code, 403)

        # 4. /api/session/prepare-children with cross-project sample_unique_id -> 403
        res = self.client.post("/titanx/api/session/prepare-children", json={
            "session_dsid": own_proj_session_id,
            "sample_unique_id": other_proj_sample_id,
            "items": [{"client_id": "c1", "dataset_name": "a.dm4"}],
        })
        self.assertEqual(res.status_code, 403)

    def test_validation_and_not_found_errors(self):
        own_session = cruc_client.datasets.create(Dataset(
            dataset_name="f200 session: run1",
            project_id="proj-1",
            owner=self.user["orcid"],
            instrument_mfid="0tkkpbc07sv6z000x7b2f1bgs0",
        ))
        session_id = own_session["dataset_mfid"]
        missing_mfid = "d" + "9" * 25

        # Invalid existing_session_dsid format -> 400
        res = self.client.post("/f200/api/session/start", json={
            "folder_name": "run1",
            "existing_session_dsid": "not-an-mfid",
        })
        self.assertEqual(res.status_code, 400)

        # Missing existing_session_dsid -> 404
        res = self.client.post("/f200/api/session/start", json={
            "folder_name": "run1",
            "existing_session_dsid": missing_mfid,
        })
        self.assertEqual(res.status_code, 404)

        # Missing sample on start -> 404
        res = self.client.post("/f200/api/session/start", json={
            "folder_name": "run1",
            "sample_unique_id": missing_mfid,
        })
        self.assertEqual(res.status_code, 404)

        # Empty items -> 400
        res = self.client.post("/f200/api/session/prepare-children", json={
            "session_dsid": session_id,
            "items": [],
        })
        self.assertEqual(res.status_code, 400)

        # > 50 items -> 400
        res = self.client.post("/f200/api/session/prepare-children", json={
            "session_dsid": session_id,
            "items": [{"client_id": f"c{i}", "dataset_name": f"f{i}.dm4"} for i in range(51)],
        })
        self.assertEqual(res.status_code, 400)

        # Malformed item rejects entire batch before creating any child datasets
        before_count = len(self.store["datasets"])
        res = self.client.post("/f200/api/session/prepare-children", json={
            "session_dsid": session_id,
            "items": [
                {"client_id": "c1", "dataset_name": "ok.dm4"},
                {"client_id": "c2", "dataset_name": ""},
            ],
        })
        self.assertEqual(res.status_code, 400)
        self.assertEqual(len(self.store["datasets"]), before_count)

        # Invalid session_dsid -> 400; missing session_dsid -> 404
        res = self.client.post("/f200/api/session/prepare-children", json={
            "session_dsid": "bad",
            "items": [{"client_id": "c1", "dataset_name": "ok.dm4"}],
        })
        self.assertEqual(res.status_code, 400)

        res = self.client.post("/f200/api/session/prepare-children", json={
            "session_dsid": missing_mfid,
            "items": [{"client_id": "c1", "dataset_name": "ok.dm4"}],
        })
        self.assertEqual(res.status_code, 404)

    def test_common_uploader_routes_registered_on_tem_blueprints(self):
        # Verify common routes like create-sample and lookup-sample work on a TEM blueprint
        create_res = self.client.post("/spectre/api/create-sample", json={
            "sample_name": "Spectre-Grid-1",
            "sample_type": "tem grid",
            "description": "Cu mesh",
        })
        self.assertEqual(create_res.status_code, 200, create_res.get_data(as_text=True))
        created = create_res.get_json()

        lookup_res = self.client.post("/spectre/api/lookup-sample", json={
            "sample_name": "Spectre-Grid-1",
        })
        self.assertEqual(lookup_res.status_code, 200)
        self.assertEqual(lookup_res.get_json()["unique_id"], created["unique_id"])

    def test_prepare_children_existing_filenames_multiple_and_fallback(self):
        start_res = self.client.post("/team1/api/session/start", json={"folder_name": "ser_run"})
        session_dsid = start_res.get_json()["session_dsid"]

        sha = "d" * 64
        existing_child = cruc_client.datasets.create(Dataset(
            dataset_name="Acq_1.ser",
            project_id="proj-1",
            owner=self.user["orcid"],
            instrument_mfid="0tbrbfgg2sstf000jk1bwhcvw8",
        ))
        child_id = existing_child["dataset_mfid"]
        cruc_client.datasets.link(session_dsid, child_id)
        self.store["files"][child_id] = [
            {"mfid": "f" + "4" * 25, "filename": "Acq.emi", "sha256_hash": "e" * 64},
            {"mfid": "f" + "5" * 25, "filename": "Acq_1.ser", "sha256_hash": sha},
        ]

        res = self.client.post("/team1/api/session/prepare-children", json={
            "session_dsid": session_dsid,
            "items": [{"client_id": "c1", "dataset_name": "Acq_1.ser", "sha256_hash": sha}],
        })
        self.assertEqual(res.status_code, 200)
        child = res.get_json()["children"][0]
        self.assertTrue(child["reused"])
        self.assertEqual(child["existing_filenames"], ["Acq.emi", "Acq_1.ser"])
        self.assertEqual(self.store["dataset_links"].count((session_dsid, child_id)), 1)

        # Graceful fallback to [] if list_files raises
        with patch.object(cruc_client.datasets, "list_files", side_effect=RuntimeError("list_files failed")):
            res2 = self.client.post("/team1/api/session/prepare-children", json={
                "session_dsid": session_dsid,
                "items": [{"client_id": "c1", "dataset_name": "Acq_1.ser", "sha256_hash": sha}],
            })
        self.assertEqual(res2.status_code, 200)
        self.assertEqual(res2.get_json()["children"][0]["existing_filenames"], [])

    def test_get_dataset_in_project_maps_http_and_network_errors(self):
        import requests

        valid_mfid = "d" + "8" * 25

        # Network / timeout error without HTTP status -> 500 (not 404)
        with patch.object(cruc_client.datasets, "get", side_effect=ConnectionError("timed out")):
            res = self.client.post("/f200/api/session/start", json={
                "folder_name": "run1",
                "existing_session_dsid": valid_mfid,
            })
        self.assertEqual(res.status_code, 500)

        # requests.HTTPError with response.status_code == 404 -> 404
        resp_404 = requests.Response()
        resp_404.status_code = 404
        with patch.object(cruc_client.datasets, "get", side_effect=requests.HTTPError("missing", response=resp_404)):
            res = self.client.post("/f200/api/session/start", json={
                "folder_name": "run1",
                "existing_session_dsid": valid_mfid,
            })
        self.assertEqual(res.status_code, 404)

        # requests.HTTPError with response.status_code == 403 -> 403
        resp_403 = requests.Response()
        resp_403.status_code = 403
        with patch.object(cruc_client.datasets, "get", side_effect=requests.HTTPError("denied", response=resp_403)):
            res = self.client.post("/f200/api/session/prepare-children", json={
                "session_dsid": valid_mfid,
                "items": [{"client_id": "c1", "dataset_name": "a.dm4"}],
            })
        self.assertEqual(res.status_code, 403)

        # requests.HTTPError with response.status_code == 503 -> 500
        resp_503 = requests.Response()
        resp_503.status_code = 503
        with patch.object(cruc_client.datasets, "get", side_effect=requests.HTTPError("unavailable", response=resp_503)):
            res = self.client.post("/f200/api/session/prepare-children", json={
                "session_dsid": valid_mfid,
                "items": [{"client_id": "c1", "dataset_name": "a.dm4"}],
            })
        self.assertEqual(res.status_code, 500)

    def test_prepare_children_incomplete_child_dataset_reuse_on_resume(self):
        start_res = self.client.post("/titanx/api/session/start", json={"folder_name": "interrupted_run"})
        session_dsid = start_res.get_json()["session_dsid"]

        sha_notes1 = "1" * 64

        # In Run 1:
        # Child 0: notes1.txt was completed
        child0 = cruc_client.datasets.create(Dataset(
            dataset_name="notes1.txt",
            project_id="proj-1",
            owner=self.user["orcid"],
            instrument_mfid="0sh6zrzxhnz8k000k7pwq0s2t8",
        ))
        child0_id = child0["dataset_mfid"]
        cruc_client.datasets.link(session_dsid, child0_id)
        self.store["files"][child0_id] = [
            {"filename": "notes1.txt", "sha256_hash": sha_notes1, "size": 100}
        ]

        # Child 1: acq_1.ser was created, companion acq.emi uploaded, primary acq_1.ser never completed
        child1 = cruc_client.datasets.create(Dataset(
            dataset_name="acq_1.ser",
            project_id="proj-1",
            owner=self.user["orcid"],
            instrument_mfid="0sh6zrzxhnz8k000k7pwq0s2t8",
        ))
        child1_id = child1["dataset_mfid"]
        cruc_client.datasets.link(session_dsid, child1_id)
        self.store["files"][child1_id] = [
            {"filename": "acq.emi", "sha256_hash": "e" * 64, "size": 500}
        ]

        # Now Run 2 resumes with:
        # - notes1.txt (has sha_notes1)
        # - acq_1.ser (has sha_ser, but no file with this sha exists yet on server)
        # - notes3.txt (brand new)
        sha_ser = "s" * 64
        sha_notes3 = "3" * 64

        res = self.client.post("/titanx/api/session/prepare-children", json={
            "session_dsid": session_dsid,
            "items": [
                {"client_id": "c0", "dataset_name": "notes1.txt", "sha256_hash": sha_notes1},
                {"client_id": "c1", "dataset_name": "acq_1.ser", "sha256_hash": sha_ser},
                {"client_id": "c2", "dataset_name": "notes3.txt", "sha256_hash": sha_notes3},
            ],
        })
        self.assertEqual(res.status_code, 200, res.get_data(as_text=True))
        children = res.get_json()["children"]
        self.assertEqual(len(children), 3)

        # Child 0 matches via SHA-256
        self.assertEqual(children[0]["client_id"], "c0")
        self.assertEqual(children[0]["dataset_mfid"], child0_id)
        self.assertTrue(children[0]["reused"])
        self.assertEqual(children[0]["existing_filenames"], ["notes1.txt"])

        # Child 1 matches incomplete child by dataset_name
        self.assertEqual(children[1]["client_id"], "c1")
        self.assertEqual(children[1]["dataset_mfid"], child1_id)
        self.assertTrue(children[1]["reused"])
        self.assertEqual(children[1]["existing_filenames"], ["acq.emi"])

        # Child 2 was never created in Run 1 -> created fresh
        self.assertEqual(children[2]["client_id"], "c2")
        self.assertFalse(children[2]["reused"])
        self.assertEqual(children[2]["existing_filenames"], [])
        self.assertNotIn(children[2]["dataset_mfid"], [child0_id, child1_id])

        # Verify no duplicate link was created for child0 and child1
        links = self.store["dataset_links"]
        self.assertEqual(links.count((session_dsid, child0_id)), 1)
        self.assertEqual(links.count((session_dsid, child1_id)), 1)
        self.assertEqual(links.count((session_dsid, children[2]["dataset_mfid"])), 1)

    def test_prepare_children_different_sha_with_same_filename_not_claimed_as_incomplete(self):
        start_res = self.client.post("/titanx/api/session/start", json={"folder_name": "subfolder_run"})
        session_dsid = start_res.get_json()["session_dsid"]

        sha_foo1 = "a" * 64
        sha_foo2 = "b" * 64

        # Existing child for foo.txt in subfolder A that already completed foo.txt with sha_foo1
        child_foo = cruc_client.datasets.create(Dataset(
            dataset_name="foo.txt",
            project_id="proj-1",
            owner=self.user["orcid"],
            instrument_mfid="0sh6zrzxhnz8k000k7pwq0s2t8",
        ))
        child_foo_id = child_foo["dataset_mfid"]
        cruc_client.datasets.link(session_dsid, child_foo_id)
        self.store["files"][child_foo_id] = [
            {"filename": "foo.txt", "sha256_hash": sha_foo1, "size": 120}
        ]

        # Second foo.txt (e.g. from subfolder B) has sha_foo2
        res = self.client.post("/titanx/api/session/prepare-children", json={
            "session_dsid": session_dsid,
            "items": [
                {"client_id": "c_sub", "dataset_name": "foo.txt", "sha256_hash": sha_foo2},
            ],
        })
        self.assertEqual(res.status_code, 200)
        child = res.get_json()["children"][0]
        # Must NOT claim child_foo because child_foo ALREADY has foo.txt!
        self.assertFalse(child["reused"])
        self.assertNotEqual(child["dataset_mfid"], child_foo_id)
        self.assertEqual(child["existing_filenames"], [])

    def test_prepare_children_mrc_and_txt_sha256_scoping_prevents_name_clobber(self):
        start_res = self.client.post("/titanx/api/session/start", json={"folder_name": "tomo_run"})
        session_dsid = start_res.get_json()["session_dsid"]

        sha_mrc = "m" * 64
        sha_txt = "t" * 64

        # DS_MRC contains tomo.mrc and sidecars tomo.rawtlt and tomo.txt
        ds_mrc = cruc_client.datasets.create(Dataset(
            dataset_name="tomo.mrc",
            project_id="proj-1",
            owner=self.user["orcid"],
            instrument_mfid="0sh6zrzxhnz8k000k7pwq0s2t8",
        ))
        ds_mrc_id = ds_mrc["dataset_mfid"]
        cruc_client.datasets.link(session_dsid, ds_mrc_id)
        self.store["files"][ds_mrc_id] = [
            {"filename": "tomo.rawtlt", "sha256_hash": "r" * 64, "size": 200},
            {"filename": "tomo.txt", "sha256_hash": sha_txt, "size": 300},
            {"filename": "tomo.mrc", "sha256_hash": sha_mrc, "size": 5000},
        ]

        # 1. Standalone tomo.txt prepared in a separate call must NOT match ds_mrc
        res_standalone = self.client.post("/titanx/api/session/prepare-children", json={
            "session_dsid": session_dsid,
            "items": [
                {"client_id": "c_txt", "dataset_name": "tomo.txt", "sha256_hash": sha_txt},
            ],
        })
        self.assertEqual(res_standalone.status_code, 200)
        txt_child = res_standalone.get_json()["children"][0]
        self.assertFalse(txt_child["reused"])
        self.assertNotEqual(txt_child["dataset_mfid"], ds_mrc_id)
        # Verify ds_mrc dataset_name was NOT overwritten to tomo.txt
        self.assertEqual(self.store["datasets"][ds_mrc_id]["dataset_name"], "tomo.mrc")

        # 2. Both prepared together: tomo.mrc reuses ds_mrc, tomo.txt reuses txt_child
        res_both = self.client.post("/titanx/api/session/prepare-children", json={
            "session_dsid": session_dsid,
            "items": [
                {"client_id": "c_mrc2", "dataset_name": "tomo.mrc", "sha256_hash": sha_mrc},
                {"client_id": "c_txt2", "dataset_name": "tomo.txt", "sha256_hash": sha_txt},
            ],
        })
        self.assertEqual(res_both.status_code, 200)
        both_children = res_both.get_json()["children"]
        self.assertEqual(both_children[0]["dataset_mfid"], ds_mrc_id)
        self.assertTrue(both_children[0]["reused"])
        self.assertEqual(both_children[1]["dataset_mfid"], txt_child["dataset_mfid"])
        self.assertTrue(both_children[1]["reused"])
        self.assertEqual(self.store["datasets"][ds_mrc_id]["dataset_name"], "tomo.mrc")

    def test_prepare_children_exclude_dsids_prevents_double_claiming_across_batches(self):
        start_res = self.client.post("/titanx/api/session/start", json={"folder_name": "calib_run"})
        session_dsid = start_res.get_json()["session_dsid"]
        sha_calib = "c" * 64

        ds_calib = cruc_client.datasets.create(Dataset(
            dataset_name="calib.txt",
            project_id="proj-1",
            owner=self.user["orcid"],
            instrument_mfid="0sh6zrzxhnz8k000k7pwq0s2t8",
        ))
        ds_calib_id = ds_calib["dataset_mfid"]
        cruc_client.datasets.link(session_dsid, ds_calib_id)
        self.store["files"][ds_calib_id] = [
            {"filename": "calib.txt", "sha256_hash": sha_calib, "size": 100}
        ]

        # Batch 1 claims ds_calib
        res1 = self.client.post("/titanx/api/session/prepare-children", json={
            "session_dsid": session_dsid,
            "items": [
                {"client_id": "b1_item", "dataset_name": "calib.txt", "sha256_hash": sha_calib},
            ],
        })
        self.assertEqual(res1.status_code, 200)
        self.assertEqual(res1.get_json()["children"][0]["dataset_mfid"], ds_calib_id)

        # Batch 2 passes exclude_dsids containing ds_calib_id
        res2 = self.client.post("/titanx/api/session/prepare-children", json={
            "session_dsid": session_dsid,
            "exclude_dsids": [ds_calib_id],
            "items": [
                {"client_id": "b2_item", "dataset_name": "calib.txt", "sha256_hash": sha_calib},
            ],
        })
        self.assertEqual(res2.status_code, 200)
        b2_child = res2.get_json()["children"][0]
        # Must create a new child dataset because ds_calib_id is excluded
        self.assertFalse(b2_child["reused"])
        self.assertNotEqual(b2_child["dataset_mfid"], ds_calib_id)

    def test_prepare_children_probing_fails_closed_on_list_files_error(self):
        start_res = self.client.post("/titanx/api/session/start", json={"folder_name": "error_probe_run"})
        session_dsid = start_res.get_json()["session_dsid"]

        child_probe = cruc_client.datasets.create(Dataset(
            dataset_name="probe.txt",
            project_id="proj-1",
            owner=self.user["orcid"],
            instrument_mfid="0sh6zrzxhnz8k000k7pwq0s2t8",
        ))
        probe_id = child_probe["dataset_mfid"]
        cruc_client.datasets.link(session_dsid, probe_id)

        # When list_files raises during probing of candidate child, it must fail-closed and not claim it
        with patch.object(cruc_client.datasets, "list_files", side_effect=RuntimeError("transient storage error")):
            res = self.client.post("/titanx/api/session/prepare-children", json={
                "session_dsid": session_dsid,
                "items": [
                    {"client_id": "c_probe", "dataset_name": "probe.txt", "sha256_hash": None},
                ],
            })
        self.assertEqual(res.status_code, 200)
        child = res.get_json()["children"][0]
        self.assertFalse(child["reused"])
        self.assertNotEqual(child["dataset_mfid"], probe_id)


if __name__ == "__main__":
    unittest.main()
