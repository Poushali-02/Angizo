"""
neurocode-backend/tools/sarvam_tts.py

Sarvam TTS Integration following Sarvam Strategy Spec:
- Zero-silence filler narration ONLY (channel='filler').
- Uses neutral/informational voice tier (e.g. speaker 'ratan' / neutral English).
- Non-blocking fire-and-forget execution so it never delays agent reasoning.
"""

import logging
import httpx
import base64
import config

logger = logging.getLogger("neurocode.sarvam_tts")

class SarvamFillerTTS:
    def __init__(self, api_key: str = None):
        self.api_key = api_key or config.SARVAM_API_KEY
        self.endpoint = "https://api.sarvam.ai/text-to-speech"
        # Neutral English speaker tier compatible with bulbul:v2
        self.speaker = getattr(config, "SARVAM_FILLER_SPEAKER", "anushka")

    async def generate_filler_audio_base64(self, text: str) -> str:
        """
        Generates short narration audio via Sarvam TTS.
        Safely truncates inputs to <=450 characters to respect Sarvam's 500 char limit.
        Falls back to ElevenLabs TTS if Sarvam fails.
        """
        api_key = self.api_key or getattr(config, "SARVAM_API_KEY", "")
        speaker = getattr(config, "SARVAM_FILLER_SPEAKER", None) or "anushka"

        if not text:
            return ""

        # Sarvam API enforces max 500 chars limit. Safely truncate to <=450 chars at word boundary.
        clean_text = text.strip()
        if len(clean_text) > 450:
            truncated = clean_text[:447]
            last_space = truncated.rfind(" ")
            if last_space > 350:
                clean_text = truncated[:last_space] + "..."
            else:
                clean_text = truncated + "..."

        if api_key:
            headers = {
                "api-subscription-key": api_key,
                "Content-Type": "application/json"
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
                "model": "bulbul:v2"
            }

            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    res = await client.post(self.endpoint, headers=headers, json=payload)
                    if res.status_code == 200:
                        audios = res.json().get("audios", [])
                        if audios:
                            return audios[0]
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
