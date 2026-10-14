import io
import wave
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import app, engine, stt_engine


@pytest.fixture
def client():
    with patch.object(engine, "load"), patch.object(stt_engine, "load"):
        with TestClient(app) as client:
            yield client


def test_studio_and_health(client):
    assert client.get("/").status_code == 200
    assert client.get("/static/studio.js").status_code == 200
    assert client.get("/api/v1/health").json()["model"] == "facebook/mms-tts-swh"


@pytest.mark.parametrize("text", ["", "  ", "1234 !!!", "a" * 1001, "a" * 251])
def test_invalid_text_never_reaches_model(client, text):
    with patch.object(engine, "synthesize") as synthesize:
        assert client.post("/api/v1/tts", json={"text": text}).status_code == 422
        synthesize.assert_not_called()


def test_returns_playable_wav_and_normalizes_whitespace(client):
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b"\0\0" * 160)
    with patch.object(engine, "synthesize", return_value=output.getvalue()) as synthesize:
        response = client.post("/api/v1/tts", json={"text": "  Habari\n  yako? "})
        synthesize.assert_called_once_with("Habari yako?")
    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/wav"
    assert response.content[:4] == b"RIFF"
    assert "kiswahili.wav" in response.headers["content-disposition"]


def test_loading_model_is_unavailable(client):
    with patch.object(engine, "status", "loading"):
        assert client.post("/api/v1/tts", json={"text": "Habari yako?"}).status_code == 503


def test_inference_errors_do_not_leak_internal_details(client):
    with patch.object(engine, "synthesize", side_effect=RuntimeError("private path")):
        response = client.post("/api/v1/tts", json={"text": "Habari yako?"})
    assert response.status_code == 500
    assert "private path" not in response.text
