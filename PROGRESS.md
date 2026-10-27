# Progress log

Running log of what was built during the hackathon, and what's next. Each new working session starts here.

## Day 1 — Oct 27, 2026

- [x] Project skeleton: README, .gitignore, .env.example, requirements
- [x] `ingest/chunk.py` — splits a video into 6s HLS segments (keyframe forced at each boundary), MP4 copies for Muse Spark, mono audio for transcription, and a `manifest.json`
- [ ] Run chunker on the full Artemis clip (60 min → ~600 segments)
- [ ] First Muse Spark call on 2–3 segments: check video input, response quality, latency, cost

## Next

- Event timeline: Muse Spark + Voice Transcribe → structured moments (type, time, confidence, evidence)
- Preference profiles and the agent's selection logic
- HLS reel builder

## Decisions

- Segment length 6s: short enough for precise clips, long enough to capture an action
- Demo footage: NASA Artemis I launch coverage, 60-min window around liftoff (~18:22 in the clip)
- Video and generated media are git-ignored; footage is credited, not redistributed
