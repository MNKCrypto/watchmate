"""Cover art for a reel, generated with Muse Image (muse-image-1.0, ~$0.01 per image)."""

from __future__ import annotations

import base64
from pathlib import Path

from common.muse import get_client

PROMPT = """Cover art for a personal highlight reel: "{title}".
It features: {moments}.
Style: a clearly ILLUSTRATED graphic poster — bold flat shapes, limited vivid palette, clean vector / screen-print look,
strong composition with a sense of scale and motion. It must read as artwork, never as a photo of the real event.
No text, no letters, no logos, no watermarks, no recognisable real people."""


def generate_cover(reel: dict, out: Path) -> Path:
    moments = "; ".join(c["title"] for c in reel["clips"][:4])
    resp = get_client().images.generate(
        model="muse-image-1.0",
        prompt=PROMPT.format(title=reel.get("title") or "highlights", moments=moments),
        n=1,
        size="1024x1024",
        response_format="b64_json",
        extra_body={"output_format": "jpeg"},
    )
    out.write_bytes(base64.b64decode(resp.data[0].b64_json))
    return out
