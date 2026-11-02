"""Serving subscribers: one failure must not stop the others, and nothing secret is printed or logged."""
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import bot.publish as P

SUBS = {"1": {"chat_id": "1", "first_name": "One", "state": "ready", "profile": {}},
        "2": {"chat_id": "2", "first_name": "Two", "state": "ready", "profile": {}},
        "3": {"chat_id": "3", "first_name": "Three", "state": "onboarding"}}


class PublishTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        (self.dir / "timeline.json").write_text(json.dumps({"title": "t", "moments": []}))
        self.events = []
        patches = [mock.patch.object(P.store, "load", lambda: SUBS),
                   mock.patch.object(P.store, "allowed", lambda cid: cid != "2b"),
                   mock.patch.object(P, "log_event", lambda kind, **d: self.events.append((kind, d)))]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def test_one_subscriber_failing_does_not_stop_the_next(self):
        served = []

        def fake_serve(sub, who, *a):
            if who == "One":
                raise ConnectionError("https://api.telegram.org/bot123:SECRET/sendVideo")
            served.append(who)
        out = io.StringIO()
        with mock.patch.object(P, "serve", fake_serve), contextlib.redirect_stdout(out):
            P.publish(self.dir, "Source", "space")
        self.assertEqual(served, ["Two"])  # "Three" is still onboarding -> not served
        self.assertIn("error", [k for k, _ in self.events])
        self.assertNotIn("SECRET", out.getvalue())
        self.assertNotIn("SECRET", json.dumps(self.events))

    def test_reel_with_no_clips_is_not_sent(self):
        delivered = []
        with mock.patch.object(P, "match", lambda *a: {"relevant": True, "score": 1, "reason": "r"}), \
             mock.patch.object(P, "build_reel", lambda *a, **k: {"verification": [], "clips": [], "video_id": "v"}), \
             mock.patch.object(P.store, "profile_for", lambda sub: {"name": "x"}), \
             mock.patch.object(P, "deliver", lambda *a, **k: delivered.append(1)), \
             contextlib.redirect_stdout(io.StringIO()):
            P.serve({"chat_id": "1"}, "One", {}, self.dir, "space")
        self.assertEqual(delivered, [])
        self.assertEqual(self.events[-1][0], "error")

    def test_skipped_subscriber_gets_no_reel(self):
        built = []
        with mock.patch.object(P, "match", lambda *a: {"relevant": False, "score": 0, "reason": "all talk"}), \
             mock.patch.object(P, "build_reel", lambda *a, **k: built.append(1)), \
             contextlib.redirect_stdout(io.StringIO()):
            P.serve({"chat_id": "1"}, "One", {}, self.dir, "news")
        self.assertEqual(built, [])
        self.assertEqual(self.events[-1], ("match", {"chat_id": "1", "user": "One", "relevant": False,
                                                      "score": 0, "reason": "all talk"}))


if __name__ == "__main__":
    unittest.main()
