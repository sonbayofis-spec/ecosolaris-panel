"""fetch_json: geçici ağ hatasında yeniden deneme."""
import io, json, os, sys, unittest, urllib.error
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import telegram_report as tr


def ok(payload):
    return io.BytesIO(json.dumps(payload).encode())


class FetchJsonTest(unittest.TestCase):
    def run_with(self, effects, **kw):
        with mock.patch.object(tr.urllib.request, "urlopen", side_effect=effects) as u, mock.patch.object(tr.time, "sleep") as sl:
            try:
                return tr.fetch_json("https://example.test/x", **kw), u.call_count, sl.call_count
            except Exception as e:
                return e, u.call_count, sl.call_count

    def test_success_first_try(self):
        self.assertEqual(self.run_with([ok({"a": 1})]), ({"a": 1}, 1, 0))

    def test_retries_after_timeout(self):
        r, calls, sleeps = self.run_with([urllib.error.URLError("handshake timed out"), ok({"a": 2})])
        self.assertEqual((r, calls, sleeps), ({"a": 2}, 2, 1))

    def test_retries_after_server_error(self):
        e500 = urllib.error.HTTPError("u", 502, "bad gateway", {}, None)
        r, calls, _ = self.run_with([e500, TimeoutError(), ok({"a": 3})])
        self.assertEqual((r, calls), ({"a": 3}, 3))

    def test_gives_up_after_last_try(self):
        r, calls, sleeps = self.run_with([urllib.error.URLError("x")] * 3, tries=3)
        self.assertIsInstance(r, urllib.error.URLError)
        self.assertEqual((calls, sleeps), (3, 2))

    def test_client_error_not_retried(self):
        e400 = urllib.error.HTTPError("u", 400, "bad request", {}, None)
        r, calls, sleeps = self.run_with([e400, ok({})])
        self.assertIsInstance(r, urllib.error.HTTPError)
        self.assertEqual((calls, sleeps), (1, 0))


class LoadForecastTest(unittest.TestCase):
    def setUp(self):
        import tempfile
        from datetime import datetime
        from zoneinfo import ZoneInfo
        self.dir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.dir.name, ".cache", "om.json")
        self.now = datetime(2026, 11, 16, 3, 10, tzinfo=ZoneInfo("Europe/Chisinau"))
        with open(os.path.join(os.path.dirname(__file__), "fixtures", "open_meteo.json"), encoding="utf-8") as f:
            self.h = json.load(f)["hourly"]

    def tearDown(self):
        self.dir.cleanup()

    def test_live_data_is_cached(self):
        with mock.patch.object(tr, "fetch_json", return_value={"hourly": self.h}):
            h, stale = tr.load_forecast(self.now, self.path)
        self.assertIsNone(stale)
        self.assertEqual(json.load(open(self.path, encoding="utf-8"))["saved"], "2026-11-16T03:10+02:00")

    def test_falls_back_to_recent_cache(self):
        from datetime import timedelta
        with mock.patch.object(tr, "fetch_json", return_value={"hourly": self.h}):
            tr.load_forecast(self.now - timedelta(hours=2), self.path)
        err = urllib.error.HTTPError("u", 429, "Too Many Requests", {}, None)
        with mock.patch.object(tr, "fetch_json", side_effect=err):
            h, stale = tr.load_forecast(self.now, self.path)
        self.assertEqual(h["time"], self.h["time"])
        self.assertEqual(f"{stale:%H:%M}", "01:10")

    def test_old_cache_is_refused(self):
        from datetime import timedelta
        with mock.patch.object(tr, "fetch_json", return_value={"hourly": self.h}):
            tr.load_forecast(self.now - timedelta(hours=7), self.path)
        err = urllib.error.HTTPError("u", 429, "Too Many Requests", {}, None)
        with mock.patch.object(tr, "fetch_json", side_effect=err):
            with self.assertRaises(urllib.error.HTTPError):
                tr.load_forecast(self.now, self.path)

    def test_no_cache_raises_original_error(self):
        with mock.patch.object(tr, "fetch_json", side_effect=urllib.error.URLError("timeout")):
            with self.assertRaises(urllib.error.URLError):
                tr.load_forecast(self.now, self.path)

    def test_stale_note_in_texts(self):
        from datetime import datetime
        from zoneinfo import ZoneInfo
        now = datetime.fromisoformat(self.h["time"][30]).replace(tzinfo=ZoneInfo("Europe/Chisinau"))
        s = tr.summary(self.h, now, 2.5)
        s["stale"] = now.replace(hour=1, minute=10)
        for lang in ("tr", "en", "ro"):
            self.assertIn("01:10", tr.caption(s, now, lang))
            self.assertIn("01:10", tr.message(s, now, lang))
        s["stale"] = None
        self.assertNotIn("ℹ️", tr.caption(s, now, "tr"))


if __name__ == "__main__":
    unittest.main()
