"""Run the Watchmate Telegram bot (long polling — no public URL needed).

    python -m bot.run

Commands users can send:
    /start      onboarding: tell Watchmate what you're into
    /profile    show what Watchmate is watching for
    /interests  change your interests
Anything else: a follow-up about the last reel (question, "show me...", "make it 30 seconds").
"""

from __future__ import annotations

import time
import traceback
from pathlib import Path

from agent.curate import build_reel
from bot import store
from bot.followup import make_clip, respond
from bot.onboarding import extract_profile
from common.events import log_event
from messaging.telegram import TelegramError, get_updates, send_text, send_typing, send_video
from scripts.send_reel import deliver

WELCOME = ("👋 Hi {name}, I'm *Watchmate*.\n\n"
           "I watch long broadcasts for you (launches, matches, shows, news) and send you just the "
           "moments you care about.\n\nTell me in your own words: what are you into, and what should I skip?")


def onboard(chat_id: str, name: str, text: str) -> None:
    send_typing(chat_id)
    data = extract_profile(name, text)
    if data.get("need_more"):
        send_text(chat_id, data.get("question", "Tell me a bit more about what you like?"))
        return
    profile = {k: data[k] for k in ("interests", "preferences", "max_seconds") if k in data}
    store.update(chat_id, state="ready", profile=profile, onboarding_text=text)
    log_event("onboarded", chat_id=chat_id, user=name, interests=profile.get("interests", []),
              preferences=profile.get("preferences", ""))
    send_text(chat_id, data.get("reply") or "Got it! I'll message you when something matching airs.")
    print(f"  ✓ onboarded {name}: {profile.get('interests')}")


def follow_up(chat_id: str, sub: dict, text: str) -> None:
    send_typing(chat_id)
    r = respond(text, sub)
    log_event("followup", chat_id=chat_id, user=sub.get("first_name"), question=text,
              type=r.get("type"), reply=r.get("text", ""))
    send_text(chat_id, r.get("text", ""), markdown=False)

    if r.get("type") == "clip" and r.get("clip"):
        send_typing(chat_id, "upload_video")
        path = make_clip(Path(r["video_dir"]), r["clip"], Path("data/clips") / chat_id)
        if path:
            send_video(chat_id, path, r["clip"].get("title", ""))

    elif r.get("type") == "rebuild" and r.get("max_seconds"):
        seconds = max(18, min(int(r["max_seconds"]), 300))
        profile = {**store.profile_for(sub), "max_seconds": seconds}
        send_typing(chat_id, "upload_video")
        reel = build_reel(profile, Path(r["video_dir"]), log=lambda line: print(f"     {line}"))
        deliver(chat_id, reel, Path(reel["mp4"]))
        log_event("delivered", chat_id=chat_id, user=sub.get("first_name"), clips=len(reel["clips"]),
                  seconds=reel["total_seconds"], recap=reel["recap"], rebuild=True)


def handle(msg: dict) -> None:
    chat_id = str(msg["chat"]["id"])
    name = msg.get("from", {}).get("first_name", "")
    text = (msg.get("text") or "").strip()
    if not text:
        return
    if not store.allowed(chat_id):
        print(f"⛔ {name} ({chat_id}) not on ALLOWED_CHAT_IDS — ignored")
        send_text(chat_id, "🙏 Watchmate is a private hackathon demo right now, so I can't chat yet. "
                  "Thanks for stopping by!", markdown=False)
        return
    print(f"← {name} ({chat_id}): {text}")
    sub = store.get(chat_id)

    if text.startswith("/start") or text.startswith("/interests") or sub is None:
        store.update(chat_id, first_name=name, state="onboarding")
        send_text(chat_id, WELCOME.format(name=name or "there"))
        return
    if text.startswith("/profile"):
        p = sub.get("profile")
        send_text(chat_id, f"🎯 I'm watching for: {', '.join(p['interests'])}\n\n{p['preferences']}"
                  if p else "No profile yet. Send /start.", markdown=False)
        return
    if sub.get("state") == "onboarding":
        onboard(chat_id, name, text)
        return
    if sub.get("last_reel"):
        follow_up(chat_id, sub, text)
        return
    send_text(chat_id, "I'm on it 👀 I'll message you as soon as something you care about airs.")


def main() -> None:
    print("Watchmate bot running. Press Ctrl+C to stop.")
    offset = None
    while True:
        try:
            for update in get_updates(offset):
                offset = update["update_id"] + 1
                if "message" in update:
                    try:
                        handle(update["message"])
                    except Exception:
                        traceback.print_exc()
                        try:
                            send_text(update["message"]["chat"]["id"],
                                      "Sorry, something went wrong on my side. Please try again.",
                                      markdown=False)
                        except TelegramError:
                            pass
        except (TelegramError, OSError) as e:
            print(f"Polling error: {e}; retrying in 5s")
            time.sleep(5)


if __name__ == "__main__":
    main()
