"""Tahmin doğruluğu: gün kaydı ve arşiv."""
import json, os, sys, tempfile, unittest
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import accuracy


def hours(day, n=24):
    return [f"{day.isoformat()}T{h:02d}:00" for h in range(n)]


class DayRecordTest(unittest.TestCase):
    def setUp(self):
        self.day = date(2026, 11, 12)
        self.obs = {h: 5.0 for h in hours(self.day)}
        self.fc = {"e": {h: 4.0 for h in hours(self.day)}, "i": {h: 3.0 for h in hours(self.day)}, "g": {h: 6.0 for h in hours(self.day)}}

    def test_full_day(self):
        rec, sums = accuracy.day_record(self.day, self.fc, self.obs)
        self.assertEqual(rec["date"], "2026-11-12")
        self.assertEqual((rec["obs"], rec["e"], rec["i"], rec["g"]), (5.0, 4.0, 3.0, 6.0))
        self.assertEqual((rec["mae_e"], rec["mae_i"], rec["mae_g"]), (1.0, 2.0, 1.0))
        self.assertEqual(rec["n_e"], 24)
        self.assertAlmostEqual(sums["e"]["f"] / sums["e"]["o"], 0.8)

    def test_too_few_observations(self):
        obs = {h: 5.0 for h in hours(self.day, 17)}
        self.assertEqual(accuracy.day_record(self.day, self.fc, obs), (None, {}))

    def test_model_with_missing_forecast_is_left_out(self):
        self.fc["i"] = {h: None for h in hours(self.day)}
        rec, sums = accuracy.day_record(self.day, self.fc, self.obs)
        self.assertNotIn("i", rec)
        self.assertNotIn("i", sums)
        self.assertIn("e", rec)


class ArchiveTest(unittest.TestCase):
    def test_archive_grows_and_keeps_old_days(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "accuracy", "days.json")
            self.assertTrue(accuracy.update_archive([{"date": "2026-11-11", "obs": 4.0, "e": 3.5}], path))
            self.assertTrue(accuracy.update_archive([{"date": "2026-11-12", "obs": 5.0, "e": 4.0}], path))
            self.assertFalse(accuracy.update_archive([{"date": "2026-11-12", "obs": 5.0, "e": 4.0}], path))
            arc = json.load(open(path, encoding="utf-8"))
            self.assertEqual(list(arc), ["2026-11-11", "2026-11-12"])
            self.assertEqual(arc["2026-11-11"]["e"], 3.5)
            self.assertNotIn("date", arc["2026-11-12"])


if __name__ == "__main__":
    unittest.main()
