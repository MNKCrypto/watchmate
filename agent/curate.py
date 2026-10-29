"""Curate a personalised highlight reel for one fan.

Muse Spark gets the fan's preferences, the moment timeline (context) and every
segment's observation (detail), and picks precise clips: the best window INSIDE each
relevant moment, not the whole moment. Code then enforces the rules (in range,
padding, no overlaps, time budget) and writes:

    data/reels/<video_id>/<profile>/reel.json        clips, reasons, recap
    data/reels/<video_id>/<profile>/playlist.m3u8    streamable reel (points at existing segments)
    data/reels/<video_id>/<profile>/reel.mp4         single file for any player (and WhatsApp)

Usage:
    python -m agent.curate --profile profiles/engineer.json            # picks, self-checks, exports reel.mp4
    python -m agent.curate --profile profiles/casual_fan.json --no-verify
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from pathlib import Path

from common.muse import get_client, parse_json
from timeline.build import compact_line, fmt_time

PROMPT = """You are Watchmate, a personal highlights agent. You watched a whole broadcast for a fan
and now cut their personal reel.

FAN PREFERENCES:
{preferences}

TIME BUDGET: at most {max_seconds} seconds in total = {max_segments} segments (each segment is 6 seconds).
The budget is hard: count the segments of every clip and make sure the total fits. No padding is added later.

BROADCAST MOMENTS (context; segment ranges are inclusive):
{moments}

SEGMENT OBSERVATIONS (detail; idx | time | event | footage | excitement | key | on-screen text | speech | visual):
{lines}

Pick the clips this fan would want. Rules:
- A clip is a contiguous range of segments: start_seg..end_seg (inclusive), typically 2-6 segments.
- Choose the best window INSIDE a moment (the peak), not the whole moment.
- Respect the preferences strictly, including what to skip and live-vs-animation wishes.
- Each clip should start at its build-up and end after the action, so it feels complete.
  The single biggest payoff for this fan (e.g. a liftoff, a goal) deserves 3-5 segments including its build-up.
- Captions must describe only what the clip itself shows — don't promise an event that happens after the clip ends.
- Cover the variety of things the fan asked for; don't spend most of the budget on one moment.
- Stay within the time budget. Fewer great clips beat many average ones.
- Give each clip a priority: 1 = must-have, 2 = strong, 3 = nice-to-have.
- Base every choice on the observations; never invent events.
- The recap must only mention what is in the clips you return.

Return ONLY JSON:
{{
  "clips": [
    {{"start_seg": <idx>, "end_seg": <idx>, "priority": 1|2|3, "title": "short caption shown on the clip",
      "reason": "why this fan wants it, citing the evidence"}}
  ],
  "recap": "2-3 short sentences (max 60 words) written to the fan in second person; warm, no quotes, no jargon lists"
}}"""

RECAP_PROMPT = """Write a short personal recap for a fan, to send on WhatsApp.
Fan preferences: {preferences}

Their reel contains ONLY these clips, in order:
{clips}

Style: 2-3 short sentences, at most 60 words, warm and natural, second person ("you").
No quotes from the commentary, no lists of technical terms, no emojis.
Mention only what the captions describe (e.g. if a caption says people are recalling
something, don't say the fan saw it). Return ONLY the recap text."""


def moments_block(timeline: dict) -> str:
    return "\n".join(
        f"{m['id']} | segs {m['start_seg']}-{m['end_seg']} | {fmt_time(m['start'])}-{fmt_time(m['end'])} | "
        f"{m['type']} | {m['footage']} | excitement {m['excitement']} | {m['title']}: {m.get('summary', '')}"
        for m in timeline["moments"]
    )


def seg_count(c: dict) -> int:
    return c["end_seg"] - c["start_seg"] + 1


def enforce(clips: list[dict], n_segments: int, max_seconds: float, seg_len: float,
            pad: int = 0) -> tuple[list[dict], list[dict]]:
    """In range, optional padding, merged if touching, within budget.

    Over budget -> drop the lowest-priority clips (never cut a clip short, so no
    moment loses its payoff). Returns (kept, dropped).
    """
    norm = []
    for c in clips:
        try:
            s, e = int(c["start_seg"]), int(c["end_seg"])
        except (KeyError, TypeError, ValueError):
            continue
        s, e = max(0, min(s, e) - pad), min(n_segments - 1, max(s, e) + pad)
        prio = c.get("priority", 2)
        norm.append({**c, "start_seg": s, "end_seg": e,
                     "priority": prio if isinstance(prio, int) and 1 <= prio <= 3 else 2})
    norm.sort(key=lambda c: c["start_seg"])

    merged: list[dict] = []
    for c in norm:
        if merged and c["start_seg"] <= merged[-1]["end_seg"] + 1:
            last = merged[-1]
            last["end_seg"] = max(last["end_seg"], c["end_seg"])
            last["title"] = f"{last['title']} / {c['title']}"
            last["reason"] = f"{last.get('reason', '')} {c.get('reason', '')}".strip()
            last["priority"] = min(last["priority"], c["priority"])
        else:
            merged.append(dict(c))

    budget = int(max_seconds // seg_len)
    kept, dropped = list(merged), []
    # drop lowest priority first; among equals, the longest (frees most time)
    while sum(seg_count(c) for c in kept) > budget and len(kept) > 1:
        victim = max(kept, key=lambda c: (c["priority"], seg_count(c)))
        kept.remove(victim)
        dropped.append(victim)
    if kept and seg_count(kept[0]) > budget:  # a single clip longer than the whole budget
        kept[0]["end_seg"] = kept[0]["start_seg"] + budget - 1
    return kept, dropped


def rewrite_recap(client, model: str, preferences: str, clips: list[dict]) -> str:
    listing = "\n".join(f"- {c['title']}" for c in clips)
    resp = client.responses.create(
        model=model,
        input=[{"role": "user", "content": [{"type": "input_text",
                "text": RECAP_PROMPT.format(preferences=preferences, clips=listing)}]}],
        reasoning={"effort": "low"},
        max_output_tokens=2000,
    )
    return resp.output_text.strip()


def write_playlist(clips: list[dict], manifest: dict, video_dir: Path, out_dir: Path) -> Path:
    """HLS playlist pointing at the already-encoded segments; a discontinuity marks each cut."""
    segs = manifest["segments"]
    target = max(int(seg["duration"] + 0.999) for seg in segs)
    lines = ["#EXTM3U", "#EXT-X-VERSION:3", f"#EXT-X-TARGETDURATION:{target}",
             "#EXT-X-MEDIA-SEQUENCE:0", "#EXT-X-PLAYLIST-TYPE:VOD"]
    for i, c in enumerate(clips):
        if i > 0:
            lines.append("#EXT-X-DISCONTINUITY")
        for idx in range(c["start_seg"], c["end_seg"] + 1):
            seg = segs[idx]
            rel = os.path.relpath(video_dir / seg["hls"], out_dir)
            lines += [f"#EXTINF:{seg['duration']:.3f},", rel]
    lines.append("#EXT-X-ENDLIST")
    path = out_dir / "playlist.m3u8"
    path.write_text("\n".join(lines) + "\n")
    return path


def export_mp4(playlist: Path) -> Path:
    out = playlist.with_name("reel.mp4")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-allowed_extensions", "ALL",
                    "-i", str(playlist), "-c", "copy", "-bsf:a", "aac_adtstoasc", str(out)], check=True)
    return out


def build_reel(profile: dict, video_dir: Path, model: str = "muse-spark-1.3",
               reasoning_effort: str = "medium", pad: int = 0, verify: bool = True,
               export: bool = True, log=print) -> dict:
    """Full agent flow for one fan: pick clips -> enforce rules -> self-check -> write reel."""
    from agent.verify import verify_clips  # local import: verify imports timeline helpers too

    manifest = json.loads((video_dir / "manifest.json").read_text())
    timeline = json.loads((video_dir / "timeline.json").read_text())
    rows = sorted((json.loads(l) for l in (video_dir / "observations.jsonl").read_text().splitlines()
                   if l.strip()), key=lambda r: r["index"])
    seg_len = manifest["segment_seconds"]
    budget_segments = int(profile["max_seconds"] // seg_len)
    segs = manifest["segments"]

    prompt = PROMPT.format(preferences=profile["preferences"], max_seconds=profile["max_seconds"],
                           max_segments=budget_segments,
                           moments=moments_block(timeline), lines="\n".join(compact_line(r) for r in rows))
    log(f"Curating for {profile['display_name']} ({profile['max_seconds']}s budget) with {model} ...")

    client = get_client()
    t0 = time.time()
    resp = client.responses.create(
        model=model,
        input=[{"role": "user", "content": [{"type": "input_text", "text": prompt}]}],
        reasoning={"effort": reasoning_effort},
        max_output_tokens=16000,
    )
    data = parse_json(resp.output_text)
    if not data or "clips" not in data:
        raise RuntimeError(f"Model did not return valid JSON:\n{resp.output_text[:2000]}")

    proposed = json.loads(json.dumps(data["clips"]))  # the model's original picks, for debugging
    clips, dropped = enforce(data["clips"], len(segs), profile["max_seconds"], seg_len, pad=pad)
    recap_stale = bool(dropped)

    verification = []
    if verify:
        log(f"Self-check: re-watching {len(clips)} clips ...")
        before = [(c["start_seg"], c["end_seg"], c["title"]) for c in clips]
        clips, verification = verify_clips(client, clips, profile["preferences"], budget_segments,
                                           video_dir, manifest, rows, log=log)
        # any replaced, dropped or retitled clip means the recap may no longer be accurate
        recap_stale |= [(c["start_seg"], c["end_seg"], c["title"]) for c in clips] != before

    for c in clips + dropped:
        c["start"], c["end"] = segs[c["start_seg"]]["start"], segs[c["end_seg"]]["end"]

    recap = data.get("recap", "")
    if recap_stale and clips:  # the model's recap may mention clips that are no longer in the reel
        recap = rewrite_recap(client, model, profile["preferences"], clips)

    out_dir = Path("data/reels") / manifest["video_id"] / profile["name"]
    out_dir.mkdir(parents=True, exist_ok=True)
    playlist = write_playlist(clips, manifest, video_dir, out_dir)
    total = sum(c["end"] - c["start"] for c in clips)
    reel = {"profile": profile, "video_id": manifest["video_id"], "title": timeline.get("title", ""),
            "model": model,
            "total_seconds": round(total, 1), "recap": recap, "clips": clips,
            "dropped": dropped, "proposed": proposed, "verification": verification,
            "playlist": str(playlist), "seconds_taken": round(time.time() - t0, 1)}
    if export and clips:
        reel["mp4"] = str(export_mp4(playlist))
    (out_dir / "reel.json").write_text(json.dumps(reel, indent=2))
    return reel


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--profile", type=Path, required=True)
    p.add_argument("--video-dir", type=Path, default=Path("data/processed/artemis_demo"))
    p.add_argument("--model", default="muse-spark-1.3")
    p.add_argument("--reasoning-effort", default="medium", choices=["minimal", "low", "medium", "high"])
    p.add_argument("--no-verify", action="store_true", help="skip the self-check")
    p.add_argument("--no-mp4", action="store_true", help="don't export reel.mp4")
    p.add_argument("--pad", type=int, default=0, help="extra segments added before/after each clip")
    args = p.parse_args()

    profile = json.loads(args.profile.read_text())
    reel = build_reel(profile, args.video_dir, args.model, args.reasoning_effort, args.pad,
                      verify=not args.no_verify, export=not args.no_mp4)

    print()
    for c in reel["clips"]:
        tag = f" (replaces '{c['replaces']}')" if c.get("replaces") else ""
        print(f"  P{c['priority']} {fmt_time(c['start'])}-{fmt_time(c['end'])}  {c['title']}{tag}\n"
              f"      why: {c.get('reason', '')}")
    for c in reel["dropped"]:
        print(f"  DROPPED (over budget) P{c['priority']} {fmt_time(c['start'])}-{fmt_time(c['end'])}  {c['title']}")
    print(f"\nReel: {len(reel['clips'])} clips, {reel['total_seconds']:.0f}s of "
          f"{profile['max_seconds']}s budget, built in {reel['seconds_taken']:.0f}s")
    print(f"Recap: {reel['recap']}\n")
    print(f"Playlist -> {reel['playlist']}")
    if reel.get("mp4"):
        print(f"MP4      -> {reel['mp4']}")


if __name__ == "__main__":
    main()
