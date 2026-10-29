"""Send a finished reel to a user on Telegram: a short intro, the video, and the recap.

Usage:
    python -m scripts.send_reel --reel data/reels/artemis_demo/engineer/reel.json
    python -m scripts.send_reel --reel ... --chat-id 123456789

Without --chat-id it sends to the first id in ALLOWED_CHAT_IDS (.env).
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from dotenv import load_dotenv

from messaging.telegram import TelegramError, latest_chat_id, send_photo, send_text, send_typing, send_video


def format_messages(reel: dict) -> tuple[str, str, str]:
    what = f"*{reel['title']}* broadcast" if reel.get("title") else "broadcast"
    intro = (f"👋 Hi! I watched the full {what} for you and cut your personal highlights: "
             f"{len(reel['clips'])} moments, {reel['total_seconds']:.0f}s.")
    caption = "\n".join(f"{i}. {c['title']}" for i, c in enumerate(reel["clips"], 1))
    recap = f"📝 *Your recap*\n{reel['recap']}\n\nAsk me anything about it 🚀"
    return intro, caption, recap


def default_chat_id() -> str:
    """First id in ALLOWED_CHAT_IDS; else whoever last messaged the bot (only works while the bot isn't running,
    because the bot reads and clears unread messages)."""
    load_dotenv()
    ids = [x.strip() for x in os.environ.get("ALLOWED_CHAT_IDS", "").split(",") if x.strip()]
    return ids[0] if ids else str(latest_chat_id())


def deliver(chat_id: int | str, reel: dict, mp4: Path, intro: str | None = None) -> None:
    """Cover art + intro, then the reel (the 9:16 phone version when we have one), then the recap."""
    default_intro, caption, recap = format_messages(reel)
    cover = Path(reel["cover"]) if reel.get("cover") else None
    if cover and cover.exists():
        send_photo(chat_id, cover, (intro or default_intro).replace("*", ""))  # photo captions are plain text
    else:
        send_text(chat_id, intro or default_intro)
    video = Path(reel["vertical_mp4"]) if reel.get("vertical_mp4") else mp4
    if not video.exists():
        video = mp4
    send_typing(chat_id, "upload_video")
    send_video(chat_id, video, caption)
    send_text(chat_id, recap)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--reel", type=Path, required=True)
    p.add_argument("--chat-id", help="Telegram chat id (default: last person who messaged the bot)")
    args = p.parse_args()

    reel = json.loads(args.reel.read_text())
    mp4 = Path(reel.get("mp4") or args.reel.with_name("reel.mp4"))
    try:
        chat_id = args.chat_id or default_chat_id()
        print(f"Sending to chat {chat_id}: intro, {mp4.name} ({mp4.stat().st_size / 1e6:.1f} MB), recap ...")
        deliver(chat_id, reel, mp4)
    except TelegramError as e:
        raise SystemExit(f"Failed: {e}")
    print(f"Delivered ✓  Check Telegram. (chat id {chat_id} — save it for later)")


if __name__ == "__main__":
    main()
