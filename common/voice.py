"""Speech to text with Muse Voice Transcribe (muse-voice-transcribe-1.0, ~$0.18 per hour of audio).

The file endpoint takes WAV only (mono, 16-bit PCM, 16 or 24 kHz), so anything else — e.g. a
Telegram voice note (OGG/Opus) — is converted with ffmpeg first. Limits: 10 minutes, 32 MB.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import requests
from dotenv import load_dotenv

URL = "https://api.meta.ai/v1/asr/transcribe"
MODEL = "muse-voice-transcribe-1.0"
# names the generic recogniser might otherwise mishear in this domain (a hint, not a guarantee)
KEYWORDS = ["Watchmate", "Artemis", "Orion", "SLS", "RS-25", "Max Q", "NASA", "Isaacman", "Kshatriya"]


class TranscribeError(RuntimeError):
    pass


def to_wav(src: Path, dst: Path) -> Path:
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(src), "-ac", "1", "-ar", "16000",
                    "-c:a", "pcm_s16le", "-map_metadata", "-1", str(dst)], check=True)
    return dst


def transcribe(audio: Path, keywords: list[str] | None = None) -> dict:
    """Returns {"text": ..., "seconds": ...}."""
    load_dotenv()
    key = os.environ.get("MODEL_API_KEY")
    if not key:
        sys.exit("MODEL_API_KEY is not set. Add it to .env (see .env.example).")
    with tempfile.TemporaryDirectory() as tmp:
        wav = to_wav(audio, Path(tmp) / "audio.wav")
        settings = {"model": MODEL, "audioEncoding": "WAV", "mode": "PUSH_TO_TALK",
                    "keywords": keywords if keywords is not None else KEYWORDS}
        with wav.open("rb") as f:
            resp = requests.post(
                URL,
                headers={"Authorization": f"Bearer {key}", "Accept": "application/json"},
                files={"request": (None, json.dumps(settings), "application/json"),
                       "audio": ("audio.wav", f, "audio/wav")},
                timeout=120,
            )
    if resp.status_code != 200:
        raise TranscribeError(f"Muse Voice Transcribe {resp.status_code}: {resp.text[:300]}")
    data = resp.json()
    return {"text": (data.get("transcript") or "").strip(),
            "seconds": round((data.get("audioDurationMs") or 0) / 1000, 1)}


if __name__ == "__main__":  # quick test: python -m common.voice path/to/audio.ogg
    print(transcribe(Path(sys.argv[1])))
