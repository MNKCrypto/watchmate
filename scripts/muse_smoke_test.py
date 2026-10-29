"""First contact with Muse Spark: send a few segments, look at what comes back.

Checks, before we build anything on top of the model:
  - does video (with its audio track) go through the API the way the docs describe?
  - how good is the description / transcript for a 6s segment?
  - latency and token usage per segment (-> cost of the full 600-segment run)

Usage:
    python -m scripts.muse_smoke_test
    python -m scripts.muse_smoke_test --segments 80,183,300 --model muse-spark-1.2
    python -m scripts.muse_smoke_test --mode dataurl      # if Files API upload fails

Results are saved to data/experiments/smoke_<timestamp>.json
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

BASE_URL = "https://api.meta.ai/v1"

# Default picks from the Artemis clip: countdown clock (~8:00), liftoff (~18:22), firing-room speech (~30:00)
DEFAULT_SEGMENTS = "80,183,300"

PROMPT = """You are watching a 6-second segment of a live broadcast. Use both the video and its audio.
Return ONLY a JSON object with these fields:
{
  "visual": "what is visible on screen, concretely (subjects, action, on-screen text)",
  "speech": "what is said in the audio, transcribed as closely as you can ('' if none)",
  "event": "one short label for what is happening, e.g. 'countdown', 'liftoff', 'speech', 'studio interview'",
  "is_key_moment": true or false,
  "confidence": a number from 0 to 1
}"""


def video_part(client: OpenAI, path: Path, mode: str) -> dict:
    if mode == "upload":
        with path.open("rb") as f:
            uploaded = client.files.create(file=f, purpose="user_data")
        return {"type": "input_file", "file_id": uploaded.id}
    data = base64.b64encode(path.read_bytes()).decode()
    return {"type": "input_video", "video_url": f"data:video/mp4;base64,{data}"}


def parse_json(text: str) -> dict | None:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`").removeprefix("json").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--manifest", type=Path,
                   default=Path("data/processed/artemis_demo/manifest.json"))
    p.add_argument("--segments", default=DEFAULT_SEGMENTS, help="comma-separated indexes")
    # 1.2 because Meta's docs say audio understanding in 1.3 is not fully supported yet
    p.add_argument("--model", default="muse-spark-1.2")
    p.add_argument("--mode", choices=["upload", "dataurl"], default="upload")
    args = p.parse_args()

    load_dotenv()
    key = os.environ.get("MODEL_API_KEY")
    if not key:
        sys.exit("MODEL_API_KEY is not set. Add it to .env (see .env.example).")
    client = OpenAI(base_url=BASE_URL, api_key=key)

    manifest = json.loads(args.manifest.read_text())
    root = args.manifest.parent
    results = []

    for idx in (int(s) for s in args.segments.split(",")):
        seg = manifest["segments"][idx]
        path = root / seg["analysis"]
        print(f"\n=== segment {idx}  ({seg['start']:.0f}s – {seg['end']:.0f}s)  {path.name}")

        t0 = time.time()
        try:
            part = video_part(client, path, args.mode)
            resp = client.responses.create(
                model=args.model,
                input=[{"role": "user", "content": [
                    {"type": "input_text", "text": PROMPT}, part,
                ]}],
            )
        except Exception as e:  # show the API's actual complaint, keep going
            print(f"  ERROR: {type(e).__name__}: {e}")
            results.append({"segment": idx, "error": f"{type(e).__name__}: {e}"})
            continue
        latency = time.time() - t0

        usage = resp.usage
        parsed = parse_json(resp.output_text)
        print(f"  latency {latency:.1f}s | tokens in {usage.input_tokens} / out {usage.output_tokens}")
        print(json.dumps(parsed, indent=2) if parsed else f"  (not JSON) {resp.output_text[:500]}")

        results.append({
            "segment": idx, "start": seg["start"], "end": seg["end"],
            "latency_s": round(latency, 2),
            "input_tokens": usage.input_tokens, "output_tokens": usage.output_tokens,
            "parsed": parsed, "raw": resp.output_text,
        })

    ok = [r for r in results if "error" not in r]
    if ok:
        avg_in = sum(r["input_tokens"] for r in ok) / len(ok)
        avg_out = sum(r["output_tokens"] for r in ok) / len(ok)
        avg_lat = sum(r["latency_s"] for r in ok) / len(ok)
        n = manifest["segment_count"]
        print(f"\nAverage per segment: {avg_in:.0f} in / {avg_out:.0f} out tokens, {avg_lat:.1f}s")
        print(f"Full video ({n} segments): ~{avg_in * n / 1e6:.2f}M in / {avg_out * n / 1e6:.2f}M out tokens, "
              f"~{avg_lat * n / 60:.0f} min if run one at a time")

    out = Path("data/experiments") / f"smoke_{datetime.now():%Y%m%d_%H%M%S}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"model": args.model, "mode": args.mode, "results": results}, indent=2))
    print(f"\nSaved -> {out}")


if __name__ == "__main__":
    main()
