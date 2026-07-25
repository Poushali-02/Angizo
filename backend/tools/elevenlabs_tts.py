"""
neurocode-backend/tools/elevenlabs_tts.py

ElevenLabs Primary TTS Integration:
- Primary risk-toned voice narration.
- Voice parameters tuned according to risk_band ('safe', 'caution', 'high-risk').
  - safe: calm, even pace
  - caution: neutral-alert tone, slightly clipped
  - high-risk: urgent, faster pace
"""

import logging
import httpx
import base64
import config

logger = logging.getLogger("neurocode.elevenlabs_tts")

class ElevenLabsTTS:
    def __init__(self, api_key: str = None):
        self.api_key = api_key or config.ELEVENLABS_API_KEY
        # Default voice ID (e.g. '21m00Tcm4TlvDq8ikWAM' Rachel / neutral voice)
        self.voice_id = "21m00Tcm4TlvDq8ikWAM"

    async def generate_narration_audio_base64(self, text: str, risk_band: str = "safe") -> str:
        """
        Generates primary narration audio via ElevenLabs REST / streaming API.
        Maps risk_band to voice stability / similarity settings.
        Returns base64 encoded audio string.
        """
        if not self.api_key:
            logger.debug("[ElevenLabsTTS] ELEVENLABS_API_KEY not set. Voice narration skipped.")
            return ""

        url = f"https://api.elevenlabs.io/v1/text-to-speech/{self.voice_id}"
        headers = {
            "xi-api-key": self.api_key,
            "Content-Type": "application/json"
        }

        # Dynamic parameter tuning per AGENT_SPEC.md risk band specs
        if risk_band == "high-risk":
            stability = 0.3
            similarity_boost = 0.85
            style = 0.4
        elif risk_band == "caution":
            stability = 0.5
            similarity_boost = 0.75
            style = 0.2
        else: # safe
            stability = 0.75
            similarity_boost = 0.75
            style = 0.0

        payload = {
            "text": text,
            "model_id": "eleven_monolingual_v1",
            "voice_settings": {
                "stability": stability,
                "similarity_boost": similarity_boost,
                "style": style,
                "use_speaker_boost": True
            }
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.post(url, headers=headers, json=payload)
                if res.status_code == 200:
                    audio_bytes = res.content
                    return base64.b64encode(audio_bytes).decode("utf-8")
                else:
                    logger.warning(f"[ElevenLabsTTS] API error {res.status_code}: {res.text}")
        except Exception as e:
            logger.warning(f"[ElevenLabsTTS] Exception during primary TTS: {e}")

        return ""

elevenlabs_tts_client = ElevenLabsTTS()
