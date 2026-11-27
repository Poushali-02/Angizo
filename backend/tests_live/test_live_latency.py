"""How soon does the user hear something? Measured through the real WebSocket API and real APIs."""

import asyncio
import time

import pytest

from test_live_llm import _edit_auth


@pytest.mark.parametrize("command", ["review my diff", "commit my changes", "what does the charge function do"])
def test_time_to_first_sound(command, playground, report):
    """Times the acknowledgement, the first sentence of the reply, and the rest of the reply."""
    from fastapi.testclient import TestClient
    from main import app
    from tools.sarvam_tts import sarvam_tts_client
    from tools.speech import prewarm_acks

    if not asyncio.run(prewarm_acks(sarvam_tts_client)):  # what the server does at startup
        from test_live_voice import sarvam_out_of_credits
        if sarvam_out_of_credits():
            pytest.skip("Sarvam account has no credits left (402): latency needs real speech")
    _edit_auth(playground)
    with TestClient(app) as client, client.websocket_connect("/ws/session") as ws:
        ws.send_json({"type": "set_workspace", "workspace_path": str(playground)})
        ws.receive_json()
        start = time.perf_counter()
        ws.send_json({"type": "text_command", "text": command})
        times, main = {}, None
        while True:
            msg = ws.receive_json()
            now = time.perf_counter() - start
            if msg["type"] == "ack":
                times["ack"] = now
                assert msg["audio_base64"], "the acknowledgement was not cached"
            elif msg.get("channel") == "agent_continuation":
                times["rest"] = now
                break
            elif msg["type"] in ("action_result", "confirmation_request"):
                times["first sentence"] = now
                main = msg
                full = msg.get("detail") or msg.get("prompt")
                if msg.get("spoken_text") == full:
                    break  # a one-sentence reply: nothing follows
        if main and main["type"] == "confirmation_request":
            ws.send_json({"type": "confirm_response", "confirmed": False})

    summary = ", ".join(f"{k} {v:.1f}s" for k, v in times.items())
    report.add("latency", command, times.get("first sentence", 0), summary)
    assert times["ack"] < 1.0, f"the acknowledgement took {times['ack']:.1f}s"
    assert main and main.get("audio_base64"), "the first sentence had no audio"
