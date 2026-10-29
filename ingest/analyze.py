"""Watch every segment with Muse Spark and record what happens in it.

For each segment in manifest.json, sends the MP4 (video + audio) to Muse Spark and
saves a structured observation to:

    data/processed/<video_id>/observations/seg_00000.json

Runs segments in parallel, retries on rate limits / transient errors, and skips
segments that already have a result — so it can be stopped and resumed without
paying twice. At the end everything is merged into observations.jsonl (time order).

Usage:
    python -m ingest.analyze                                   # all segments, 8 in parallel
    python -m ingest.analyze --segments 80,183,300             # just a few
    python -m ingest.analyze --segments 80,183,300 --reasoning-effort low --tag low
"""

from __future__ import annotations

import argparse
import json
import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import openai

from common.muse import delete_file, get_client, parse_json, video_part

PROMPT = """You are watching one 6-second segment of a long live broadcast, at {start} into the video.
Use BOTH the video and its audio. Be concrete and factual; do not guess beyond what you see or hear.

Return ONLY a JSON object:
{{
  "visual": "what is on screen: subjects, action, camera view",
  "speech": "what is said in the audio, transcribed as closely as possible ('' if none)",
  "on_screen_text": "any readable text or clocks, exactly as shown, including +/- signs ('' if none)",
  "event": "short label for what is happening, e.g. 'countdown', 'engine ignition', 'liftoff', 'booster separation', 'crowd reaction', 'celebration', 'studio interview', 'mission control'",
  "footage": "live | animation | graphic | studio | mixed",
  "tags": ["3-8 lowercase keywords a viewer might search for"],
  "excitement": a number 0-10 for how much a typical viewer would want to see this,
  "is_key_moment": true or false,
  "confidence": a number 0-1
}}"""

RETRYABLE = (openai.RateLimitError, openai.APIConnectionError,
             openai.APITimeoutError, openai.InternalServerError)


def fmt_time(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    return f"{m:02d}:{s:02d}"


def analyze_segment(client, seg: dict, root: Path, model: str, effort: str | None,
                    mode: str, retries: int = 5) -> dict:
    path = root / seg["analysis"]
    prompt = PROMPT.format(start=fmt_time(seg["start"]))
    for attempt in range(retries):
        file_id = None
        try:
            t0 = time.time()
            part, file_id = video_part(client, path, mode)
            kwargs = {"reasoning": {"effort": effort}} if effort else {}
            resp = client.responses.create(
                model=model,
                input=[{"role": "user", "content": [{"type": "input_text", "text": prompt}, part]}],
                **kwargs,
            )
            return {
                "index": seg["index"], "start": seg["start"], "end": seg["end"],
                "observation": parse_json(resp.output_text),
                "raw": resp.output_text,
                "model": model, "reasoning_effort": effort,
                "latency_s": round(time.time() - t0, 2),
                "input_tokens": resp.usage.input_tokens,
                "output_tokens": resp.usage.output_tokens,
            }
        except RETRYABLE as e:
            wait = min(60, 2 ** attempt * 2) + random.random()
            print(f"  seg {seg['index']}: {type(e).__name__}, retry {attempt + 1}/{retries} in {wait:.0f}s")
            time.sleep(wait)
        finally:
            delete_file(client, file_id)
    raise RuntimeError(f"segment {seg['index']} failed after {retries} retries")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--manifest", type=Path, default=Path("data/processed/artemis_demo/manifest.json"))
    p.add_argument("--segments", help="comma-separated indexes (default: all)")
    p.add_argument("--model", default="muse-spark-1.2")
    p.add_argument("--reasoning-effort", choices=["minimal", "low", "medium", "high"],
                   help="lower = cheaper/faster; default is the model's own default")
    p.add_argument("--workers", type=int, default=8, help="parallel requests")
    p.add_argument("--mode", choices=["upload", "dataurl"], default="upload")
    p.add_argument("--tag", default="", help="suffix for the output folder, to compare settings")
    p.add_argument("--force", action="store_true", help="redo segments that already have results")
    args = p.parse_args()

    manifest = json.loads(args.manifest.read_text())
    root = args.manifest.parent
    out_dir = root / (f"observations_{args.tag}" if args.tag else "observations")
    out_dir.mkdir(exist_ok=True)

    segs = [s for s in manifest["segments"] if s.get("analyze", True)]
    if args.segments:
        wanted = {int(x) for x in args.segments.split(",")}
        segs = [s for s in segs if s["index"] in wanted]
    todo = [s for s in segs if args.force or not (out_dir / f"seg_{s['index']:05d}.json").exists()]
    print(f"{len(segs)} segments selected, {len(segs) - len(todo)} already done, {len(todo)} to analyze "
          f"({args.model}, effort={args.reasoning_effort or 'default'}, {args.workers} workers)")

    client = get_client()
    lock = threading.Lock()
    done = failed = tok_in = tok_out = 0
    t_start = time.time()

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(analyze_segment, client, s, root, args.model,
                               args.reasoning_effort, args.mode): s for s in todo}
        for fut in as_completed(futures):
            seg = futures[fut]
            try:
                r = fut.result()
            except Exception as e:
                with lock:
                    failed += 1
                print(f"  seg {seg['index']}: FAILED {e}")
                continue
            (out_dir / f"seg_{seg['index']:05d}.json").write_text(json.dumps(r, indent=2))
            with lock:
                done += 1
                tok_in += r["input_tokens"]
                tok_out += r["output_tokens"]
                obs = r["observation"] or {}
                flag = " *" if obs.get("is_key_moment") else ""
                print(f"  [{done}/{len(todo)}] {fmt_time(r['start'])} {obs.get('event', '?')}{flag}")

    # merge everything (old + new) into one time-ordered file
    rows = sorted((json.loads(f.read_text()) for f in out_dir.glob("seg_*.json")), key=lambda r: r["start"])
    merged = out_dir.parent / f"{out_dir.name}.jsonl"
    merged.write_text("".join(json.dumps(r) + "\n" for r in rows))

    mins = (time.time() - t_start) / 60
    print(f"\nDone in {mins:.1f} min: {done} analyzed, {failed} failed. "
          f"Tokens this run: {tok_in / 1000:.1f}K in / {tok_out / 1000:.1f}K out")
    print(f"Merged {len(rows)} observations -> {merged}")
    if failed:
        print("Re-run the same command to retry the failed segments.")


if __name__ == "__main__":
    main()
