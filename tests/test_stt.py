import io
import wave
from unittest.mock import Mock, patch

import numpy as np
import pytest
from fastapi import HTTPException

from app.main import stt_engine
from app.stt import decode_audio, MAX_AUDIO_BYTES, TranscriptionEngine
from tests.test_api import client


def wav_bytes(seconds=1, rate=16000, channels=1):
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        signal = (np.sin(np.arange(int(seconds * rate)) * 2 * np.pi * 440 / rate) * 1000).astype(np.int16)
        wav.writeframes(np.repeat(signal[:, None], channels, axis=1).tobytes())
    return output.getvalue()


def test_decoding_resamples_stereo_audio():
    audio = decode_audio(wav_bytes(rate=44100, channels=2))
    assert audio.shape == (16000,)
    assert audio.dtype == np.float32
    assert np.isfinite(audio).all()


def test_duration_limit_is_enforced_during_decoding():
    with pytest.raises(HTTPException) as error:
        decode_audio(wav_bytes(seconds=61))
    assert error.value.status_code == 422
    assert "60 seconds" in error.value.detail


def test_bad_audio_is_rejected_without_inference(client):
    recognizer = Mock()
    with patch.object(stt_engine, "status", "ready"), patch.object(stt_engine, "recognizer", recognizer):
        response = client.post("/api/v1/stt", files={"file": ("bad.wav", b"not audio", "audio/wav")})
    assert response.status_code == 422
    recognizer.assert_not_called()
    assert not stt_engine.lock.locked()


def test_transcript_response_and_language(client):
    with patch.object(stt_engine, "status", "ready"), patch.object(stt_engine, "recognizer", return_value={"text": " habari yako "}):
        response = client.post("/api/v1/stt", files={"file": ("speech.wav", wav_bytes(), "audio/wav")})
    assert response.status_code == 200
    assert response.json() == {"text": "habari yako", "language": "swh", "model": "facebook/mms-1b-all", "duration_seconds": 1.0}


def test_missing_empty_and_oversized_uploads(client):
    assert client.post("/api/v1/stt").status_code == 422
    assert client.post("/api/v1/stt", files={"file": ("empty.wav", b"")}).status_code == 422
    assert client.post("/api/v1/stt", files={"file": ("big.wav", b"0" * (MAX_AUDIO_BYTES + 1))}).status_code == 413


def test_recognizer_loading_and_busy_states(client):
    with patch.object(stt_engine, "status", "loading"):
        assert client.post("/api/v1/stt", files={"file": ("audio.wav", wav_bytes())}).status_code == 503
    with patch.object(stt_engine, "status", "ready"):
        stt_engine.lock.acquire()
        try:
            assert client.post("/api/v1/stt", files={"file": ("audio.wav", wav_bytes())}).status_code == 429
        finally:
            stt_engine.lock.release()


def test_stt_errors_are_sanitized(client):
    with patch.object(stt_engine, "transcribe", side_effect=RuntimeError("private path")):
        response = client.post("/api/v1/stt", files={"file": ("audio.wav", wav_bytes())})
    assert response.status_code == 500
    assert "private path" not in response.text


def test_mms_loader_selects_swahili_for_model_and_processor():
    with patch("transformers.AutoProcessor.from_pretrained") as processor, \
         patch("transformers.Wav2Vec2ForCTC.from_pretrained") as model, \
         patch("transformers.pipeline"):
        recognizer = TranscriptionEngine()
        recognizer.load()
    assert recognizer.status == "ready"
    processor.assert_called_once_with("facebook/mms-1b-all", target_lang="swh")
    assert model.call_args.args == ("facebook/mms-1b-all",)
    assert model.call_args.kwargs["target_lang"] == "swh"
    assert model.call_args.kwargs["ignore_mismatched_sizes"] is True
