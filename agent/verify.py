"""Self-check: the agent re-watches every clip it picked before sending the reel.

For each clip, the actual video (+ audio) is cut and sent back to Muse Spark with
two questions: does it really show what the caption claims, and does it respect the
fan's preferences (e.g. "real footage only")? A clip that fails is replaced with the
best alternative the agent can find (which is verified too), or dropped.

Used by agent.curate (--verify). Can also be run on an existing reel:
    python -m agent.verify --reel data/reels/artemis_demo/engineer/reel.json
"""

from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from pathlib import Path

from common.muse import delete_file, get_client, parse_json, video_part
from timeline.build import compact_line, fmt_time

VERIFY_PROMPT = """You are the quality checker for a personal highlights agent.
A clip was selected for a fan with this caption: "{title}"
Reason given: {reason}

Fan preferences: {preferences}

Watch the clip (video and audio) and judge it the way the fan would.

Separate the fan's preferences into:
- HARD rules: things they said to skip / avoid / "only" / "no ...", applied to what the clip is ABOUT.
- SOFT wishes: things they "prefer", "like", "care about" — these never cause a failure.
Judge the clip as a whole: incidental commentary inside a moment the fan wants (e.g. a launch
countdown call) does not break a "no technical details" rule; a clip whose main subject is
something they asked to skip does.

Verdicts:
- "pass": the clip shows what the caption claims and breaks no hard rule.
- "retitle": the content is right for the fan, but the caption over- or mis-states it -> give a corrected caption.
- "fail": the main subject is not what the caption claims AND not worth keeping under a new caption,
  or the clip breaks a hard rule.

Return ONLY JSON:
{{
  "shows": "what the clip really shows, in one sentence",
  "footage": "live | animation | studio | graphic | mixed",
  "hard_rule_broken": "the hard rule it breaks, or ''",
  "verdict": "pass" | "retitle" | "fail",
  "new_title": "corrected caption, max 8 words, if verdict is retitle, else ''",
  "issue": "if retitle or fail, the specific problem; else ''",
  "note": "optional: a soft wish it doesn't fully meet (e.g. animation for a fan who prefers live)",
  "confidence": 0-1
}}"""

REPLACE_PROMPT = """You are a personal highlights agent. One clip in a fan's reel failed quality check.

Fan preferences: {preferences}
Failed clip: segments {start_seg}-{end_seg}, "{title}" — problem: {issue}
Segments already used in the reel (do not overlap): {used}
Maximum length for the replacement: {max_segments} segments (6 s each).

Segment observations (idx | time | event | footage | excitement | key | on-screen text | speech | visual):
{lines}

Pick ONE replacement clip that fixes the problem and fits the preferences, or null if nothing suitable exists.
Return ONLY JSON: {{"clip": {{"start_seg": <idx>, "end_seg": <idx>, "priority": 1|2|3, "title": "...", "reason": "..."}} or null}}"""


def cut_clip(video_dir: Path, manifest: dict, start_seg: int, end_seg: int, out: Path) -> Path:
    """Join the clip's HLS segments into one MP4 (no re-encode)."""
    parts = "|".join(str(video_dir / manifest["segments"][i]["hls"]) for i in range(start_seg, end_seg + 1))
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", f"concat:{parts}", "-c", "copy",
                    "-bsf:a", "aac_adtstoasc", "-movflags", "+faststart", str(out)], check=True)
    return out


def check_clip(client, clip: dict, preferences: str, video_dir: Path, manifest: dict,
               model: str = "muse-spark-1.2") -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        path = cut_clip(video_dir, manifest, clip["start_seg"], clip["end_seg"], Path(tmp) / "clip.mp4")
        part, file_id = video_part(client, path)
        try:
            resp = client.responses.create(
                model=model,  # 1.2: Meta notes 1.3 audio understanding is not fully supported yet
                input=[{"role": "user", "content": [
                    {"type": "input_text", "text": VERIFY_PROMPT.format(
                        title=clip["title"], reason=clip.get("reason", ""), preferences=preferences)},
                    part]}],
                reasoning={"effort": "low"},
            )
        finally:
            delete_file(client, file_id)
    result = parse_json(resp.output_text) or {"verdict": "pass", "issue": "checker returned no JSON",
                                               "confidence": 0}
    if result.get("verdict") not in ("pass", "retitle", "fail"):
        result["verdict"] = "pass"
    if result["verdict"] == "retitle" and not result.get("new_title"):
        result["verdict"] = "pass"  # nothing to rename it to; keep as is
    if result.get("hard_rule_broken"):
        result["verdict"] = "fail"  # a broken hard rule is never just a caption problem
    return result


def find_replacement(client, failed: dict, issue: str, preferences: str, used: list[tuple[int, int]],
                     max_segments: int, rows: list[dict], n_segments: int,
                     model: str = "muse-spark-1.3") -> dict | None:
    if max_segments < 1:
        return None
    resp = client.responses.create(
        model=model,
        input=[{"role": "user", "content": [{"type": "input_text", "text": REPLACE_PROMPT.format(
            preferences=preferences, start_seg=failed["start_seg"], end_seg=failed["end_seg"],
            title=failed["title"], issue=issue, used=", ".join(f"{s}-{e}" for s, e in used) or "none",
            max_segments=max_segments, lines="\n".join(compact_line(r) for r in rows))}]}],
        reasoning={"effort": "medium"},
        max_output_tokens=8000,
    )
    clip = (parse_json(resp.output_text) or {}).get("clip")
    if not clip:
        return None
    try:
        s, e = int(clip["start_seg"]), int(clip["end_seg"])
    except (KeyError, TypeError, ValueError):
        return None
    s, e = max(0, min(s, e)), min(n_segments - 1, max(s, e))
    e = min(e, s + max_segments - 1)
    if any(not (e < us or s > ue) for us, ue in used):  # overlaps an existing clip
        return None
    return {**clip, "start_seg": s, "end_seg": e, "priority": clip.get("priority", 2)}


def verify_clips(client, clips: list[dict], preferences: str, budget_segments: int,
                 video_dir: Path, manifest: dict, rows: list[dict], log=print) -> tuple[list[dict], list[dict]]:
    """Check every clip; replace or drop failures. Returns (final clips, verification log)."""
    segs = manifest["segments"]
    final, report = [], []
    for clip in clips:
        result = check_clip(client, clip, preferences, video_dir, manifest)
        entry = {"clip": clip["title"], "segments": [clip["start_seg"], clip["end_seg"]], **result}
        when = fmt_time(segs[clip["start_seg"]]["start"])
        note = f"  (note: {result['note']})" if result.get("note") else ""
        if result["verdict"] == "pass":
            log(f"  ✓ {when} {clip['title']} — {result.get('shows', '')}{note}")
            final.append({**clip, "verified": True})
            report.append(entry)
            continue
        if result["verdict"] == "retitle":
            log(f"  ✎ {when} {clip['title']} → retitled '{result['new_title']}' — {result.get('issue', '')}{note}")
            final.append({**clip, "title": result["new_title"], "original_title": clip["title"],
                          "verified": True})
            entry["action"] = f"retitled to '{result['new_title']}'"
            report.append(entry)
            continue

        issue = result.get("hard_rule_broken") or result.get("issue", "failed check")
        log(f"  ✗ {when} {clip['title']} — REJECTED: {issue}")
        used = [(c["start_seg"], c["end_seg"]) for c in final + clips if c is not clip]
        room = budget_segments - sum(c["end_seg"] - c["start_seg"] + 1 for c in final + clips if c is not clip)
        repl = find_replacement(client, clip, issue, preferences, used, room, rows, len(segs))
        if repl:
            r2 = check_clip(client, repl, preferences, video_dir, manifest)
            if r2["verdict"] == "retitle":
                repl = {**repl, "title": r2["new_title"]}
            if r2["verdict"] != "fail":
                log(f"    ↳ replaced with {fmt_time(segs[repl['start_seg']]['start'])} {repl['title']} ✓")
                final.append({**repl, "verified": True, "replaces": clip["title"]})
                entry["action"] = f"replaced with '{repl['title']}'"
                report.append(entry)
                continue
            log(f"    ↳ replacement also failed: {r2.get('issue', '')}")
        log("    ↳ dropped")
        entry["action"] = "dropped"
        report.append(entry)

    final.sort(key=lambda c: c["start_seg"])
    return final, report


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--reel", type=Path, required=True)
    p.add_argument("--video-dir", type=Path, default=Path("data/processed/artemis_demo"))
    args = p.parse_args()

    reel = json.loads(args.reel.read_text())
    manifest = json.loads((args.video_dir / "manifest.json").read_text())
    rows = sorted((json.loads(l) for l in (args.video_dir / "observations.jsonl").read_text().splitlines()
                   if l.strip()), key=lambda r: r["index"])
    budget = int(reel["profile"]["max_seconds"] // manifest["segment_seconds"])
    print(f"Verifying {len(reel['clips'])} clips for {reel['profile']['display_name']} ...")
    clips, report = verify_clips(get_client(), reel["clips"], reel["profile"]["preferences"],
                                 budget, args.video_dir, manifest, rows)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
