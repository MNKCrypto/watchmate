"""Phone-friendly 9:16 version of a reel that follows the action, using SAM 3.1.

For each clip:
  1. a small proxy (10 fps, 640 px wide) is sent to SAM 3.1 with the clip's subject ("rocket")
  2. SAM returns a box around the subject for every frame
  3. the box centres are smoothed into a camera path
  4. ffmpeg cuts a 9:16 window that pans along that path from the full-quality clip
If SAM finds nothing, the clip falls back to a centre crop.
"""

from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path

from agent.verify import cut_clip
from common.muse import delete_file, get_client

PROXY_FPS = 10
PROXY_WIDTH = 640
OUT_W, OUT_H = 720, 1280
BOX = re.compile(r"<\|box;([^|]*)\|>")
MIN_COVERAGE = 0.3   # below this, retry with a simpler subject
FALLBACKS = ["rocket", "person"]


def fallback_subjects(subject: str, alternates: list[str] | None = None, max_tries: int = 3) -> list[str]:
    """What to ask SAM for, in order: the agent's subject, the agent's own alternates for this scene
    (e.g. 'exhaust plume' for a night launch), then a generic noun. Capped at max_tries."""
    words = [w for w in re.findall(r"[a-zA-Z]+", subject.lower()) if len(w) > 2]
    people = {"director", "host", "hosts", "astronaut", "astronauts", "commentator", "anchor", "team", "crowd",
              "people", "man", "woman", "speaker", "presenter", "reporter", "engineer", "engineers", "player"}
    generic = ["person", "rocket"] if people & set(words) else FALLBACKS
    tries = []
    for cand in [subject, *(alternates or []), *generic]:
        cand = (cand or "").strip()
        if cand and cand.lower() not in [t.lower() for t in tries]:
            tries.append(cand)
    return tries[:max_tries]


def _proxy(src: Path, out: Path) -> Path:
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(src), "-an",
                    "-vf", f"fps={PROXY_FPS},scale={PROXY_WIDTH}:-2", "-c:v", "libx264", "-preset", "veryfast",
                    "-movflags", "+faststart", str(out)], check=True)
    return out


def parse_track(text: str) -> dict[int, float]:
    """SAM output -> {frame: subject centre x as a fraction of frame width} (most confident/largest box)."""
    centres = {}
    for line in text.splitlines():
        m = re.match(r"\s*<(\d+)f>", line)
        if not m:
            continue
        best, best_score = None, -1.0
        for fields in BOX.findall(line):
            kv = dict(p.split("=", 1) for p in fields.split(";") if "=" in p)
            try:
                x1, x2, w = float(kv["x1"]), float(kv["x2"]), float(kv["w"])
                y1, y2 = float(kv["y1"]), float(kv["y2"])
            except (KeyError, ValueError):
                continue
            score = float(kv.get("c", 1.0)) * (x2 - x1) * (y2 - y1)
            if score > best_score:
                best, best_score = (x1 + x2) / 2 / w, score
        if best is not None:
            centres[int(m.group(1))] = best
    return centres


def camera_path(centres: dict[int, float], n_frames: int, step: int = 5) -> list[tuple[float, float]]:
    """Smoothed keyframes [(seconds, centre_x_fraction)], every `step` proxy frames."""
    if not centres:
        return [(0.0, 0.5)]
    filled, last = [], next(iter(sorted(centres.items())))[1]
    for f in range(n_frames):
        last = centres.get(f, last)  # hold the last known position through gaps
        filled.append(last)
    smooth, alpha, cur = [], 0.15, filled[0]
    for v in filled:  # exponential smoothing: a steady camera, not a jittery one
        cur = cur + alpha * (v - cur)
        smooth.append(cur)
    return [(f / PROXY_FPS, smooth[f]) for f in range(0, n_frames, step)] + [((n_frames - 1) / PROXY_FPS, smooth[-1])]


def crop_expr(path: list[tuple[float, float]], src_w: int, crop_w: int) -> str:
    """Piecewise-linear ffmpeg expression for the crop's x position over time."""
    def x_at(c: float) -> float:
        return max(0.0, min(src_w - crop_w, c * src_w - crop_w / 2))
    if len(path) == 1:
        return f"{x_at(path[0][1]):.1f}"
    expr = f"{x_at(path[-1][1]):.1f}"
    for (t0, c0), (t1, c1) in reversed(list(zip(path, path[1:]))):
        x0, x1 = x_at(c0), x_at(c1)
        seg = f"{x0:.1f}+({x1 - x0:.1f})*(t-{t0:.2f})/{max(t1 - t0, 1e-3):.2f}"
        expr = f"if(lt(t,{t1:.2f}),{seg},{expr})"
    return expr


def track_subject(client, proxy: Path, subject: str) -> dict[int, float]:
    with proxy.open("rb") as f:
        uploaded = client.files.create(file=f, purpose="user_data")
    try:
        resp = client.responses.create(
            model="sam-3.1",
            input=[{"type": "message", "role": "user", "content": [
                {"type": "input_text", "text": subject},
                {"type": "input_video", "file_id": uploaded.id}]}],
            metadata={"include_confidence": "true", "mask_encoding": "one_bit"},
        )
    finally:
        delete_file(client, uploaded.id)
    return parse_track(resp.output_text)


def fit_clip(src: Path, out: Path) -> Path:
    """No reliable track: keep the whole 16:9 frame, centred over a blurred, zoomed copy of itself
    (the usual Reels/Shorts look), so nothing important is cropped away."""
    graph = (f"[0:v]split[a][b];"
             f"[a]scale={OUT_W}:{OUT_H}:force_original_aspect_ratio=increase,crop={OUT_W}:{OUT_H},"
             f"boxblur=20:2,eq=brightness=-0.08[bg];"
             f"[b]scale={OUT_W}:-2[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1[v]")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(src), "-filter_complex", graph,
                    "-map", "[v]", "-map", "0:a?", "-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
                    "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(out)], check=True)
    return out


def vertical_clip(src: Path, out: Path, path: list[tuple[float, float]]) -> Path:
    probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                            "stream=width,height", "-of", "csv=p=0", str(src)],
                           capture_output=True, text=True, check=True).stdout.strip().split(",")
    w, h = int(probe[0]), int(probe[1])
    crop_w = int(h * 9 / 16) // 2 * 2
    x = crop_expr(path, w, crop_w)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(src),
                    "-vf", f"crop={crop_w}:{h}:'{x}':0,scale={OUT_W}:{OUT_H}",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "22", "-c:a", "aac", "-b:a", "128k",
                    "-movflags", "+faststart", str(out)], check=True)
    return out


def make_vertical(reel: dict, video_dir: Path, manifest: dict, out: Path, log=print) -> tuple[Path, list[dict]]:
    """Build reel_vertical.mp4. Returns (path, per-clip tracking report)."""
    client = get_client()
    report = []
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        parts = []
        for i, c in enumerate(reel["clips"]):
            subject = c.get("subject") or "main subject"
            clip = cut_clip(video_dir, manifest, c["start_seg"], c["end_seg"], tmp / f"clip{i}.mp4")
            proxy = _proxy(clip, tmp / f"proxy{i}.mp4")
            n_frames = int(subprocess.run(
                ["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0", "-show_entries",
                 "stream=nb_read_frames", "-of", "csv=p=0", str(proxy)],
                capture_output=True, text=True).stdout.strip() or 0)
            centres, used = {}, subject
            alternates = c.get("subject_alternates") if isinstance(c.get("subject_alternates"), list) else []
            for attempt in fallback_subjects(subject, alternates):  # simple nouns track best; stop once one works
                try:
                    found = track_subject(client, proxy, attempt)
                except Exception as e:  # tracking is a bonus: never lose the reel over it
                    log(f"  SAM 3.1 failed on '{c['title']}' ({e})")
                    break
                if len(found) > len(centres):
                    centres, used = found, attempt
                if len(centres) / max(n_frames, 1) >= MIN_COVERAGE:
                    break
            subject = used
            coverage = len(centres) / max(n_frames, 1)
            tracked = coverage >= MIN_COVERAGE
            mode = "follow" if tracked else "fit"
            log(f"  📱 SAM 3.1 tracked '{subject}' in {coverage:.0%} of frames — {c['title']}"
                + ("" if tracked else " → full frame on blurred background"))
            report.append({"clip": c["title"], "subject": subject, "coverage": round(coverage, 2),
                           "frames": n_frames, "mode": mode})
            out_i = tmp / f"vert{i}.mp4"
            parts.append(vertical_clip(clip, out_i, camera_path(centres, n_frames)) if tracked
                         else fit_clip(clip, out_i))
        listing = tmp / "list.txt"
        listing.write_text("".join(f"file '{p}'\n" for p in parts))
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(listing),
                        "-c", "copy", "-movflags", "+faststart", str(out)], check=True)
    return out, report
