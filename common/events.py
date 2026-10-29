"""Append-only log of the agent's decisions (feeds the control-room page)."""

from __future__ import annotations

import json
import time
from pathlib import Path

EVENTS = Path("data/events.jsonl")


def log_event(kind: str, **data) -> dict:
    event = {"ts": round(time.time(), 2), "kind": kind, **data}
    EVENTS.parent.mkdir(parents=True, exist_ok=True)
    with EVENTS.open("a") as f:
        f.write(json.dumps(event) + "\n")
    return event


def read_events(since: float = 0) -> list[dict]:
    if not EVENTS.exists():
        return []
    rows = [json.loads(l) for l in EVENTS.read_text().splitlines() if l.strip()]
    return [r for r in rows if r["ts"] > since]
