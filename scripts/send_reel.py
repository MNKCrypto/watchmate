"""Send a finished reel to a user on Telegram: a short intro, the video, and the recap.

Usage:
    python -m scripts.send_reel --reel data/reels/artemis_demo/engineer/reel.json
    python -m scripts.send_reel --reel ... --chat-id 123456789

Without --chat-id it sends to whoever last messaged the bot (press Start in the bot first).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from messaging.telegram import TelegramError, latest_chat_id, send_text, send_typing, send_video


def format_messages(reel: dict) -> tuple[str, str, str]:
    what = f"*{reel['title']}* broadcast" if reel.get("title") else "broadcast"
    intro = (f"👋 Hi! I watched the full {what} for you and cut your personal highlights: "
             f"{len(reel['clips'])} moments, {reel['total_seconds']:.0f}s.")
    caption = " · ".join(c["title"] for c in reel["clips"])
    recap = f"📝 *Your recap*\n{reel['recap']}\n\nAsk me anything about it 🚀"
    return intro, caption, recap


def deliver(chat_id: int | str, reel: dict, mp4: Path, intro: str | None = None) -> None:
    default_intro, caption, recap = format_messages(reel)
    send_text(chat_id, intro or default_intro)
    send_typing(chat_id, "upload_video")
    send_video(chat_id, mp4, caption)
    send_text(chat_id, recap)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--reel", type=Path, required=True)
    p.add_argument("--chat-id", help="Telegram chat id (default: last person who messaged the bot)")
    args = p.parse_args()

    reel = json.loads(args.reel.read_text())
    mp4 = Path(reel.get("mp4") or args.reel.with_name("reel.mp4"))
    try:
        chat_id = args.chat_id or latest_chat_id()
        print(f"Sending to chat {chat_id}: intro, {mp4.name} ({mp4.stat().st_size / 1e6:.1f} MB), recap ...")
        deliver(chat_id, reel, mp4)
    except TelegramError as e:
        raise SystemExit(f"Failed: {e}")
    print(f"Delivered ✓  Check Telegram. (chat id {chat_id} — save it for later)")


if __name__ == "__main__":
    main()
