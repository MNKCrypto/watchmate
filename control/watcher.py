"""The watcher agent: checks every active source for new videos and serves subscribers.

For each new video it runs the whole pipeline on its own, logging every step to the live feed:
  chunk -> Muse Spark watches every segment -> long-context timeline -> match subscribers ->
  personal reels (self-checked) -> Telegram

Each pipeline step is the same command you can run by hand (python -m ingest.chunk, ...).
Already-seen videos are remembered in data/seen.json.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

from common.events import log_event
from control import sources

SEEN = Path("data/seen.json")
POLL_SECONDS = 5


def _seen() -> set[str]:
    return set(json.loads(SEEN.read_text())) if SEEN.exists() else set()


def _mark_seen(key: str) -> None:
    s = _seen() | {key}
    SEEN.parent.mkdir(parents=True, exist_ok=True)
    SEEN.write_text(json.dumps(sorted(s)))


def _run(args: list[str], on_line=None) -> None:
    """Run a pipeline step as a subprocess, streaming its output."""
    # -u: unbuffered, so progress lines (and the live-feed progress bar) arrive as they happen
    proc = subprocess.Popen([sys.executable, "-u", "-m", *args], stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, bufsize=1)
    for line in proc.stdout:
        print(f"    {line.rstrip()}")
        if on_line:
            on_line(line)
    if proc.wait() != 0:
        raise RuntimeError(f"step failed: {' '.join(args)}")


def process(src: dict, video: Path) -> None:
    vid = re.sub(r"[^a-zA-Z0-9_-]+", "_", video.stem)
    video_dir = Path("data/processed") / vid
    ctx = {"source": src["name"], "category": src["category"], "video_id": vid}
    log_event("new_video", file=video.name, **ctx)

    if not (video_dir / "manifest.json").exists():
        log_event("step", step="chunk", status="started", **ctx)
        _run(["ingest.chunk", str(video), "--video-id", vid])
    manifest = json.loads((video_dir / "manifest.json").read_text())
    log_event("step", step="chunk", status="done", segments=manifest["segment_count"],
              minutes=round(manifest["source_duration"] / 60, 1), **ctx)

    total = manifest["segment_count"]
    log_event("step", step="watch", status="started", total=total, **ctx)
    last = {"n": 0}

    def progress(line: str) -> None:
        m = re.search(r"\[(\d+)/(\d+)\]", line)
        if m and int(m.group(1)) - last["n"] >= 25:
            last["n"] = int(m.group(1))
            log_event("step", step="watch", status="progress", done=int(m.group(1)),
                      total=int(m.group(2)), **ctx)

    _run(["ingest.analyze", "--manifest", str(video_dir / "manifest.json"), "--reasoning-effort", "low"],
         on_line=progress)
    log_event("step", step="watch", status="done", total=total, **ctx)

    log_event("step", step="timeline", status="started", **ctx)
    _run(["timeline.build", "--video-dir", str(video_dir)])
    timeline = json.loads((video_dir / "timeline.json").read_text())
    log_event("step", step="timeline", status="done", moments=len(timeline["moments"]),
              title=timeline.get("title", vid),
              highlights=[m["title"] for m in sorted(timeline["moments"], key=lambda m: -m["excitement"])[:4]],
              **ctx)

    _run(["bot.publish", "--video-dir", str(video_dir), "--source", src["name"],
          "--category", src["category"]])
    log_event("step", step="serve", status="done", **ctx)


def loop(stop: threading.Event) -> None:
    log_event("watcher", status="started")
    print("👁  Watcher running")
    while not stop.is_set():
        for src in sources.load():
            if not src.get("active"):
                continue
            for video in sorted(Path(src["folder"]).glob("*.mp4")):
                key = f"{src['id']}/{video.name}"
                if key in _seen():
                    continue
                _mark_seen(key)  # mark first, so a failure isn't retried in a loop
                print(f"🆕 {src['name']}: {video.name}")
                try:
                    process(src, video)
                except Exception as e:  # keep watching other sources
                    log_event("error", source=src["name"], file=video.name, error=str(e))
                    print(f"  ✗ {e}")
        stop.wait(POLL_SECONDS)


def start() -> threading.Event:
    stop = threading.Event()
    threading.Thread(target=loop, args=(stop,), daemon=True).start()
    return stop
