"""Swahili recognition using Meta MMS and its swh language adapter."""
import io
import logging
import os
import threading
from pathlib import Path

from fastapi import HTTPException

MODEL_ID = "facebook/mms-1b-all"
LANGUAGE = "swh"
MAX_AUDIO_BYTES = 20 * 1024 * 1024
MAX_AUDIO_SECONDS = 60
SAMPLE_RATE = 16000
# Official model.safetensors metadata for this MMS checkpoint.
CHECKPOINT_BYTES = 3859521128
CHECKPOINT_SHA256 = "0f1d95ce43d27e03d5d8dd56c697c805460f967c793dd2cbec2e8e8012deda98"
logger = logging.getLogger(__name__)


def decode_audio(data):
    import av
    import numpy as np

    chunks, sample_count = [], 0
    try:
        # Only decode the supplied bytes; never follow URLs or external files.
        with av.open(io.BytesIO(data), options={"protocol_whitelist": "pipe"}) as container:
            if not container.streams.audio:
                raise HTTPException(422, "This file has no audio track.")
            resampler = av.AudioResampler(format="fltp", layout="mono", rate=SAMPLE_RATE)

            def append_frame(converted):
                nonlocal sample_count
                samples = converted.to_ndarray().flatten()
                sample_count += samples.size
                if sample_count > MAX_AUDIO_SECONDS * SAMPLE_RATE:
                    raise HTTPException(422, "Audio must be 60 seconds or shorter.")
                chunks.append(samples)

            for frame in container.decode(audio=0):
                for converted in resampler.resample(frame):
                    append_frame(converted)
            for converted in resampler.resample(None):
                append_frame(converted)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(422, "Cannot read this audio. Upload a WAV, MP3, M4A, OGG, or WebM file.")
    if sample_count < SAMPLE_RATE // 10:
        raise HTTPException(422, "Please provide at least 0.1 seconds of audio.")
    return np.concatenate(chunks).astype(np.float32)


class TranscriptionEngine:
    def __init__(self):
        self.status = "loading"
        self.model = None
        self.recognizer = None
        self.lock = threading.Lock()

    def progress(self):
        if self.status != "loading":
            return {"phase": self.status}
        folder = Path(os.environ["HF_HOME"]) / "hub" / "models--facebook--mms-1b-all" / "blobs"
        if (folder / CHECKPOINT_SHA256).exists():
            return {"phase": "initializing"}
        try:
            downloaded = (folder / f"{CHECKPOINT_SHA256}.incomplete").stat().st_size
        except FileNotFoundError:
            downloaded = 0
        return {"phase": "downloading", "downloaded_bytes": downloaded,
                "total_bytes": CHECKPOINT_BYTES,
                "percent": round(min(100, downloaded / CHECKPOINT_BYTES * 100), 1)}

    def load(self):
        try:
            from transformers import AutoProcessor, Wav2Vec2ForCTC, pipeline
            processor = AutoProcessor.from_pretrained(MODEL_ID, target_lang=LANGUAGE)
            self.model = Wav2Vec2ForCTC.from_pretrained(
                MODEL_ID, target_lang=LANGUAGE, ignore_mismatched_sizes=True,
                low_cpu_mem_usage=True,
            ).eval()
            self.recognizer = pipeline(
                "automatic-speech-recognition", model=self.model,
                tokenizer=processor.tokenizer, feature_extractor=processor.feature_extractor,
                device=-1,
            )
            self.status = "ready"
        except Exception:
            logger.exception("Could not load MMS speech recognition")
            self.status = "error"

    def transcribe(self, data):
        if self.status != "ready":
            raise HTTPException(503, "Speech recognition is still loading." if self.status == "loading" else "Speech recognition unavailable. Check the server logs and restart to retry.")
        if not self.lock.acquire(blocking=False):
            raise HTTPException(429, "Speech recognition is busy. Please try again shortly.")
        try:
            import torch
            audio = decode_audio(data)
            # Overlapping CTC chunks bound inference memory and avoid cutting words.
            with torch.inference_mode():
                result = self.recognizer(
                    {"raw": audio, "sampling_rate": SAMPLE_RATE},
                    chunk_length_s=15, stride_length_s=(2, 2),
                )
            return {"text": result["text"].strip(), "language": LANGUAGE,
                    "model": MODEL_ID, "duration_seconds": round(audio.size / SAMPLE_RATE, 2)}
        finally:
            self.lock.release()
