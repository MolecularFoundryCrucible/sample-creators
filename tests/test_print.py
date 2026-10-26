import os
import unittest
from unittest.mock import patch

os.environ.setdefault("CRUCIBLE_API_KEY", "test-api-key")

from app import create_app
from routes.shared import publish_barcode, list_printers, PrinterTimeoutError


class PublishBarcodeTests(unittest.TestCase):
    def test_ok_status_returns_result(self):
        result = {"job_id": "abc", "status": "ok", "detail": None}
        with patch("routes.shared.cruc_client.print.barcode", return_value=result) as barcode:
            returned = publish_barcode("crucible-printer/b30-113", "mfid123", "Sample 1")

        self.assertEqual(returned, result)
        barcode.assert_called_once_with(printer_id="b30-113", mfid="mfid123", name="Sample 1")

    def test_timeout_status_raises_printer_timeout_error(self):
        result = {"job_id": "abc", "status": "timeout", "detail": "printer offline"}
        with patch("routes.shared.cruc_client.print.barcode", return_value=result):
            with self.assertRaises(PrinterTimeoutError) as ctx:
                publish_barcode("b30-113", "mfid123", "Sample 1")
        self.assertIn("printer offline", str(ctx.exception))

    def test_error_status_raises_runtime_error(self):
        result = {"job_id": "abc", "status": "error", "detail": "printer jammed"}
        with patch("routes.shared.cruc_client.print.barcode", return_value=result):
            with self.assertRaises(RuntimeError) as ctx:
                publish_barcode("b30-113", "mfid123", "Sample 1")
        self.assertNotIsInstance(ctx.exception, PrinterTimeoutError)
        self.assertIn("printer jammed", str(ctx.exception))

    def test_unknown_but_well_formed_printer_is_not_rejected_locally(self):
        # No local allowlist anymore -- an unrecognized printer_id is crucible-api's call
        # to make (it'll come back as a timeout/error from the real printer), not ours.
        result = {"job_id": "abc", "status": "ok", "detail": None}
        with patch("routes.shared.cruc_client.print.barcode", return_value=result) as barcode:
            publish_barcode("not-a-real-printer", "mfid123", "Sample 1")
        barcode.assert_called_once_with(printer_id="not-a-real-printer", mfid="mfid123", name="Sample 1")

    def test_malformed_printer_id_is_rejected_before_calling_api(self):
        with patch("routes.shared.cruc_client.print.barcode") as barcode:
            with self.assertRaises(ValueError):
                publish_barcode("weird/printer", "mfid123", "Sample 1")
        barcode.assert_not_called()


class ListPrintersTests(unittest.TestCase):
    def test_returns_printers_list_from_response(self):
        response = {"printers": [{"printer_id": "b30-113", "online": True, "ts": 123.0}]}
        with patch("routes.shared.cruc_client._request", return_value=response) as request:
            result = list_printers()

        self.assertEqual(result, response["printers"])
        request.assert_called_once_with("get", "/print/printers")


class PrintersEndpointTests(unittest.TestCase):
    def setUp(self):
        app = create_app()
        app.config.update(TESTING=True, SECRET_KEY="test")
        self.client = app.test_client()

    def test_printers_endpoint_does_not_require_login(self):
        response = {"printers": [{"printer_id": "spinbot", "online": False, "ts": None}]}
        with patch("routes.shared.cruc_client._request", return_value=response):
            res = self.client.get("/print/api/printers")

        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json(), response)


if __name__ == "__main__":
    unittest.main()
