import os
import unittest

os.environ.setdefault("CRUCIBLE_API_KEY", "test-api-key")

import fake_crucible  # noqa: E402
from crucible import Sample  # noqa: E402
from app import create_app  # noqa: E402
from routes.shared import cruc_client  # noqa: E402

P = "10k_test"
USER = {"orcid": "0000-0002", "user_name": "Ana", "projects": [P], "selected_project": P}


def row(**values):
    return {"Sample Name": "", "Sample Description": "", "Timestamp": "", **values}


class SynthesisUploadTests(unittest.TestCase):
    def setUp(self):
        self.store, restore = fake_crucible.install(cruc_client)
        self.addCleanup(restore)
        app = create_app()
        app.config.update(TESTING=True, SECRET_KEY="test")
        self.api = app.test_client()
        with self.api.session_transaction() as sess:
            sess["user"] = dict(USER)

    def existing(self, name, sample_type, project=P):
        return cruc_client.samples.create(Sample(sample_name=name, sample_type=sample_type, project_id=project))["unique_id"]

    def upload(self, synthesis_type, rows, **extra):
        body = {"project": P, "category": "Perovskites_10k", "synthesis_type": synthesis_type, "data": rows, **extra}
        return self.api.post("/synthesis/api/upload", json=body)

    def test_requires_login_and_project_membership(self):
        with self.api.session_transaction() as sess:
            sess["user"] = {**USER, "projects": ["other"]}
        self.assertEqual(self.upload("Solid Precursor", [row(**{"Sample Name": "x"})]).status_code, 403)
        with self.api.session_transaction() as sess:
            sess.pop("user")
        self.assertEqual(self.upload("Solid Precursor", [row(**{"Sample Name": "x"})]).status_code, 401)

    def test_unknown_category_is_a_400_not_a_500(self):
        r = self.api.post("/synthesis/api/upload", json={"project": P, "category": "Nope", "synthesis_type": "x", "data": [{}]})
        self.assertEqual(r.status_code, 400)
        self.assertIn("Unknown synthesis category", r.get_json()["detail"])

    def test_writes_samples_links_and_datasets(self):
        parent = self.existing("PbI2", "solid precursor")
        r = self.upload("Stock Solution", [row(**{"Sample Name": "SS-1", "Sample Description": "d",
                                                  "Timestamp": "2026-11-01T10:00:00", "Metal Salt SP-ID": "PbI2"})])
        body = r.get_json()
        self.assertTrue(body["success"], body)
        self.assertEqual(body["summary"]["Samples Uploaded"], 1)
        created = body["summary"]["Created Samples"][0]["unique_id"]
        self.assertEqual(self.store["samples"][created]["sample_type"], "stock solution")
        self.assertIn((parent, created), self.store["links"])
        dataset_id = next(d for s, d in self.store["sample_datasets"] if s == created)
        meta = self.store["datasets"][dataset_id]["scientific_metadata"]
        self.assertEqual(meta["metal_salt_sp-id"], "PbI2")
        self.assertEqual(self.store["datasets"][dataset_id]["measurement"], "Stock Solution synthesis")

    def test_smiles_are_canonicalized(self):
        self.upload("Solid Precursor", [row(**{"Sample Name": "EtOH", "SMILES": "OCC"})])
        meta = next(d["scientific_metadata"] for d in self.store["datasets"].values())
        self.assertEqual(meta["smiles_canonical"], "CCO")

    def test_ambiguous_parent_halts_before_writing(self):
        first = self.existing("PbI2", "solid precursor")
        self.existing("PbI2", "solid precursor")
        before = len(self.store["samples"])
        body = self.upload("Stock Solution", [row(**{"Sample Name": "SS-1", "Metal Salt SP-ID": "PbI2"})]).get_json()
        self.assertFalse(body["success"])
        self.assertEqual(len(body["needs_selection"]), 1)
        self.assertEqual(len(body["needs_selection"][0]["candidates"]), 2)
        self.assertEqual(len(self.store["samples"]), before)

        # The user's choice is re-checked and then used.
        body = self.upload("Stock Solution", [row(**{"Sample Name": "SS-1", "Metal Salt SP-ID": "PbI2"})],
                           parent_selections=[{"row": 0, "field": "metal_salt_sp-id", "unique_id": first}]).get_json()
        self.assertTrue(body["success"], body)
        created = body["summary"]["Created Samples"][0]["unique_id"]
        self.assertIn((first, created), self.store["links"])

    def test_unresolved_parent_skips_only_that_row(self):
        self.existing("PbI2", "solid precursor")
        body = self.upload("Stock Solution", [
            row(**{"Sample Name": "SS-ok", "Metal Salt SP-ID": "PbI2"}),
            row(**{"Sample Name": "SS-bad", "Metal Salt SP-ID": "Missing"}),
        ]).get_json()
        self.assertTrue(body["success"])
        self.assertEqual(body["summary"]["Samples Uploaded"], 1)
        self.assertEqual(body["summary"]["Failed"], 1)
        self.assertIn("matched no solid precursor", body["summary"]["Errors"][0])

    def test_duplicate_names_need_confirmation(self):
        self.existing("SP-1", "solid precursor")
        body = self.upload("Solid Precursor", [row(**{"Sample Name": "SP-1"})]).get_json()
        self.assertFalse(body["success"])
        self.assertEqual(body["duplicate_names"][0]["sample_name"], "SP-1")
        body = self.upload("Solid Precursor", [row(**{"Sample Name": "SP-1"})], confirm_duplicate_names=True).get_json()
        self.assertTrue(body["success"])

    def test_owner_comes_from_the_session(self):
        r = self.upload("Solid Precursor", [row(**{"Sample Name": "SP-2"})], orcid="9999-9999")
        self.assertTrue(r.get_json()["success"])


if __name__ == "__main__":
    unittest.main()
