"""
neurocode-backend/tools/sarvam_tts.py

Sarvam TTS (bulbul) for every spoken line, with:
- an in-memory cache, so repeated phrases ("Syntax error resolved in main.py.") cost no API call;
- API key rotation through SarvamKeyManager when a key is rate-limited (429) or rejected (401/403);
- bulbul:v3 first, falling back to bulbul:v2 when v3 rejects the request (400/422);
- ElevenLabs as the last fallback when every Sarvam attempt fails.
"""

import hashlib
import logging

import httpx

import config
from tools.sarvam_key_manager import sarvam_key_manager

logger = logging.getLogger("neurocode.sarvam_tts")

SARVAM_TTS_ENDPOINT = "https://api.sarvam.ai/text-to-speech"
MAX_TEXT_CHARS = 450  # Sarvam's hard limit is 500 characters per input

# Male speaker pools: the configured speaker is used only if it belongs to the model's pool
MALE_V3_SPEAKERS = {
    "shubh", "aditya", "rahul", "rohan", "amit", "dev", "ratan", "varun",
    "manan", "sumit", "kabir", "aayan", "ashutosh", "advait", "anand", "tarun",
    "sunny", "mani", "gokul", "vijay", "mohit", "rehan", "soham",
}
MALE_V2_SPEAKERS = {"karun", "hitesh", "abhilash"}


def truncate_for_tts(text: str) -> str:
    """Trim to MAX_TEXT_CHARS at a word boundary, adding '...' when cut."""
    clean = text.strip()
    if len(clean) <= MAX_TEXT_CHARS:
        return clean
    cut = clean[: MAX_TEXT_CHARS - 3]
    last_space = cut.rfind(" ")
    return (cut[:last_space] if last_space > 350 else cut) + "..."


def pick_speaker(model: str, configured: str) -> str:
    configured = (configured or "").lower()
    if model == "bulbul:v3":
        return configured if configured in MALE_V3_SPEAKERS else "shubh"
    return configured if configured in MALE_V2_SPEAKERS else "karun"


class SarvamFillerTTS:
    def __init__(self, max_cache_size: int = 500):
        self.endpoint = SARVAM_TTS_ENDPOINT
        self._audio_cache: dict[str, str] = {}
        self._max_cache_size = max_cache_size

    @staticmethod
    def _cache_key(text: str, model: str, speaker: str) -> str:
        return hashlib.md5(f"{text.strip().lower()}:{model}:{speaker}".encode("utf-8")).hexdigest()

    def _remember(self, key: str, audio_b64: str) -> None:
        if len(self._audio_cache) >= self._max_cache_size:
            self._audio_cache.pop(next(iter(self._audio_cache)), None)  # evict the oldest entry
        self._audio_cache[key] = audio_b64

    async def generate_filler_audio_base64(self, text: str) -> str:
        """Returns base64 audio for `text`, or "" if every Sarvam attempt and ElevenLabs fail."""
        if not text or not text.strip():
            return ""

        clean_text = truncate_for_tts(text)
        model = getattr(config, "SARVAM_TTS_MODEL", "bulbul:v3")
        speaker = pick_speaker(model, getattr(config, "SARVAM_FILLER_SPEAKER", "shubh"))
        cache_enabled = getattr(config, "SARVAM_CACHE_ENABLED", True)

        cache_key = self._cache_key(clean_text, model, speaker)
        if cache_enabled and cache_key in self._audio_cache:
            logger.info(f"[SarvamTTS Cache HIT] '{clean_text[:40]}...'")
            return self._audio_cache[cache_key]

        # One attempt per key, plus one extra for the v3 -> v2 model fallback
        attempts = max(1, len(sarvam_key_manager.keys)) + 1
        for attempt in range(attempts):
            api_key = sarvam_key_manager.get_active_key()
            if not api_key:
                logger.warning("[SarvamTTS] No Sarvam API key available.")
                break

            payload = {
                "inputs": [clean_text],
                "target_language_code": "en-IN",
                "speaker": speaker,
                "pace": 1.05,
                "speech_sample_rate": 16000,
                "enable_preprocessing": True,
                "model": model,
            }
            if model == "bulbul:v2":  # only v2 supports pitch and loudness
                payload["pitch"] = 0
                payload["loudness"] = 1.5

            try:
                async with httpx.AsyncClient(timeout=6.0) as client:
                    res = await client.post(
                        self.endpoint,
                        headers={"api-subscription-key": api_key, "Content-Type": "application/json"},
                        json=payload,
                    )
            except Exception as e:
                logger.warning(f"[SarvamTTS] Network error (attempt {attempt + 1}): {e}")
                sarvam_key_manager.report_key_failure(api_key, 503)
                continue

            if res.status_code == 200:
                audios = res.json().get("audios", [])
                if audios and audios[0]:
                    sarvam_key_manager.report_key_success(api_key)
                    if cache_enabled:
                        self._remember(self._cache_key(clean_text, model, speaker), audios[0])
                    return audios[0]
                logger.warning("[SarvamTTS] 200 response without audio.")
                break

            if res.status_code in (400, 422) and model == "bulbul:v3":
                logger.warning(f"[SarvamTTS] bulbul:v3 returned {res.status_code}; retrying with bulbul:v2.")
                model = "bulbul:v2"
                speaker = pick_speaker(model, getattr(config, "SARVAM_FILLER_SPEAKER", "karun"))
                continue

            if res.status_code in (401, 403, 429, 503):
                logger.warning(f"[SarvamTTS] Key failed with {res.status_code}; rotating (attempt {attempt + 1}).")
                sarvam_key_manager.report_key_failure(api_key, res.status_code)
                continue

            logger.warning(f"[SarvamTTS] API error {res.status_code}: {res.text[:200]}")
            break

        try:
            from tools.elevenlabs_tts import elevenlabs_tts_client
            logger.info("[SarvamTTS] Sarvam failed; falling back to ElevenLabs.")
            return await elevenlabs_tts_client.generate_narration_audio_base64(clean_text)
        except Exception as fallback_err:
            logger.error(f"[SarvamTTS] ElevenLabs fallback error: {fallback_err}")
        return ""


sarvam_tts_client = SarvamFillerTTS()
