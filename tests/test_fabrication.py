"""End-to-end checks of the /fabrication/api routes against an in-memory Crucible.

Ported from manual-synthesis-ui backend/tests/test_fabrication.py (c25ae5c). Step file uploads
now go through /api/uploads (tested in test_uploads.py), so those checks became a check that
attached files are listed with download links.
"""
import os
import unittest

os.environ.setdefault("CRUCIBLE_API_KEY", "test-api-key")

import fake_crucible  # noqa: E402
from app import create_app  # noqa: E402
from routes import fab_templates  # noqa: E402
from routes.shared import cruc_client  # noqa: E402

P, T = "QCMF_TEST", "QCMF_Qubit_v1"
USER = {"orcid": "0000-0001", "user_name": "Tim", "projects": [P], "selected_project": P}


class TravelerEndToEndTests(unittest.TestCase):
    def setUp(self):
        self.store, restore = fake_crucible.install(cruc_client)
        self.addCleanup(restore)
        app = create_app()
        app.config.update(TESTING=True, SECRET_KEY="test")
        self.api = app.test_client()
        with self.api.session_transaction() as sess:
            sess["user"] = dict(USER)
        self.failures = []

    def check(self, name, cond):
        if not cond:
            self.failures.append(name)

    def step(self, wafer_id, step_id, targets, status="done", rows=None, new_children=None):
        body = {"project": P, "template_id": T, "step_id": step_id, "wafer_id": wafer_id, "target_ids": targets,
                "status": status, "step_date": "2026-11-10", "rows": rows or {}, "comments": "c",
                "new_children": new_children or {}, "template_default": "standard"}
        return self.api.post("/fabrication/api/steps", json=body)

    @staticmethod
    def fields(step_def, row_key):
        return {f["key"]: f for f in next(r for r in step_def["rows"] if r["key"] == row_key)["fields"]}

    def test_requires_login_and_project_membership(self):
        with self.api.session_transaction() as sess:
            sess.pop("user")
        self.assertEqual(self.api.get(f"/fabrication/api/wafers?project={P}").status_code, 401)
        with self.api.session_transaction() as sess:
            sess["user"] = {**USER, "projects": ["OTHER"]}
        r = self.api.get(f"/fabrication/api/wafers?project={P}")
        self.assertEqual(r.status_code, 403)
        self.assertIn("detail", r.get_json())

    def test_validation_errors_are_422_with_detail(self):
        r = self.api.post("/fabrication/api/wafers", json={"project": P})
        self.assertEqual(r.status_code, 422)
        self.assertIsInstance(r.get_json()["detail"], list)

    def test_traveler_end_to_end(self):
        api, store, check, step, fields = self.api, self.store, self.check, self.step, self.fields
        check("templates listed", T in api.get("/fabrication/api/templates").get_json()["templates"])

        r = api.post("/fabrication/api/wafers", json={"project": P, "template_id": T, "wafer_name": "QCMF_WFR_99",
                                                     "wafer_options": {"wafer_type": "qubit"},
                                                     "spec": {"batch_number": "B7", "base_metal": "Al"}})
        check("wafer created", r.status_code == 200)
        wid = r.get_json()["wafer"]["unique_id"]
        check("wafer owner comes from the session", store["samples"][wid]["sample_name"] == "QCMF_WFR_99")
        check("duplicate wafer name -> 409", api.post("/fabrication/api/wafers", json={
            "project": P, "template_id": T, "wafer_name": "QCMF_WFR_99", "wafer_options": {"wafer_type": "qubit"}}).status_code == 409)
        check("invalid wafer type -> 400", api.post("/fabrication/api/wafers", json={
            "project": P, "template_id": T, "wafer_name": "X", "wafer_options": {"wafer_type": "prod"}}).status_code == 400)

        trav = api.get(f"/fabrication/api/wafers/{wid}/traveler").get_json()
        labels = {s["label"]: s for s in trav["steps"]}
        check("qubit variants only", "Step 1A" in labels and "Step 1B" not in labels and "Step 10B" not in labels)
        check("3A/3B/8A/8B/9 all available and optional",
              all(labels[l]["optional"] for l in ["Step 3A", "Step 3B", "Step 8A", "Step 8B", "Step 9"]))
        check("renamed deposition steps", labels["Step 3A"]["name"] == "E-beam evaporation"
              and labels["Step 3B"]["name"] == "Sputtering")
        check("chiplets are Step 14, post clean Step 21", labels["Step 14"]["id"] == "cut_chiplets"
              and labels["Step 21"]["id"] == "jj_post_clean" and "Step 13b" not in labels)
        check("file uploads on every step", all(st.get("allow_files") for st in labels.values()))
        check("split times", {"strike_time_s", "etch_time_s"} <= set(fields(labels["Step 7"], "o2_descum"))
              and {"strike_time_s", "etch_time_s"} <= set(fields(labels["Step 15"], "o2_descum"))
              and {"etch1_time_s", "etch2_time_s"} <= set(fields(labels["Step 9"], "trench_etch")))
        check("liftoff NMP time in minutes", fields(labels["Step 20"], "nmp_1_hotplate")["time_min"]["default"] == 120)
        check("rows carry their own units", fields(labels["Step 1A"], "diw_rinse")["time_s"]["unit"] == "s"
              and fields(labels["Step 1A"], "rca_1_clean")["time_min"]["unit"] == "min")
        check("every sub-step has a comment field", all(
            any(f["key"] == "comment" for f in r["fields"]) for st in labels.values() for r in st["rows"]))
        check("sheet comment kept as default", fields(labels["Step 1A"], "rca_1_clean")["comment"]["default"].startswith("20ml"))
        check("comment on a row that had none", step(wid, "jj_development", [wid],
              rows={"ipa": {"comment": "used fresh IPA"}}).status_code == 200)
        check("RT became 20 C", fields(labels["Step 2"], "boe_dip")["temp_c"]["default"] == 20)
        check("base metal stored as spec", trav["spec"]["base_metal"] == "Al")

        check("template default stored and served", trav["template_default"] == "standard"
              and "standard" in trav["template_defaults"])
        check("unknown template default on wafer -> 400", api.post("/fabrication/api/wafers", json={
            "project": P, "template_id": T, "wafer_name": "QCMF_WFR_X", "wafer_options": {"wafer_type": "qubit"},
            "template_default": "nope"}).status_code == 400)
        body = {"project": P, "template_id": T, "step_id": "exposure", "wafer_id": wid, "target_ids": [wid],
                "status": "done", "step_date": "2026-11-11", "rows": {}, "template_default": "nope"}
        check("unknown template default on step -> 400", api.post("/fabrication/api/steps", json=body).status_code == 400)

        fab_templates.QCMF_QUBIT_V1_DEFAULTS["typo"] = {"name": "Typo", "overrides": {"rca_clean": {"rca_1_clean": {"temperature": 1}}}}
        try:
            fab_templates.check_template_defaults(T)
            check("bad override caught at import", False)
        except ValueError as err:
            check("bad override caught at import", "rca_clean.rca_1_clean.temperature" in str(err))
        finally:
            del fab_templates.QCMF_QUBIT_V1_DEFAULTS["typo"]

        r = step(wid, "rca_clean", [wid], rows={"rca_1_clean": {"temp_c": "90", "time_min": 20, "tool": "Hotplate"},
                                               "diw_rinse": {"temp_c": 20, "time_s": "20"}})
        check("record step 1A", r.status_code == 200 and r.get_json()["success"])
        ds_id = r.get_json()["dataset_id"]
        meta = store["datasets"][ds_id]["scientific_metadata"]
        check("operator comes from the session", meta["operator"] == "Tim")
        check("template default recorded on the step", meta["template_default"] == "standard")
        check("rows stored in template order", [r["key"] for r in meta["rows"]]
              == ["rca_1_clean", "diw_beaker_1", "diw_beaker_2", "diw_rinse", "n2_blow_dry"])
        check("flat searchable values, numbers parsed", meta["values"] == {
              "rca_1_clean_temp_c": 90, "rca_1_clean_time_min": 20, "rca_1_clean_tool": "Hotplate",
              "diw_rinse_temp_c": 20, "diw_rinse_time_s": 20} and meta["fab_step_id"] == "rca_clean")

        r = step(wid, "native_oxide_removal", [wid], rows={"boe_dip": {"time_min": "1.5", "chemistry": "7:1 mixture"}})
        m2 = store["datasets"][r.get_json()["dataset_id"]]["scientific_metadata"]
        check("text + decimal values saved", m2["values"]["boe_dip_time_min"] == 1.5 and m2["values"]["boe_dip_chemistry"] == "7:1 mixture")
        check("unknown row -> 400", step(wid, "native_oxide_removal", [wid], rows={"nope": {"temp_c": 1}}).status_code == 400)
        check("unknown field -> 400", step(wid, "native_oxide_removal", [wid], rows={"boe_dip": {"rpm": 1}}).status_code == 400)
        step2_id = r.get_json()["dataset_id"]

        check("both 3A and 3B can be recorded", step(wid, "ebeam_evaporation", [wid]).status_code == 200
              and step(wid, "sputtering", [wid]).status_code == 200)
        check("bad number -> 400", step(wid, "exposure", [wid], rows={"expose": {"dose_mj_cm2": "lots"}}).status_code == 400)
        check("bad number in another row -> 400", step(wid, "exposure", [wid], rows={"expose": {"defocus": "x"}}).status_code == 400)
        check("skip required -> 400", step(wid, "exposure", [wid], status="skipped").status_code == 400)
        check("skip optional ok", step(wid, "wafer_trench", [wid], status="skipped").status_code == 200)
        check("foreign target -> 400", step(wid, "exposure", ["S_nope"]).status_code == 400)

        # View + edit in place
        rec = api.get(f"/fabrication/api/steps/{ds_id}").get_json()
        check("view record", rec["record"]["values"]["rca_1_clean_time_min"] == 20 and rec["files"] == [])
        edit = {"step_date": "2026-11-09", "rows": {"rca_1_clean": {"temp_c": 85, "time_min": 25}}, "comments": "fixed typo"}
        r = api.put(f"/fabrication/api/steps/{ds_id}", json=edit)
        m3 = store["datasets"][ds_id]["scientific_metadata"]
        check("edit overwrites in place", r.status_code == 200 and m3["values"]["rca_1_clean_time_min"] == 25
              and m3["step_date"] == "2026-11-09" and m3["edited_by"] == "Tim" and m3["operator"] == "Tim"
              and m3["fab_step_id"] == "rca_clean")
        store["can_edit"] = False
        r = api.put(f"/fabrication/api/steps/{ds_id}", json=edit)
        check("edit without permission -> clear 403", r.status_code == 403 and "edit permission" in r.get_json()["detail"])
        store["can_edit"] = True
        check("edit unknown record -> 404", api.put("/fabrication/api/steps/D_nope", json=edit).status_code == 404)

        # Files attached through /api/uploads are listed with download links
        store["files"][step2_id] = [{"mfid": "F1", "filename": "boe_recipe.txt", "size": 14}]
        files = api.get(f"/fabrication/api/steps/{step2_id}").get_json()["files"]
        check("files listed with links", files[0]["filename"] == "boe_recipe.txt" and files[0]["url"].endswith("boe_recipe.txt"))

        # Chiplets, dicing, multi-target steps
        r = step(wid, "cut_chiplets", [wid], new_children={wid: ["WFR99_CL01", "WFR99_CL02"]})
        check("chiplets created", r.status_code == 200 and len(r.get_json()["created"]) == 2)
        cl = [c["unique_id"] for c in r.get_json()["created"]]
        check("re-cut wafer -> 400", step(wid, "cut_chiplets", [wid], new_children={wid: ["CLX"]}).status_code == 400)
        check("dup child names -> 400", step(wid, "dicing", cl, new_children={cl[0]: ["A", "A"]}).status_code == 400)
        r = step(wid, "jj_deposition", cl, rows={"oxidation": {"time_s": 600, "pressure_torr": 12}})
        check("step on both chiplets", r.status_code == 200
              and {(c, r.get_json()["dataset_id"]) for c in cl} <= set(store["sample_datasets"]))
        r = step(wid, "dicing", cl, new_children={cl[0]: ["CL01_C01", "CL01_C02"], cl[1]: ["CL02_C01"]})
        check("chips created under chiplets", r.status_code == 200 and len(r.get_json()["created"]) == 3)

        trav = api.get(f"/fabrication/api/wafers/{wid}/traveler").get_json()
        check("3-level tree", sorted(u["sample_type"] for u in trav["units"]) == ["chip"] * 3 + ["chiplet"] * 2 + ["wafer"])
        st = {s["id"]: s for s in trav["steps"]}
        check("statuses + edits visible", st["rca_clean"]["status"] == "done" and st["wafer_trench"]["status"] == "skipped"
              and st["development"]["status"] == "pending" and st["rca_clean"]["records"][0]["edited_by"] == "Tim")

        leaves = [u["unique_id"] for u in trav["units"] if u["is_leaf"]]
        store["fail_link"] = {leaves[-1]}
        r = step(wid, "jj_liftoff", leaves, rows={"nmp_1_hotplate": {"time_min": 90}})
        check("partial link failure reported", r.status_code == 200 and not r.get_json()["success"] and len(r.get_json()["errors"]) == 1)
        store["fail_link"] = set()

        # Printing
        check("printers listed", api.get("/fabrication/api/printers").get_json()["printers"][0]["printer_id"] == "b30-113")
        check("bad printer id -> 400", api.post("/fabrication/api/print", json={"printer_id": "a/b#", "sample_id": wid}).status_code == 400)
        r = api.post("/fabrication/api/print", json={"printer_id": "b30-113", "sample_id": wid})
        check("print ok", r.get_json()["success"] and store["prints"][-1] == ("b30-113", wid, "QCMF_WFR_99"))
        store["print_result"] = {"status": "timeout", "detail": "Printer b30-113 appears offline"}
        r = api.post("/fabrication/api/print", json={"printer_id": "b30-113", "sample_id": wid})
        check("print timeout surfaced", not r.get_json()["success"] and "offline" in r.get_json()["detail"])

        check("synthesis fields still served", "Perovskites_10k" in api.get("/synthesis/api/fields").get_json()["categories"])

        self.assertEqual(self.failures, [])


if __name__ == "__main__":
    unittest.main()
