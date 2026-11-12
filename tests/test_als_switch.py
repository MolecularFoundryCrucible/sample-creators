import os
import unittest
from unittest.mock import patch

os.environ.setdefault("CRUCIBLE_API_KEY", "test-api-key")

from routes import als_shared


class AlsSwitchTests(unittest.TestCase):
    def test_disabled_tracker_refuses_calls(self):
        with patch.object(als_shared, "ALS_SAMPLE_TRACKER_ENABLED", False):
            with self.assertRaisesRegex(RuntimeError, "turned off"):
                als_shared._LazySampleTrackerClient().sample_create


if __name__ == "__main__":
    unittest.main()
