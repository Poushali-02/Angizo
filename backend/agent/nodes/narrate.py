"""
neurocode-backend/agent/nodes/narrate.py
"""
import logging
from agent.state import AgentState
from tools.elevenlabs_tts import elevenlabs_tts_client
from tools.sarvam_tts import sarvam_tts_client

logger = logging.getLogger("neurocode.agent.narrate")

async def narrate_response(state: AgentState) -> AgentState:
    """
    [Narrate] node.
    Generates the final spoken audio summary for dynamic tool executions.
    """
    v_status = state.get("verification_status")
    result = state.get("action_result", {})
    reasoning = state.get("reasoning", "")
    ctx = state.get("context", {})
    risk_band = ctx.get("risk_band", "safe")

    executed_steps = result.get("executed_steps", []) if isinstance(result, dict) else []
    executed_tools = [s.get("tool") for s in executed_steps]

    if v_status == "failure" or (isinstance(result, dict) and result.get("status") == "failure"):
        narration = f"Action failed: {result.get('detail', 'unknown error')}."
        risk_band = "high-risk"
    elif "commit_changes" in executed_tools and "push_to_remote" in executed_tools:
        narration = f"Committed {_commit_summary(executed_steps)} and pushed to origin."
    elif "commit_changes" in executed_tools:
        narration = f"Committed {_commit_summary(executed_steps)}."
    elif "push_to_remote" in executed_tools:
        narration = "Push completed successfully."
    elif "pull_from_remote" in executed_tools:
        narration = "Pulled latest changes from remote origin successfully."
    else:
        narration = reasoning if reasoning else "Action completed successfully."

    # Primary narration audio via Sarvam TTS (with ElevenLabs fallback)
    audio_base64 = ""
    try:
        audio_base64 = await sarvam_tts_client.generate_filler_audio_base64(narration)
    except Exception as e:
        logger.error(f"[Narrate] Sarvam TTS generation failed: {e}")

    if not audio_base64:
        try:
            logger.info("[Narrate] Falling back to ElevenLabs TTS for voice narration")
            audio_base64 = await elevenlabs_tts_client.generate_narration_audio_base64(narration, risk_band=risk_band)
        except Exception as e:
            logger.error(f"[Narrate] ElevenLabs TTS fallback failed: {e}")

    logger.info(f"[Narrate] {narration} (risk_band={risk_band}, audio_len={len(audio_base64)})")
    return {
        "narration": narration,
        "earcon": risk_band,
        "action_result": {
            **(result if isinstance(result, dict) else {}),
            "audio_base64": audio_base64
        }
    }


def _commit_summary(executed_steps: list) -> str:
    """'2 files with message: fix login retry' from the commit step's result."""
    for step in executed_steps:
        if step.get("tool") == "commit_changes" and isinstance(step.get("result"), dict):
            res = step["result"]
            n = len(res.get("files", []))
            noun = "file" if n == 1 else "files"
            if res.get("message"):
                return f"{n} {noun} with message: {res['message']}"
    return "your changes"
