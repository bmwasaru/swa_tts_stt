# Sauti · Kiswahili Voice Studio

A local Bootstrap web interface and FastAPI API for Kiswahili speech. Text-to-speech uses Meta's `facebook/mms-tts-swh`; speech-to-text uses Meta's `facebook/mms-1b-all` with its Swahili (`swh`) adapter. Generate and download speech, or upload/record audio and copy a transcript.

The interface uses Bootstrap 5.3.8 components and utilities exclusively for styling, served from `app/static/vendor/bootstrap/`. No frontend build step or CDN connection is needed. The small `studio.js` and `transcription.js` files handle API requests, model status, recording, and audio playback. Bootstrap’s JavaScript provides the accessible tool tabs. Bootstrap is MIT-licensed; its license is included beside the vendored CSS.

## Run

Use Python 3.12 (recommended) and create a virtual environment:

```sh
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements.txt
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000. Interactive API documentation is at `/docs`.

Both models load once in separate background threads so the interface remains available while they download. The ASR checkpoint downloads several GB and requires several GB of available RAM for CPU inference. The first run needs internet access to Hugging Face; later runs use `.cache/huggingface` in this project. Override `HF_HOME` to choose another cache. Downloads use HTTP by default; set `HF_HUB_DISABLE_XET=0` to opt into Xet transfers. Inference runs on CPU. Start one server worker to avoid duplicate model copies. If loading fails, check the terminal and restart after fixing the connection or dependency issue.

## API

```sh
curl -X POST http://127.0.0.1:8000/api/v1/tts \
  -H 'Content-Type: application/json' \
  -d '{"text":"Habari yako? Karibu katika studio yetu ya sauti."}' \
  --output kiswahili.wav
```

`GET /api/v1/health` reports `loading`, `ready`, or `error`. The speech endpoint accepts 1–1,000 characters with readable Latin letters, normalizes whitespace, and splits long passages at word boundaries into short chunks. Spell numbers out in Kiswahili. There is one model voice; this interface does not invent additional accents or speakers. Errors: `422` for invalid input, `503` when the model is unavailable, `429` during another generation, and `500` for an inference failure. Generated audio stays in memory and is not stored by the server. Your browser retains only the latest result until the page closes.

## Swahili speech-to-text

Select **Speech to text**, upload an audio file or record through your microphone, then choose **Transcribe Swahili**. Microphone recording works on localhost or HTTPS, requires browser permission, and stops automatically at 60 seconds. Audio uploads can use WAV, MP3, M4A, OGG, or WebM; the server decodes the actual audio rather than trusting the filename. Uploaded audio is converted to mono 16 kHz before inference. Each clip is limited to 60 seconds and 20 MB. PyAV includes its decoding libraries; a separate FFmpeg install is unnecessary.

```sh
curl -X POST http://127.0.0.1:8000/api/v1/stt \
  -F 'file=@kiswahili.wav'
```

The JSON response contains `text`, `language` (`swh`), `model`, and `duration_seconds`. This transcribes Kiswahili rather than translating it. MMS uses overlapping 15-second chunks to bound inference memory. The interface shows live checkpoint download progress, then switches to model initialization and readiness. The health response includes a separate `stt` readiness status and progress details; TTS can be ready while the larger STT model is still loading. Only one STT request runs at a time; additional requests return `429`. Uploads are closed after the request and not retained by the application. Browser recordings stay local until you press **Transcribe Swahili**. Review transcripts for names, accents, noise, and mixed-language speech.

## Checks

```sh
uv pip install --python .venv/bin/python -r requirements-dev.txt
.venv/bin/python -m pytest -q
node --check app/static/studio.js
node --check app/static/transcription.js
```

API tests mock model inference and verify text validation, WAV delivery, transcription responses, upload size and duration limits, stereo resampling, malformed files, readiness, concurrency, and error handling. A real generation requires the downloaded model; listen to representative Kiswahili sentences to evaluate pronunciation and naturalness. Long passages receive brief silence between chunks, which may affect pacing.

## Model attribution and scope

[Meta MMS Swahili model](https://huggingface.co/facebook/mms-tts-swh), developed by the Meta MMS team; see [Scaling Speech Technology to 1,000+ Languages](https://arxiv.org/abs/2305.13516). [Meta MMS ASR](https://huggingface.co/facebook/mms-1b-all) supplies recognition with its `swh` adapter. Both sets of model weights are licensed [CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/). This is a non-commercial evaluation application. The model license restricts commercial use; changing the interface does not change the model's license.

This service binds to localhost by default. Public deployment needs authentication, per-user rate limits, bounded request bodies at the proxy, and deployment-specific resource limits. It is not configured for public hosting. Fine-tuning and streaming live recognition are outside this implementation.
