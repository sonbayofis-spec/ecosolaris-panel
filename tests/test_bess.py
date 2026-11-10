"""BESS planı: kısıtlar ve temel davranış."""
import os, sys, unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import bess

CAP = bess.E_MWH * bess.USABLE


class PlanTest(unittest.TestCase):
    def check(self, wind, price):
        c, d = bess.plan(wind, price)
        ec = bess.RTE ** 0.5
        s = 0.0
        for h in range(24):
            self.assertLessEqual(c[h], min(bess.P_MW, wind[h]) + 1e-6, "şarj yalnızca türbinden")
            self.assertLessEqual(wind[h] - c[h] + d[h], bess.LIMIT_MW + 1e-6, "sayaç sınırı")
            self.assertFalse(c[h] > 0 and d[h] > 0, "aynı saatte şarj ve deşarj")
            s += c[h] * ec - d[h] / ec
            self.assertGreaterEqual(s, -1e-6)
            self.assertLessEqual(s, CAP + 1e-6)
        self.assertAlmostEqual(s, 0.0, places=6, msg="gün sonunda batarya boş")
        self.assertLessEqual(sum(c) * ec, CAP + 1e-6, "günde bir çevrim")
        return c, d

    def test_shifts_cheap_to_expensive(self):
        wind = [1.5] * 24
        price = [1000.0] * 12 + [5000.0] * 12
        c, d = self.check(wind, price)
        self.assertAlmostEqual(sum(c[12:]), 0.0)
        self.assertAlmostEqual(sum(d[:12]), 0.0)
        self.assertAlmostEqual(sum(d), CAP * bess.RTE ** 0.5, delta=0.05)
        self.assertGreater(sum((d[h] - c[h]) * price[h] for h in range(24)), 0)

    def test_flat_price_no_action(self):
        c, d = self.check([1.0] * 24, [4000.0] * 24)
        self.assertEqual(sum(c), 0.0)
        self.assertEqual(sum(d), 0.0)

    def test_small_spread_not_worth_losses(self):
        # %12 kayıp: %5 fiyat farkı kaydırmaya değmez
        c, d = self.check([1.0] * 24, [4000.0] * 12 + [4200.0] * 12)
        self.assertEqual(sum(d), 0.0)

    def test_no_wind_no_charge(self):
        c, d = self.check([0.0] * 24, [100.0] * 12 + [9000.0] * 12)
        self.assertEqual(sum(c), 0.0)

    def test_negative_price_hours_are_charged(self):
        wind = [2.0] * 24
        price = [3000.0] * 10 + [-200.0] * 3 + [3000.0] * 11
        c, d = self.check(wind, price)
        self.assertGreater(sum(c[10:13]), 4.0)

    def test_export_limit_binds(self):
        wind = [2.0] * 24
        price = [1000.0] * 23 + [9000.0]
        c, d = self.check(wind, price)
        self.assertAlmostEqual(d[23], bess.LIMIT_MW - 2.0, delta=bess.Q)

    def test_day_plan_totals(self):
        wind = [1.0] * 24
        raw = [2000.0] * 12 + [6000.0] * 12
        r = bess.day_plan("2026-01-01", wind, raw, "opem", 300.0)
        self.assertEqual(r["price"][0], 1700.0)
        self.assertEqual(r["base_mdl"], round(sum(wind[h] * (raw[h] - 300) for h in range(24))))
        self.assertGreater(r["extra_mdl"], 0)
        self.assertLessEqual(r["peak_mw"], bess.LIMIT_MW)


class TelegramTest(unittest.TestCase):
    def setUp(self):
        import bess_telegram
        self.bt = bess_telegram
        self.plan = bess.day_plan("2026-11-11", [1.5] * 24, [1000.0] * 12 + [5000.0] * 12, "est", 300.0)

    def test_spans(self):
        v = [0.0] * 24
        v[0] = v[1] = v[5] = v[23] = 1.0
        self.assertEqual(self.bt.spans(v, "tr"), "00–02, 05–06, 23–00")
        self.assertEqual(self.bt.spans([0.0] * 24, "tr"), "yok")

    def test_caption_all_languages(self):
        for lang in ("tr", "en", "ro"):
            c = self.bt.caption(self.plan, lang)
            self.assertIn("11", c)
            self.assertIn("lei", c)
            self.assertNotIn("{", c)

    def test_card_data_complete(self):
        from datetime import datetime
        for lang in ("tr", "en", "ro"):
            d = self.bt.card_data(self.plan, {"limit_mw": 3.96, "usable": 0.9, "rte": 0.88}, datetime(2026, 11, 10, 7, 30), lang)
            self.assertEqual(len(d["rows"]), 4)
            self.assertNotIn("{", d["foot2"] + d["t1_s"] + d["t2_s"])
            self.assertTrue(d["t2_v"].startswith("+"))


if __name__ == "__main__":
    unittest.main()
