"""
neurocode-backend/tools/sarvam_tts.py

Sarvam TTS Integration with:
- In-memory TTSAudioCache: saves API calls for repeated phrases (<2ms replay)
- Persistent httpx.AsyncClient: eliminates SSL handshake overhead (~250ms saved/req)
- Falls back to ElevenLabs if Sarvam fails or is unconfigured
"""

import logging
import hashlib
import httpx
import config

logger = logging.getLogger("neurocode.sarvam_tts")

# ── In-Memory TTS Audio Cache ───────────────────────────────────────────────
# Key: sha256(text + speaker), Value: base64-encoded audio string
# Avoids redundant API calls for identical narration phrases (e.g. "Syntax errors resolved")
_tts_cache: dict[str, str] = {}
MAX_CACHE_SIZE = 200  # Maximum number of cached phrases

def _cache_key(text: str, speaker: str) -> str:
    return hashlib.sha256(f"{text}|{speaker}".encode()).hexdigest()[:24]


class SarvamFillerTTS:
    def __init__(self, api_key: str = None):
        self.api_key = api_key or config.SARVAM_API_KEY
        self.endpoint = "https://api.sarvam.ai/text-to-speech"
        self.speaker = getattr(config, "SARVAM_FILLER_SPEAKER", "anushka")
        # Persistent HTTP client (reused across requests — saves TCP/TLS handshake time)
        self._client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        """Return or create a persistent AsyncClient with connection pooling."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(connect=2.0, read=5.0, write=3.0, pool=1.0),
                limits=httpx.Limits(max_keepalive_connections=5, max_connections=10),
            )
        return self._client

    async def close(self) -> None:
        """Gracefully close the persistent HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def generate_filler_audio_base64(self, text: str) -> str:
        """
        Generates short narration audio via Sarvam TTS.
        - Checks in-memory cache first (instant <2ms replay for repeated phrases).
        - Safely truncates inputs to <=450 characters.
        - Falls back to ElevenLabs TTS if Sarvam fails.
        """
        api_key = self.api_key or getattr(config, "SARVAM_API_KEY", "")
        speaker = getattr(config, "SARVAM_FILLER_SPEAKER", None) or "anushka"

        if not text:
            return ""

        # Truncate to <=450 chars at word boundary (Sarvam hard limit: 500 chars)
        clean_text = text.strip()
        if len(clean_text) > 450:
            truncated = clean_text[:447]
            last_space = truncated.rfind(" ")
            clean_text = (truncated[:last_space] + "...") if last_space > 350 else (truncated + "...")

        # ── Cache Hit → instant return ────────────────────────────────────────
        key = _cache_key(clean_text, speaker)
        if key in _tts_cache:
            logger.debug(f"[SarvamTTS] Cache HIT for '{clean_text[:40]}...' — returning instantly")
            return _tts_cache[key]

        if api_key:
            headers = {
                "api-subscription-key": api_key,
                "Content-Type": "application/json",
            }
            payload = {
                "inputs": [clean_text],
                "target_language_code": "en-IN",
                "speaker": speaker,
                "pitch": 0,
                "pace": 1.1,
                "loudness": 1.5,
                "speech_sample_rate": 16000,
                "enable_preprocessing": True,
                "model": "bulbul:v2",
            }

            try:
                client = self._get_client()
                res = await client.post(self.endpoint, headers=headers, json=payload)
                if res.status_code == 200:
                    audios = res.json().get("audios", [])
                    if audios:
                        audio_b64 = audios[0]
                        # ── Cache Miss → store result ─────────────────────────
                        if len(_tts_cache) >= MAX_CACHE_SIZE:
                            # Evict oldest entry (simple LRU-lite: remove first key)
                            oldest = next(iter(_tts_cache))
                            del _tts_cache[oldest]
                        _tts_cache[key] = audio_b64
                        logger.debug(f"[SarvamTTS] Cached audio for '{clean_text[:40]}' (cache size: {len(_tts_cache)})")
                        return audio_b64
                else:
                    logger.warning(f"[SarvamTTS] API error {res.status_code}: {res.text}")
            except Exception as e:
                logger.warning(f"[SarvamTTS] Exception during Sarvam TTS: {e}")

        # Fallback to ElevenLabs TTS if Sarvam fails or is unconfigured
        try:
            from tools.elevenlabs_tts import elevenlabs_tts_client
            logger.info("[SarvamTTS] Falling back to ElevenLabs TTS")
            return await elevenlabs_tts_client.generate_narration_audio_base64(clean_text)
        except Exception as fallback_err:
            logger.error(f"[SarvamTTS] ElevenLabs fallback error: {fallback_err}")

        return ""


sarvam_tts_client = SarvamFillerTTS()
