import os
import unittest

os.environ.setdefault("CRUCIBLE_API_KEY", "test-api-key")

from routes.b30_sem import _dataset_to_row, _parse_ts as sem_parse_ts
from routes.deposition_common import parse_ts as deposition_parse_ts
from routes.print_only import _parse_ts as print_parse_ts


class NaiveTimestampTests(unittest.TestCase):
    def test_naive_timestamps_are_berkeley_local_time(self):
        for parse in (sem_parse_ts, deposition_parse_ts, print_parse_ts):
            with self.subTest(parse=parse.__module__):
                self.assertEqual(parse("2026-06-18T11:02:18").isoformat(), "2026-06-18T11:02:18-07:00")
                self.assertEqual(parse("2026-01-18T11:02:18").isoformat(), "2026-01-18T11:02:18-08:00")
                self.assertEqual(parse("2026-06-18T11:02:18Z").isoformat(), "2026-06-18T11:02:18+00:00")

    def test_sem_logbook_shows_ingested_acquisition_time_unchanged(self):
        row = _dataset_to_row({"timestamp": "2026-06-18T11:02:18", "scientific_metadata": {}})
        self.assertEqual(row["Date"], "2026-06-18 11:02")

    def test_mixed_naive_and_aware_timestamps_sort(self):
        values = ["2026-06-18T11:02:18", "2026-06-18T12:00:00-07:00", "2026-06-18T20:00:00Z"]  # 13:00 in Berkeley
        ordered = sorted(values, key=sem_parse_ts)
        self.assertEqual(ordered, values)


if __name__ == "__main__":
    unittest.main()
