"""Clip rules the agent's picks must obey: in range, merged when touching, within the time budget."""
import unittest

from agent.curate import enforce, seg_count


def clip(s, e, prio=2, title="t"):
    return {"start_seg": s, "end_seg": e, "priority": prio, "title": title}


class EnforceTest(unittest.TestCase):
    def test_clamps_to_video_and_fixes_reversed_ranges(self):
        kept, _ = enforce([clip(-3, 2), clip(99, 95)], n_segments=100, max_seconds=600, seg_len=6)
        self.assertEqual([(c["start_seg"], c["end_seg"]) for c in kept], [(0, 2), (95, 99)])

    def test_skips_clips_the_model_returned_without_numbers(self):
        kept, _ = enforce([{"start_seg": "x", "end_seg": 3}, clip(5, 6)], 100, 600, 6)
        self.assertEqual(len(kept), 1)

    def test_touching_clips_merge_and_keep_the_more_important_caption(self):
        kept, _ = enforce([clip(10, 12, prio=3, title="Crowd"), clip(13, 15, prio=1, title="Liftoff")],
                          100, 600, 6)
        self.assertEqual(len(kept), 1)
        self.assertEqual((kept[0]["start_seg"], kept[0]["end_seg"]), (10, 15))
        self.assertEqual(kept[0]["title"], "Liftoff")  # one caption, not "Crowd / Liftoff"
        self.assertEqual(kept[0]["priority"], 1)

    def test_over_budget_drops_lowest_priority_never_cuts_a_clip_short(self):
        clips = [clip(0, 4, 1, "must"), clip(20, 24, 3, "nice"), clip(40, 42, 2, "strong")]
        kept, dropped = enforce(clips, 100, max_seconds=48, seg_len=6)  # budget = 8 segments
        self.assertEqual([c["title"] for c in kept], ["must", "strong"])
        self.assertEqual([c["title"] for c in dropped], ["nice"])
        self.assertTrue(all(seg_count(c) in (5, 3) for c in kept))  # untouched lengths
        self.assertLessEqual(sum(seg_count(c) for c in kept), 8)

    def test_a_single_clip_longer_than_the_budget_is_trimmed(self):
        kept, _ = enforce([clip(0, 20, 1)], 100, max_seconds=30, seg_len=6)
        self.assertEqual(seg_count(kept[0]), 5)

    def test_invalid_priority_defaults_to_strong(self):
        kept, _ = enforce([{**clip(1, 2), "priority": 9}], 100, 600, 6)
        self.assertEqual(kept[0]["priority"], 2)


if __name__ == "__main__":
    unittest.main()
