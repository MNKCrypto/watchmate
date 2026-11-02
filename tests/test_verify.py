"""Self-check flow: pass / retitle / reject -> replace or drop (model calls are faked)."""
import unittest
from pathlib import Path
from unittest import mock

from agent import verify as V

MANIFEST = {"segments": [{"start": i * 6.0, "end": i * 6.0 + 6} for i in range(100)]}


def clip(s, e, title):
    return {"start_seg": s, "end_seg": e, "title": title, "priority": 2}


def run(clips, verdicts, replacement=None, budget=10):
    """Run verify_clips with fake checker/replacer. Returns (final, report, calls to find_replacement)."""
    def fake_check(client, c, *a, **k):
        v = verdicts[c["title"]]
        return {"verdict": v, "issue": "x", "shows": "", "new_title": "Better caption" if v == "retitle" else ""}
    calls = []

    def fake_find(client, failed, issue, prefs, used, room, rows, n):
        calls.append({"used": sorted(used), "room": room})
        return replacement
    with mock.patch.object(V, "check_clip", fake_check), mock.patch.object(V, "find_replacement", fake_find):
        final, report = V.verify_clips(None, clips, "prefs", budget, Path("."), MANIFEST, [], log=lambda *a: None)
    return final, report, calls


class VerifyTest(unittest.TestCase):
    def test_all_pass(self):
        final, report, _ = run([clip(1, 2, "A"), clip(5, 6, "B")], {"A": "pass", "B": "pass"})
        self.assertEqual([c["title"] for c in final], ["A", "B"])
        self.assertTrue(all(c["verified"] for c in final))

    def test_retitle_keeps_the_clip_with_a_corrected_caption(self):
        final, report, _ = run([clip(1, 2, "Moon landing in 2028")], {"Moon landing in 2028": "retitle"})
        self.assertEqual(final[0]["title"], "Better caption")
        self.assertEqual(final[0]["original_title"], "Moon landing in 2028")
        self.assertIn("retitled", report[0]["action"])

    def test_replacement_room_counts_each_remaining_clip_once(self):
        # budget 10: A (3 segs) already checked, B fails, C (2 segs) still to check -> room 5
        clips = [clip(10, 12, "A"), clip(20, 22, "B"), clip(30, 31, "C")]
        final, _, calls = run(clips, {"A": "pass", "B": "fail", "C": "pass", "R": "pass"},
                              replacement=clip(40, 41, "R"))
        self.assertEqual(calls[0]["room"], 5)
        self.assertEqual(calls[0]["used"], [(10, 12), (30, 31)])
        self.assertEqual([c["title"] for c in final], ["A", "C", "R"])  # sorted by time
        self.assertEqual(final[-1]["replaces"], "B")

    def test_rejected_clip_without_replacement_is_dropped(self):
        final, report, _ = run([clip(1, 2, "A"), clip(5, 6, "B")], {"A": "pass", "B": "fail"}, replacement=None)
        self.assertEqual([c["title"] for c in final], ["A"])
        self.assertEqual(report[1]["action"], "dropped")

    def test_replacement_that_also_fails_is_dropped(self):
        final, report, _ = run([clip(1, 2, "B")], {"B": "fail", "R": "fail"}, replacement=clip(40, 41, "R"))
        self.assertEqual(final, [])
        self.assertEqual(report[0]["action"], "dropped")


if __name__ == "__main__":
    unittest.main()
