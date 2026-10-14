"""Local Kiswahili speech studio and MMS inference API."""
import asyncio
import io
import logging
import os
import re
import threading
from contextlib import asynccontextmanager
from pathlib import Path

# Keep downloaded model files inside this project unless the user selects a cache.
os.environ.setdefault("HF_HOME", str(Path(__file__).resolve().parent.parent / ".cache" / "huggingface"))
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")

from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator
from app.stt import TranscriptionEngine, MAX_AUDIO_BYTES, MAX_AUDIO_SECONDS, MODEL_ID as STT_MODEL_ID

MODEL_ID = "facebook/mms-tts-swh"
STATIC = Path(__file__).parent / "static"
logger = logging.getLogger(__name__)


class SpeechEngine:
    def __init__(self):
        self.status = "loading"
        self.model = None
        self.tokenizer = None
        self.lock = threading.Lock()

    def load(self):
        try:
            from transformers import AutoTokenizer, VitsModel
            self.tokenizer = AutoTokenizer.from_pretrained(MODEL_ID)
            self.model = VitsModel.from_pretrained(MODEL_ID).eval()
            self.status = "ready"
        except Exception:
            logger.exception("Could not load MMS model")
            self.status = "error"

    def synthesize(self, text: str) -> bytes:
        import numpy as np
        import torch
        from scipy.io.wavfile import write

        if self.status != "ready":
            raise HTTPException(503, "The voice is still loading." if self.status == "loading" else "Voice unavailable. Check the server logs and restart to retry.")
        if not self.lock.acquire(blocking=False):
            raise HTTPException(429, "The voice is busy. Please try again shortly.")
        try:
            # Short chunks bound VITS memory use; retain word boundaries.
            words = text.split()
            chunks, current = [], ""
            for word in words:
                if len(current) + len(word) + 1 > 250 and current:
                    chunks.append(current)
                    current = ""
                current = f"{current} {word}".strip()
            if current:
                chunks.append(current)
            waveforms = []
            rate = self.model.config.sampling_rate
            with torch.inference_mode(), torch.random.fork_rng(devices=[]):
                torch.manual_seed(42)
                for chunk in chunks:
                    inputs = self.tokenizer(chunk, return_tensors="pt")
                    if inputs["input_ids"].shape[-1] == 0:
                        raise HTTPException(422, "Please enter words that the Kiswahili voice can read.")
                    waveform = self.model(**inputs).waveform.squeeze().cpu().numpy()
                    if waveforms:
                        waveforms.append(np.zeros(int(rate * 0.18), dtype=np.float32))
                    waveforms.append(waveform)
            audio = np.concatenate(waveforms)
            buffer = io.BytesIO()
            write(buffer, rate, (np.clip(audio, -1, 1) * 32767).astype(np.int16))
            return buffer.getvalue()
        finally:
            self.lock.release()


class SpeechRequest(BaseModel):
    text: str = Field(min_length=1, max_length=1000)

    @field_validator("text")
    @classmethod
    def readable_text(cls, value):
        value = re.sub(r"\s+", " ", value).strip()
        if not re.search(r"[a-zA-Z]", value):
            raise ValueError("Enter Kiswahili words, not only numbers or punctuation.")
        if any(len(word) > 250 for word in value.split()):
            raise ValueError("A single word cannot exceed 250 characters.")
        return value


engine = SpeechEngine()
stt_engine = TranscriptionEngine()


@asynccontextmanager
async def lifespan(app):
    thread = threading.Thread(target=engine.load, daemon=True)
    thread.start()
    threading.Thread(target=stt_engine.load, daemon=True).start()
    yield


app = FastAPI(title="Kiswahili Voice Studio", version="1.0.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/v1/health")
def health():
    return {"status": engine.status, "model": MODEL_ID, "sample_rate": 16000, "max_characters": 1000,
            "stt": {"status": stt_engine.status, "model": STT_MODEL_ID, "language": "swh",
                    "max_seconds": MAX_AUDIO_SECONDS, "max_bytes": MAX_AUDIO_BYTES,
                    "progress": stt_engine.progress()}}


@app.post("/api/v1/tts", response_class=Response, responses={200: {"content": {"audio/wav": {}}}})
async def tts(request: SpeechRequest):
    try:
        audio = await asyncio.to_thread(engine.synthesize, request.text)
    except HTTPException:
        raise
    except Exception:
        logger.exception("Speech generation failed")
        raise HTTPException(500, "Speech generation failed. Try a shorter passage.")
    return Response(audio, media_type="audio/wav", headers={"Content-Disposition": 'attachment; filename="kiswahili.wav"', "Cache-Control": "no-store"})


@app.post("/api/v1/stt")
async def stt(file: UploadFile = File(...)):
    try:
        data = await file.read(MAX_AUDIO_BYTES + 1)
        if len(data) > MAX_AUDIO_BYTES:
            raise HTTPException(413, "Audio files must be 20 MB or smaller.")
        if not data:
            raise HTTPException(422, "Choose a non-empty audio file.")
        return await asyncio.to_thread(stt_engine.transcribe, data)
    except HTTPException:
        raise
    except Exception:
        logger.exception("Transcription failed")
        raise HTTPException(500, "Transcription failed. Please try another audio clip.")
    finally:
        await file.close()
