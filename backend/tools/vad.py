"""
backend/tools/vad.py

Decides when a mic recording should stop by itself, so the user presses the mic shortcut
once, speaks, and stops talking (no second press).

How: the first ~0.3 s measure the room's background level; anything clearly louder
(3x the background, and at least MIN_LEVEL) counts as speech. After speech, a stretch
of quiet (default 1.2 s) ends the recording. Two safety limits: nothing said within 6 s
(stop, and skip transcription, so no Sarvam credits are spent on silence), and 15 s at most.
"""

import math
import os
from typing import Optional

MIN_LEVEL = 0.01  # RMS of float samples in [-1, 1]; quieter than this is never speech


def _rms(samples) -> float:
    try:
        import numpy as np
        arr = np.asarray(samples, dtype="float64").ravel()
        return float(np.sqrt(np.mean(arr * arr))) if arr.size else 0.0
    except ImportError:
        values = list(samples)
        return math.sqrt(sum(v * v for v in values) / len(values)) if values else 0.0


class SilenceDetector:
    def __init__(self, sample_rate: int = 16000, silence_ms: Optional[int] = None,
                 no_speech_s: float = 6.0, max_s: float = 15.0, calibrate_ms: int = 300):
        self.sample_rate = sample_rate
        self.silence_s = (silence_ms if silence_ms is not None
                          else int(os.getenv("ANGIZO_MIC_SILENCE_MS", "1200"))) / 1000
        self.no_speech_s = no_speech_s
        self.max_s = max_s
        self.calibrate_s = calibrate_ms / 1000
        self._samples = 0        # counted as integers so the limits don't drift
        self._quiet_samples = 0
        self.heard_speech = False
        self._noise_levels: list[float] = []
        self.threshold = MIN_LEVEL

    @property
    def elapsed(self) -> float:
        return self._samples / self.sample_rate

    @property
    def quiet_for(self) -> float:
        return self._quiet_samples / self.sample_rate

    def feed(self, samples) -> Optional[str]:
        """Add one block of audio. Returns why to stop ("silence", "no_speech", "max_length") or None."""
        n = len(samples)
        if n == 0:
            return None
        level = _rms(samples)
        self._samples += n

        if self._samples <= round(self.calibrate_s * self.sample_rate):
            self._noise_levels.append(level)
            self.threshold = max(MIN_LEVEL, 3 * (sum(self._noise_levels) / len(self._noise_levels)))
            return None

        if level >= self.threshold:
            self.heard_speech = True
            self._quiet_samples = 0
        elif self.heard_speech:
            self._quiet_samples += n

        if self.heard_speech and self._quiet_samples >= round(self.silence_s * self.sample_rate):
            return "silence"
        if not self.heard_speech and self._samples >= round(self.no_speech_s * self.sample_rate):
            return "no_speech"
        if self._samples >= round(self.max_s * self.sample_rate):
            return "max_length"
        return None
