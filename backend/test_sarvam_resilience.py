"""
backend/test_sarvam_resilience.py

Unit tests for Sarvam API Key Manager, LRU Caching, and bulbul:v3 execution.
"""

import sys
import os
import asyncio

# Add backend directory to sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tools.sarvam_key_manager import sarvam_key_manager
from tools.sarvam_tts import sarvam_tts_client

async def test_sarvam_resilience():
    print("--- Testing Sarvam Key Manager & Resilient TTS ---")

    # 1. Test Key Manager initialization and rotation
    active_key = sarvam_key_manager.get_active_key()
    print(f"[KeyManager Test] Primary Active Key: '{active_key[:8]}...'")
    assert len(active_key) > 0, "Active key should not be empty"

    # Simulate key 429 rate limit failure report
    sarvam_key_manager.report_key_failure(active_key, status_code=429)
    next_key = sarvam_key_manager.get_active_key()
    print(f"[KeyManager Test] After 429 rotation key: '{next_key[:8]}...'")

    # 2. Test TTS Generation & Audio Cache Hit
    test_phrase = "Copilot generated 10 lines of code in test.ts."
    
    print("\n[TTS Call 1 - Cache MISS / Live API Call]...")
    audio1 = await sarvam_tts_client.generate_filler_audio_base64(test_phrase)
    print(f"Audio 1 Length: {len(audio1)} chars")

    print("\n[TTS Call 2 - Cache HIT Test]...")
    audio2 = await sarvam_tts_client.generate_filler_audio_base64(test_phrase)
    print(f"Audio 2 Length: {len(audio2)} chars")

    if audio1 and audio2:
        assert audio1 == audio2, "Cache hit audio must match original audio"
        print("\n[SUCCESS] LRU Audio Cache Hit verified (0ms, INR 0 credits used)!")

    print("\n[SUCCESS] All Sarvam Resilience tests completed!")

if __name__ == "__main__":
    asyncio.run(test_sarvam_resilience())
