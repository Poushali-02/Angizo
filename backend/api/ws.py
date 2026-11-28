"""
backend/api/ws.py

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
import time
import os
import re
import base64
import logging
import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from agent.graph import agent_graph
from agent.state import AgentState
from langgraph.types import Command
from tools.diff_intelligence import diff_intelligence
from tools.sarvam_tts import sarvam_tts_client
from tools.speech import ack_phrase, split_for_speech, ACK_PHRASES

logger = logging.getLogger("angizo.ws")
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
    """A spoken yes/no answers a pending question; anything else is a new command."""
    session = session_states.get(session_id)
    if not session:
        return
    logger.info(f"[Voice] Processing transcript: '{transcript}'")

    if session.get("awaiting_answer"):
        # Match whole words: a substring check heard "ok" in "look" and confirmed a commit.
        words = set(re.findall(r"[a-z]+", transcript.lower()))
        # Cancel wins when both appear ("no, don't confirm"), since it is the safe choice.
        if words & {"no", "cancel", "deny", "stop", "don"}:
            logger.info("[Voice] Verbal cancellation detected.")
            asyncio.create_task(answer_confirmation(ws, session_id, False))
            return
        if words & {"yes", "confirm", "proceed", "ok", "okay", "permit"}:
            logger.info("[Voice] Verbal confirmation detected.")
            asyncio.create_task(answer_confirmation(ws, session_id, True))
            return

    if "\x00" in transcript or is_gibberish(transcript):
        logger.warning(f"[WS Voice] Rejecting invalid/irrelevant voice transcript: {transcript}")
        await ws.send_json({
            "type": "action_result",
            "status": "failure",
            "detail": "Rejected: Invalid or irrelevant voice input detected."
        })
        return

    asyncio.create_task(start_command(ws, session_id, transcript))


# In-memory session state for the hackathon (Step 2)
# Real implementation would use MongoDB per DESIGN.md
session_states = {}

# Per-session audio buffers for incoming 16kHz PCM audio frames
session_audio_buffers = {}

# Per-session active workspace paths set by client
session_workspaces = {}

def _log_speech(audio_b64: str, text: str) -> None:
    """
    With ANGIZO_SPEECH_LOG=<folder>, save every clip sent to the panel with the time it was
    sent (scripts/record_demo.py builds a demo video's soundtrack from these). Off by default.
    """
    folder = os.environ.get("ANGIZO_SPEECH_LOG")
    if not folder or not audio_b64:
        return
    try:
        os.makedirs(folder, exist_ok=True)
        stamp = time.time()
        name = f"{int(stamp * 1000)}-{len(os.listdir(folder))}.wav"
        with open(os.path.join(folder, name), "wb") as f:
            f.write(base64.b64decode(audio_b64))
        with open(os.path.join(folder, "index.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps({"t": stamp, "file": name, "text": text}) + "\n")
    except Exception as e:  # logging must never break speech
        logger.warning(f"[SpeechLog] Could not save clip: {e}")


async def send_ack(ws: WebSocket, phrase: str):
    """
    Say something the moment a command arrives, before any LLM call. The phrases are cached
    at startup, so this is instant; if one is not cached yet, the text goes alone (the panel
    reads it with the system voice) and its audio is cached in the background for next time.
    """
    audio = sarvam_tts_client.cached(phrase)
    await ws.send_json({"type": "ack", "text": phrase, "audio_base64": audio})
    _log_speech(audio, phrase)
    if not audio:
        asyncio.create_task(sarvam_tts_client.generate_filler_audio_base64(phrase))


async def send_spoken(ws: WebSocket, message: dict, text: str):
    """
    Send `message` with audio for the first sentence of `text`, then the rest of the text as a
    separate audio_narration. Both are synthesised at once, but the first (short) one is sent
    as soon as it is ready, so speech starts several seconds earlier for long replies.
    """
    first, rest = split_for_speech(text)
    rest_task = asyncio.create_task(sarvam_tts_client.generate_filler_audio_base64(rest)) if rest else None
    first_audio = await sarvam_tts_client.generate_filler_audio_base64(first) if first else ""
    await ws.send_json({**message, "audio_base64": first_audio, "spoken_text": first})
    _log_speech(first_audio, first)
    if rest_task:
        rest_audio = await rest_task
        await ws.send_json({
            "type": "audio_narration",
            "channel": "agent_continuation",  # the panel plays it without adding a new feed entry
            "narration": rest,
            "audio_base64": rest_audio,
        })
        _log_speech(rest_audio, rest)


def _new_session() -> dict:
    # Each command runs in its own checkpointed thread, so no state leaks between commands.
    return {"thread_id": None, "awaiting_answer": False, "commands": 0}


def _forget_thread(thread_id):
    """Drop a finished or abandoned run from the in-memory checkpointer."""
    if thread_id:
        try:
            agent_graph.checkpointer.delete_thread(thread_id)
        except Exception:
            pass


def _bind_workspace(session_id):
    workspace_path = session_workspaces.get(session_id)
    if workspace_path:
        import tools.git_tool as git_tool
        git_tool._set_repo_path(workspace_path)


async def start_command(ws: WebSocket, session_id, transcript: str):
    """Run a new command from the start of the graph (a pending question is dropped)."""
    session = session_states.setdefault(session_id, _new_session())
    _forget_thread(session.get("thread_id"))
    session["commands"] += 1
    session["thread_id"] = f"{session_id}-{session['commands']}"
    session["awaiting_answer"] = False
    _bind_workspace(session_id)
    await send_ack(ws, ack_phrase(transcript))
    logger.info(f"[WS] Invoking agent graph for transcript: '{transcript}'")
    await _drive_graph(ws, session_id, {
        "transcript": transcript,
        "context": {},
        "confirmation_required": False,
        "confirmed": False,
        "cancelled": False,
        "env_confirmations_received": 0,
        "attempts": 0,
        "verification_status": "pending",
    })


async def answer_confirmation(ws: WebSocket, session_id, yes: bool):
    """Resume the paused graph with the user's answer (Alt+Y / Alt+N or a spoken yes/no)."""
    session = session_states.get(session_id)
    if not session or not session.get("awaiting_answer"):
        await ws.send_json({"type": "action_result", "status": "skipped",
                            "detail": "Nothing is waiting for a yes or no."})
        return
    session["awaiting_answer"] = False
    if yes:
        await send_ack(ws, ACK_PHRASES["confirm"])
    _bind_workspace(session_id)
    logger.info(f"[WS] Resuming the graph with answer: {'yes' if yes else 'no'}")
    await _drive_graph(ws, session_id, Command(resume=yes))


async def _drive_graph(ws: WebSocket, session_id, graph_input):
    """
    Run the graph until it finishes or pauses at confirm's interrupt(). A pause sends a
    confirmation_request (it can happen twice: again after verify -> recover -> confirm).
    """
    session = session_states[session_id]
    config = {"configurable": {"thread_id": session["thread_id"]}}
    try:
        result = await agent_graph.ainvoke(graph_input, config)
    except Exception as e:
        logger.error(f"[WS] Graph execution failed: {e}")
        _forget_thread(session["thread_id"])
        await ws.send_json({"type": "action_result", "status": "failure", "detail": str(e)})
        return

    interrupts = result.get("__interrupt__") or []
    if interrupts:
        question = interrupts[0].value or {}
        prompt = question.get("prompt") or "Continue?"
        session["awaiting_answer"] = True
        logger.info("[WS] Agent paused for confirmation.")
        await send_spoken(
            ws, {"type": "confirmation_request", "prompt": prompt, "risk_band": question.get("risk_band")}, prompt
        )
        return

    logger.info("[WS] Agent completed run.")
    _forget_thread(session["thread_id"])
    narration = result.get("narration", "")
    await send_spoken(
        ws,
        {"type": "action_result", "status": result.get("verification_status", "success"), "detail": narration},
        narration,
    )


# Active backend recording tasks per session
active_mic_tasks = {}


async def record_backend_audio(ws: WebSocket, session_id: str):
    """Records audio directly from OS microphone using sounddevice, then transcribes."""
    logger.info(f"[Backend Mic] Starting OS microphone capture for session {session_id}")
    # Registered before the first await, so a quick second press stops this recording
    # instead of starting another one.
    task = {"recording": True, "stop_reason": None}
    active_mic_tasks[session_id] = task

    def release_mic():
        if active_mic_tasks.get(session_id) is task:
            active_mic_tasks.pop(session_id, None)

    try:
        await ws.send_json({"type": "mic_status", "state": "recording"})
        import sounddevice as sd
        import numpy as np

        from tools.vad import SilenceDetector

        audio_buffer = bytearray()

        sample_rate = 16000
        channels = 1
        detector = SilenceDetector(sample_rate=sample_rate)

        def audio_callback(indata, frames, time, status):
            if status:
                logger.warning(f"[Backend Mic] Status: {status}")
            if task.get("recording"):
                # Convert float32 [-1.0, 1.0] to int16 PCM
                pcm_data = (indata * 32767).astype(np.int16).tobytes()
                audio_buffer.extend(pcm_data)
                reason = detector.feed(indata[:, 0] if getattr(indata, "ndim", 1) > 1 else indata)
                if reason:
                    # Auto-stop: the user stopped talking (or never started).
                    task["stop_reason"] = reason
                    task["recording"] = False

        stream = sd.InputStream(
            samplerate=sample_rate,
            channels=channels,
            dtype='float32',
            callback=audio_callback
        )

        with stream:
            while task.get("recording"):
                await asyncio.sleep(0.1)

        # The mic is free again: the next press starts a new recording, even while this
        # one is still being transcribed and answered.
        release_mic()
        reason = task.get("stop_reason") or "manual"
        logger.info(f"[Backend Mic] Recording stopped ({reason}). Total bytes captured: {len(audio_buffer)}")
        if reason == "no_speech":
            # Nothing was said: skip transcription so no Sarvam credits are spent on silence.
            await ws.send_json({"type": "mic_status", "state": "idle", "reason": "no_speech"})
            await ws.send_json({"type": "action_result", "status": "failure",
                                "detail": "I didn't hear anything.", "spoken_text": "I didn't hear anything."})
            return
        await ws.send_json({"type": "mic_status", "state": "transcribing", "reason": reason})

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
        release_mic()


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
        _log_speech(audio_b64, narration)
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


async def handle_manual_observer_event(ws: WebSocket, session_id: int, msg: dict):
    """
    Handles Stage 1 (Syntax Error) and Stage 2 (Runtime / Compilation Error) events.
    """
    event_type = msg.get("event_type", "syntax_error")
    target_file = (msg.get("file") or "your file").split("/")[-1]
    logger.info(f"[ManualObserver] Received event: {event_type} for file: {target_file}")

    try:
        if event_type == "syntax_error":
            is_resolved = msg.get("is_resolved", False)
            line = msg.get("line", 1)
            err_msg = msg.get("error_message", "")
            count = int(msg.get("error_count") or 1) if msg.get("is_summary") else 1
            narration = diff_intelligence.format_syntax_error_narration(
                target_file, line, err_msg, is_resolved, count=count
            )
        else:
            # Stage 2: Runtime Exception / Compilation Error
            narration = await diff_intelligence.generate_runtime_error_summary(msg)

        logger.info(f"[ManualObserver] Narration ({event_type}): {narration}")

        # Convert to audio via Sarvam TTS
        audio_b64 = await sarvam_tts_client.generate_filler_audio_base64(narration)

        _log_speech(audio_b64, narration)
        if audio_b64:
            await ws.send_json({
                "type": "audio_narration",
                "channel": "manual_observer",
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
        logger.error(f"[ManualObserver] Error handling manual event: {e}")


@router.websocket("/ws/session")
async def ws_session(ws: WebSocket):
    await ws.accept()
    session_id = id(ws)
    session_states[session_id] = _new_session()
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

                # Run in a background task so the receive loop stays free (e.g. for Alt+N)
                asyncio.create_task(start_command(ws, session_id, text))

            elif msg_type == "confirm_response":
                confirmed = bool(msg.get("confirmed", False))
                logger.info(f"confirm_response received: {confirmed}")
                asyncio.create_task(answer_confirmation(ws, session_id, confirmed))

            elif msg_type == "interrupt":
                logger.info("interrupt received")

            elif msg_type == "copilot_observer_event":
                asyncio.create_task(handle_observer_event(ws, session_id, msg))

            elif msg_type == "manual_observer_event":
                asyncio.create_task(handle_manual_observer_event(ws, session_id, msg))

            else:
                await ws.send_json({"type": "action_result", "status": "failure", "detail": f"Unknown message type: {msg_type}"})

    except WebSocketDisconnect:
        logger.info(f"WebSocket client disconnected (session: {session_id})")
        if session_id in active_mic_tasks:
            active_mic_tasks[session_id]["recording"] = False
        active_mic_tasks.pop(session_id, None)
        _forget_thread((session_states.pop(session_id, None) or {}).get("thread_id"))
        session_audio_buffers.pop(session_id, None)
        session_workspaces.pop(session_id, None)

