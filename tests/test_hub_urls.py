import os
import unittest
from unittest.mock import patch

os.environ.setdefault("CRUCIBLE_API_KEY", "test-api-key")

import crucible.config  # noqa: E402
from crucible.errors import RemovedError  # noqa: E402
from routes.synthesis_common import explorer_url  # noqa: E402


class HubUrlContractTests(unittest.TestCase):
    def test_explorer_url_builds_canonical_hub_sample_url(self):
        mfid = "s0000000000000000000000001"
        url = explorer_url("proj-alpha", mfid)
        self.assertEqual(url, f"https://crucible.lbl.gov/hub/samples/{mfid}")
        self.assertNotIn("/explore", url)
        self.assertNotIn("proj-alpha", url)

    def test_explorer_url_honors_crucible_hub_url_env_override(self):
        mfid = "s0000000000000000000000001"
        self.addCleanup(crucible.config.config.reload)
        with patch.dict(os.environ, {"CRUCIBLE_HUB_URL": "https://staging.crucible.example/hub/"}):
            crucible.config.config.reload()
            self.assertEqual(
                explorer_url("any-project", mfid),
                f"https://staging.crucible.example/hub/samples/{mfid}",
            )

    def test_legacy_get_graph_explorer_url_raises_removed_error_in_v4(self):
        with self.assertRaises(RemovedError):
            crucible.config.get_graph_explorer_url()


if __name__ == "__main__":
    unittest.main()
