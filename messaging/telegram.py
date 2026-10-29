"""Send and receive messages through a Telegram bot (Bot API).

Needs in .env:
    TELEGRAM_BOT_TOKEN=...   from @BotFather (/newbot)

A bot can only message a user after that user has pressed Start (/start) in the bot's chat.
Receiving uses long polling (getUpdates), so no public URL / webhook is needed.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # Bot API upload limit


class TelegramError(RuntimeError):
    pass


def _api(method: str) -> str:
    load_dotenv()
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        sys.exit("Set TELEGRAM_BOT_TOKEN in .env (create a bot with @BotFather)")
    return f"https://api.telegram.org/bot{token}/{method}"


def _call(method: str, timeout: int = 30, **kwargs) -> dict | list:
    resp = requests.post(_api(method), timeout=timeout, **kwargs)
    data = resp.json()
    if not data.get("ok"):
        raise TelegramError(f"Telegram {method} failed: {data.get('description', data)}")
    return data["result"]


def send_text(chat_id: int | str, text: str, markdown: bool = True) -> dict:
    payload = {"chat_id": chat_id, "text": text[:4096]}
    if markdown:
        payload["parse_mode"] = "Markdown"
    try:
        return _call("sendMessage", json=payload)
    except TelegramError as e:
        if markdown and "parse entities" in str(e):  # model text with a stray * or _ -> send plain
            return send_text(chat_id, text.replace("*", ""), markdown=False)
        raise


def send_video(chat_id: int | str, path: Path, caption: str = "") -> dict:
    if path.stat().st_size > MAX_UPLOAD_BYTES:
        raise TelegramError(f"{path.name} is {path.stat().st_size / 1e6:.1f} MB; bots can upload 50 MB")
    with path.open("rb") as f:
        return _call("sendVideo", timeout=180,
                     data={"chat_id": chat_id, "caption": caption[:1024], "supports_streaming": "true"},
                     files={"video": (path.name, f, "video/mp4")})


def send_photo(chat_id: int | str, path: Path, caption: str = "") -> dict:
    with path.open("rb") as f:
        return _call("sendPhoto", timeout=60, data={"chat_id": chat_id, "caption": caption[:1024]},
                     files={"photo": (path.name, f, "image/jpeg")})


def send_typing(chat_id: int | str, action: str = "typing") -> None:
    """Show 'typing…' / 'sending video…' in the chat while we work."""
    try:
        _call("sendChatAction", json={"chat_id": chat_id, "action": action})
    except TelegramError:
        pass


def get_updates(offset: int | None = None, timeout: int = 25) -> list[dict]:
    """Long-poll for new messages. Pass offset = last update_id + 1 to acknowledge earlier ones."""
    params = {"timeout": timeout, "allowed_updates": ["message"]}
    if offset is not None:
        params["offset"] = offset
    return _call("getUpdates", timeout=timeout + 10, json=params)


def latest_chat_id() -> int:
    """Chat id of whoever most recently messaged the bot (used for quick tests)."""
    updates = get_updates(timeout=0)
    chats = [u["message"]["chat"]["id"] for u in updates if "message" in u]
    if not chats:
        raise TelegramError("No messages yet — open the bot in Telegram and press Start (/start) first.")
    return chats[-1]
