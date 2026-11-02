"""The watcher must not start on a video that is still being copied."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from control import watcher as W


class ReadyTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.video = self.dir / "launch.mp4"

    def test_waits_until_the_size_stops_changing(self):
        sizes = {}
        self.video.write_bytes(b"x" * 10)
        self.assertFalse(W.ready(self.video, sizes))   # first sight: unknown if still growing
        self.video.write_bytes(b"x" * 20)
        self.assertFalse(W.ready(self.video, sizes))   # grew since last poll
        self.assertTrue(W.ready(self.video, sizes))    # same size twice -> copy finished

    def test_empty_or_missing_file_is_never_ready(self):
        sizes = {}
        self.video.write_bytes(b"")
        self.assertFalse(W.ready(self.video, sizes))
        self.assertFalse(W.ready(self.video, sizes))
        self.assertFalse(W.ready(self.dir / "gone.mp4", sizes))


class ScanTest(unittest.TestCase):
    def test_processes_a_new_video_only_after_its_copy_finishes(self):
        folder = Path(tempfile.mkdtemp())
        (folder / "launch.mp4").write_bytes(b"x" * 10)
        src = [{"id": "nasa", "name": "NASA", "active": True, "folder": str(folder)}]
        seen, processed = set(), []
        with mock.patch.object(W.sources, "load", lambda: src), \
             mock.patch.object(W, "_seen", lambda: seen), \
             mock.patch.object(W, "_mark_seen", seen.add), \
             mock.patch.object(W, "process", lambda s, v: processed.append(v.name)):
            sizes = {}
            W.scan_once(sizes)
            self.assertEqual(processed, [])            # still might be copying
            W.scan_once(sizes)
            self.assertEqual(processed, ["launch.mp4"])
            W.scan_once(sizes)
            self.assertEqual(processed, ["launch.mp4"])  # never twice


if __name__ == "__main__":
    unittest.main()
