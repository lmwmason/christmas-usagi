# Christmas Usagi

A small Christmas stage where Usagi performs your favorite songs. Paste a YouTube link, generate a performance, and share the finished song with a friend.

The frontend uses plain HTML, CSS, and JavaScript. A Python service separates the instrumental, estimates the vocal melody with an AI pitch model, and arranges real Usagi sound samples to the music.

<p align="center"><img src="assets/images/usagi-official.png" width="180" alt="Usagi cheering with pom-poms"></p>

**Live stage:** https://usagi-christmas.front.cbgpu.com  
**API:** https://usagi-christmas-api.server.cbgpu.com

## Features

- Convert a complete song or start with a 30-second or one-minute excerpt.
- Keep the song recognizable with its separated instrumental backing.
- Combine varied Usagi calls with pitch-synchronous singing and energetic rhythmic phrases.
- Synchronize dancing to the audio playback position, including after seeking.
- Switch between the full mix and isolated Usagi vocals without losing your place.
- Share a finished performance through a link, clipboard copy, or the device share menu.
- Keep shared performances for 30 days, independently of temporary conversion jobs.
- Download the audio, browse the source soundbank, and enjoy snow, lights, and cheering effects.
- Support reduced motion and keyboard controls: **Space** to play/pause and **M** to mute.

The current user interface is in Korean. This is an unofficial fan project.

## Run locally

Requirements: Python 3.11+, FFmpeg, Node.js 20+, and [uv](https://docs.astral.sh/uv/).

```bash
uv venv .venv
uv pip install --python .venv/bin/python -r server/requirements.txt
.venv/bin/python -m uvicorn server.app:app --host 127.0.0.1 --port 8000 --workers 1
```

Open **http://127.0.0.1:8000**. No paid AI API key is required. Opening `index.html` directly also plays the bundled example, but conversion and share links require the server.

Use public, non-live YouTube videos up to 10 minutes long. YouTube access restrictions can prevent downloading some videos; the application reports these failures without exposing extractor logs.

## How the audio works

1. Download the selected song with yt-dlp.
2. Separate the instrumental with **UVR-MDX-NET-Inst_HQ_3 ONNX** and derive a vocal guide.
3. Analyze singing pitch with **RMVPE ONNX**, using four CPU threads and overlapping five-second windows.
4. Detect vocal activity independently of pitch, so consonants and unpitched passages can still receive rhythmic Usagi phrases.
5. Arrange actual soundbank utterances and use **Praat PSOLA** to follow the melody. Time changes stay within 0.82–1.22 times the original duration; pitch changes stay within six semitones.
6. Audit vocal coverage, add short responses in musical rests, and master aligned mix, vocal, and instrumental files.

This is sample-based resynthesis assisted by AI separation and pitch analysis. It is **not a trained Usagi voice-cloning or singing model**. Pitch estimates, speaker labels, and musical naturalness can still be imperfect. Coverage measures an automatically estimated vocal mask, with 50 ms articulation tolerance; it is not a human transcription score.

The first conversion downloads approximately 64 MB of separation weights and 362 MB of pitch weights, then caches them. RMVPE weights are SHA-256 verified. The source soundbank records provenance and hashes; known contaminated recordings are blocked by both ID and content hash.

## Sharing and storage

After conversion, choose **Share this performance** beneath the stage. The generated `?share=...` link loads the same audio and choreography without converting the song again. Shared links take precedence over the browser's previously restored job. Playback starts only when the visitor presses play.

| Data | Retention |
| --- | --- |
| Temporary jobs | Up to 24 hours and the 10 most recent completed jobs |
| Explicitly shared performances | 30 days from creation |
| Shared audio storage | 2 GiB total; new shares are refused when full |
| Model cache | Persistent and reused |

Shared copies contain only the three playable audio files and playback metadata. They survive removal of the original job and application restarts when `/data` uses persistent storage. Existing shares are not evicted early to make room. Expired copies are cleaned during subsequent share creation or startup.

Anyone with a share URL can listen to that performance. Localhost links work only on your computer; use the deployed frontend address when sharing with other people.

## API

| Method | Endpoint | Purpose |
| --- | --- | --- |
| GET | `/api/health` | Readiness and processing configuration |
| POST | `/api/jobs` | Create a conversion |
| GET | `/api/jobs/{id}` | Progress and completed performance |
| DELETE | `/api/jobs/{id}` | Cancel a queued or running conversion |
| GET | `/api/jobs/{id}/audio/{kind}` | Temporary mix, voice, or backing audio |
| POST | `/api/jobs/{id}/share` | Persist a completed performance for sharing |
| GET | `/api/shares/{id}` | Shared playback metadata |
| GET | `/api/shares/{id}/audio/{kind}` | Shared mix, voice, or backing audio |

Example conversion request:

```json
{"youtube_url": "https://youtu.be/yXQViqx6GMY", "start": 0, "duration": 30}
```

Set `duration` to `null` for the remaining full song. Audio endpoints support HTTP Range seeking and `?download=true`. Conversion runs one job at a time, with at most three queued or running jobs in total.

## Frontend build

```bash
npm run check
npm run build
```

`dist/` contains only the frontend and public assets. No frontend framework or third-party JavaScript dependency is required.

For separate frontend and API deployments:

```bash
USAGI_API_BASE_URL=https://your-api.example.com npm run build
```

This value is a public API origin, not a secret. Configure `USAGI_ALLOWED_ORIGINS` on the server to allow the frontend origin. Same-origin local development uses the default `config.js`.

## Docker and CBGPU

```bash
docker build -t christmas-usagi .
docker run --rm -p 127.0.0.1:8000:8000 -v usagi-data:/data christmas-usagi
```

`compose.yaml` configures four CPU cores, 16 GB RAM, one conversion worker, and a persistent `/data` volume. These match the CBGPU MCP input limits inspected for this project; account capacity and actual deployment performance must be verified separately. No GPU allocation field is exposed by that MCP version. The deployment plan requests 40 GB storage.

- `USAGI_DATA_DIR`: model, job, and share storage; defaults to `.cache/runtime` outside Docker.
- `USAGI_ALLOWED_ORIGINS`: comma-separated allowed frontend origins.
- `USAGI_CPU_THREADS`: processing thread count, capped at four.
- `PORT`: HTTP port, default `8000` in the container.

The API and static frontend are deployed as separate CBGPU projects. The API builds `main` with Compose. The frontend serves the generated `frontend` branch with framework `static`, output directory `.`, and empty install/build commands. This avoids a CBGPU build-worker symlink/path issue encountered during the initial deployment.

After committing source changes to `main`, rebuild and publish the static branch:

```bash
python tools/publish_frontend.py --api-base https://usagi-christmas-api.server.cbgpu.com
```

Then request a frontend redeployment through CBGPU. The publisher uses an isolated temporary worktree and a regular fast-forward push; it does not switch or overwrite your working branch. Frontend auto-deploy is disabled so promotion stays explicit. Deployment settings and verification records live in `deploy/`.

## Validation

```bash
uv pip install --python .venv/bin/python -r server/requirements-dev.txt
.venv/bin/python -m unittest server.test_app server.test_audio -v
npm run check
npm run build
docker compose --env-file /dev/null config --quiet
```

Tests cover input validation, queue limits, cancellation, retry deduplication, missing vocal passages, instrumental leakage, source exclusions, pitch decoding, audio seeking, sharing, expiration, storage limits, and recovery after the original job is removed or the server restarts.

The current local suite has **18 passing tests**. Actual YouTube conversion and seekable shared audio have also been exercised on the deployed CBGPU server, with both AI model caches ready. Browser interaction review was unavailable because the browser host was disconnected. Local container builds were unavailable because the Docker daemon was stopped; the CBGPU remote Docker build and container health check passed. Remote conversion and sharing checks are recorded in `deploy/`.

## Project layout

- `index.html`, `style.css`, `script.js`: stage, player, conversion, and sharing UI.
- `server/`: FastAPI service, conversion worker, and persistent share storage.
- `tools/`: source collection, neural pitch analysis, arrangement, separation, and frontend packaging.
- `assets/sources/manifest.json`: soundbank provenance and hashes.
- `assets/sources/policy.json`: known recording exclusions.
- `assets/images/sources.json`: official image provenance.
- `assets/preview.json`: bundled performance arrangement and coverage metadata.
- `deploy/`: CBGPU configuration and validation records.

## License and credits

Original project source code is licensed under **[Apache License 2.0](LICENSE)**. See [NOTICE](NOTICE) and [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

The Apache license does **not** relicense third-party character artwork, sound recordings, songs, generated arrangements incorporating those recordings, model weights, or dependency code. Those materials remain subject to their respective owners' rights and licenses.

- Usagi and Chiikawa artwork: [official Chiikawa anime website](https://www.anime-chiikawa.jp/), © Nagano / Chiikawa Production Committee. The original transparent PNG is retained with its source and hash.
- Usagi sound effects: individually attributed [Myinstants recordings](https://www.myinstants.com/ko/search/?name=chiikawa), linked in the soundbank manifest. Source-page labels are not automatic speaker verification.
- Bundled example song: *All I Want for Christmas Is You*, performed by Mariah Carey. Song and recording rights remain with their respective owners.
- RMVPE interoperability: [RVC project](https://github.com/RVC-Project/Retrieval-based-Voice-Conversion-WebUI/blob/main/infer/rmvpe.py); weights from [VoiceConversionWebUI](https://huggingface.co/lj1995/VoiceConversionWebUI/blob/main/rmvpe.onnx).
- Instrumental separation: [UVR model repository](https://github.com/TRvlvr/model_repo/releases/tag/all_public_uvr_models).
