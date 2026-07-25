"""
neurocode-backend/test_ws_echo.py

Automated verification for Step 1 (voice input spike).
Connects to the WebSocket endpoint, sends a fake audio_frame,
and asserts the echo response matches the expected format.

Run:
  python test_ws_echo.py
  (backend must be running: uvicorn main:app)
"""

import asyncio
import json
import base64
import sys

try:
    import websockets
except ImportError:
    print("ERROR: 'websockets' package required. Run: pip install websockets")
    sys.exit(1)


WS_URL = "ws://localhost:7001/ws/session"


async def test_audio_frame_echo():
    """Send a fake audio_frame and verify the echo response."""
    print(f"Connecting to {WS_URL}...")

    async with websockets.connect(WS_URL) as ws:
        print("Connected.")

        # Create a fake PCM chunk: 1600 Int16 samples (100ms at 16kHz) of silence
        fake_pcm = bytes(1600 * 2)  # 3200 bytes of zeros
        b64_data = base64.b64encode(fake_pcm).decode("ascii")

        # Send the audio_frame message
        msg = json.dumps({"type": "audio_frame", "data": b64_data})
        await ws.send(msg)
        print(f"Sent audio_frame: {len(fake_pcm)} bytes of PCM data")

        # Wait for the echo response
        response_raw = await asyncio.wait_for(ws.recv(), timeout=5.0)
        response = json.loads(response_raw)
        print(f"Received: {json.dumps(response, indent=2)}")

        # Validate the response
        assert response["type"] == "action_result", \
            f"Expected type 'action_result', got '{response['type']}'"
        assert response["status"] == "success", \
            f"Expected status 'success', got '{response['status']}'"
        assert "3200 bytes" in response["detail"], \
            f"Expected '3200 bytes' in detail, got '{response['detail']}'"

        print("\n[PASS]: audio_frame echo works correctly")


async def test_invalid_json():
    """Send invalid JSON and verify error handling."""
    async with websockets.connect(WS_URL) as ws:
        await ws.send("not valid json")
        response_raw = await asyncio.wait_for(ws.recv(), timeout=5.0)
        response = json.loads(response_raw)

        assert response["type"] == "action_result"
        assert response["status"] == "failure"
        assert "Invalid JSON" in response["detail"]

        print("[PASS]: invalid JSON handled gracefully")


async def test_unknown_type():
    """Send an unknown message type and verify error handling."""
    async with websockets.connect(WS_URL) as ws:
        await ws.send(json.dumps({"type": "unknown_type"}))
        response_raw = await asyncio.wait_for(ws.recv(), timeout=5.0)
        response = json.loads(response_raw)

        assert response["type"] == "action_result"
        assert response["status"] == "failure"
        assert "Unknown message type" in response["detail"]

        print("[PASS]: unknown message type handled gracefully")


async def test_health_endpoint():
    """Verify the /health REST endpoint."""
    try:
        import urllib.request
        resp = urllib.request.urlopen("http://localhost:8000/health")
        data = json.loads(resp.read().decode())
        assert data["status"] == "ok"
        print("[PASS]: /health returns {\"status\": \"ok\"}")
    except Exception as e:
        print(f"[FAIL]: /health check failed: {e}")
        return False
    return True


async def main():
    print("=" * 60)
    print("NeuroCode Step 1 — Voice Input Spike Verification")
    print("=" * 60)
    print()

    # REST health check
    await test_health_endpoint()
    print()

    # WebSocket tests
    await test_audio_frame_echo()
    print()
    await test_invalid_json()
    await test_unknown_type()

    print()
    print("=" * 60)
    print("All Step 1 verification tests passed!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
