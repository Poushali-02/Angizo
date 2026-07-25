"""
neurocode-backend/api/ws.py

Main WebSocket endpoint — client <-> agent bridge.
Step 2 & 3: Wires the WebSocket to the LangGraph agent graph.

Matches DESIGN.md API contract:
  Client → Server: {"type": "audio_frame", "data": "<base64 PCM chunk>"}
  Client → Server: {"type": "text_command", "text": "commit my changes"}
  Client → Server: {"type": "confirm_response", "confirmed": true}
  
  Server → Client: {"type": "action_result", "status": "success", "detail": "..."}
  Server → Client: {"type": "confirmation_request", "prompt": "..."}
"""

import json
import base64
import logging
import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from agent.graph import agent_graph
from agent.state import AgentState
from tools.diff_intelligence import diff_intelligence
from tools.sarvam_tts import sarvam_tts_client

logger = logging.getLogger("neurocode.ws")
router = APIRouter()

def is_gibberish(text: str) -> bool:
    text = text.strip()
    if not text:
        return True
    
    # If the text matches command keywords, it's not gibberish
    valid_keywords = {
        "git", "diff", "status", "commit", "push", "pull", "explain", "help", 
        "show", "get", "review", "save", "what", "how", "why", "code", "file", 
        "add", "create", "make", "delete", "remove", "run", "start", "stop"
    }
    
    # Split the text into words and check
    words = text.split()
    if not words:
        return True
        
    # If any word is in valid_keywords, it's definitely not gibberish
    if any(w.lower() in valid_keywords for w in words):
        return False

    vowels = set("aeiouyAEIOUY")
    
    # Check words
    for word in words:
        # Ignore short words
        if len(word) <= 3:
            continue
            
        # Count vowels and consonants
        v_count = sum(1 for c in word if c in vowels)
        c_count = sum(1 for c in word if c.isalpha() and c not in vowels)
        
        # 1. No vowels in a relatively long word (len >= 4)
        if len(word) >= 4 and v_count == 0:
            return True
            
        # 2. Vowel ratio is extremely low in a long word (len >= 6)
        if len(word) >= 6 and (v_count / len(word)) < 0.10:
            return True
            
        # 3. Too many consecutive consonants in a row
        consecutive_consonants = 0
        max_consecutive_consonants = 0
        for char in word:
            if char.isalpha() and char not in vowels:
                consecutive_consonants += 1
                if consecutive_consonants > max_consecutive_consonants:
                    max_consecutive_consonants = consecutive_consonants
            else:
                consecutive_consonants = 0
        if max_consecutive_consonants >= 6:
            return True
            
        # 4. Same character repeating 4+ times consecutively
        consecutive_same = 1
        max_consecutive_same = 1
        for i in range(1, len(word)):
            if word[i] == word[i-1]:
                consecutive_same += 1
                if consecutive_same > max_consecutive_same:
                    max_consecutive_same = consecutive_same
            else:
                consecutive_same = 1
        if max_consecutive_same >= 4:
            return True

    return False


async def handle_voice_transcript(ws: WebSocket, session_id: str, transcript: str):
    """Processes transcribed voice text, handling verbal confirmations if active."""
    state = session_states.get(session_id)
    if not state:
        return

    logger.info(f"[Voice] Processing transcript: '{transcript}'")
    
    if state.get("confirmation_required"):
        t_lower = transcript.lower().strip()
        # Verbal confirm keywords
        if any(w in t_lower for w in ["yes", "confirm", "proceed", "ok", "permit"]):
            logger.info("[Voice] Verbal confirmation detected.")
            state["confirmed"] = True
            asyncio.create_task(run_agent_graph(ws, session_id))
            return
        # Verbal cancel keywords
        elif any(w in t_lower for w in ["no", "cancel", "deny", "stop"]):
            logger.info("[Voice] Verbal cancellation detected.")
            state["confirmed"] = False
            state["confirmation_required"] = False
            state["env_confirmations_received"] = 0
            await ws.send_json({
                "type": "action_result",
                "status": "cancelled",
                "detail": "Action cancelled by user."
            })
            return

    # Not in confirmation or not a confirmation keyword; treat as new text command
    if "\x00" in transcript or is_gibberish(transcript):
        logger.warning(f"[WS Voice] Rejecting invalid/irrelevant voice transcript: {transcript}")
        await ws.send_json({
            "type": "action_result",
            "status": "failure",
            "detail": "Rejected: Invalid or irrelevant voice input detected."
        })
        return

    state["transcript"] = transcript
    state["confirmation_required"] = False
    state["confirmed"] = False
    state["env_confirmations_received"] = 0
    asyncio.create_task(run_agent_graph(ws, session_id))


# In-memory session state for the hackathon (Step 2)
# Real implementation would use MongoDB per DESIGN.md
session_states = {}

# Per-session audio buffers for incoming 16kHz PCM audio frames
session_audio_buffers = {}

# Per-session active workspace paths set by client
session_workspaces = {}

async def run_agent_graph(ws: WebSocket, session_id: str):
    """Runs the LangGraph agent and handles messaging with the client."""
    state = session_states.get(session_id)
    if not state:
        return

    # Set the workspace path for this session in git_tool
    workspace_path = session_workspaces.get(session_id)
    if workspace_path:
        import tools.git_tool as git_tool
        git_tool._set_repo_path(workspace_path)

    # Check if we are resuming from a confirmation
    if state.get("confirmation_required") and state.get("confirmed"):
        logger.info("[WS] Resuming agent after confirmation.")

        transcript = state.get("transcript", "")
        if ".env" in transcript.lower() or "dotenv" in transcript.lower():
            # We have the user's confirmation! Regenerate actual reasoning from RAG context
            from tools.gemini_llm import gemini_llm
            ctx = state.get("context", {})
            git_status = ctx.get("git_status", {})
            diff_text = ctx.get("diff_text", "")
            rag_context = ctx.get("rag_context", "")
            git_combined_info = f"Git Status: {git_status}\n\nWorking Tree Git Diff:\n{diff_text[:3000]}"
            logger.info("[WS] Generating actual reasoning for .env access...")
            reasoning = await gemini_llm.generate_reasoning(transcript, rag_context=rag_context, git_info=git_combined_info)
            state["reasoning"] = reasoning

        from agent.nodes import execute_action, verify_action, narrate_response
        result = await execute_action(state)
        state.update(result)
        result = verify_action(state)
        state.update(result)
        result = await narrate_response(state)
        state.update(result)

        # Reset confirmation state
        state["confirmation_required"] = False
        state["confirmed"] = False
        state["env_confirmations_received"] = 0
        
        act_res = state.get("action_result", {})
        await ws.send_json({
            "type": "action_result",
            "status": state.get("verification_status", "success"),
            "detail": state.get("narration", ""),
            "audio_base64": act_res.get("audio_base64", "") if isinstance(act_res, dict) else ""
        })
        return

    # Trigger non-blocking Sarvam zero-silence filler narration if available
    try:
        from tools.sarvam_tts import sarvam_tts_client
        filler_audio = await sarvam_tts_client.generate_filler_audio_base64("Processing your request...")
        if filler_audio:
            await ws.send_json({
                "type": "audio_narration",
                "audio_base64": filler_audio,
                "channel": "filler"
            })
    except Exception as e:
        logger.debug(f"[WS] Filler TTS skipped: {e}")

    # Otherwise, it's a new command. Run the graph from the start.
    logger.info(f"[WS] Invoking agent graph for transcript: '{state['transcript']}'")
    try:
        final_state = await agent_graph.ainvoke(state)
        session_states[session_id] = final_state

        act_res = final_state.get("action_result", {})
        audio_b64 = act_res.get("audio_base64", "") if isinstance(act_res, dict) else ""

        if final_state.get("confirmation_required") and not final_state.get("confirmed"):
            logger.info("[WS] Agent paused for confirmation.")
            await ws.send_json({
                "type": "confirmation_request",
                "prompt": final_state.get("confirmation_message", "Continue?"),
                "audio_base64": audio_b64
            })
        else:
            logger.info("[WS] Agent completed run.")
            await ws.send_json({
                "type": "action_result",
                "status": final_state.get("verification_status", "success"),
                "detail": final_state.get("narration", ""),
                "audio_base64": audio_b64
            })

    except Exception as e:
        logger.error(f"[WS] Graph execution failed: {e}")
        await ws.send_json({
            "type": "action_result",
            "status": "failure",
            "detail": str(e)
        })


# Active backend recording tasks per session
active_mic_tasks = {}


async def record_backend_audio(ws: WebSocket, session_id: str):
    """Records audio directly from OS microphone using sounddevice, then transcribes."""
    logger.info(f"[Backend Mic] Starting OS microphone capture for session {session_id}")
    await ws.send_json({"type": "mic_status", "state": "recording"})

    try:
        import sounddevice as sd
        import numpy as np

        audio_buffer = bytearray()
        active_mic_tasks[session_id] = {"recording": True}

        sample_rate = 16000
        channels = 1

        def audio_callback(indata, frames, time, status):
            if status:
                logger.warning(f"[Backend Mic] Status: {status}")
            if active_mic_tasks.get(session_id, {}).get("recording"):
                # Convert float32 [-1.0, 1.0] to int16 PCM
                pcm_data = (indata * 32767).astype(np.int16).tobytes()
                audio_buffer.extend(pcm_data)

        stream = sd.InputStream(
            samplerate=sample_rate,
            channels=channels,
            dtype='float32',
            callback=audio_callback
        )

        with stream:
            while active_mic_tasks.get(session_id, {}).get("recording"):
                await asyncio.sleep(0.1)

        logger.info(f"[Backend Mic] Recording stopped. Total bytes captured: {len(audio_buffer)}")
        await ws.send_json({"type": "mic_status", "state": "transcribing"})

        if len(audio_buffer) > 0:
            from tools.sarvam_stt import sarvam_stt_client
            transcript = await sarvam_stt_client.transcribe_pcm_bytes(bytes(audio_buffer))
            if transcript:
                logger.info(f"[Backend Mic] Transcribed audio: '{transcript}'")
                await ws.send_json({"type": "mic_status", "state": "idle", "transcript": transcript})
                await handle_voice_transcript(ws, session_id, transcript)
            else:
                await ws.send_json({"type": "mic_status", "state": "idle"})
                await ws.send_json({"type": "action_result", "status": "failure", "detail": "No speech detected in audio."})
        else:
            await ws.send_json({"type": "mic_status", "state": "idle"})

    except ImportError as e:
        logger.error(f"[Backend Mic] Import error: {e}")
        await ws.send_json({"type": "mic_status", "state": "idle"})
        await ws.send_json({
            "type": "action_result",
            "status": "failure",
            "detail": f"Backend audio import error: {str(e)}"
        })
    except Exception as e:
        logger.error(f"[Backend Mic] Error during recording: {e}")
        await ws.send_json({"type": "mic_status", "state": "idle"})
        await ws.send_json({"type": "action_result", "status": "failure", "detail": f"Mic error: {str(e)}"})
    finally:
        active_mic_tasks.pop(session_id, None)


async def handle_observer_event(ws: WebSocket, session_id: int, msg: dict):
    """
    Handles Copilot Observer milestone events from the VS Code extension.

    Flow:
      - copilot_start: Instantly plays spoken alert ("Copilot is generating code in {file}...")
      - copilot_complete: Groq LLM analyzes code_snippet and generates architectural summary
                          (what the file does & why it is necessary) -> Sarvam TTS narration.
    """
    event_type = msg.get("event_type", "copilot_complete")
    target_file = (msg.get("file") or "your file").split("/")[-1]
    logger.info(f"[Observer] Received event: {event_type} for file: {target_file}")

    try:
        if event_type == "copilot_start":
            narration = f"Copilot is generating code in {target_file}."
        else:
            # Generate summary narration matching STREAM.md specifications
            narration = await diff_intelligence.generate_observer_summary(msg)

        logger.info(f"[Observer] Narration ({event_type}): {narration}")

        # Convert to audio via Sarvam TTS
        audio_b64 = await sarvam_tts_client.generate_filler_audio_base64(narration)

        # Send to webview UI
        if audio_b64:
            await ws.send_json({
                "type": "audio_narration",
                "channel": "observer",
                "narration": narration,
                "audio_base64": audio_b64,
            })
        else:
            await ws.send_json({
                "type": "action_result",
                "status": "success",
                "detail": narration,
            })

    except Exception as e:
        logger.error(f"[Observer] Error handling observer event: {e}")


@router.websocket("/ws/session")
async def ws_session(ws: WebSocket):
    await ws.accept()
    session_id = id(ws)
    session_states[session_id] = {
        "transcript": "",
        "intent": None,
        "plan_data": None,
        "context": {},
        "reasoning": None,
        "confirmation_required": False,
        "confirmed": False,
        "action_result": None,
        "verification_status": "pending",
        "narration": None,
        "earcon": None
    }
    session_audio_buffers[session_id] = bytearray()
    
    logger.info(f"WebSocket client connected (session: {session_id})")

    try:
        while True:
            raw = await ws.receive_text()

            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await ws.send_json({"type": "action_result", "status": "failure", "detail": "Invalid JSON"})
                continue

            msg_type = msg.get("type")

            if msg_type == "audio_frame":
                data = msg.get("data", "")
                try:
                    pcm_bytes = base64.b64decode(data)
                    session_audio_buffers[session_id].extend(pcm_bytes)
                except Exception:
                    await ws.send_json({"type": "action_result", "status": "failure", "detail": "Invalid base64 in audio_frame"})
                    continue

                byte_count = len(pcm_bytes)
                total_bytes = len(session_audio_buffers[session_id])
                
                # If audio buffer exceeds ~1 sec of 16kHz Int16 PCM (32000 bytes), trigger STT transcription
                if total_bytes >= 32000:
                    pcm_data = bytes(session_audio_buffers[session_id])
                    session_audio_buffers[session_id].clear()
                    
                    from tools.sarvam_stt import sarvam_stt_client
                    transcript = await sarvam_stt_client.transcribe_pcm_bytes(pcm_data)
                    if transcript:
                        logger.info(f"[WS] Transcribed audio to text: '{transcript}'")
                        await handle_voice_transcript(ws, session_id, transcript)

            elif msg_type == "toggle_backend_mic" or msg_type == "start_backend_mic":
                if session_id in active_mic_tasks:
                    logger.info(f"Stopping backend mic for session {session_id}")
                    active_mic_tasks[session_id]["recording"] = False
                else:
                    logger.info(f"Starting backend mic for session {session_id}")
                    asyncio.create_task(record_backend_audio(ws, session_id))

            elif msg_type == "stop_backend_mic":
                if session_id in active_mic_tasks:
                    active_mic_tasks[session_id]["recording"] = False

            elif msg_type == "set_workspace":
                workspace_path = msg.get("workspace_path", "")
                logger.info(f"set_workspace received: {workspace_path}")
                session_workspaces[session_id] = workspace_path
                await ws.send_json({
                    "type": "workspace_ack",
                    "status": "success",
                    "detail": f"Workspace set to {workspace_path}"
                })

            elif msg_type == "text_command":
                text = msg.get("text", "")
                logger.info(f"text_command received: {text}")

                # Reject null character injection and irrelevant/gibberish typing
                if "\x00" in text or is_gibberish(text):
                    logger.warning(f"[WS] Rejecting invalid text command: {text}")
                    await ws.send_json({
                        "type": "action_result",
                        "status": "failure",
                        "detail": "Rejected: Invalid or irrelevant typing detected."
                    })
                    continue

                # Update state and run agent
                session_states[session_id]["transcript"] = text
                session_states[session_id]["env_confirmations_received"] = 0
                # Reset previous command state
                session_states[session_id]["confirmation_required"] = False
                session_states[session_id]["confirmed"] = False

                # Run graph in background task so we don't block the websocket receive loop
                asyncio.create_task(run_agent_graph(ws, session_id))

            elif msg_type == "confirm_response":
                confirmed = msg.get("confirmed", False)
                logger.info(f"confirm_response received: {confirmed}")
                
                session_states[session_id]["confirmed"] = confirmed
                
                if not confirmed:
                    # Cancelled by user
                    session_states[session_id]["confirmation_required"] = False
                    session_states[session_id]["env_confirmations_received"] = 0
                    await ws.send_json({
                        "type": "action_result",
                        "status": "cancelled",
                        "detail": "Action cancelled by user."
                    })
                else:
                    # Resume graph
                    asyncio.create_task(run_agent_graph(ws, session_id))

            elif msg_type == "interrupt":
                logger.info("interrupt received")

            elif msg_type == "copilot_observer_event":
                asyncio.create_task(handle_observer_event(ws, session_id, msg))

            else:
                await ws.send_json({"type": "action_result", "status": "failure", "detail": f"Unknown message type: {msg_type}"})

    except WebSocketDisconnect:
        logger.info(f"WebSocket client disconnected (session: {session_id})")
        if session_id in active_mic_tasks:
            active_mic_tasks[session_id]["recording"] = False
        active_mic_tasks.pop(session_id, None)
        session_states.pop(session_id, None)
        session_audio_buffers.pop(session_id, None)
        session_workspaces.pop(session_id, None)

