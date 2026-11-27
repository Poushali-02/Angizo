"""
neurocode-backend/tools/sarvam_stt.py

Sarvam STT Integration following Sarvam Strategy Spec:
- 16kHz mono 16-bit PCM streaming audio capture.
- WebSocket / REST audio chunk transcription.
- Transcribes user voice commands into English text.
"""

import logging
import httpx
import config

logger = logging.getLogger("neurocode.sarvam_stt")

class SarvamSTT:
    def __init__(self, api_key: str = None):
        self.api_key = api_key or config.SARVAM_API_KEY
        self.endpoint = "https://api.sarvam.ai/speech-to-text"

    async def transcribe_pcm_bytes(self, pcm_bytes: bytes, sample_rate: int = 16000) -> str:
        """
        Transcribes Int16 PCM audio bytes using Sarvam STT REST/streaming API.
        If SARVAM_API_KEY is not set or request fails, falls back gracefully.
        """
        if not self.api_key:
            logger.warning("[SarvamSTT] SARVAM_API_KEY not configured. STT skipping.")
            return ""
        headers = {
            "api-subscription-key": self.api_key
        }

        # Convert raw PCM bytes to WAV header + PCM payload for API compatibility
        wav_bytes = self._pcm_to_wav(pcm_bytes, sample_rate=sample_rate)

        files = {
            "file": ("command.wav", wav_bytes, "audio/wav")
        }
        data = {
            "model": "saarika:v2.5",
            "language_code": "en-IN",
            "with_timestamps": "false"
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(self.endpoint, headers=headers, files=files, data=data)
                if response.status_code == 200:
                    res_json = response.json()
                    transcript = res_json.get("transcript", "").strip()
                    logger.info(f"[SarvamSTT] Transcribed audio: '{transcript}'")
                    return transcript
                else:
                    logger.error(f"[SarvamSTT] API error status {response.status_code}: {response.text}")
                    return ""
        except Exception as e:
            logger.error(f"[SarvamSTT] Exception during transcription: {e}")
            return ""

    def _pcm_to_wav(self, pcm_bytes: bytes, sample_rate: int = 16000, num_channels: int = 1, bits_per_sample: int = 16) -> bytes:
        """Constructs a basic WAV header around raw PCM data."""
        byte_rate = sample_rate * num_channels * (bits_per_sample // 8)
        block_align = num_channels * (bits_per_sample // 8)
        data_size = len(pcm_bytes)
        chunk_size = 36 + data_size

        header = bytearray()
        # RIFF header
        header.extend(b'RIFF')
        header.extend(chunk_size.to_bytes(4, 'little'))
        header.extend(b'WAVE')
        # fmt subchunk
        header.extend(b'fmt ')
        header.extend((16).to_bytes(4, 'little')) # Subchunk1Size (16 for PCM)
        header.extend((1).to_bytes(2, 'little'))  # AudioFormat (1 for PCM)
        header.extend(num_channels.to_bytes(2, 'little'))
        header.extend(sample_rate.to_bytes(4, 'little'))
        header.extend(byte_rate.to_bytes(4, 'little'))
        header.extend(block_align.to_bytes(2, 'little'))
        header.extend(bits_per_sample.to_bytes(2, 'little'))
        # data subchunk
        header.extend(b'data')
        header.extend(data_size.to_bytes(4, 'little'))
        
        return bytes(header) + pcm_bytes

sarvam_stt_client = SarvamSTT()
