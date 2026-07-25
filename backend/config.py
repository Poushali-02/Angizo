"""
neurocode-backend/config.py

Environment variable configuration.
Step 1: Only WS host/port. API keys added in later steps.

Loaded server-side only — never exposed to the webview
(DESIGN.md: SecretStorage + server-side only config).
"""

import os


# --- Server ---
HOST: str = os.getenv("NEUROCODE_HOST", "0.0.0.0")
PORT: int = int(os.getenv("NEUROCODE_PORT", "8000"))

# --- Target Repository ---
# Path to the Git repository the agent should operate on
# If not set, defaults to the backend's working directory
REPO_PATH: str = os.getenv("NEUROCODE_REPO_PATH", os.getcwd())

# --- API Keys ---
SARVAM_API_KEY: str = os.getenv("SARVAM_API_KEY", "")
ELEVENLABS_API_KEY: str = os.getenv("ELEVENLABS_API_KEY", "")
GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")
GITHUB_PAT: str = os.getenv("GITHUB_PAT", "")
MONGODB_URI: str = os.getenv("MONGODB_URI", "")
GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL: str = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")



# Voice / Audio Settings
SARVAM_STT_ENDPOINT: str = os.getenv("SARVAM_STT_ENDPOINT", "https://api.sarvam.ai/speech-to-text")
SARVAM_FILLER_SPEAKER: str = os.getenv("SARVAM_FILLER_SPEAKER", "anushka") # Compatible with bulbul:v2
ELEVENLABS_VOICE_ID: str = os.getenv("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM") # Standard neutral speaker ID
