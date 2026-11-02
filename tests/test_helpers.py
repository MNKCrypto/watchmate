"""Small helpers: JSON parsing of model output, allowlist, timeline clean-up."""
import os
import unittest
from unittest import mock

from bot import store
from common.muse import parse_json
from timeline.build import fmt_time, validate


class ParseJsonTest(unittest.TestCase):
    def test_plain_fenced_and_wrapped(self):
        self.assertEqual(parse_json('{"a": 1}'), {"a": 1})
        self.assertEqual(parse_json('```json\n{"a": 1}\n```'), {"a": 1})
        self.assertEqual(parse_json('Sure! {"a": {"b": 2}} hope that helps'), {"a": {"b": 2}})

    def test_garbage_returns_none(self):
        self.assertIsNone(parse_json("no json here"))
        self.assertIsNone(parse_json('{"a": }'))


class AllowlistTest(unittest.TestCase):
    def test_fails_closed_when_empty(self):
        with mock.patch.dict(os.environ, {"ALLOWED_CHAT_IDS": ""}), mock.patch.object(store, "load_dotenv"):
            self.assertFalse(store.allowed("123"))

    def test_only_listed_ids(self):
        with mock.patch.dict(os.environ, {"ALLOWED_CHAT_IDS": "111, 222"}), mock.patch.object(store, "load_dotenv"):
            self.assertTrue(store.allowed(222))
            self.assertFalse(store.allowed("333"))


class TimelineTest(unittest.TestCase):
    def test_moments_are_ordered_non_overlapping_and_cover_every_segment(self):
        segs = list(range(10))
        out = validate([{"start_seg": 6, "end_seg": 12, "title": "B"},
                        {"start_seg": 2, "end_seg": 7, "title": "A"}], segs)
        spans = [(m["start_seg"], m["end_seg"]) for m in out]
        self.assertEqual(spans, [(0, 1), (2, 7), (8, 9)])  # gap filled, overlap trimmed, clamped to 9
        self.assertEqual(out[0]["title"], "Other coverage")

    def test_fmt_time(self):
        self.assertEqual(fmt_time(1104), "18:24")


if __name__ == "__main__":
    unittest.main()
