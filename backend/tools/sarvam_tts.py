"""
neurocode-backend/tools/sarvam_tts.py

High-scale Sarvam TTS Integration with:
- LRU In-memory audio caching for repetitive observer announcements (0 credits cost)
- Key rotation pool via SarvamKeyManager for HTTP 429/401 failover
- Primary bulbul:v3 model support with automatic fallback to bulbul:v2
- Text pre-normalization and character budget management
"""

import logging
import httpx
import hashlib
import config
from tools.sarvam_key_manager import sarvam_key_manager

logger = logging.getLogger("neurocode.sarvam_tts")

# Strict male speaker pools for Sarvam TTS
MALE_V3_SPEAKERS = {
    "shubh", "aditya", "rahul", "rohan", "amit", "dev", "ratan", "varun",
    "manan", "sumit", "kabir", "aayan", "ashutosh", "advait", "anand", "tarun",
    "sunny", "mani", "gokul", "vijay", "mohit", "rehan", "soham"
}

MALE_V2_SPEAKERS = {"karun", "hitesh", "abhilash"}

class SarvamFillerTTS:
    def __init__(self):
        self.endpoint = "https://api.sarvam.ai/text-to-speech"
        self._audio_cache: dict[str, str] = {}
        self._max_cache_size = 500

    def _get_cache_key(self, text: str, model: str, speaker: str) -> str:
        raw = f"{text.strip().lower()}:{model}:{speaker}"
        return hashlib.md5(raw.encode("utf-8")).hexdigest()

    async def generate_filler_audio_base64(self, text: str) -> str:
        """
        Generates short narration audio via Sarvam TTS with LRU caching & key rotation.
        Strictly enforces male speaker selection.
        """
        if not text:
            return ""

        clean_text = text.strip()
        # Truncate to <=450 chars at word boundary for character efficiency
        if len(clean_text) > 450:
            truncated = clean_text[:447]
            last_space = truncated.rfind(" ")
            if last_space > 350:
                clean_text = truncated[:last_space] + "..."
            else:
                clean_text = truncated + "..."

        model = getattr(config, "SARVAM_TTS_MODEL", "bulbul:v3")
        configured_speaker = getattr(config, "SARVAM_FILLER_SPEAKER", "shubh").lower()

        # Enforce strict male speaker selection
        if model == "bulbul:v3":
            speaker = configured_speaker if configured_speaker in MALE_V3_SPEAKERS else "shubh"
        else:
            speaker = configured_speaker if configured_speaker in MALE_V2_SPEAKERS else "karun"

        # 1. Check in-memory audio cache
        cache_enabled = getattr(config, "SARVAM_CACHE_ENABLED", True)
        cache_key = self._get_cache_key(clean_text, model, speaker)
        if cache_enabled and cache_key in self._audio_cache:
            logger.info(f"[SarvamTTS Cache HIT] Re-serving cached audio for '{clean_text[:40]}...' (₹0 cost, 0ms)")
            return self._audio_cache[cache_key]

        # 2. Try API key rotation pool
        max_attempts = max(1, len(sarvam_key_manager.keys))
        for attempt in range(max_attempts):
            api_key = sarvam_key_manager.get_active_key()
            if not api_key:
                logger.warning("[SarvamTTS] No Sarvam API key available.")
                break

            headers = {
                "api-subscription-key": api_key,
                "Content-Type": "application/json"
            }

            payload = {
                "inputs": [clean_text],
                "target_language_code": "en-IN",
                "speaker": speaker,
                "pace": 1.05,
                "speech_sample_rate": 16000,
                "enable_preprocessing": True,
                "model": model
            }

            # bulbul:v2 supports pitch and loudness
            if model == "bulbul:v2":
                payload["pitch"] = 0
                payload["loudness"] = 1.5

            try:
                async with httpx.AsyncClient(timeout=6.0) as client:
                    res = await client.post(self.endpoint, headers=headers, json=payload)

                    if res.status_code == 200:
                        audios = res.json().get("audios", [])
                        if audios and audios[0]:
                            audio_b64 = audios[0]
                            sarvam_key_manager.report_key_success(api_key)

                            # Save in cache
                            if cache_enabled:
                                if len(self._audio_cache) >= self._max_cache_size:
                                    # Evict oldest key
                                    oldest_key = next(iter(self._audio_cache))
                                    self._audio_cache.pop(oldest_key, None)
                                self._audio_cache[cache_key] = audio_b64

                            return audio_b64

                    elif res.status_code in (400, 422) and model == "bulbul:v3":
                        logger.warning(f"[SarvamTTS] bulbul:v3 error {res.status_code}. Falling back to bulbul:v2 with male speaker 'karun'...")
                        model = "bulbul:v2"
                        speaker = "karun"
                        continue

                    elif res.status_code in (429, 401, 403, 503):
                        logger.warning(f"[SarvamTTS] Key failed with status {res.status_code}. Rotating key (attempt {attempt+1}/{max_attempts}).")
                        sarvam_key_manager.report_key_failure(api_key, res.status_code)
                        continue
                    else:
                        logger.warning(f"[SarvamTTS] API error {res.status_code}: {res.text}")
                        break

            except Exception as e:
                logger.warning(f"[SarvamTTS] Network exception (attempt {attempt+1}): {e}")
                sarvam_key_manager.report_key_failure(api_key, 503)

        # 3. Fallback to ElevenLabs TTS if Sarvam failover exhausted
        try:
            from tools.elevenlabs_tts import elevenlabs_tts_client
            logger.info("[SarvamTTS] All Sarvam attempts failed, falling back to ElevenLabs TTS")
            return await elevenlabs_tts_client.generate_narration_audio_base64(clean_text)
        except Exception as fallback_err:
            logger.error(f"[SarvamTTS] ElevenLabs fallback error: {fallback_err}")

        return ""

sarvam_tts_client = SarvamFillerTTS()
