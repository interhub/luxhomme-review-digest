import json
import os
import sys
import tempfile
import threading
import unittest
from datetime import date
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from review_digest import analyze, digest, llm, sources, store  # noqa: E402

CSV = ROOT / "data" / "reviews.csv"
WEEK = date(2026, 10, 5)


def labelled_db(provider="mock"):
    conn = store.connect(":memory:")
    reviews, _ = sources.load_csv(str(CSV), 2026)
    store.add_reviews(conn, reviews)
    analyze.run(conn, provider=provider)
    return conn


class Validation(unittest.TestCase):
    ids = ["a", "b"]

    def ok(self, rid, themes=None, conf=0.9):
        return {"id": rid, "themes": [{"theme": "noise", "sentiment": "neg"}] if themes is None else themes, "confidence": conf}

    def test_accepts_valid(self):
        out = analyze.validate_batch({"results": [self.ok("a"), self.ok("b")]}, self.ids)
        self.assertEqual(set(out), {"a", "b"})

    def test_rejects_bad_output(self):
        bad = [
            {"results": [self.ok("a")]},                                          # missing id
            {"results": [self.ok("a"), self.ok("a"), self.ok("b")]},              # duplicate id
            {"results": [self.ok("a"), self.ok("zzz")]},                          # id the model invented
            {"results": [self.ok("a"), self.ok("b", [{"theme": "weather", "sentiment": "neg"}])]},
            {"results": [self.ok("a"), self.ok("b", [{"theme": "noise", "sentiment": "angry"}])]},
            {"results": [self.ok("a"), self.ok("b", conf=1.7)]},
            {"results": [self.ok("a"), self.ok("b", themes=[])]},
            {"oops": []},
        ]
        for parsed in bad:
            with self.assertRaises(ValueError, msg=str(parsed)):
                analyze.validate_batch(parsed, self.ids)

    def test_json_in_code_fence(self):
        raw = 'Вот ответ:\n```json\n{"results": []}\n```'
        self.assertEqual(llm.extract_json(raw), {"results": []})


class Flags(unittest.TestCase):
    def test_sarcasm_goes_to_human(self):
        res = {"themes": [{"theme": "perf", "sentiment": "neg"}], "confidence": 0.9}
        self.assertIn("rating_mismatch", analyze.flags_for({"rating": 5}, res))
        self.assertEqual(analyze.flags_for({"rating": 1}, res), [])

    def test_low_confidence(self):
        res = {"themes": [{"theme": "perf", "sentiment": "pos"}], "confidence": 0.4}
        self.assertIn("low_confidence", analyze.flags_for({"rating": 4}, res))


class Ingest(unittest.TestCase):
    def test_reimport_adds_nothing(self):
        conn = store.connect(":memory:")
        reviews, _ = sources.load_csv(str(CSV), 2026)
        self.assertEqual(store.add_reviews(conn, reviews), 48)
        self.assertEqual(store.add_reviews(conn, reviews), 0)

    def test_bad_rows_are_reported_not_dropped_silently(self):
        with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, encoding="utf-8") as f:
            f.write("date,sku,rating,text\n06.10,AF-5501,5,Готовит быстро\n07.10,AF-5501,9,плохо\nxx,AF,3,текст\n08.10,AF,4,\n")
        reviews, skipped = sources.load_csv(f.name, 2026)
        os.unlink(f.name)
        self.assertEqual(len(reviews), 1)
        self.assertEqual(reviews[0]["date"], "2026-10-06")
        self.assertEqual(len(skipped), 3)

    def test_pending_only_new(self):
        conn = labelled_db()
        self.assertEqual(store.pending(conn), [])


class Digest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.conn = labelled_db("replay")
        cls.data, cls.text = digest.make(cls.conn, WEEK)

    def test_numbers_come_from_data(self):
        self.assertEqual((self.data["total"], self.data["prev_total"]), (28, 20))
        self.assertEqual(self.data["avg"], 3.1)

    def test_every_quote_is_verbatim(self):
        texts = {r["id"]: r["text"] for r in store.analyzed_reviews(self.conn)}
        quotes = [q for section in ("complaints", "praise") for item in self.data[section] for q in item["quotes"]]
        self.assertTrue(quotes)
        for q in quotes:
            self.assertTrue(texts[q["id"]].startswith(q["text"].rstrip("…")), q)

    def test_fits_telegram(self):
        self.assertLessEqual(len(self.text), 4096)

    def test_html_is_escaped(self):
        rows = store.analyzed_reviews(self.conn)
        rows[-1] = dict(rows[-1], text="<b>hack</b> & co", date="2026-10-11",
                        themes=[{"theme": "noise", "sentiment": "neg"}], rating=1)
        data = digest.build(rows, WEEK)
        self.assertNotIn("<b>hack</b>", digest.render(data))

    def test_week_boundaries(self):
        self.assertEqual(digest.week_of(date(2026, 10, 11)), date(2026, 10, 5))
        self.assertEqual(digest.last_full_week(date(2026, 10, 15)), date(2026, 10, 5))

    def test_empty_week(self):
        text = digest.render(digest.build([], WEEK))
        self.assertIn("нет", text)

    def test_empty_week_still_reports_failures(self):
        self.assertIn("сбоя модели: 3", digest.render(digest.build([], WEEK, unanalyzed=3)))

    def test_counts_per_theme(self):
        by = {b["theme"]: b for b in self.data["by_theme"]}
        self.assertEqual((by["noise"]["total"], by["noise"]["neg"]), (7, 6))
        self.assertEqual(by["durability"]["neg"], 5)
        self.assertIn("Отзывов по темам", self.text)

    def test_spam_does_not_move_average(self):
        rows = [r for r in store.analyzed_reviews(self.conn) if r["id"] != "9474c516"]
        self.assertEqual(digest.build(rows, WEEK)["avg"], self.data["avg"])

    def test_sku_is_escaped(self):
        rows = store.analyzed_reviews(self.conn)
        rows[-1] = dict(rows[-1], sku="A&B<1>", date="2026-10-11", rating=1,
                        themes=[{"theme": "noise", "sentiment": "neg"}])
        self.assertNotIn("A&B<1>", digest.render(digest.build(rows, WEEK)))

    def test_unanalyzed_counted_per_week(self):
        conn = store.connect(":memory:")
        reviews, _ = sources.load_csv(str(CSV), 2026)
        store.add_reviews(conn, reviews)
        self.assertEqual(store.count_unanalyzed(conn, "2026-10-05", "2026-10-12"), 28)
        self.assertEqual(store.count_unanalyzed(conn, "2026-09-28", "2026-10-05"), 20)

    def test_week_is_not_sent_twice(self):
        conn = store.connect(":memory:")
        self.assertFalse(store.week_already_sent(conn, "2026-10-05"))
        conn.execute("INSERT INTO runs (week_start, text, created_at, sent_at) VALUES ('2026-10-05','x','t','t')")
        self.assertTrue(store.week_already_sent(conn, "2026-10-05"))


class FakeAnthropic(BaseHTTPRequestHandler):
    seen = {}

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["content-length"])))
        FakeAnthropic.seen = {"path": self.path, "key": self.headers["x-api-key"], "body": body}
        out = json.dumps({"content": [{"type": "text", "text": '{"results": []}'}]}).encode()
        self.send_response(200)
        self.send_header("content-length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *args):
        pass


class AnthropicProvider(unittest.TestCase):
    def test_request_shape(self):
        server = HTTPServer(("127.0.0.1", 0), FakeAnthropic)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        os.environ.update(ANTHROPIC_API_KEY="test-key", ANTHROPIC_BASE_URL=f"http://127.0.0.1:{server.server_port}")
        try:
            raw = llm.complete("sys", "usr", "anthropic")
        finally:
            server.shutdown()
            del os.environ["ANTHROPIC_API_KEY"], os.environ["ANTHROPIC_BASE_URL"]
        self.assertEqual(raw, '{"results": []}')
        seen = FakeAnthropic.seen
        self.assertEqual((seen["path"], seen["key"]), ("/v1/messages", "test-key"))
        self.assertEqual(seen["body"]["system"], "sys")
        self.assertEqual(seen["body"]["messages"], [{"role": "user", "content": "usr"}])


if __name__ == "__main__":
    unittest.main()
