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
                             "headers": {"Content-Length": "5", "x-goog-hash": f"crc32c={CRC}"}}]}
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
            crucible_api.request_ingestion(FILE, False, "Ignored")
        self.assertEqual(request.call_args_list[0].kwargs["params"], {"status": "requested", "ingestion_class": "FeiSemTifIngestor"})
        self.assertEqual(request.call_args_list[1].kwargs["params"], {"status": "not_requested"})
        self.assertFalse(request.call_args_list[0].kwargs["retry"])


if __name__ == "__main__":
    unittest.main()
