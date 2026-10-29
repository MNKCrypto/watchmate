"""A broadcast has been processed: decide who cares, build their reels, deliver them.

This is the agent's autonomous step — nobody asks for anything. For every subscriber,
Muse Spark decides whether the broadcast matches their interests; matched users get a
personal, self-checked reel on Telegram, the rest are skipped (with a reason).

Usage:
    python -m bot.publish --video-dir data/processed/artemis_demo
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from agent.curate import build_reel
from bot import store
from bot.matcher import match
from common.events import log_event
from messaging.telegram import TelegramError, send_text
from scripts.send_reel import deliver


def publish(video_dir: Path, source: str = "", category: str = "") -> None:
    timeline = json.loads((video_dir / "timeline.json").read_text())
    title = timeline.get("title", video_dir.name)
    subs = [s for s in store.load().values() if s.get("state") == "ready" and store.allowed(s["chat_id"])]
    log_event("broadcast", video_id=video_dir.name, title=title, moments=len(timeline["moments"]),
              subscribers=len(subs), source=source, category=category)
    print(f"📡 {title}: {len(timeline['moments'])} moments, {len(subs)} subscribers")

    for sub in subs:
        who = sub.get("first_name") or sub["chat_id"]
        m = match(timeline, sub, category)
        log_event("match", chat_id=sub["chat_id"], user=who, **m)
        if not m["relevant"]:
            print(f"  ⏭  {who}: skipped — {m['reason']}")
            continue
        print(f"  🎯 {who}: matched — {m['reason']}")

        def log(line: str, _who=who) -> None:
            print(f"     {line}")

        reel = build_reel(store.profile_for(sub), video_dir, log=log)
        for v in reel["verification"]:
            log_event("verify", chat_id=sub["chat_id"], user=who, clip=v.get("clip"),
                      verdict=v.get("verdict"), shows=v.get("shows", ""), issue=v.get("issue", ""),
                      action=v.get("action", ""))
        reel_path = Path("data/reels") / reel["video_id"] / store.profile_for(sub)["name"] / "reel.json"
        try:
            deliver(sub["chat_id"], reel, Path(reel["mp4"]))
        except TelegramError as e:
            print(f"     ✗ delivery failed: {e}")
            log_event("delivery_failed", chat_id=sub["chat_id"], user=who, error=str(e))
            continue
        store.update(sub["chat_id"], last_reel=str(reel_path))
        log_event("delivered", chat_id=sub["chat_id"], user=who, clips=len(reel["clips"]),
                  seconds=reel["total_seconds"], recap=reel["recap"])
        print(f"     ✓ delivered {len(reel['clips'])} clips, {reel['total_seconds']:.0f}s")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--video-dir", type=Path, default=Path("data/processed/artemis_demo"))
    p.add_argument("--source", default="", help="source name, e.g. NASA (shown in the live feed)")
    p.add_argument("--category", default="", help="source category, e.g. space (a hint for matching)")
    args = p.parse_args()
    publish(args.video_dir, args.source, args.category)


if __name__ == "__main__":
    main()
