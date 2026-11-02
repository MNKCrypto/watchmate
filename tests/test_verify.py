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
        if isinstance(v, dict):  # a raw checker result, to test check_clip-level outcomes
            return v
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

    def test_unreadable_check_keeps_the_clip_but_never_reports_it_verified(self):
        final, report, _ = run([clip(1, 2, "A")], {"A": {"verdict": "unchecked", "issue": "checker returned no JSON"}})
        self.assertEqual(len(final), 1)
        self.assertFalse(final[0]["verified"])
        self.assertTrue(final[0]["unchecked"])
        self.assertEqual(report[0]["action"], "kept, unchecked")

    def test_unchecked_replacement_is_not_used(self):
        final, report, _ = run([clip(1, 2, "B")], {"B": "fail", "R": "unchecked"}, replacement=clip(40, 41, "R"))
        self.assertEqual(final, [])
        self.assertEqual(report[0]["action"], "dropped")


class CheckClipTest(unittest.TestCase):
    """check_clip's handling of the checker's raw answer (the model call is faked)."""

    def verdict_for(self, output_text):
        resp = mock.Mock(output_text=output_text)
        client = mock.Mock()
        client.responses.create.return_value = resp
        with mock.patch.object(V, "cut_clip", lambda *a, **k: Path("clip.mp4")), \
             mock.patch.object(V, "video_part", lambda *a, **k: ({}, None)), \
             mock.patch.object(V, "delete_file", lambda *a, **k: None):
            return V.check_clip(client, clip(1, 2, "A"), "prefs", Path("."), MANIFEST)["verdict"]

    def test_unreadable_or_unknown_answers_are_unchecked_not_passed(self):
        self.assertEqual(self.verdict_for("sorry, no JSON"), "unchecked")
        self.assertEqual(self.verdict_for('{"verdict": "maybe"}'), "unchecked")

    def test_broken_hard_rule_always_fails(self):
        self.assertEqual(self.verdict_for('{"verdict": "pass", "hard_rule_broken": "no politics"}'), "fail")

    def test_retitle_without_a_new_title_is_a_pass(self):
        self.assertEqual(self.verdict_for('{"verdict": "retitle", "new_title": ""}'), "pass")


if __name__ == "__main__":
    unittest.main()
