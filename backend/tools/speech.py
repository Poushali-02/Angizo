"""
backend/tools/speech.py

How the agent talks, as fast as the free tiers allow:

- ack_phrase(): a short, specific acknowledgement chosen without any LLM call
  ("Reading your changes."), spoken the moment a command arrives. The phrases are
  synthesised once at startup (prewarm_acks), so every acknowledgement after that is
  served from the TTS cache instantly and costs no credits.
- split_for_speech(): splits a reply into its first sentence and the rest, so the first
  sentence can be synthesised and played while the rest is still being synthesised.
  Sarvam's latency grows with text length, so a short first chunk starts sooner.
"""

import asyncio
import logging
import re

logger = logging.getLogger("angizo.speech")

ACK_PHRASES = {
    "commit": "Preparing a commit.",
    "push": "Getting ready to push.",
    "pull": "Checking the remote.",
    "review": "Reading your changes.",
    "status": "Checking your status.",
    "confirm": "Working on it.",
    "other": "Looking into it.",
}

# Order matters: "commit and push" is a commit first.
_ACK_KEYWORDS = [
    ("commit", ("commit", "save my")),
    ("push", ("push",)),
    ("pull", ("pull", "sync", "latest changes")),
    ("review", ("diff", "review", "what changed", "changes")),
    ("status", ("status", "which files", "what files")),
]


def ack_phrase(transcript: str) -> str:
    text = transcript.lower()
    for kind, words in _ACK_KEYWORDS:
        if any(w in text for w in words):
            return ACK_PHRASES[kind]
    return ACK_PHRASES["other"]


# A sentence ends at . ! or ? followed by whitespace. "auth.py" or "v1.2" do not split,
# because there is no space after the dot.
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=\S)")


def split_for_speech(text: str, min_first: int = 15) -> tuple[str, str]:
    """
    (first sentence, rest). A first sentence shorter than min_first characters is merged
    with the next one, so the first chunk is never a lone "Done." followed by a long wait.
    """
    text = (text or "").strip()
    if not text:
        return "", ""
    parts = _SENTENCE_END.split(text)
    first = parts[0]
    i = 1
    while len(first) < min_first and i < len(parts):
        first = f"{first} {parts[i]}"
        i += 1
    rest = " ".join(parts[i:]).strip()
    return first, rest


async def prewarm_acks(tts) -> int:
    """Synthesise every acknowledgement phrase into the TTS cache. Returns how many are ready."""
    results = await asyncio.gather(
        *(tts.generate_filler_audio_base64(p) for p in ACK_PHRASES.values()), return_exceptions=True
    )
    ready = sum(1 for r in results if isinstance(r, str) and r)
    logger.info(f"[Speech] Acknowledgement phrases cached: {ready}/{len(ACK_PHRASES)}")
    return ready


def prefetch_speech(sentence: str) -> None:
    """
    Start synthesising a sentence that will open the reply, while the LLM is still working.
    The audio lands in the TTS cache, so when the reply is spoken its first sentence is
    already there. Only worth calling with text that will be the reply's first sentence.
    """
    from tools.sarvam_tts import sarvam_tts_client
    try:
        asyncio.get_running_loop().create_task(sarvam_tts_client.generate_filler_audio_base64(sentence))
    except RuntimeError:
        pass  # no running loop (called from sync code): nothing to overlap with
