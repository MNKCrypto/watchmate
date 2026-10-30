"""Build the event timeline: group 6-second observations into meaningful moments.

Instead of fixed rules, the whole broadcast's observations (all 600 segments) go to
Muse Spark in ONE request — its 1M-token context sees the entire event at once, so it
can decide where a moment really starts and ends (e.g. ignition -> liftoff -> tower
clear is one moment), merge repetitive stretches, and pick an anchor event (liftoff)
for mission-relative time.

Output: data/processed/<video_id>/timeline.json

Usage:
    python -m timeline.build
    python -m timeline.build --model muse-spark-1.3 --reasoning-effort medium
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from common.muse import get_client, parse_json

PROMPT = """You are given frame-by-frame observations of a long live broadcast, one line per 6-second segment:
idx | time | event | footage | excitement(0-10) | key | on-screen text | speech | visual

Group consecutive segments into MOMENTS a viewer would recognise (e.g. "Final countdown",
"Engine ignition and liftoff", "Booster separation (animation)", "Launch director's speech").
First decide what kind of broadcast this is:
- EVENT coverage (a launch, a match, a ceremony): moments follow what HAPPENS.
- TALK coverage (a news conference, briefing, interview, panel, speech): moments follow what is SAID.

Rules:
- Every segment belongs to exactly one moment; moments are in time order and do not overlap.
- Split when what is happening changes; merge long uneventful stretches into one moment.
- EVENT coverage: a key action plus its immediate build-up/aftermath (e.g. ignition -> liftoff -> clearing
  the tower) is ONE moment.
- TALK coverage: split by TOPIC, not by speaker. Each announcement, decision, date, result or distinct
  question is its own moment (typically 30 s to 3 min), even when the same person keeps talking.
  Title it with the news itself, e.g. "Artemis III becomes a 2027 Earth-orbit test", not "Administrator speaks".
  Rate "excitement" by newsworthiness: a new date or decision is high, pleasantries and housekeeping are low.
  Use type "announcement", "result", "explainer", "q&a", "opening" or "politics/budget" so viewers can filter.
- Keep "footage" honest: live footage vs animation vs studio matters to viewers.
- Base everything on the observations; do not invent events.
- ANCHOR: the single physical event the broadcast builds up to (liftoff, kick-off, touchdown), if there is one.
  For TALK coverage there usually is none: return null.

Return ONLY JSON:
{{
  "title": "short title for the whole broadcast",
  "kind": "event" | "talk",
  "anchor": {{"label": "e.g. liftoff", "segment": <idx where it happens>}} or null,
  "moments": [
    {{
      "start_seg": <idx>, "end_seg": <idx>,
      "title": "short viewer-facing title",
      "summary": "1-2 sentences of what happens",
      "type": "short category, e.g. countdown | launch | ascent | separation | mission control | speech | interview | explainer | crowd",
      "footage": "live | animation | graphic | studio | mixed",
      "excitement": <0-10>,
      "tags": ["keywords"],
      "evidence": "the key speech or visual detail that supports this moment"
    }}
  ]
}}

Observations ({n} segments):
{lines}"""


def clip(text: str | None, n: int) -> str:
    text = (text or "").replace("\n", " ").replace("|", "/").strip()
    return text if len(text) <= n else text[: n - 1] + "…"


def fmt_time(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    return f"{m:02d}:{s:02d}"


def compact_line(r: dict) -> str:
    o = r.get("observation") or {}
    return " | ".join([
        str(r["index"]), fmt_time(r["start"]), clip(o.get("event"), 30), clip(o.get("footage"), 10),
        str(o.get("excitement", "")), "KEY" if o.get("is_key_moment") else "",
        clip(o.get("on_screen_text"), 50), clip(o.get("speech"), 140), clip(o.get("visual"), 160),
    ])


def validate(moments: list[dict], segments: list[dict]) -> list[dict]:
    """Keep moments sane: in range, ordered, non-overlapping; fill any gaps."""
    last = len(segments) - 1
    cleaned, cursor = [], 0
    for m in sorted(moments, key=lambda m: int(m.get("start_seg", 0))):
        s = max(int(m.get("start_seg", 0)), cursor)
        e = min(int(m.get("end_seg", s)), last)
        if e < s:
            continue
        if s > cursor:  # gap the model skipped -> keep it as an unlabeled stretch
            cleaned.append({"start_seg": cursor, "end_seg": s - 1, "title": "Other coverage",
                            "summary": "", "type": "other", "footage": "mixed", "excitement": 0,
                            "tags": [], "evidence": ""})
        cleaned.append({**m, "start_seg": s, "end_seg": e})
        cursor = e + 1
    if cursor <= last:
        cleaned.append({"start_seg": cursor, "end_seg": last, "title": "Other coverage", "summary": "",
                        "type": "other", "footage": "mixed", "excitement": 0, "tags": [], "evidence": ""})
    return cleaned


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--video-dir", type=Path, default=Path("data/processed/artemis_demo"))
    p.add_argument("--observations", default="observations.jsonl")
    p.add_argument("--model", default="muse-spark-1.3")  # text-only task: latest model
    p.add_argument("--reasoning-effort", default="medium", choices=["minimal", "low", "medium", "high"])
    args = p.parse_args()

    manifest = json.loads((args.video_dir / "manifest.json").read_text())
    segments = manifest["segments"]
    rows = [json.loads(l) for l in (args.video_dir / args.observations).read_text().splitlines() if l.strip()]
    rows.sort(key=lambda r: r["index"])
    missing = len([s for s in segments if s.get("analyze", True)]) - len(rows)
    if missing > 0:
        print(f"Warning: {missing} segments have no observation yet (re-run ingest.analyze to fill them).")

    lines = "\n".join(compact_line(r) for r in rows)
    prompt = PROMPT.format(n=len(rows), lines=lines)
    print(f"Sending {len(rows)} observations (~{len(prompt) // 4 / 1000:.0f}K tokens) to {args.model} ...")

    client = get_client()
    t0 = time.time()
    resp = client.responses.create(
        model=args.model,
        input=[{"role": "user", "content": [{"type": "input_text", "text": prompt}]}],
        reasoning={"effort": args.reasoning_effort},
        max_output_tokens=32000,
    )
    data = parse_json(resp.output_text)
    if not data or "moments" not in data:
        raw_path = args.video_dir / "timeline_raw.txt"
        raw_path.write_text(resp.output_text)
        raise SystemExit(f"Model did not return valid JSON — raw output saved to {raw_path}")

    moments = validate(data["moments"], segments)
    for i, m in enumerate(moments):
        m["id"] = f"m{i:03d}"
        m["start"] = segments[m["start_seg"]]["start"]
        m["end"] = segments[m["end_seg"]]["end"]

    anchor = data.get("anchor")
    if anchor and isinstance(anchor.get("segment"), int) and 0 <= anchor["segment"] < len(segments):
        anchor["time"] = segments[anchor["segment"]]["start"]
        # mission-relative time (T-/T+) computed from position, not from on-screen clocks
        for m in moments:
            m["t_rel"] = round(m["start"] - anchor["time"], 1)
    else:
        anchor = None

    timeline = {
        "video_id": manifest["video_id"],
        "title": data.get("title", manifest["video_id"]),
        "kind": data.get("kind", "event"),
        "anchor": anchor,
        "model": args.model,
        "moments": moments,
    }
    out = args.video_dir / "timeline.json"
    out.write_text(json.dumps(timeline, indent=2))

    u = resp.usage
    print(f"Done in {time.time() - t0:.0f}s | tokens {u.input_tokens / 1000:.1f}K in / {u.output_tokens / 1000:.1f}K out")
    print(f"\n{timeline['title']}  ({timeline['kind']})  —  {len(moments)} moments"
          + (f", anchor: {anchor['label']} at {fmt_time(anchor['time'])}" if anchor else ""))
    for m in moments:
        rel = f"T{m['t_rel']:+.0f}s" if "t_rel" in m else ""
        print(f"  {fmt_time(m['start'])}-{fmt_time(m['end'])} {rel:>8}  [{m['excitement']:>2}] "
              f"{m['title']}  ({m['footage']})")
    print(f"\nSaved -> {out}")


if __name__ == "__main__":
    main()
