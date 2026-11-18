import json
import os
import unittest
from unittest.mock import patch

import requests

os.environ.setdefault("CRUCIBLE_API_KEY", "test-api-key")

from app import create_app
from routes import uploads

DATASET = "0tqn3vn2xhrbs00069f98s8s94"
FILE = "0tqn3vrnb5zc9000td6rzcetr4"
CRC = "AAAAAA=="


def http_error(status, detail=None, headers=None):
    response = requests.Response()
    response.status_code = status
    response._content = json.dumps({"detail": detail}).encode()
    response.headers.update(headers or {})
    return requests.HTTPError(response=response)


class UploadRoutesTests(unittest.TestCase):
    def setUp(self):
        app = create_app()
        app.config.update(TESTING=True, SECRET_KEY="test")
        self.client = app.test_client()
        uploads._access_cache.clear()
        self.get_dataset = patch("routes.uploads.cruc_client.datasets.get",
                                 return_value={"project_id": "proj-1"}).start()
        self.addCleanup(patch.stopall)

    def login(self, projects=("proj-1",)):
        with self.client.session_transaction() as sess:
            sess["user"] = {"orcid": "0000-0001-2345-6789", "projects": list(projects), "selected_project": projects[0]}

    def initiate(self, **overrides):
        body = {"dataset_mfid": DATASET, "filename": "image.tif", "size": 100, "idempotency_key": "a" * 32, **overrides}
        return self.client.post("/api/uploads/initiate", json=body)

    def test_requires_login(self):
        self.assertEqual(self.initiate().status_code, 401)

    def test_rejects_datasets_outside_the_users_projects(self):
        self.login(projects=("other-project",))
        response = self.initiate()
        self.assertEqual(response.status_code, 403)

    def test_initiate_returns_upload_session(self):
        self.login()
        with patch("routes.uploads.crucible_api.multipart_initiate",
                   return_value={"state": "uploading", "upload_id": "up-1", "part_size": 8388608}) as call:
            response = self.initiate()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"state": "uploading", "upload_id": "up-1", "part_size": 8388608})
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        call.assert_called_once_with(DATASET, "image.tif", 100, "a" * 32)

    def test_initiate_passes_through_deduplicated_file(self):
        self.login()
        with patch("routes.uploads.crucible_api.multipart_initiate",
                   return_value={"state": "completed", "existing_file": {"mfid": FILE}}):
            response = self.initiate()
        self.assertEqual(response.get_json(), {"state": "completed", "file": {"mfid": FILE}})

    def test_initiate_reports_existing_filename(self):
        self.login()
        error = http_error(409, {"code": "filename_exists", "message": "taken", "file_mfid": FILE})
        with patch("routes.uploads.crucible_api.multipart_initiate", side_effect=error):
            response = self.initiate()
        self.assertEqual(response.status_code, 409)
        body = response.get_json()
        self.assertEqual(body["code"], "filename_exists")
        self.assertIn("image.tif already exists", body["error"])
        self.assertFalse(body["retryable"])

    def test_initiate_validates_input(self):
        self.login()
        for overrides in ({"filename": "../x"}, {"filename": "a\\b"}, {"size": 0}, {"size": True}, {"idempotency_key": "x"}):
            with self.subTest(overrides=overrides):
                self.assertEqual(self.initiate(**overrides).status_code, 400)

    def test_upstream_failures_are_retryable_bad_gateway(self):
        self.login()
        with patch("routes.uploads.crucible_api.multipart_initiate",
                   side_effect=http_error(503, "busy", {"Retry-After": "7"})):
            response = self.initiate()
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.get_json(), {"error": "busy", "retryable": True, "retry_after": 7})

    def test_sign_drops_content_length_and_rejects_insecure_urls(self):
        self.login()
        signed = {"parts": [{"part_number": 1, "url": "https://storage.googleapis.com/x",
                             "headers": {"Content-Length": "5", "Host": "storage.googleapis.com", "x-goog-hash": f"crc32c={CRC}"}}]}
        with patch("routes.uploads.crucible_api.multipart_sign_parts", return_value=signed) as call:
            response = self.client.post("/api/uploads/sign", json={
                "dataset_mfid": DATASET, "upload_id": "up-1", "parts": [{"part_number": 1, "crc32c": CRC}]})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["parts"][0]["headers"], {"x-goog-hash": f"crc32c={CRC}"})
        call.assert_called_once_with(DATASET, "up-1", [{"part_number": 1, "crc32c": CRC}])

        signed["parts"][0]["url"] = "http://storage.example/x"
        with patch("routes.uploads.crucible_api.multipart_sign_parts", return_value=signed):
            response = self.client.post("/api/uploads/sign", json={
                "dataset_mfid": DATASET, "upload_id": "up-1", "parts": [{"part_number": 1, "crc32c": CRC}]})
        self.assertEqual(response.status_code, 502)

    def test_sign_limits_parts_per_request(self):
        self.login()
        parts = [{"part_number": n, "crc32c": CRC} for n in range(1, 66)]
        response = self.client.post("/api/uploads/sign", json={"dataset_mfid": DATASET, "upload_id": "up-1", "parts": parts})
        self.assertEqual(response.status_code, 400)

    def test_status_follows_pagination(self):
        self.login()
        pages = [
            {"state": "uploading", "parts": [{"part_number": 1}, {"part_number": 2}], "next_part_number_marker": 2, "part_size": 8},
            {"state": "uploading", "parts": [{"part_number": 3}], "next_part_number_marker": None, "part_size": 8},
        ]
        with patch("routes.uploads.crucible_api.multipart_status_page", side_effect=pages) as call:
            response = self.client.get(f"/api/uploads/status?dataset_mfid={DATASET}&upload_id=up-1")
        self.assertEqual(response.get_json()["acknowledged_part_numbers"], [1, 2, 3])
        self.assertEqual(call.call_args_list[1].args, (DATASET, "up-1", 2))

    def test_complete_validates_checksums(self):
        self.login()
        response = self.client.post("/api/uploads/complete", json={
            "dataset_mfid": DATASET, "upload_id": "up-1", "sha256_hash": "XYZ", "crc32c": CRC})
        self.assertEqual(response.status_code, 400)
        with patch("routes.uploads.crucible_api.multipart_complete", return_value={"mfid": FILE}) as call:
            response = self.client.post("/api/uploads/complete", json={
                "dataset_mfid": DATASET, "upload_id": "up-1", "sha256_hash": "a" * 64, "crc32c": CRC})
        self.assertEqual(response.get_json(), {"mfid": FILE})
        call.assert_called_once_with(DATASET, "up-1", "a" * 64, CRC)

    def test_ingest_passes_choice_through(self):
        self.login()
        with patch("routes.uploads.crucible_api.request_ingestion", return_value={"status": "requested"}) as call:
            self.client.post("/api/uploads/ingest", json={
                "dataset_mfid": DATASET, "file_mfid": FILE, "ingestion_class": "FeiSemTifIngestor"})
            self.client.post("/api/uploads/ingest", json={"dataset_mfid": DATASET, "file_mfid": FILE, "requested": False})
        self.assertEqual(call.call_args_list[0].args, (FILE, True, "FeiSemTifIngestor"))
        self.assertEqual(call.call_args_list[1].args, (FILE, False, None))
        response = self.client.post("/api/uploads/ingest", json={
            "dataset_mfid": DATASET, "file_mfid": FILE, "ingestion_class": "bad class!"})
        self.assertEqual(response.status_code, 400)

    def test_request_ingestion_builds_query(self):
        from routes import crucible_api
        with patch("routes.shared.cruc_client._request", return_value={}) as request:
            crucible_api.request_ingestion(FILE, True, "FeiSemTifIngestor")
            crucible_api.request_ingestion(FILE, True, None)
            crucible_api.request_ingestion(FILE, False, "Ignored")
        self.assertEqual(request.call_args_list[0].args, ("post", f"/files/{FILE}/ingest"))
        self.assertEqual(request.call_args_list[0].kwargs["params"], {"status": "requested", "ingestion_class": "FeiSemTifIngestor"})
        self.assertEqual(request.call_args_list[1].kwargs["params"], {"status": "requested"})
        self.assertEqual(request.call_args_list[2].kwargs["params"], {"status": "not_requested"})
        for call in request.call_args_list:
            self.assertFalse(call.kwargs["retry"])
            self.assertNotIn("json", call.kwargs)


class CrucibleApiWrapperContractTests(unittest.TestCase):
    def test_all_nine_request_wrappers_match_v4_signature_and_wire_contracts(self):
        import inspect
        from crucible.client import CrucibleClient
        from routes import crucible_api

        sig = inspect.signature(CrucibleClient._request)
        recorded = []

        def fake_request(method, endpoint, *args, **kwargs):
            sig.bind(None, method, endpoint, *args, **kwargs)
            recorded.append((method, endpoint, args, kwargs))
            if endpoint == "/print/printers":
                return {"printers": [{"printer_id": "b30-113", "online": True}]}
            return {"ok": True}

        with patch("routes.shared.cruc_client._request", side_effect=fake_request):
            self.assertEqual(crucible_api.list_printers(), [{"printer_id": "b30-113", "online": True}])
            crucible_api.add_scientific_metadata(DATASET, {"temp_c": 20})
            crucible_api.multipart_initiate(DATASET, "scan.tif", 512, "k" * 32)
            crucible_api.multipart_sign_parts(DATASET, "up-1", [{"part_number": 1, "crc32c": CRC}])
            crucible_api.multipart_status_page(DATASET, "up-1", 4)
            crucible_api.multipart_complete(DATASET, "up-1", "a" * 64, CRC)
            crucible_api.multipart_abort(DATASET, "up-1")
            crucible_api.request_ingestion(FILE, True, "GdsChipMapIngestor")
            crucible_api.list_ingestion_requests(DATASET)

        self.assertEqual(len(recorded), 9)
        self.assertEqual(recorded[0], ("get", "/print/printers", (), {}))
        self.assertEqual(recorded[1], ("post", f"/resources/{DATASET}/metadata", (), {"json": {"temp_c": 20}}))
        self.assertEqual(recorded[2], (
            "post", f"/datasets/{DATASET}/upload/multipart/initiate", (),
            {"retry": False, "json": {"filename": "scan.tif", "size": 512}, "headers": {"Idempotency-Key": "k" * 32}},
        ))
        self.assertEqual(recorded[3], (
            "post", f"/datasets/{DATASET}/upload/multipart/up-1/parts", (),
            {"retry": False, "log_body": False, "json": {"parts": [{"part_number": 1, "crc32c": CRC}]}},
        ))
        self.assertEqual(recorded[4], (
            "get", f"/datasets/{DATASET}/upload/multipart/up-1", (),
            {"log_body": False, "params": {"limit": crucible_api.STATUS_PAGE_LIMIT, "part_number_marker": 4}},
        ))
        self.assertEqual(recorded[5], (
            "post", f"/datasets/{DATASET}/upload/multipart/complete", (),
            {"retry": False, "timeout": (10, crucible_api.COMPLETE_TIMEOUT_S),
             "json": {"upload_id": "up-1", "sha256_hash": "a" * 64, "crc32c": CRC}},
        ))
        self.assertEqual(recorded[6], ("delete", f"/datasets/{DATASET}/upload/multipart/up-1", (), {"retry": False}))
        self.assertEqual(recorded[7], (
            "post", f"/files/{FILE}/ingest", (),
            {"retry": False, "params": {"status": "requested", "ingestion_class": "GdsChipMapIngestor"}},
        ))
        self.assertEqual(recorded[8], (
            "get", "/ingestion_requests", (),
            {"params": {"dataset_mfid": DATASET, "limit": 100}},
        ))

    def test_upload_ingest_endpoint_end_to_end_with_fake_crucible(self):
        try:
            from tests import fake_crucible
        except ImportError:
            import fake_crucible
        from crucible import Dataset
        from routes.shared import cruc_client

        store, restore = fake_crucible.install(cruc_client)
        self.addCleanup(restore)
        uploads._access_cache.clear()
        ds_id = cruc_client.datasets.create(
            Dataset(dataset_name="Upload Test", project_id="proj-1")
        )["dataset_mfid"]

        app = create_app()
        app.config.update(TESTING=True, SECRET_KEY="test")
        client = app.test_client()
        with client.session_transaction() as sess:
            sess["user"] = {"orcid": "0000-0001-2345-6789", "projects": ["proj-1"], "selected_project": "proj-1"}

        r1 = client.post("/api/uploads/ingest", json={
            "dataset_mfid": ds_id, "file_mfid": FILE, "ingestion_class": "GdsChipMapIngestor"
        })
        self.assertEqual(r1.status_code, 200, r1.get_data(as_text=True))
        r2 = client.post("/api/uploads/ingest", json={
            "dataset_mfid": ds_id, "file_mfid": FILE, "requested": False, "ingestion_class": "Ignored"
        })
        self.assertEqual(r2.status_code, 200, r2.get_data(as_text=True))
        self.assertEqual(store["file_ingestions"], [
            {"id": store["file_ingestions"][0]["id"], "file_mfid": FILE, "status": "requested", "ingestion_class": "GdsChipMapIngestor"},
            {"id": store["file_ingestions"][1]["id"], "file_mfid": FILE, "status": "not_requested"},
        ])


if __name__ == "__main__":
    unittest.main()
