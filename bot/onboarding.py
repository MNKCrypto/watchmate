"""Turn what a user says about their interests into a viewer profile (Muse Spark)."""

from __future__ import annotations

from common.muse import get_client, parse_json

PROMPT = """You are Watchmate, an AI that watches long live broadcasts (sports, entertainment, news,
space launches...) for people and sends them personalised highlight reels.

A new user named {name} told you what they're into:
\"\"\"{text}\"\"\"

Build their viewer profile. Stay faithful to what they said; don't invent interests.
If what they said is too vague to pick highlights (e.g. just "hi"), ask ONE short friendly question instead.

Return ONLY JSON:
{{
  "need_more": true or false,
  "question": "if need_more: one short question; else ''",
  "interests": ["topics, e.g. 'space technology', 'rocket launches', 'cricket'"],
  "preferences": "first-person paragraph in the user's voice: what they want in highlights, what to skip, live vs studio, tone",
  "max_seconds": <reel length: 60 if they want it short, 150 if detailed, else 90>,
  "reply": "friendly confirmation (max 45 words): what you'll watch for and that you'll message them when something matching airs"
}}"""


def extract_profile(name: str, text: str) -> dict:
    resp = get_client().responses.create(
        model="muse-spark-1.3",
        input=[{"role": "user", "content": [{"type": "input_text",
                "text": PROMPT.format(name=name or "there", text=text)}]}],
        reasoning={"effort": "low"},
        max_output_tokens=4000,
    )
    data = parse_json(resp.output_text) or {}
    if not data.get("need_more") and not data.get("preferences"):
        data = {"need_more": True,
                "question": "Tell me a bit more — which topics, teams or shows do you want me to watch for?"}
    return data
