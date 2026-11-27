"""
neurocode-backend/config.py

Environment variable configuration.
Values come from the process environment first, then backend/.env.
Set ANGIZO_SKIP_DOTENV=1 to ignore .env (the test suite does, so tests never touch real keys).

Loaded server-side only — never exposed to the webview
(DESIGN.md: SecretStorage + server-side only config).
"""

import os
from pathlib import Path

# Parse backend/.env file into os.environ
env_path = Path(__file__).parent / ".env"
if env_path.exists() and os.getenv("ANGIZO_SKIP_DOTENV") != "1":
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                k = k.strip()
                if k not in os.environ:
                    os.environ[k] = v.strip()


# --- Server ---
HOST: str = os.getenv("NEUROCODE_HOST", "0.0.0.0")
PORT: int = int(os.getenv("NEUROCODE_PORT", "7001"))  # the extension connects to 7001

# --- Target Repository ---
# Path to the Git repository the agent should operate on
# If not set, defaults to the backend's working directory
REPO_PATH: str = os.getenv("NEUROCODE_REPO_PATH", os.getcwd())

# --- API Keys ---
SARVAM_API_KEY: str = os.getenv("SARVAM_API_KEY", "")
SARVAM_API_KEYS: str = os.getenv("SARVAM_API_KEYS", os.getenv("SARVAM_API_KEY", ""))
ELEVENLABS_API_KEY: str = os.getenv("ELEVENLABS_API_KEY", "")
GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
GITHUB_PAT: str = os.getenv("GITHUB_PAT", "")
MONGODB_URI: str = os.getenv("MONGODB_URI", "")
GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL: str = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
GROQ_FALLBACK_MODEL: str = os.getenv("GROQ_FALLBACK_MODEL", "openai/gpt-oss-20b")  # used when GROQ_MODEL is rate-limited

# Voice / Audio Settings
SARVAM_STT_ENDPOINT: str = os.getenv("SARVAM_STT_ENDPOINT", "https://api.sarvam.ai/speech-to-text")
SARVAM_FILLER_SPEAKER: str = os.getenv("SARVAM_FILLER_SPEAKER", "shubh")  # must be a male bulbul:v3 voice
SARVAM_TTS_MODEL: str = os.getenv("SARVAM_TTS_MODEL", "bulbul:v3")
SARVAM_CACHE_ENABLED: bool = os.getenv("SARVAM_CACHE_ENABLED", "true").lower() == "true"
ELEVENLABS_VOICE_ID: str = os.getenv("ELEVENLABS_VOICE_ID", "EXAVITQu4vr4xnSDxMaL")  # Bella, free tier
ELEVENLABS_MODEL_ID: str = os.getenv("ELEVENLABS_MODEL_ID", "eleven_flash_v2_5")  # low latency, free tier
