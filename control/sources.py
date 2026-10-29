"""Video sources the agent monitors, stored in data/sources.json.

For the demo every source is a watched folder: dropping an MP4 into sources/<id>/ counts as
"this source published a new video". Broadcaster APIs / RSS are future work.
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

PATH = Path("data/sources.json")
DEFAULTS = [
    {"id": "nasa", "name": "NASA", "category": "space", "type": "folder", "folder": "sources/nasa", "active": True},
    {"id": "icc", "name": "ICC", "category": "cricket", "type": "folder", "folder": "sources/icc", "active": True},
]


def load() -> list[dict]:
    if not PATH.exists():
        save([{**d, "added": time.time()} for d in DEFAULTS])
    sources = json.loads(PATH.read_text())
    for s in sources:
        Path(s["folder"]).mkdir(parents=True, exist_ok=True)
    return sources


def save(sources: list[dict]) -> None:
    PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(sources, indent=2))
    os.replace(tmp, PATH)


def add(name: str, category: str) -> dict:
    sources = load()
    sid = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "source"
    while any(s["id"] == sid for s in sources):
        sid += "-2"
    src = {"id": sid, "name": name.strip(), "category": category.strip().lower(), "type": "folder",
           "folder": f"sources/{sid}", "active": True, "added": time.time()}
    Path(src["folder"]).mkdir(parents=True, exist_ok=True)
    save(sources + [src])
    return src


def set_active(sid: str, active: bool) -> None:
    sources = load()
    for s in sources:
        if s["id"] == sid:
            s["active"] = active
    save(sources)


def remove(sid: str) -> None:
    save([s for s in load() if s["id"] != sid])
