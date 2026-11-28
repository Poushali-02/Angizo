"""Offline tests for the mic auto-stop (tools/vad.py). No microphone needed: audio is synthesised."""

import numpy as np

from tools.vad import SilenceDetector

RATE = 16000
BLOCK = 1600  # 0.1 s


def _quiet(level=0.002):
    rng = np.random.default_rng(0)
    return (rng.standard_normal(BLOCK) * level).astype("float32")


def _speech(level=0.2):
    t = np.arange(BLOCK) / RATE
    return (np.sin(2 * np.pi * 220 * t) * level).astype("float32")


def _run(detector, blocks):
    for i, block in enumerate(blocks):
        reason = detector.feed(block)
        if reason:
            return reason, round((i + 1) * BLOCK / RATE, 1)
    return None, None


def test_stops_after_silence_following_speech():
    d = SilenceDetector(sample_rate=RATE, silence_ms=1200)
    blocks = [_quiet()] * 5 + [_speech()] * 10 + [_quiet()] * 30
    reason, at = _run(d, blocks)
    assert reason == "silence"
    assert at == 2.7  # 0.5 s room + 1.0 s speech + 1.2 s quiet


def test_short_pauses_inside_a_sentence_do_not_stop():
    d = SilenceDetector(sample_rate=RATE, silence_ms=1200)
    blocks = [_quiet()] * 5 + ([_speech()] * 5 + [_quiet()] * 6) * 4
    reason, _ = _run(d, blocks)
    assert reason is None


def test_no_speech_gives_up_without_transcribing():
    d = SilenceDetector(sample_rate=RATE, silence_ms=1200, no_speech_s=6.0)
    reason, at = _run(d, [_quiet()] * 100)
    assert reason == "no_speech"
    assert at == 6.0


def test_never_records_longer_than_the_limit():
    d = SilenceDetector(sample_rate=RATE, silence_ms=1200, max_s=15.0)
    reason, at = _run(d, [_quiet()] * 3 + [_speech()] * 200)
    assert reason == "max_length"
    assert at == 15.0


def test_noisy_room_raises_the_threshold():
    # A fan-level hum during calibration must not count as speech afterwards.
    d = SilenceDetector(sample_rate=RATE, silence_ms=1200, no_speech_s=3.0)
    hum = _quiet(level=0.03)
    reason, _ = _run(d, [hum] * 40)
    assert reason == "no_speech"


def test_silence_window_comes_from_env(monkeypatch):
    monkeypatch.setenv("ANGIZO_MIC_SILENCE_MS", "500")
    d = SilenceDetector(sample_rate=RATE)
    assert d.silence_s == 0.5


def test_empty_block_is_ignored():
    d = SilenceDetector(sample_rate=RATE)
    assert d.feed(np.zeros(0, dtype="float32")) is None
    assert d.elapsed == 0.0


# --- The backend mic loop with a fake microphone (no audio device, no Sarvam) ---

import asyncio
import sys
import types


class _FakeWs:
    def __init__(self):
        self.sent = []

    async def send_json(self, msg):
        self.sent.append(msg)


def _fake_sounddevice(blocks):
    """A sounddevice stand-in whose stream feeds the given 0.1 s blocks to the callback on start."""
    class InputStream:
        def __init__(self, samplerate, channels, dtype, callback, device=None):
            self.callback = callback

        def __enter__(self):
            for block in blocks:
                self.callback(block.reshape(-1, 1), len(block), None, None)
            return self

        def __exit__(self, *exc):
            return False

    return types.SimpleNamespace(InputStream=InputStream)


def _record(monkeypatch, blocks):
    from api import ws as ws_module
    from tools import sarvam_stt

    calls = []

    async def fake_transcribe(pcm_bytes, sample_rate=16000):
        calls.append(len(pcm_bytes))
        return ""

    monkeypatch.setitem(sys.modules, "sounddevice", _fake_sounddevice(blocks))
    monkeypatch.setattr(sarvam_stt.sarvam_stt_client, "transcribe_pcm_bytes", fake_transcribe)
    fake = _FakeWs()
    asyncio.run(ws_module.record_backend_audio(fake, "s1"))
    return fake.sent, calls


def test_silent_recording_is_never_sent_for_transcription(monkeypatch):
    sent, calls = _record(monkeypatch, [_quiet()] * 70)
    assert calls == []  # no Sarvam request (and no credits) for silence
    assert {"type": "mic_status", "state": "idle", "reason": "no_speech"} in sent
    assert any(m.get("spoken_text") == "I didn't hear anything." for m in sent)


def test_speech_then_silence_stops_and_transcribes(monkeypatch):
    sent, calls = _record(monkeypatch, [_quiet()] * 5 + [_speech()] * 10 + [_quiet()] * 20)
    assert len(calls) == 1
    assert {"type": "mic_status", "state": "transcribing", "reason": "silence"} in sent


def test_quiet_laptop_mic_still_counts_as_speech():
    # Measured on her laptop mic: room about 0.0035, speech 0.006-0.018. The old fixed 0.01 floor missed it.
    d = SilenceDetector(sample_rate=RATE, silence_ms=1200)
    blocks = [_quiet(0.0035)] * 5 + [_speech(0.0127)] * 10 + [_quiet(0.0035)] * 20  # sine peak 0.0127 = level 0.009, below the old 0.01 floor
    reason, _ = _run(d, blocks)
    assert reason == "silence"


def test_mic_is_chosen_by_part_of_its_name(monkeypatch):
    from tools.vad import pick_input_device
    devices = [{"name": "Speakers (Realtek)", "max_input_channels": 0},
               {"name": "Microphone (Realtek(R) Audio)", "max_input_channels": 2},
               {"name": "Headset (ZEB-DUKE)", "max_input_channels": 1}]
    fake = types.SimpleNamespace(query_devices=lambda kind=None: devices[1] if kind == "input" else devices)
    monkeypatch.setitem(sys.modules, "sounddevice", fake)
    assert pick_input_device("zeb-duke") == (2, "Headset (ZEB-DUKE)")
    assert pick_input_device("") == (None, "Microphone (Realtek(R) Audio)")
    monkeypatch.setenv("ANGIZO_MIC_DEVICE", "ZEB")
    assert pick_input_device() == (2, "Headset (ZEB-DUKE)")
