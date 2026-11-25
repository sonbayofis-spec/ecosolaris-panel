"""Trader payı: tek kaynak (margin.py)."""
import json, os, sys, tempfile, unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import margin, bess


class MarginTest(unittest.TestCase):
    def test_bess_uses_same_constant(self):
        self.assertEqual(bess.SPREAD_EUR, margin.SPREAD_EUR)
        self.assertEqual(margin.SPREAD_EUR, 15.0)

    def test_reads_rate_from_bess_json(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "bess.json"), "w") as f:
                json.dump({"params": {"eur_mdl": 20.1}}, f)
            self.assertAlmostEqual(margin.spread_mdl(d), 15 * 20.1)

    def test_falls_back_when_missing_or_absurd(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertAlmostEqual(margin.spread_mdl(d), 15 * margin.EUR_MDL_FALLBACK)
            with open(os.path.join(d, "bess.json"), "w") as f:
                json.dump({"params": {"eur_mdl": 3.0}}, f)
            self.assertAlmostEqual(margin.spread_mdl(d), 15 * margin.EUR_MDL_FALLBACK)


if __name__ == "__main__":
    unittest.main()
