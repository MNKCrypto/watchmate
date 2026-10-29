# Watchmate

**An AI agent that watches long live streams for you and delivers tailor-made highlight reels based on your preferences.**

Tell Watchmate once what you care about — "launch milestones and booster separation", "every wicket and six", "the plot twists". It watches the full broadcast on your behalf, alerts you when your moments happen, checks its own clips, and sends you a personalised reel you can stream instantly. Then ask follow-ups: *"make it 60 seconds"*, *"what happened right after liftoff?"*

Built for the **Meta Global AI Developer Hackathon 2026** with Meta's Muse models.

> **Status:** in active development during the hackathon (Oct 26 – Nov 4, 2026). See [PROGRESS.md](PROGRESS.md).

## How it works (planned)

```
long video ──► chunk into 6s segments ──► Muse Spark watches each segment (video + audio)
                                          Muse Voice Transcribe follows the commentary
                                                     │
                                                     ▼
                                     structured event timeline (what · when · evidence)
                                                     │
     your preferences ──► agent selects & verifies moments ──► personalised HLS reel + recap
                                                     │
                                      follow-up chat over the whole timeline (1M context)
```

## Meta models used

| Model | Role |
|---|---|
| Muse Spark | Watches segments (video + audio), builds the event timeline, selects and verifies clips, answers follow-ups |
| Muse Voice Transcribe | Transcribes broadcast commentary |
| SAM 3.1 | Tracks the subject to auto-crop vertical clips *(planned)* |
| Muse Image | Generates reel cover art *(planned)* |
| Muse Spark Open | High-volume segment analysis via partner inference *(planned)* |

## Quick start

Requirements: Python 3.10+, `ffmpeg`.

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # add your MODEL_API_KEY

# Step 1 — split a video into segments
python -m ingest.chunk data/raw/artemis_demo.mp4
```

Output (in `data/processed/<video_id>/`):

| Path | Purpose |
|---|---|
| `hls/index.m3u8`, `hls/seg_*.ts` | Streamable segments; reels are playlists of these |
| `analysis/seg_*.mp4` | Same segments as MP4, sent to Muse Spark |
| `audio.mp3` | Mono speech track for transcription |
| `manifest.json` | Start/end time of every segment |

## Built during the hackathon

All code in this repository was written during the hackathon, starting Oct 26, 2026. The commit history shows what was built and when.

The concept builds on ideas from my earlier prototype, [SemanticStream](https://github.com/MNKCrypto/semantic-stream) (semantic search over cricket video). No code from that project is reused here.

## Credits

Demo footage: **Artemis I Live Launch Coverage**, NASA/Michelle Stone (NASA Image and Video Library, ID `KSC-20221116-VP-MMS01-0001-Artemis_I_Live_Launch_Coverage_720p-3314595`). Used under [NASA media guidelines](http://www.nasa.gov/multimedia/guidelines/index.html). NASA does not endorse this project. Footage is not redistributed in this repository.
