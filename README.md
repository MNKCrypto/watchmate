# Watchmate

**An AI agent that watches long videos for you and sends each person their own highlight reel.**

Live broadcasts run for hours — a rocket launch, a match, a news bulletin. Most people care about a few minutes of it, and different minutes from the person next to them. Tell Watchmate once, in your own words, what you're into. When a source publishes something new, the agent watches all of it, decides who it's for, cuts each subscriber a personal reel, checks its own work, and delivers it to their phone on Telegram. Then you can ask follow-ups: *"show me what happened after the boosters separated"*, *"make it 30 seconds"*.

Built for the **Meta Global AI Developer Hackathon 2026** (Indie track · *Build for Your World*) with Meta's Muse models.

> 🎬 Demo video: *(link added at submission)*

---

## What it does

1. **Onboarding by conversation.** A user tells the Telegram bot what they care about ("space tech and rocket launches — real engine and separation moments, skip the studio chat"). Muse Spark turns that into a profile: interests, preferences in the user's voice, reel length.
2. **Watches every new video, by itself.** The watcher agent monitors sources. A new video is split into 6-second segments and Muse Spark watches **every segment — video and audio together** — writing what's on screen, what's said, on-screen text, an event label, footage type (live / animation / studio) and an excitement score.
3. **Understands the whole broadcast at once.** All observations (~50K tokens for an hour of video) go to Muse Spark in **one long-context call**, which groups them into the moments a viewer would recognise ("Engine ignition and liftoff", "Solid rocket booster separation") and anchors them to the key event (liftoff → T−/T+ times).
4. **Decides who it's for.** For every subscriber, Muse Spark judges whether the broadcast matches their interests — and says why. Matched users get a reel; others are skipped, with a reason.
5. **Cuts a personal reel.** The agent picks the best window inside each relevant moment (the last seconds of a 10-minute countdown, not all of it), within the user's time budget, ranked by priority.
6. **Checks its own work.** Every chosen clip is cut and **re-watched** by Muse Spark: does it really show what the caption says? Does it break a rule the user set? Each clip is **passed**, **retitled** (good clip, overclaiming caption) or **rejected and replaced** (the replacement is checked too).
7. **Makes it phone-ready.** **SAM 3.1** tracks each clip's main subject (the rocket, or its flame at night) and a 9:16 frame pans along with it; when nothing can be tracked, the full shot is kept over a blurred background. **Muse Image** paints illustrated cover art.
8. **Delivers and keeps talking.** Cover, vertical reel and a short recap arrive on Telegram. Follow-up questions are answered from the whole broadcast — in words, with a short clip, or by rebuilding the reel at a new length.

Everything the agent decides is logged and shown live in the **Control Room**.

## The Control Room

`python -m control.server` → <http://localhost:8000> — the operator console of the company running Watchmate:

| Page | Shows |
|---|---|
| **Live feed** | Every decision as it happens: 🆕 new video → 👀 watching (progress) → 🧭 moments found → 🎯 matched / ⏭ skipped (with reasons) → ✓ ✎ ✗ self-checks → 🎨 cover → 📱 SAM 3.1 tracking → 📨 delivered → 💬 follow-ups |
| **Subscribers** | Each user's interests and preferences, in their own words |
| **Sources** | The video sources the agent monitors; add, pause or remove them |

## How it works

```
                  ┌──────────── Control Room (sources · subscribers · live feed) ────────────┐
                  │                                                                           │
new video ──► ffmpeg: 6 s segments ──► Muse Spark watches every segment (video + audio, parallel)
                                                   │
                                                   ▼
                         Muse Spark, ONE long-context call: 600 notes → moments + anchor
                                                   │
          subscribers ──► Muse Spark: who is this for? (match / skip + reason)
                                                   │
                         Muse Spark: pick clips per person (budget, priorities)
                                                   │
                         Muse Spark re-watches each clip: pass / retitle / replace
                                                   │
                         Muse Image cover · SAM 3.1 follow-cam 9:16 version
                                                   │
                                                   ▼
                    Telegram: cover → reel → recap   ◄──►  follow-ups (answer · clip · rebuild)
```

## Meta models used

| Model | Where | What it does here |
|---|---|---|
| **Muse Spark 1.2** | `ingest/analyze.py`, `agent/verify.py` | Watches each 6 s segment and each chosen clip — video **and** audio in one call |
| **Muse Spark 1.3** | `timeline/build.py`, `agent/curate.py`, `bot/` | Long-context reasoning over the whole broadcast; matching; clip selection; onboarding; follow-ups |
| **SAM 3.1** | `agent/vertical.py` | Tracks the subject frame by frame so the 9:16 phone version follows the action |
| **Muse Image** | `agent/cover.py` | Illustrated cover art for every reel |

Muse Spark 1.2 is used wherever audio matters, because Meta's docs note that audio understanding in 1.3 is not fully supported yet.

## Design notes

- **Per-segment notes, whole-broadcast reasoning.** Segments are watched in parallel (8 at a time, resumable), then reasoned over together in one long-context call — moments come from the story of the event, not from text similarity.
- **Self-check with three outcomes.** Hard rules (things the user said to skip, "only …") can reject a clip; soft wishes ("I prefer live footage") only add a note. A wrong caption is fixed rather than throwing away a good clip.
- **Fail soft.** Cover art and the phone version never block delivery; an untracked clip falls back to full-frame; tracking retries with the agent's own alternative subjects (e.g. *rocket → exhaust plume → flame* at night).
- **Honest time.** Mission time (T−/T+) is computed from the detected anchor event, because the model can misread the sign on broadcast clocks.
- **Measured cost:** about $3–4 to watch an hour of video (600 segments, ~16 min with 8 workers); a few cents for the timeline, matching and each reel; $0.01 per cover.

## Run it

Requirements: Python 3.10+, `ffmpeg`, a Meta Model API key, a Telegram bot token (from @BotFather).

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env    # MODEL_API_KEY, TELEGRAM_BOT_TOKEN, ALLOWED_CHAT_IDS
```

**The full experience (two terminals):**

```bash
python -m bot.run           # Telegram bot: onboarding + follow-ups
python -m control.server    # Control Room + watcher agent → http://localhost:8000
```

Send `/start` to your bot, describe what you're into, then publish a video by dropping it into a source folder:

```bash
cp my_video.mp4 sources/nasa/
```

**Step by step (each stage on its own):**

```bash
python -m ingest.chunk data/raw/artemis_demo.mp4            # 6 s segments + manifest
python -m ingest.analyze --reasoning-effort low             # Muse Spark watches every segment
python -m timeline.build                                    # long-context moments
python -m agent.curate --profile profiles/engineer.json     # reel + self-check + cover + 9:16
python -m scripts.send_reel --reel data/reels/artemis_demo/engineer/reel.json
python -m bot.publish --video-dir data/processed/artemis_demo   # match + serve all subscribers
```

## Project layout

```
ingest/     chunk.py (ffmpeg segments) · analyze.py (Muse Spark per segment)
timeline/   build.py (long-context moments + anchor)
agent/      curate.py (pick clips, budget) · verify.py (self-check) · cover.py (Muse Image) · vertical.py (SAM 3.1)
bot/        run.py (Telegram) · onboarding.py · matcher.py · followup.py · publish.py · store.py
control/    server.py · watcher.py · sources.py · static/index.html (Control Room)
messaging/  telegram.py
common/     muse.py (API client) · events.py (decision log)
```

## Limits (honest)

- **Sources are watched folders in this demo.** Dropping a video into `sources/<name>/` stands in for a broadcaster publishing it; broadcaster APIs and RSS feeds are the next step.
- **Telegram, not WhatsApp.** WhatsApp Cloud API was tried first; the new business account was locked by Meta's automated review (error 131031), so delivery runs on Telegram.
- **Private demo.** The bot only serves chat ids listed in `ALLOWED_CHAT_IDS`; everyone else gets a polite reply and nothing is stored or spent.
- Processing is near-real-time per segment (~8 s per 6 s segment, parallelised), not yet a true live-stream ingest.

## Where this goes

Any long video, re-cut for each viewer and delivered where they already are — sports, entertainment, news. A league, broadcaster or streaming library plugs in as a source; every viewer gets their own version. And because every subscriber tells Watchmate exactly what they care about, it is a natural channel for **contextual, consent-based sponsorships**: the right brand next to the right moment, using only what the viewer chose to share.

## Built during the hackathon

All code in this repository was written during the hackathon, from Oct 27, 2026 onwards — the commit history shows what was built and when. The idea grew out of my earlier prototype, [SemanticStream](https://github.com/MNKCrypto/semantic-stream) (semantic search over cricket video); no code from it is reused. Developed with the help of an AI coding assistant.

## Credits

Demo footage: **Artemis I Live Launch Coverage**, NASA/Michelle Stone (NASA Image and Video Library, ID `KSC-20221116-VP-MMS01-0001-Artemis_I_Live_Launch_Coverage_720p-3314595`). Used under [NASA media guidelines](http://www.nasa.gov/multimedia/guidelines/index.html). NASA does not endorse this project. Footage is not redistributed in this repository.
