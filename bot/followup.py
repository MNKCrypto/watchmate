"""Answer a subscriber's follow-up message about the broadcast they received.

Muse Spark sees the whole broadcast (moments + every segment's observation — long context),
the reel it sent, and the question. It decides how to respond:
  answer  -> text only
  clip    -> text + a short clip that shows it
  rebuild -> a new reel with a different length (e.g. "make it 30 seconds")
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from agent.curate import moments_block
from agent.verify import cut_clip
from common.muse import get_client, parse_json
from timeline.build import compact_line

PROMPT = """You are Watchmate. You watched this broadcast for the user and sent them a personal reel.
Now they're messaging you about it.

USER PREFERENCES: {preferences}

REEL YOU SENT ({seconds:.0f}s): {clips}

BROADCAST MOMENTS (segment ranges inclusive, 6 s per segment):
{moments}

SEGMENT OBSERVATIONS (idx | time | event | footage | excitement | key | on-screen text | speech | visual):
{lines}

USER: {question}

Decide how to respond:
- "clip": the question is about something that HAPPENED in the broadcast (an event, a moment, a reaction,
  "what happened after...", "show me...", "how did ... look") -> answer in words AND pick 2-5 segments
  that show it, preferring live footage. This is the default for questions about moments.
- "answer": only for questions that can't be shown (facts, explanations, "why", "how fast", opinions),
  or when the broadcast has no footage of it.
- "rebuild": they want the reel changed in length (e.g. "make it 30 seconds", "longer version").
Base everything on the observations; if the broadcast doesn't contain it, say so honestly.

Return ONLY JSON:
{{"type": "answer" | "clip" | "rebuild",
  "text": "your reply, friendly, max 70 words, no markdown; if you attach a clip, end with a short lead-in like 'Here it is:'",
  "clip": {{"start_seg": <idx>, "end_seg": <idx>, "title": "short caption"}} or null,
  "max_seconds": <new reel length if rebuild, else null>}}"""


def respond(question: str, sub: dict) -> dict:
    reel = json.loads(Path(sub["last_reel"]).read_text())
    video_dir = Path("data/processed") / reel["video_id"]
    timeline = json.loads((video_dir / "timeline.json").read_text())
    rows = sorted((json.loads(l) for l in (video_dir / "observations.jsonl").read_text().splitlines()
                   if l.strip()), key=lambda r: r["index"])
    resp = get_client().responses.create(
        model="muse-spark-1.3",
        input=[{"role": "user", "content": [{"type": "input_text", "text": PROMPT.format(
            preferences=sub["profile"]["preferences"], seconds=reel["total_seconds"],
            clips=" · ".join(c["title"] for c in reel["clips"]), moments=moments_block(timeline),
            lines="\n".join(compact_line(r) for r in rows), question=question)}]}],
        reasoning={"effort": "low"},
        max_output_tokens=4000,
    )
    data = parse_json(resp.output_text) or {"type": "answer",
                                            "text": "Sorry, I couldn't work that out. Could you rephrase?"}
    data["video_dir"] = str(video_dir)
    return data


def make_clip(video_dir: Path, clip: dict, out_dir: Path) -> Path | None:
    manifest = json.loads((video_dir / "manifest.json").read_text())
    n = len(manifest["segments"])
    try:
        s, e = int(clip["start_seg"]), int(clip["end_seg"])
    except (KeyError, TypeError, ValueError):
        return None
    s, e = max(0, min(s, e)), min(n - 1, max(s, e))
    e = min(e, s + 4)  # keep follow-up clips short (<= 30 s)
    out_dir.mkdir(parents=True, exist_ok=True)
    return cut_clip(video_dir, manifest, s, e, out_dir / f"clip_{s}_{e}.mp4")
