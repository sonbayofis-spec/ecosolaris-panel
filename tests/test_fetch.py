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


if __name__ == "__main__":
    unittest.main()
