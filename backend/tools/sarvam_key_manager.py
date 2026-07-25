"""
neurocode-backend/tools/sarvam_key_manager.py

Sarvam API Key Pool Manager:
- Manages key rotation across multiple Sarvam API keys.
- Tracks per-key rate limit cooldowns (HTTP 429) and authentication failures (401/403).
- Seamlessly failover to the next healthy key without interrupting application requests.
"""

import os
import time
import logging
import config

logger = logging.getLogger("neurocode.sarvam_key_manager")

class SarvamKeyManager:
    def __init__(self):
        self.keys: list[str] = []
        self.current_index = 0
        self.key_status: dict[str, dict] = {}
        self.reload_keys()

    def reload_keys(self) -> None:
        """
        Loads API keys from config/env:
        - SARVAM_API_KEYS (comma-separated list)
        - Individual keys: SARVAM_API_KEY, SARVAM_API_KEY1, SARVAM_API_KEY2, SARVAM_API_KEY3, etc.
        """
        discovered_keys = []

        # 1. Check SARVAM_API_KEYS comma-separated string
        raw_keys = getattr(config, "SARVAM_API_KEYS", "") or os.getenv("SARVAM_API_KEYS", "")
        for k in raw_keys.split(","):
            if k.strip():
                discovered_keys.append(k.strip())

        # 2. Check all environment variables matching SARVAM_API_KEY*
        for env_k, env_v in os.environ.items():
            if env_k.startswith("SARVAM_API_KEY") and env_v.strip():
                discovered_keys.append(env_v.strip())

        # Deduplicate keys while preserving order
        unique_keys = []
        seen = set()
        for k in discovered_keys:
            if k not in seen:
                seen.add(k)
                unique_keys.append(k)

        self.keys = unique_keys
        self.current_index = 0
        for k in self.keys:
            if k not in self.key_status:
                self.key_status[k] = {
                    "cooldown_until": 0,
                    "consecutive_errors": 0,
                    "total_requests": 0,
                }
        logger.info(f"[SarvamKeyManager] Loaded {len(self.keys)} API key(s): {[k[:8] + '...' for k in self.keys]}")

    def get_active_key(self) -> str:
        """Returns the currently active healthy key, rotating past cooling-down keys."""
        if not self.keys:
            self.reload_keys()

        if not self.keys:
            return ""

        now = time.time()
        start_idx = self.current_index

        # Scan for an active key not in cooldown
        for i in range(len(self.keys)):
            idx = (start_idx + i) % len(self.keys)
            key = self.keys[idx]
            status = self.key_status.get(key, {})
            if status.get("cooldown_until", 0) <= now:
                self.current_index = idx
                status["total_requests"] = status.get("total_requests", 0) + 1
                return key

        # If all keys are cooling down, select key with earliest cooldown expiration
        earliest_key = min(self.keys, key=lambda k: self.key_status.get(k, {}).get("cooldown_until", 0))
        logger.warning(f"[SarvamKeyManager] All {len(self.keys)} keys cooling down. Using earliest key.")
        return earliest_key

    def report_key_failure(self, key: str, status_code: int = 429) -> None:
        """Puts a failed key into cooldown (60s for 429 rate limits, 300s for auth errors)."""
        if not key or key not in self.key_status:
            return

        status = self.key_status[key]
        status["consecutive_errors"] = status.get("consecutive_errors", 0) + 1
        
        # Cooldown duration: 60s for 429 / 503, 300s for 401/403
        cooldown_sec = 300 if status_code in (401, 403) else 60
        status["cooldown_until"] = time.time() + cooldown_sec

        logger.warning(
            f"[SarvamKeyManager] Key starting with '{key[:8]}...' hit status {status_code}. "
            f"Cooling down for {cooldown_sec}s. Rotating key."
        )

        # Advance index to next key
        if len(self.keys) > 1:
            self.current_index = (self.current_index + 1) % len(self.keys)

    def report_key_success(self, key: str) -> None:
        """Resets error counters on successful API response."""
        if key in self.key_status:
            self.key_status[key]["consecutive_errors"] = 0

sarvam_key_manager = SarvamKeyManager()
