"""
neurocode-backend/tools/elevenlabs_tts.py

ElevenLabs TTS Integration with:
- In-memory TTSAudioCache: instant replay for repeated phrases (<2ms)
- Persistent httpx.AsyncClient: eliminates SSL/TCP handshake overhead
- Default model: eleven_flash_v2_5 (<150ms latency, Free Tier compatible)
- Automatic fallback to eleven_multilingual_v2 on model restriction errors
- Risk-band voice tuning: safe / caution / high-risk
"""

import asyncio
import logging
import time
import hashlib
import httpx
import base64
import config

logger = logging.getLogger("neurocode.elevenlabs_tts")

# ── In-Memory TTS Audio Cache ───────────────────────────────────────────────
# Key: sha256(text + voice_id + risk_band), Value: base64 audio string
_tts_cache: dict[str, str] = {}
MAX_CACHE_SIZE = 200

def _cache_key(text: str, voice_id: str, risk_band: str) -> str:
    return hashlib.sha256(f"{text}|{voice_id}|{risk_band}".encode()).hexdigest()[:24]


# Free-tier premade voices that work without a paid plan
FREE_VOICE_IDS = {
    "21m00Tcm4TlvDq8ikWAM",  # Rachel — redirect to Bella
}
BELLA_VOICE_ID = "EXAVITQu4vr4xnSDxMaL"  # Bella — Premade female, Free Tier compatible

# Ultra-fast model (Free Tier) with fallback
FLASH_MODEL = "eleven_flash_v2_5"
MULTILINGUAL_MODEL = "eleven_multilingual_v2"


class ElevenLabsTTS:
    def __init__(self, api_key: str = None):
        self.api_key = api_key or config.ELEVENLABS_API_KEY
        self.voice_id = getattr(config, "ELEVENLABS_VOICE_ID", BELLA_VOICE_ID)
        # Persistent HTTP client (reused across requests on the same event loop)
        self._client: httpx.AsyncClient | None = None
        self._client_loop = None
        # After the key is rejected (401/403: wrong key or missing text_to_speech permission),
        # stop calling for a while instead of paying a round trip on every sentence.
        self._disabled_until = 0.0

    def _get_client(self) -> httpx.AsyncClient:
        """Return a pooled AsyncClient for the running event loop (a new loop gets a new client)."""
        loop = asyncio.get_running_loop()
        if self._client is None or self._client.is_closed or self._client_loop is not loop:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(connect=2.0, read=8.0, write=3.0, pool=1.0),
                limits=httpx.Limits(max_keepalive_connections=5, max_connections=10),
            )
            self._client_loop = loop
        return self._client

    async def close(self) -> None:
        """Gracefully close the persistent HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def generate_narration_audio_base64(self, text: str, risk_band: str = "safe") -> str:
        """
        Generates primary narration audio via ElevenLabs REST API.
        - Checks in-memory cache first (instant <2ms replay).
        - Uses eleven_flash_v2_5 (ultra-low latency, Free Tier compatible).
        - Automatically falls back to eleven_multilingual_v2 on model restriction.
        - Maps risk_band to voice stability/similarity settings.
        """
        api_key = self.api_key or getattr(config, "ELEVENLABS_API_KEY", "")
        if not api_key:
            logger.debug("[ElevenLabsTTS] ELEVENLABS_API_KEY not set. Narration skipped.")
            return ""
        if time.monotonic() < self._disabled_until:
            return ""  # key recently rejected: the panel's system voice reads the text instead

        # Resolve voice ID — redirect known library voices to free-tier Bella
        voice_id = getattr(config, "ELEVENLABS_VOICE_ID", None) or BELLA_VOICE_ID
        if voice_id in FREE_VOICE_IDS:
            voice_id = BELLA_VOICE_ID

        # ── Cache Hit → instant return ────────────────────────────────────────
        key = _cache_key(text, voice_id, risk_band)
        if key in _tts_cache:
            logger.debug(f"[ElevenLabsTTS] Cache HIT for '{text[:40]}...' — returning instantly")
            return _tts_cache[key]

        # Risk-band voice parameter tuning
        if risk_band == "high-risk":
            stability, similarity_boost, style = 0.3, 0.85, 0.4
        elif risk_band == "caution":
            stability, similarity_boost, style = 0.5, 0.75, 0.2
        else:  # safe
            stability, similarity_boost, style = 0.75, 0.75, 0.0

        headers = {
            "xi-api-key": api_key,
            "Content-Type": "application/json",
        }
        payload = {
            "text": text,
            "voice_settings": {
                "stability": stability,
                "similarity_boost": similarity_boost,
                "style": style,
                "use_speaker_boost": True,
            },
        }

        client = self._get_client()

        # Try eleven_flash_v2_5 first (ultra-fast, Free Tier)
        for model_id in [FLASH_MODEL, MULTILINGUAL_MODEL]:
            url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
            payload["model_id"] = model_id
            try:
                res = await client.post(url, headers=headers, json=payload)
                if res.status_code == 200:
                    audio_bytes = res.content
                    audio_b64 = base64.b64encode(audio_bytes).decode("utf-8")
                    # ── Cache result ──────────────────────────────────────────
                    if len(_tts_cache) >= MAX_CACHE_SIZE:
                        oldest = next(iter(_tts_cache))
                        del _tts_cache[oldest]
                    _tts_cache[key] = audio_b64
                    logger.debug(f"[ElevenLabsTTS] Cached audio (model={model_id}, cache size: {len(_tts_cache)})")
                    return audio_b64
                elif res.status_code == 401:
                    logger.warning(f"[ElevenLabsTTS] Key rejected (401); not retrying for 10 minutes: {res.text[:160]}")
                    self._disabled_until = time.monotonic() + 600
                    break
                elif res.status_code in (402, 403) and model_id == FLASH_MODEL:
                    logger.warning(f"[ElevenLabsTTS] {model_id} not available, trying {MULTILINGUAL_MODEL}")
                    continue
                else:
                    logger.warning(f"[ElevenLabsTTS] API error {res.status_code}: {res.text}")
                    break
            except Exception as e:
                logger.warning(f"[ElevenLabsTTS] Exception during TTS ({model_id}): {e}")
                break

        return ""


elevenlabs_tts_client = ElevenLabsTTS()
