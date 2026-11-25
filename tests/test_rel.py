"""Normal güne göre fark metni: yön açık yazılır (yüzde, 'fark' değil 'oran' diye okunmasın)."""
import os, sys, unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import telegram_report as t

F = lambda v, d=0: str(int(round(v)))


class RelTest(unittest.TestCase):
    def test_lower(self):
        self.assertEqual(t.rel_vs_normal(t.L["tr"], "Kasım", 0.40, F), "Kasım ayı normal üretiminden %60 az")
        self.assertEqual(t.rel_vs_normal(t.L["en"], "November", 0.40, F), "60% below normal November output")

    def test_higher_and_equal(self):
        self.assertEqual(t.rel_vs_normal(t.L["tr"], "Kasım", 1.10, F), "Kasım ayı normal üretiminden %10 fazla")
        self.assertEqual(t.rel_vs_normal(t.L["tr"], "Kasım", 1.01, F), "Kasım ayı normal üretimi düzeyinde")
        self.assertIn("sub producția", t.rel_vs_normal(t.L["ro"], "noiembrie", 0.5, F))


if __name__ == "__main__":
    unittest.main()
