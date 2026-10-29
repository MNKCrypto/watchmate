"""Decide which subscribers care about a newly processed broadcast (Muse Spark)."""

from __future__ import annotations

from common.muse import get_client, parse_json

PROMPT = """A new broadcast has just been watched and broken into moments:
TITLE: {title}
SOURCE CATEGORY: {category}
MOMENTS:
{moments}

A subscriber's profile:
INTERESTS: {interests}
PREFERENCES: {preferences}

Would this subscriber want a personal highlight reel of this broadcast? Judge by their interests,
not by whether the broadcast is generally exciting. Return ONLY JSON:
{{"relevant": true or false, "score": 0-1, "reason": "one short sentence citing their interest and the broadcast"}}"""


def match(timeline: dict, sub: dict, category: str = "") -> dict:
    moments = "\n".join(f"- {m['title']}: {m.get('summary', '')}" for m in timeline["moments"])
    p = sub["profile"]
    resp = get_client().responses.create(
        model="muse-spark-1.3",
        input=[{"role": "user", "content": [{"type": "input_text", "text": PROMPT.format(
            title=timeline.get("title", ""), category=category or "unknown", moments=moments,
            interests=", ".join(p.get("interests", [])), preferences=p["preferences"])}]}],
        reasoning={"effort": "low"},
        max_output_tokens=2000,
    )
    data = parse_json(resp.output_text) or {}
    return {"relevant": bool(data.get("relevant")), "score": data.get("score", 0),
            "reason": data.get("reason", "")}
