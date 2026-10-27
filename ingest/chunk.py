"""Split a long video into fixed-length segments for Watchmate.

One encode produces two views of the same segments:

  hls/        index.m3u8 + seg_00000.ts ...   -> streamed to the viewer (reels are playlists of these)
  analysis/   seg_00000.mp4 ...               -> sent to Muse Spark (the API takes MP4)

plus:

  audio.mp3        whole-video mono audio for Muse Voice Transcribe
  manifest.json    one entry per segment with exact start/end times

Keyframes are forced at every segment boundary so each segment starts cleanly and
any subset of segments can be stitched into a highlight playlist later.

Usage:
    python -m ingest.chunk data/raw/artemis_demo.mp4
    python -m ingest.chunk data/raw/artemis_demo.mp4 --segment-seconds 6 --out data/processed
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

MIN_ANALYZE_SECONDS = 1.0


def require_tools() -> None:
    missing = [t for t in ("ffmpeg", "ffprobe") if shutil.which(t) is None]
    if missing:
        sys.exit(f"Missing required tool(s): {', '.join(missing)}. Install ffmpeg first.")


def run(cmd: list[str]) -> str:
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        sys.exit(f"Command failed: {' '.join(cmd)}\n{result.stderr[-2000:]}")
    return result.stdout


def probe(path: Path) -> dict:
    out = run([
        "ffprobe", "-v", "error", "-print_format", "json",
        "-show_format", "-show_streams", str(path),
    ])
    return json.loads(out)


def segment_hls(src: Path, hls_dir: Path, seconds: int) -> None:
    """Re-encode once with a keyframe forced every `seconds`, cut into HLS .ts segments."""
    hls_dir.mkdir(parents=True, exist_ok=True)
    run([
        "ffmpeg", "-y", "-v", "error", "-i", str(src),
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
        "-force_key_frames", f"expr:gte(t,n_forced*{seconds})",
        "-sc_threshold", "0",          # no extra keyframes on scene cuts -> even segments
        "-c:a", "aac", "-b:a", "128k", "-ac", "2",
        "-f", "hls",
        "-hls_time", str(seconds),
        "-hls_playlist_type", "vod",
        "-hls_segment_filename", str(hls_dir / "seg_%05d.ts"),
        str(hls_dir / "index.m3u8"),
    ])


def parse_playlist(m3u8: Path) -> list[tuple[str, float]]:
    """Return (segment filename, duration) pairs in playlist order."""
    entries, duration = [], None
    for line in m3u8.read_text().splitlines():
        m = re.match(r"#EXTINF:([\d.]+)", line)
        if m:
            duration = float(m.group(1))
        elif line and not line.startswith("#") and duration is not None:
            entries.append((line.strip(), duration))
            duration = None
    return entries


def remux_to_mp4(ts_path: Path, mp4_path: Path) -> None:
    """Copy a .ts segment into an .mp4 container (no re-encode, fast)."""
    run([
        "ffmpeg", "-y", "-v", "error", "-i", str(ts_path),
        "-c", "copy", "-bsf:a", "aac_adtstoasc",
        "-movflags", "+faststart", str(mp4_path),
    ])


def extract_audio(src: Path, audio_path: Path) -> None:
    """Mono 16 kHz MP3 — small, and plenty for speech transcription."""
    run([
        "ffmpeg", "-y", "-v", "error", "-i", str(src),
        "-vn", "-ac", "1", "-ar", "16000", "-c:a", "libmp3lame", "-b:a", "48k",
        str(audio_path),
    ])


def chunk(src: Path, out_root: Path, seconds: int, video_id: str | None) -> Path:
    require_tools()
    if not src.exists():
        sys.exit(f"Input not found: {src}")

    video_id = video_id or src.stem
    out_dir = out_root / video_id
    hls_dir, analysis_dir = out_dir / "hls", out_dir / "analysis"
    analysis_dir.mkdir(parents=True, exist_ok=True)

    info = probe(src)
    source_duration = float(info["format"]["duration"])
    print(f"[1/4] Source: {src.name} ({source_duration / 60:.1f} min)")

    print(f"[2/4] Encoding {seconds}s HLS segments ...")
    segment_hls(src, hls_dir, seconds)
    playlist = parse_playlist(hls_dir / "index.m3u8")

    print(f"[3/4] Creating {len(playlist)} MP4 copies for analysis ...")
    segments, t = [], 0.0
    for i, (ts_name, dur) in enumerate(playlist):
        mp4_name = Path(ts_name).with_suffix(".mp4").name
        remux_to_mp4(hls_dir / ts_name, analysis_dir / mp4_name)
        segments.append({
            "index": i,
            "start": round(t, 3),
            "end": round(t + dur, 3),
            "duration": round(dur, 3),
            "hls": f"hls/{ts_name}",
            "analysis": f"analysis/{mp4_name}",
            # a tiny leftover at the end isn't worth a model call
            "analyze": dur >= MIN_ANALYZE_SECONDS,
        })
        t += dur

    print("[4/4] Extracting audio for transcription ...")
    extract_audio(src, out_dir / "audio.mp3")

    v = next((s for s in info["streams"] if s["codec_type"] == "video"), {})
    manifest = {
        "video_id": video_id,
        "source": str(src),
        "source_duration": round(source_duration, 3),
        "resolution": f"{v.get('width')}x{v.get('height')}",
        "segment_seconds": seconds,
        "segment_count": len(segments),
        "playlist": "hls/index.m3u8",
        "audio": "audio.mp3",
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "segments": segments,
    }
    manifest_path = out_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2))

    drift = abs(t - source_duration)
    print(f"Done: {len(segments)} segments, {t / 60:.1f} min covered "
          f"(drift {drift:.2f}s) -> {manifest_path}")
    return manifest_path


def main() -> None:
    p = argparse.ArgumentParser(description="Split a video into segments for Watchmate.")
    p.add_argument("input", type=Path, help="source video, e.g. data/raw/artemis_demo.mp4")
    p.add_argument("--out", type=Path, default=Path("data/processed"), help="output root")
    p.add_argument("--segment-seconds", type=int, default=6, help="segment length (default 6)")
    p.add_argument("--video-id", help="folder name for outputs (default: input file name)")
    args = p.parse_args()
    chunk(args.input, args.out, args.segment_seconds, args.video_id)


if __name__ == "__main__":
    main()
