import os
import unittest
from unittest.mock import patch

os.environ.setdefault("CRUCIBLE_API_KEY", "test-api-key")

from routes.shared import publish_barcode, PrinterTimeoutError


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

    def test_unknown_printer_is_rejected_before_calling_api(self):
        with patch("routes.shared.cruc_client.print.barcode") as barcode:
            with self.assertRaises(ValueError):
                publish_barcode("not-a-real-printer", "mfid123", "Sample 1")
        barcode.assert_not_called()


if __name__ == "__main__":
    unittest.main()
