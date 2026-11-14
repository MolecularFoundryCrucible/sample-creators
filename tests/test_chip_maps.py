"""Mask design review and map-driven fabrication against the in-memory Crucible."""
import os
import unittest

os.environ.setdefault("CRUCIBLE_API_KEY", "test-api-key")

import fake_crucible  # noqa: E402
from app import create_app  # noqa: E402
from routes.shared import cruc_client  # noqa: E402

P, T = "QCMF_TEST", "QCMF_Qubit_v1"
USER = {"orcid": "0000-0001", "user_name": "Tim", "projects": [P], "selected_project": P}


def map_body(expected_version=0):
    return {
        "units": "mm", "expected_version": expected_version,
        "blocks": [{"id": "B1", "name": "Block one"}, {"id": "B2", "name": "Block two"}],
        "chips": [
            {"id": "chip-1", "block": "B1", "label": "R1D1", "outline": [0, 0, 12, 7], "layer": "2/0"},
            {"id": "chip-2", "block": "B1", "label": "R1D1", "outline": [12, 0, 24, 7], "layer": "2/0"},
            {"id": "chip-3", "block": "B2", "label": "R2D1", "outline": [0, 10, 5, 15], "layer": "10/0"},
        ],
    }


class ChipMapTests(unittest.TestCase):
    def setUp(self):
        self.store, restore = fake_crucible.install(cruc_client)
        self.addCleanup(restore)
        app = create_app()
        app.config.update(TESTING=True, SECRET_KEY="test")
        self.api = app.test_client()
        with self.api.session_transaction() as sess:
            sess["user"] = dict(USER)
        response = self.api.post("/fabrication/api/masks", json={"project": P, "dataset_name": "WFR_99"})
        self.mask_id = response.get_json()["mask"]["dataset_id"]

    def geometry_ready(self):
        geometry = {"units": "mm", "source": {"file": "WFR_99.gds"}, "min_size_mm": 1,
                    "shapes": [], "labels": [], "unresolved_labels": []}
        self.store["datasets"][self.mask_id]["scientific_metadata"] = {"gds_geometry": geometry}
        self.store["ingestion_requests"][self.mask_id] = [{
            "id": 10, "status": "complete", "ingestion_class": "GdsChipMapIngestor"}]

    def save_map(self, expected_version=0):
        return self.api.post(f"/fabrication/api/masks/{self.mask_id}/chip-maps", json=map_body(expected_version))

    def create_wafer(self, map_id, name="QCMF_WFR_99", plan=None):
        response = self.api.post("/fabrication/api/wafers", json={
            "project": P, "template_id": T, "wafer_name": name, "wafer_options": {"wafer_type": "qubit"},
            "spec": {"mask_design": map_id}, "step_date": "2026-11-12",
            "planned_chiplets": plan or []})
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        return response.get_json()["wafer"]["unique_id"]

    def record(self, wafer_id, step_id, targets, new_children, details):
        return self.api.post("/fabrication/api/steps", json={
            "project": P, "template_id": T, "step_id": step_id, "wafer_id": wafer_id,
            "target_ids": targets, "status": "done", "step_date": "2026-11-12", "rows": {},
            "new_children": new_children, "child_details": details})

    def test_reviewed_versions_when_child_list_omits_metadata(self):
        self.assertEqual(self.api.get(f"/fabrication/api/masks?project={P}").get_json()["masks"][0]["geometry_ready"], False)
        self.geometry_ready()
        detail = self.api.get(f"/fabrication/api/masks/{self.mask_id}").get_json()
        self.assertEqual(detail["geometry"]["source"]["file"], "WFR_99.gds")
        self.assertEqual(detail["ingestion"][0]["status"], "complete")

        response = self.save_map()
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        first_id = response.get_json()["map"]["dataset_id"]
        first = response.get_json()["map"]["chip_map"]
        self.assertEqual(first["version"], 1)
        self.assertFalse(first["locked"])
        self.assertEqual(self.store["dataset_links"], [(self.mask_id, first_id)])
        self.assertEqual(self.save_map(expected_version=0).status_code, 409)

        second_response = self.save_map(expected_version=1)
        second_id = second_response.get_json()["map"]["dataset_id"]
        self.assertEqual(second_response.get_json()["map"]["chip_map"]["version"], 2)
        detail = self.api.get(f"/fabrication/api/masks/{self.mask_id}").get_json()
        self.assertEqual([v["chip_map"]["version"] for v in detail["versions"]], [2, 1])
        self.assertEqual(detail["chip_map"]["dataset_id"], second_id)
        listed = self.api.get(f"/fabrication/api/masks?project={P}").get_json()["masks"][0]
        self.assertEqual(listed["reviewed_map"]["version"], 2)
        self.assertEqual(listed["reviewed_map"]["chip_count"], 3)
        self.assertEqual(listed["reviewed_map"]["block_count"], 2)

    def test_validation_rejects_bad_maps_without_creating_a_version(self):
        cases = []
        body = map_body()
        body["chips"][0]["block"] = "missing"
        cases.append(body)
        body = map_body()
        body["chips"][0]["outline"] = [0, 0, 0, 2]
        cases.append(body)
        body = map_body()
        body["chips"][0]["label"] = "?"
        cases.append(body)
        body = map_body()
        body["chips"][1]["id"] = "chip-1"
        cases.append(body)
        body = map_body()
        body["blocks"][1]["name"] = "Block one"
        cases.append(body)
        for body in cases:
            response = self.api.post(f"/fabrication/api/masks/{self.mask_id}/chip-maps", json=body)
            self.assertEqual(response.status_code, 400, response.get_data(as_text=True))
        self.assertEqual(self.save_map(expected_version=1).status_code, 409)
        body = map_body()
        body["blocks"].append({"id": "B3", "name": "Empty block"})
        response = self.api.post(f"/fabrication/api/masks/{self.mask_id}/chip-maps", json=body)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(len(self.store["datasets"]), 1)

    def test_pages_and_access_control(self):
        mask_list = self.api.get("/fabrication/masks/").get_data(as_text=True)
        self.assertIn('data-mask-id=""', mask_list)
        self.assertIn('data-initial-view="masks"', mask_list)
        self.assertIn('data-initial-view="wafers"', self.api.get("/fabrication/").get_data(as_text=True))
        self.assertIn(f'data-mask-id="{self.mask_id}"', self.api.get(f"/fabrication/masks/{self.mask_id}").get_data(as_text=True))
        with self.api.session_transaction() as sess:
            sess["user"] = {**USER, "projects": ["OTHER"]}
        self.assertEqual(self.api.get(f"/fabrication/api/masks?project={P}").status_code, 403)
        self.assertEqual(self.api.get(f"/fabrication/api/masks/{self.mask_id}").status_code, 403)

    def test_wafer_keeps_its_version_and_new_samples_carry_map_metadata(self):
        map_id = self.save_map().get_json()["map"]["dataset_id"]
        wafer_id = self.create_wafer(map_id)
        map_meta = self.store["datasets"][map_id]["scientific_metadata"]
        self.assertTrue(map_meta["locked"])
        self.assertIn((wafer_id, map_id), self.store["sample_datasets"])
        other_wafer = self.create_wafer(map_id, "QCMF_WFR_100")
        self.assertEqual(set(self.api.get(f"/fabrication/api/wafers/{wafer_id}/traveler").get_json()
                             ["chip_map"]["chip_map"]["used_by"]), {wafer_id, other_wafer})
        self.assertEqual(self.store["datasets"][map_id]["scientific_metadata"]["version"], 1)
        traveler = self.api.get(f"/fabrication/api/wafers/{wafer_id}/traveler").get_json()
        self.assertEqual(traveler["chip_map"]["dataset_id"], map_id)
        self.assertEqual(traveler["chip_map"]["chip_map"]["blocks"][0]["name"], "Block one")
        self.assertEqual(traveler["units"][0]["chip_details"], None)

        details = {"WFR99_Block one": {
            "block": "B1", "outline_mm": [0, 0, 24, 7], "mask_design": map_id}}
        response = self.record(wafer_id, "cut_chiplets", [wafer_id], {wafer_id: ["WFR99_Block one"]}, details)
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        chiplet_id = response.get_json()["created"][0]["unique_id"]
        self.assertEqual(self.store["samples"][chiplet_id]["scientific_metadata"], details["WFR99_Block one"])
        traveler = self.api.get(f"/fabrication/api/wafers/{wafer_id}/traveler").get_json()
        chiplet = next(u for u in traveler["units"] if u["unique_id"] == chiplet_id)
        self.assertEqual(chiplet["chip_details"]["block"], "B1")

        chip_details = {
            "WFR99_B1_R1D1": {"chip_id": "chip-1", "block": "B1", "label": "R1D1",
                              "outline_mm": [0, 0, 12, 7], "mask_design": map_id},
            "WFR99_B1_R1D1-2": {"chip_id": "chip-2", "block": "B1", "label": "R1D1",
                                "outline_mm": [12, 0, 24, 7], "mask_design": map_id},
        }
        response = self.record(wafer_id, "dicing", [chiplet_id], {chiplet_id: list(chip_details)}, chip_details)
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        self.assertEqual(len(response.get_json()["created"]), 2)
        for child in response.get_json()["created"]:
            self.assertEqual(self.store["samples"][child["unique_id"]]["scientific_metadata"], chip_details[child["sample_name"]])

        # A later review is another child. The existing traveler still resolves its original map id.
        second_id = self.save_map(expected_version=1).get_json()["map"]["dataset_id"]
        self.assertNotEqual(second_id, map_id)
        self.assertTrue(self.store["datasets"][map_id]["scientific_metadata"]["locked"])
        self.assertFalse(self.store["datasets"][second_id]["scientific_metadata"]["locked"])
        traveler = self.api.get(f"/fabrication/api/wafers/{wafer_id}/traveler").get_json()
        self.assertEqual(traveler["chip_map"]["dataset_id"], map_id)

    def test_child_metadata_and_map_project_are_validated(self):
        map_id = self.save_map().get_json()["map"]["dataset_id"]
        response = self.api.post("/fabrication/api/wafers", json={
            "project": P, "template_id": T, "wafer_name": "Bad", "wafer_options": {"wafer_type": "qubit"},
            "spec": {"mask_design": "D_missing"}})
        self.assertEqual(response.status_code, 404)
        wafer_id = self.create_wafer(map_id, "WFR_valid")
        details = {"C1": {"block": "not-a-block", "outline_mm": [0, 0, 1, 1], "mask_design": map_id}}
        response = self.record(wafer_id, "cut_chiplets", [wafer_id], {wafer_id: ["C1"]}, details)
        self.assertEqual(response.status_code, 400)
        details = {"C1": {"block": "B1", "outline_mm": [0, 0, 0, 1], "mask_design": map_id}}
        response = self.record(wafer_id, "cut_chiplets", [wafer_id], {wafer_id: ["C1"]}, details)
        self.assertEqual(response.status_code, 400)
        details = {"Other": {"block": "B1", "outline_mm": [0, 0, 1, 1], "mask_design": map_id}}
        response = self.record(wafer_id, "cut_chiplets", [wafer_id], {wafer_id: ["C1"]}, details)
        self.assertEqual(response.status_code, 400)


    def test_children_cannot_change_map_block_or_reviewed_geometry(self):
        map_id = self.save_map().get_json()["map"]["dataset_id"]
        other_map = self.api.post("/fabrication/api/masks", json={"project": P, "dataset_name": "Other"})
        other_map_id = other_map.get_json()["mask"]["dataset_id"]
        wafer_id = self.create_wafer(map_id)
        block = {"block": "B1", "outline_mm": [0, 0, 24, 7], "mask_design": map_id}
        response = self.record(wafer_id, "cut_chiplets", [wafer_id], {wafer_id: ["CL1"]}, {"CL1": block})
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        chiplet_id = response.get_json()["created"][0]["unique_id"]
        chip = {"chip_id": "chip-1", "block": "B1", "label": "R1D1",
                "outline_mm": [0, 0, 12, 7], "mask_design": map_id}
        invalid = [
            {**chip, "mask_design": other_map_id},
            {**chip, "chip_id": "chip-3", "block": "B2", "outline_mm": [0, 10, 5, 15]},
            {**chip, "outline_mm": [0, 0, 13, 7]},
            {**chip, "label": "altered"},
            {**chip, "chip_id": "not-a-chip"},
        ]
        for fields in invalid:
            response = self.record(wafer_id, "dicing", [chiplet_id], {chiplet_id: ["C1"]}, {"C1": fields})
            self.assertEqual(response.status_code, 400, response.get_data(as_text=True))
        response = self.record(wafer_id, "dicing", [chiplet_id], {chiplet_id: ["C1"]}, {})
        self.assertEqual(response.status_code, 400)
        self.assertEqual({s["sample_name"] for s in self.store["samples"].values()}, {"QCMF_WFR_99", "CL1"})
        response = self.record(wafer_id, "dicing", [chiplet_id], {chiplet_id: ["C1"]}, {"C1": chip})
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        repeated = self.record(wafer_id, "dicing", [chiplet_id], {chiplet_id: ["C2"]}, {"C2": chip})
        self.assertEqual(repeated.status_code, 400, repeated.get_data(as_text=True))
        self.assertIn("has already been cut", repeated.get_json()["detail"])

    def test_same_map_usage_keeps_both_wafers_after_second_lock(self):
        map_id = self.save_map().get_json()["map"]["dataset_id"]
        one = self.create_wafer(map_id, "WFR_one")
        metadata = dict(self.store["datasets"][map_id]["scientific_metadata"])
        two = self.create_wafer(map_id, "WFR_two")
        self.assertEqual(dict(self.store["datasets"][map_id]["scientific_metadata"]), metadata)
        loaded = self.api.get(f"/fabrication/api/wafers/{one}/traveler").get_json()["chip_map"]["chip_map"]
        self.assertEqual(loaded["used_by"], sorted([one, two]))
        self.assertTrue(loaded["locked"])

    def test_step_zero_stores_planned_chiplets_without_creating_samples(self):
        map_id = self.save_map().get_json()["map"]["dataset_id"]
        bad_spec = self.api.post("/fabrication/api/wafers", json={
            "project": P, "template_id": T, "wafer_name": "bad_plan", "wafer_options": {"wafer_type": "qubit"},
            "spec": {"mask_design": map_id}, "step_date": "2026-11-12",
            "planned_chiplets": [{"block": "B1", "name": "same name"}, {"block": "B1", "name": "same name"}]})
        self.assertEqual(bad_spec.status_code, 400)
        self.assertEqual(len(self.store["samples"]), 0)
        spec = self.api.post("/fabrication/api/wafers", json={
            "project": P, "template_id": T, "wafer_name": "WFR_planned", "wafer_options": {"wafer_type": "qubit"},
            "spec": {"mask_design": map_id}, "step_date": "2026-11-12",
            "planned_chiplets": [{"block": "B1", "name": "planned top"}, {"block": "B2", "name": "planned bottom"}]})
        self.assertEqual(spec.status_code, 200, spec.get_data(as_text=True))
        self.assertEqual(len(self.store["samples"]), 1)
        wafer_id = spec.get_json()["wafer"]["unique_id"]
        expected_plan = {"mask_design": map_id, "chiplets": [
            {"block": "B1", "name": "planned top"}, {"block": "B2", "name": "planned bottom"}]}
        spec_id = spec.get_json()["dataset_id"]
        self.assertEqual(self.store["datasets"][spec_id]["scientific_metadata"]["planned_chiplets"], expected_plan)
        self.assertEqual(self.api.get(f"/fabrication/api/wafers/{wafer_id}/traveler").get_json()["planned_chiplets"], expected_plan)
        self.assertEqual(self.api.get(f"/fabrication/api/chip-maps/{map_id}").get_json()["map"]["dataset_id"], map_id)
        no_reset = self.api.put(f"/fabrication/api/steps/{spec_id}", json={"parameters": {"mask_design": map_id}, "step_date": "2026-11-12"})
        self.assertEqual(no_reset.status_code, 200)
        self.assertEqual(no_reset.get_json()["record"]["planned_chiplets"], expected_plan)

        other_map = self.save_map(expected_version=1).get_json()["map"]["dataset_id"]
        response = self.api.put(f"/fabrication/api/steps/{spec_id}", json={
            "parameters": {"mask_design": other_map}, "step_date": "2026-11-12"})
        self.assertEqual(response.status_code, 400)
        response = self.api.put(f"/fabrication/api/steps/{spec_id}", json={
            "parameters": {"mask_design": other_map}, "step_date": "2026-11-12",
            "planned_chiplets": [{"block": "not-a-block", "name": "bad"}]})
        self.assertEqual(response.status_code, 400)
        response = self.api.put(f"/fabrication/api/steps/{spec_id}", json={
            "parameters": {"mask_design": other_map}, "step_date": "2026-11-12", "planned_chiplets": []})
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.get_json()["record"]["planned_chiplets"])
        self.assertEqual(len(self.store["samples"]), 1)

if __name__ == "__main__":
    unittest.main()
