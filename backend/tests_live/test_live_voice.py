"""Live voice tests: Sarvam and ElevenLabs speech, Sarvam transcription, and the real microphone."""

import asyncio
import base64
import io
import threading
import time
import wave

import pytest

from conftest import MIC


def _wav_to_pcm(wav_bytes: bytes):
    with wave.open(io.BytesIO(wav_bytes)) as w:
        return w.readframes(w.getnframes()), w.getframerate(), w.getnchannels()


def _speak(text: str) -> bytes:
    """Real Sarvam TTS (no cache) -> WAV bytes."""
    from tools.sarvam_tts import SarvamFillerTTS
    b64 = asyncio.run(SarvamFillerTTS().generate_filler_audio_base64(text))
    assert b64, "no audio from Sarvam (or the ElevenLabs fallback)"
    return base64.b64decode(b64)


def test_sarvam_speech_returns_playable_audio(report):
    with report.timed("voice", "Sarvam TTS") as t:
        audio = _speak("Committed two files with message fix login retries.")
        t.done(f"{len(audio)} bytes, header {audio[:4]!r}")
    assert audio[:4] == b"RIFF", "Sarvam should return a WAV file"
    pcm, rate, channels = _wav_to_pcm(audio)
    assert rate == 16000 and channels == 1 and len(pcm) > 16000  # at least half a second


def test_repeated_phrase_comes_from_the_cache(report):
    from tools.sarvam_tts import SarvamFillerTTS
    tts = SarvamFillerTTS()
    asyncio.run(tts.generate_filler_audio_base64("Syntax error resolved in main.py."))
    start = time.perf_counter()
    asyncio.run(tts.generate_filler_audio_base64("Syntax error resolved in main.py."))
    elapsed = time.perf_counter() - start
    report.add("voice", "cache hit", elapsed, f"{elapsed * 1000:.1f} ms")
    assert elapsed < 0.05


def test_elevenlabs_fallback_voice(report):
    from tools.elevenlabs_tts import ElevenLabsTTS
    client = ElevenLabsTTS()
    if not client.api_key:
        report.add("voice", "ElevenLabs", 0, "no ELEVENLABS_API_KEY", "skipped")
        pytest.skip("no ELEVENLABS_API_KEY")
    with report.timed("voice", "ElevenLabs TTS") as t:
        b64 = asyncio.run(client.generate_narration_audio_base64("Push completed.", risk_band="caution"))
        t.done(f"{len(b64)} base64 chars" if b64 else "(empty: key or plan rejected)", "ok" if b64 else "FAIL")
    if not b64:
        pytest.xfail("ElevenLabs returned no audio; Sarvam still covers every narration")


@pytest.mark.parametrize("phrase, must_hear", [
    ("commit my changes", "commit"),
    ("what is my git status", "status"),
    ("review my diff", "review"),
])
def test_speech_to_text_round_trip(phrase, must_hear, report):
    """Sarvam speaks the phrase, then Sarvam STT must hear it back."""
    from tools.sarvam_stt import sarvam_stt_client
    pcm, rate, _ = _wav_to_pcm(_speak(phrase))
    with report.timed("voice", f"STT round trip: {phrase}") as t:
        heard = asyncio.run(sarvam_stt_client.transcribe_pcm_bytes(pcm, sample_rate=rate))
        t.done(heard, "ok" if must_hear in heard.lower() else "FAIL")
    assert must_hear in heard.lower(), f"said {phrase!r}, heard {heard!r}"


# ── Microphone (opt-in: plays a phrase on the speakers and records it) ──────

mic_only = pytest.mark.skipif(not MIC, reason="microphone test: set ANGIZO_LIVE_MIC=1")


def _play_while_recording(wav_bytes: bytes, seconds: float):
    import numpy as np
    import sounddevice as sd
    import winsound

    rec = sd.rec(int(seconds * 16000), samplerate=16000, channels=1, dtype="float32")
    time.sleep(0.4)
    winsound.PlaySound(wav_bytes, winsound.SND_MEMORY)  # blocks until played
    sd.wait()
    return (rec[:, 0] * 32767).astype(np.int16)


@mic_only
def test_microphone_records_sound(report):
    import numpy as np
    samples = _play_while_recording(_speak("Testing the microphone."), 3.5)
    rms = float(np.sqrt(np.mean(samples.astype(np.float64) ** 2)))
    report.add("mic", "input level while speaker plays", 0, f"RMS {rms:.0f} (silence is under ~50)",
               "ok" if rms > 50 else "FAIL")
    assert rms > 50, "the microphone recorded near-silence: check the input device and its volume"


@mic_only
def test_microphone_to_transcript(report):
    from tools.sarvam_stt import sarvam_stt_client
    samples = _play_while_recording(_speak("what is my git status"), 4.0)
    with report.timed("mic", "speaker -> mic -> Sarvam STT") as t:
        heard = asyncio.run(sarvam_stt_client.transcribe_pcm_bytes(samples.tobytes()))
        t.done(heard, "ok" if "status" in heard.lower() else "FAIL")
    assert "status" in heard.lower(), f"heard {heard!r}"


@mic_only
def test_backend_mic_button_runs_the_agent(playground, report):
    """The extension's mic button path: toggle_backend_mic on, speak, toggle off -> agent answers."""
    import winsound
    from fastapi.testclient import TestClient
    from main import app

    wav = _speak("what is my git status")
    with TestClient(app) as client, client.websocket_connect("/ws/session") as ws:
        ws.send_json({"type": "set_workspace", "workspace_path": str(playground)})
        ws.receive_json()
        ws.send_json({"type": "toggle_backend_mic"})
        assert ws.receive_json() == {"type": "mic_status", "state": "recording"}
        time.sleep(0.5)
        player = threading.Thread(target=winsound.PlaySound, args=(wav, winsound.SND_MEMORY))
        player.start()
        player.join()
        time.sleep(0.5)
        with report.timed("mic", "mic button -> agent") as t:
            ws.send_json({"type": "toggle_backend_mic"})
            transcript, result = "", None
            while result is None:
                msg = ws.receive_json()
                if msg.get("transcript"):
                    transcript = msg["transcript"]
                if msg["type"] == "action_result":
                    result = msg
            t.done(f"heard {transcript!r} -> {result.get('detail', '')}")
    assert "status" in transcript.lower(), f"heard {transcript!r}"
    assert result["status"] in ("skipped", "success"), result
    assert result.get("audio_base64")
