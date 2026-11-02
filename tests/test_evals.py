"""The evaluation must actually catch a reel that breaks a subscriber's rule."""
import unittest
from unittest import mock

from evals import evaluate as E

TIMELINE = {"moments": [{"start_seg": 0, "end_seg": 9, "type": "announcement", "footage": "studio"},
                        {"start_seg": 10, "end_seg": 19, "type": "politics/budget", "footage": "studio"}]}


def reel(clips, total=24):
    return {"profile": {"max_seconds": 60, "display_name": "Fan"}, "video_id": "v", "total_seconds": total,
            "clips": clips, "verification": [{"verdict": "pass"} for _ in clips]}


def run(r):
    files = {"r.json": r, "t.json": TIMELINE}
    case = {"reel": "r.json", "timeline": "t.json", "rule": "skip politics",
            "forbidden_moment_types": ["politics/budget"], "forbidden_footage": []}
    with mock.patch.object(E, "load", lambda rel: files[rel]):
        _, checks = E.eval_reel(case)
    return {label: ok for label, ok, _ in checks}


class EvalCatchesProblemsTest(unittest.TestCase):
    def test_clean_reel_passes(self):
        self.assertTrue(all(run(reel([{"start_seg": 2, "end_seg": 5, "verified": True}])).values()))

    def test_politics_clip_breaks_the_hard_rule(self):
        self.assertFalse(run(reel([{"start_seg": 12, "end_seg": 14, "verified": True}]))["hard rules"])

    def test_over_budget_and_unchecked_clips_fail(self):
        r = reel([{"start_seg": 2, "end_seg": 5}], total=90)
        r["verification"] = []
        res = run(r)
        self.assertFalse(res["budget"])
        self.assertFalse(res["self-check"])


if __name__ == "__main__":
    unittest.main()
