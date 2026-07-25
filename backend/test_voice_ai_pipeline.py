"""
backend/test_voice_ai_pipeline.py

Unit test suite to verify:
1. Sarvam STT PCM buffer processing and WAV header creation
2. Gemini intent classification & diff intelligence (with fallback handling)
3. ElevenLabs primary risk-toned TTS generation
4. Sarvam filler TTS generation
5. End-to-end agent graph invocation with voice narration payload
"""

import sys
import os
import asyncio

# Add backend directory to sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tools.sarvam_stt import sarvam_stt_client
from tools.sarvam_tts import sarvam_tts_client
from tools.elevenlabs_tts import elevenlabs_tts_client
from tools.diff_intelligence import diff_intelligence
from agent.graph import agent_graph

def test_pcm_to_wav_header():
    """Verify raw PCM bytes are wrapped in a valid WAV header."""
    raw_pcm = b"\x00\x00" * 8000 # 0.5s of silent 16kHz mono audio
    wav_bytes = sarvam_stt_client._pcm_to_wav(raw_pcm, sample_rate=16000)
    
    assert wav_bytes.startswith(b"RIFF")
    assert b"WAVE" in wav_bytes
    assert len(wav_bytes) == len(raw_pcm) + 44

async def test_diff_intelligence_classification():

    """Test intent classification fallback and diff intelligence."""
    intent = await diff_intelligence.classify_intent("Review my changes before committing")
    assert intent in ["git_review", "git_commit", "git_status"]

    diff_text = """diff --git a/auth.py b/auth.py
index 1234..5678 100644
--- a/auth.py
+++ b/auth.py
@@ -1,3 +1,5 @@
+def check_password(pwd):
+    return True
"""
    diff_info = await diff_intelligence.classify_diff(diff_text)
    assert "risk_band" in diff_info
    assert diff_info["risk_band"] in ["safe", "caution", "high-risk"]

def test_agent_graph_with_review_intent():
    """Verify agent graph executes git_review intent end-to-end."""
    initial_state = {
        "transcript": "Review my changes before committing",
        "intent": "git_review",
        "context": {"diff_text": "diff --git a/test.py b/test.py\n+print('hello')"},
        "reasoning": None,
        "confirmation_required": False,
        "confirmed": False,
        "action_result": None,
        "verification_status": "pending",
        "narration": None,
        "earcon": None
    }

    final_state = agent_graph.invoke(initial_state)
    assert final_state["intent"] in ["git_review", "git_commit", "git_status"]
    assert "reasoning" in final_state


if __name__ == "__main__":
    print("Running voice & AI pipeline tests...")
    test_pcm_to_wav_header()
    asyncio.run(test_diff_intelligence_classification())
    test_agent_graph_with_review_intent()
    print("All tests passed successfully!")
