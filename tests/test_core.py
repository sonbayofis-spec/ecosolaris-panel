"""Ecosolaris Python birim testleri (yalnızca standart kütüphane).

Çalıştırma:  python -m unittest discover -s tests -v
Ağ gerekmez; Open-Meteo/OPEM yanıtları tests/fixtures altındaki kayıtlardan ya da sahte verilerden gelir.
"""
import contextlib, io, json, math, os, sys, tempfile, unittest
from datetime import datetime
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import monitor
import prices
import telegram_report as tr
import tracking as tk


def jload(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def jdump(obj, path):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f)


def write(path, text):
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def fixture():
    return jload(os.path.join(HERE, "fixtures", "open_meteo.json"))["hourly"]


def expected():
    return jload(os.path.join(HERE, "fixtures", "expected.json"))


class PowerCurve(unittest.TestCase):
    def test_edges(self):
        self.assertEqual(tr.pw(0), 0)
        self.assertEqual(tr.pw(3.4), 0)          # başlama eşiğinin altı
        self.assertEqual(tr.pw(25.1), 0)         # durma eşiğinin üstü
        self.assertEqual(tr.pw(None), 0)

    def test_known_points(self):
        self.assertAlmostEqual(tr.pw(8.0), 885, places=3)
        self.assertAlmostEqual(tr.pw(12.5), 2000, places=3)
        self.assertAlmostEqual(tr.pw(20), 2000, places=3)

    def test_interpolates_and_is_monotonic(self):
        self.assertAlmostEqual(tr.pw(7.25), (601 + 732) / 2, places=3)
        prev = 0
        for i in range(0, 126):
            v = tr.pw(i / 10)
            self.assertGreaterEqual(v, prev - 1e-9, f"{i / 10} m/s'de güç düştü")
            prev = v


class Density(unittest.TestCase):
    def test_colder_air_is_denser(self):
        self.assertGreater(tr.dens_factor(-10), tr.dens_factor(10))
        self.assertGreater(tr.dens_factor(10), tr.dens_factor(30))

    def test_fallbacks_use_fixed_density(self):
        base = (tr.RHO / 1.225) ** (1 / 3)
        self.assertAlmostEqual(tr.dens_factor(None), base)
        self.assertAlmostEqual(tr.dens_factor(99), base)    # saçma sıcaklık
        self.assertAlmostEqual(tr.dens_factor(-99), base)

    def test_plausible_range(self):
        for t in (-20, 0, 15, 35):
            self.assertTrue(0.9 < tr.dens_factor(t) < 1.1, t)


class Profile(unittest.TestCase):
    def test_constant_wind_stays_constant(self):
        u = tr.profile([(10, 6.0), (80, 6.0), (100, 6.0), (120, 6.0), (180, 6.0)])
        for z in (10, 60, 105, 150, 180):
            self.assertAlmostEqual(u(z), 6.0, places=6)

    def test_wind_increases_with_height(self):
        u = tr.profile([(10, 4.0), (80, 6.0), (100, 6.3), (120, 6.5), (180, 7.0)])
        self.assertLess(u(60), u(105))
        self.assertLess(u(105), u(150))
        self.assertAlmostEqual(u(100), 6.3, places=6)


class Compute(unittest.TestCase):
    def test_matches_recorded_fixture(self):
        h, e = fixture(), expected()
        i0 = h["time"].index(e["fixed_now"])
        for m, key in tr.MODELS.items():
            _, kw = tr.compute(h, key)
            got = sum(kw[i0:i0 + 24]) / 1000 * tr.NET
            self.assertAlmostEqual(got, e["models"][m], places=6, msg=f"{m}: hesap kayıttan ayrıştı")

    def test_site_factor_scales_energy(self):
        h = fixture()
        old = tr.SITE
        try:
            tr.SITE = 1.05
            _, lo = tr.compute(h, tr.MODELS["e"])
            tr.SITE = 1.25
            _, hi = tr.compute(h, tr.MODELS["e"])
        finally:
            tr.SITE = old
        self.assertLess(sum(lo), sum(hi))

    def test_output_is_bounded(self):
        _, kw = tr.compute(fixture(), tr.MODELS["e"])
        self.assertTrue(all(0 <= x <= 2000 + 1e-9 for x in kw))

    def test_missing_levels_do_not_crash(self):
        h = {"time": ["2026-10-27T00:00"], "wind_speed_100m_X": [7.0]}  # tek seviye: hesaplanamaz, 0 kW
        hub, kw = tr.compute(h, "X")
        self.assertEqual(kw, [0.0])


class Validation(unittest.TestCase):
    def setUp(self):
        self.h = fixture()
        self.e = tr.MODELS["e"]

    def test_good_data_passes(self):
        tr.validate_hourly(self.h)

    def _bad(self, mutate):
        import copy
        x = copy.deepcopy(self.h)
        mutate(x)
        with self.assertRaises(ValueError):
            tr.validate_hourly(x)

    def test_rejects_garbage(self):
        self._bad(lambda x: x[f"wind_speed_100m_{self.e}"].__setitem__(5, 999))
        self._bad(lambda x: x[f"wind_speed_10m_{self.e}"].__setitem__(3, -4))
        self._bad(lambda x: x[f"temperature_2m_{self.e}"].__setitem__(2, 120))
        self._bad(lambda x: x.__setitem__(f"wind_speed_80m_{self.e}", x[f"wind_speed_80m_{self.e}"][:-5]))
        self._bad(lambda x: x.__setitem__(f"wind_speed_100m_{self.e}",
                                          [None if i % 2 else v for i, v in enumerate(x[f"wind_speed_100m_{self.e}"])]))
        self._bad(lambda x: [x.__setitem__(k, v[:10]) for k, v in list(x.items())])


class ActualFile(unittest.TestCase):
    def read(self, text):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "actual.csv")
            write(p, text)
            return tk.read_actual(p)

    def test_hourly_comma(self):
        out, skipped = self.read("# yorum\nsaat,kwh\n2026-11-02 14:00,812.5\n2026-11-02 15:00,900\n")
        self.assertEqual(out, {("2026-11-02", "14"): 812.5, ("2026-11-02", "15"): 900.0})
        self.assertEqual(skipped, 0)

    def test_semicolon_decimal_comma(self):
        out, _ = self.read("saat;kwh\n02.11.2026 14:00;812,5\n")
        self.assertEqual(out, {("2026-11-02", "14"): 812.5})

    def test_quarter_hours_are_summed_and_partial_hours_skipped(self):
        full = "".join(f"2026-11-02 14:{m:02d},100\n" for m in (0, 15, 30, 45))
        partial = "".join(f"2026-11-02 15:{m:02d},100\n" for m in (0, 15, 30))
        out, skipped = self.read("saat,kwh\n" + full + partial)
        self.assertEqual(out, {("2026-11-02", "14"): 400.0})
        self.assertEqual(skipped, 1)

    def test_mwh_header_is_scaled(self):
        out, _ = self.read("saat,MWh\n2026-11-02 14:00,0.8\n")
        self.assertAlmostEqual(out[("2026-11-02", "14")], 800.0)

    def test_garbage_rows_are_ignored(self):
        out, _ = self.read("saat,kwh\nnot a date,5\n2026-11-02 14:00,abc\n2026-11-02 16:00,50\n")
        self.assertEqual(out, {("2026-11-02", "16"): 50.0})

    def test_missing_file(self):
        self.assertEqual(tk.read_actual(os.path.join(tempfile.gettempdir(), "yok_yok_actual.csv")), ({}, 0))


class TrackingStats(unittest.TestCase):
    def test_stats(self):
        s = tk.stats([(100.0, 80.0), (60.0, 80.0)])
        self.assertEqual(s["n"], 2)
        self.assertAlmostEqual(s["bias_kwh"], 0.0)
        self.assertAlmostEqual(s["mae_kwh"], 20.0)
        self.assertAlmostEqual(s["nmae_pct"], 1.0)     # 20 kWh / 2000 kW
        self.assertEqual((s["over_h"], s["under_h"]), (1, 1))
        self.assertIsNone(tk.stats([]))

    def test_end_to_end_with_late_flag_and_reference_cost(self):
        with tempfile.TemporaryDirectory() as d:
            fdir, pdir = os.path.join(d, "forecast"), os.path.join(d, "prices")
            os.makedirs(fdir); os.makedirs(pdir)
            date = "2026-11-02"
            times = [f"{h:02d}:00" for h in range(24)]
            rec = {"issued": "2026-11-01T10:15", "late": True, "delivery": date, "net": 0.92, "times": times,
                   "kw": {"e": [1000.0] * 24, "i": [800.0] * 24, "g": [1200.0] * 24}}
            jdump(rec, os.path.join(fdir, f"{date}.json"))
            jdump([4000.0] * 24, os.path.join(pdir, f"{date}.json"))
            act = os.path.join(d, "actual.csv")
            write(act, "saat,kwh\n" + "".join(f"{date} {t},900\n" for t in times[:10]))
            out = os.path.join(d, "tracking.json")
            argv = ["tracking.py", "--actual", act, "--forecast-dir", fdir, "--price-dir", pdir, "--out", out, "--no-fetch"]
            with mock.patch.object(sys, "argv", argv), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(tk.main(), 0)
            j = jload(out)
            self.assertEqual(j["hours"], 10)
            self.assertEqual(j["late_days"], 1)
            self.assertTrue(j["days"][0]["late"])
            self.assertEqual(j["best"], "e")                    # 920 kWh tahmin, gerçek 900: en yakın
            self.assertAlmostEqual(j["summary"]["e"]["mae_kwh"], 20.0)
            self.assertAlmostEqual(j["summary"]["e"]["bias_pct"], (920 / 900 - 1) * 100, places=1)
            # 10 saat × 0,020 MWh × 4000 MDL/MWh = 800 MDL (hepsi "tahmin fazla")
            self.assertAlmostEqual(j["ref_cost"]["cost_mdl"], 800.0, places=1)
            self.assertAlmostEqual(j["ref_cost"]["over_mdl"], 800.0, places=1)


class PriceFile(unittest.TestCase):
    CSV = ('"PIP si volum tranzactionat pentru ziua de livrare: 2026-10-26"\n\n'
           'Categorie,"Pret [MDL/MWh]","Volum [MWh]"\n"Base (1-24)","4,437.04",801.550\n\n'
           'Interval,"Pret [MDL/MWh]","Volum Total Tranzactionat [MWh]"\n')

    def run_load(self, rows):
        body = self.CSV + "".join(f'{i + 1},"{p:,.2f}",1.000\n' for i, p in enumerate(rows))

        class R(io.BytesIO):
            pass
        with tempfile.TemporaryDirectory() as d, mock.patch.object(tk.urllib.request, "urlopen", return_value=R(body.encode("utf-8"))), \
                contextlib.redirect_stderr(io.StringIO()):
            return tk.load_prices("2026-10-26", d, fetch=True)

    def test_parses_thousand_separators(self):
        rows = [1100.0] + [5111.0] * 22 + [5401.5]
        got = self.run_load(rows)
        self.assertEqual(len(got), 24)
        self.assertEqual(got[0], 1100.0)
        self.assertEqual(got[-1], 5401.5)

    def test_25_hour_day_is_returned_whole(self):
        self.assertEqual(len(self.run_load([4000.0] * 25)), 25)   # saat dilimi geçişi; prices.py atlar

    def test_too_few_rows_is_rejected(self):
        self.assertIsNone(self.run_load([4000.0] * 10))


class PriceStamp(unittest.TestCase):
    P = [4000.0] * 24

    def test_first_run_sets_stamp(self):
        self.assertEqual(prices.updated_stamp(None, {"2026-10-30": self.P}, "2026-10-29T09:52"), "2026-10-29T09:52")

    def test_unchanged_prices_keep_old_stamp(self):
        old = {"updated": "2026-10-29T09:52", "days": {"2026-10-30": self.P}}
        self.assertEqual(prices.updated_stamp(old, {"2026-10-30": self.P}, "2026-10-29T10:20"), "2026-10-29T09:52")

    def test_new_day_updates_stamp(self):
        old = {"updated": "2026-10-29T09:52", "days": {"2026-10-30": self.P}}
        new = {"2026-10-30": self.P, "2026-10-31": self.P}
        self.assertEqual(prices.updated_stamp(old, new, "2026-10-30T09:50"), "2026-10-30T09:50")

    def test_dropped_old_day_is_not_an_update(self):
        old = {"updated": "2026-10-29T09:52", "days": {"2026-10-26": self.P, "2026-10-30": self.P}}
        self.assertEqual(prices.updated_stamp(old, {"2026-10-30": self.P}, "2026-10-30T00:10"), "2026-10-29T09:52")

    def test_changed_price_updates_stamp(self):
        old = {"updated": "2026-10-29T09:52", "days": {"2026-10-30": self.P}}
        self.assertEqual(prices.updated_stamp(old, {"2026-10-30": [4100.0] * 24}, "2026-10-29T11:30"), "2026-10-29T11:30")


class Monitor(unittest.TestCase):
    @staticmethod
    def runs(*concl):
        return [{"id": 100 - i, "conclusion": c} for i, c in enumerate(concl)]

    def test_decisions(self):
        cases = [
            ("failure", self.runs("failure", "success"), "fail"),
            ("failure", self.runs("failure", "failure", "success"), None),     # sorun sürüyor, tekrar uyarma
            ("success", self.runs("success", "failure"), "ok"),                # düzeldi
            ("success", self.runs("success", "success"), None),
            ("failure", self.runs("failure", "cancelled", "failure"), None),   # iptal atlanır
            ("success", self.runs("success", "cancelled", "failure"), "ok"),
            ("failure", self.runs("failure"), "fail"),
        ]
        for concl, rs, want in cases:
            self.assertEqual(monitor.decide(concl, monitor.previous_conclusion(rs, 100)), want, (concl, rs))

    def test_messages(self):
        self.assertIn("başarısız", monitor.text("fail", "Üretim takibi", "http://x"))
        self.assertIn("yeniden", monitor.text("ok", "Üretim takibi", ""))


class TelegramText(unittest.TestCase):
    def setUp(self):
        self.h, self.e = fixture(), expected()
        self.now = datetime.fromisoformat(self.e["fixed_now"])
        self.s = tr.summary(self.h, self.now, 2.50)

    def test_summary_matches_expected_energy(self):
        self.assertAlmostEqual(self.s["e"], self.e["models"]["e"], places=6)
        self.assertLessEqual(self.s["lo"], self.s["e"])
        self.assertGreaterEqual(self.s["hi"], self.s["e"])

    def test_messages_in_all_languages_with_and_without_extras(self):
        extras = {"p10": 8.0, "p50": 11.0, "p90": 15.0, "opem_lei": 7900.0, "opem_avg": 4.2}
        for lang in ("tr", "en", "ro"):
            plain = tr.message(dict(self.s), self.now, lang)
            full = tr.message({**self.s, **extras}, self.now, lang)
            self.assertNotIn("P10", plain)
            self.assertIn("P10", full)
            self.assertIn("OPEM", full)
            self.assertIn("P10", tr.caption({**self.s, **extras}, self.now, lang))
            self.assertNotIn("P10", tr.caption(dict(self.s), self.now, lang))

    def test_card_data_has_optional_lines_only_with_extras(self):
        extras = {"p10": 8.0, "p50": 11.0, "p90": 15.0, "opem_lei": 7900.0, "opem_avg": 4.2}
        self.assertEqual(tr.card_data(dict(self.s), self.now, "tr", 2.5)["t1_s2"], "")
        self.assertIn("P10–P90", tr.card_data({**self.s, **extras}, self.now, "tr", 2.5)["t1_s2"])
        self.assertIn("OPEM", tr.card_data({**self.s, **extras}, self.now, "tr", 2.5)["t2_s2"])


if __name__ == "__main__":
    unittest.main()
