"""Subscribers, stored as one JSON file keyed by Telegram chat id."""

from __future__ import annotations

import json
import os
from pathlib import Path

from dotenv import load_dotenv

PATH = Path("data/subscribers.json")


def load() -> dict[str, dict]:
    return json.loads(PATH.read_text()) if PATH.exists() else {}


def save(subs: dict[str, dict]) -> None:
    PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(subs, indent=2))
    os.replace(tmp, PATH)  # atomic: the bot and the publisher may both write


def get(chat_id: int | str) -> dict | None:
    return load().get(str(chat_id))


def update(chat_id: int | str, **fields) -> dict:
    subs = load()  # re-read right before writing, so we don't overwrite the other process
    sub = subs.setdefault(str(chat_id), {"chat_id": str(chat_id)})
    sub.update(fields)
    save(subs)
    return sub


def profile_for(sub: dict) -> dict:
    """The profile format agent.curate.build_reel expects."""
    p = sub["profile"]
    return {"name": f"user_{sub['chat_id']}", "display_name": sub.get("first_name") or sub["chat_id"],
            "preferences": p["preferences"], "max_seconds": p.get("max_seconds", 90)}


def allowed(chat_id: int | str) -> bool:
    """Private demo: only chat ids listed in ALLOWED_CHAT_IDS (comma-separated) may use the bot.
    If the variable is empty or missing, nobody is allowed — fail closed."""
    load_dotenv()
    ids = {x.strip() for x in os.environ.get("ALLOWED_CHAT_IDS", "").split(",") if x.strip()}
    return str(chat_id) in ids
