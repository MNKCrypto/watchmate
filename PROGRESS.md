# Progress log

Running log of what was built during the hackathon, and what's next. Each new working session starts here.

## Day 1 — Oct 27, 2026

- [x] Project skeleton: README, .gitignore, .env.example, requirements
- [x] `ingest/chunk.py` — 6s HLS segments (keyframe forced at each boundary), MP4 copies for Muse Spark, mono audio, `manifest.json`. Artemis clip: 600 segments, 60.0 min, 0.00s drift
- [x] `scripts/muse_smoke_test.py` — Muse Spark 1.2 on 3 segments: liftoff detected (0.98), speech transcribed, on-screen clock read, animation recognised. ~$0.007 per segment
- [x] Reasoning effort default vs low: same quality, −32% output tokens, ~35% faster → use `low`
- [x] `ingest/analyze.py` — 600 segments in 15.7 min, 0 failures, 93 distinct event labels (747K in / 480K out tokens)
- [x] `timeline/build.py` — whole broadcast in ONE Muse Spark 1.3 call (50K tokens, 24s) → 19 moments, anchor: liftoff at 18:24. Mission time (T−/T+) computed from the anchor, since the model misreads the clock's sign
- [x] `agent/curate.py` + `profiles/` — two fans (engineer, casual fan) get clearly different reels. Budget fix: no auto-padding, priority-based dropping

## Day 2 — Oct 28, 2026

- [x] `agent/verify.py` — self-check: each clip is cut and re-watched by Muse Spark 1.2. Verdicts: pass / retitle / fail; hard rules vs soft wishes; failures replaced (replacement verified too) or dropped
- [x] `agent.curate.build_reel()` = pick → enforce → verify → recap (≤ 60 words, rewritten after any change) → playlist + MP4
- [x] Results: engineer 6 clips / 120s, all milestones; casual fan 3 clips / 60s. Self-check caught a "crowd cheering" clip that was really studio + animation
- [x] `messaging/telegram.py` + `scripts/send_reel.py` — first personalised reel delivered to a phone via Telegram
- [x] `bot/` — Telegram agent: conversational onboarding (Muse Spark → profile), matching (who cares about a new broadcast, with reasons), delivery, follow-ups (answer / clip / rebuild), `data/events.jsonl` decision log

## Next (build until Sunday Nov 1; record Monday; submit Tuesday)

- [x] `control/` — Control Room (`python -m control.server`, http://localhost:8000): Subscribers · Sources (watched folders, demo feed) · Live feed. Watcher agent runs the full pipeline when a source gets a new video
- [ ] `agent/cover.py` — Muse Image cover art per reel (sent as a photo with the intro)
- [ ] `agent/vertical.py` — SAM 3.1 tracks each clip's subject; ffmpeg pans a 9:16 window along the smoothed path → `reel_vertical.mp4` (sent on Telegram)
- [ ] README: architecture, how to run, Meta models, built-during-hackathon, credits, vision (platforms, contextual consent-based sponsorships)
- [ ] Second subscriber (current affairs / climate) + This Week @NASA bulletin as a second source
- Optional: Spark Open on partner inference (needs Baseten/Modal credits)

## Demo story (decided)

Telegram onboarding (user mentions "space technology") → Artemis full broadcast (5h+) → control room shows the agent's work (timeline, matching, self-check) → reel + recap already waiting in Telegram → follow-up question in chat. Second user (cricket only) is skipped by the agent.

## Decisions

- Segment length 6s: short enough for precise clips, long enough to capture an action
- Demo footage: NASA Artemis I launch coverage, 60-min window around liftoff (~18:24 in the clip)
- Video and generated media are git-ignored; footage is credited, not redistributed
- Channel: Telegram bot. WhatsApp Cloud API was tried, but the new business account was locked by Meta's automated review (error 131031)
