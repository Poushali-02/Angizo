"""
backend/tools/gemini_llm.py

Gemini LLM Integration (with Groq LLM Fallback):
- Primary LLM: Google Gemini REST API (gemini-1.5-flash)
- Fallback LLM: Groq API (openai/gpt-oss-120b)
- Generates voice reasoning, code explanations, and intent classification with RAG context.
"""

import json
import re
import logging
import httpx
import config
from agent.plan_schema import parse_plan
from tools.diff_intelligence import diff_intelligence, _clean_spoken

logger = logging.getLogger("angizo.gemini_llm")

class GeminiLLM:
    def __init__(self):
        self.api_key = config.GEMINI_API_KEY
        self.model = getattr(config, "GEMINI_MODEL", "gemini-1.5-flash-latest")
        self.endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"

    async def generate(self, prompt: str) -> str:
        """
        Queries Primary Gemini LLM. If missing key or API failure occurs,
        automatically falls back to Groq LLM.
        """
        if self.api_key:
            url = f"{self.endpoint}?key={self.api_key}"
            headers = {"Content-Type": "application/json"}
            payload = {
                "contents": [
                    {
                        "parts": [{"text": prompt}]
                    }
                ]
            }

            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    res = await client.post(url, json=payload, headers=headers)
                    if res.status_code == 200:
                        data = res.json()
                        candidates = data.get("candidates", [])
                        if candidates:
                            parts = candidates[0].get("content", {}).get("parts", [])
                            if parts:
                                response_text = parts[0].get("text", "").strip()
                                logger.info("[GeminiLLM] Response generated via Gemini API")
                                return response_text
                    elif (res.status_code in (400, 401, 403) and "API key" in res.text) or res.status_code == 404:
                        # A rejected key or a retired model won't start working mid-session:
                        # stop paying the round trip on every call
                        logger.warning(f"[GeminiLLM] Gemini unavailable ({res.status_code}: "
                                       f"{'model not found' if res.status_code == 404 else 'key rejected'}). "
                                       "Using Groq only until restart.")
                        self.api_key = ""
                    else:
                        logger.warning(f"[GeminiLLM] API error {res.status_code}: {res.text}. Falling back to Groq.")
            except Exception as e:
                logger.warning(f"[GeminiLLM] Exception during Gemini API call: {e}. Falling back to Groq.")

        # Fallback to Groq LLM (openai/gpt-oss-120b)
        logger.info("[GeminiLLM] Using Groq LLM fallback for generation")
        return await diff_intelligence._call_groq(prompt)

    async def classify_intent(self, transcript: str) -> str:
        """Classifies transcript using Gemini with Groq fallback."""
        return await diff_intelligence.classify_intent(transcript)

    async def plan_actions(self, transcript: str, status_info: dict = None) -> dict:
        """
        Dynamically plans atomic tool executions for user prompt.
        Returns structured JSON plan containing tool_calls, reasoning, and confirmation requirements.
        """
        status_info = status_info or {}

        # Clear, common commands skip the LLM entirely (about 2 s faster); anything else is planned by it
        quick = fast_plan(transcript)
        if quick is not None:
            logger.info(f"[Planner] Fast path for '{transcript}': {[c['tool'] for c in quick['tool_calls']]}")
            return quick

        prompt = f"""You are the AI Planner for Angizo accessibility development agent.
Analyze the user command and select atomic tools to execute:

Available Atomic Tools:
- get_git_status: Get active branch and modified/untracked files.
- get_git_diff: Get working tree git diff for modified files.
- commit_changes: Stage and commit changes (args: {{"message": "conventional commit msg"}}, optional: leave it out and the system drafts one from the diff).
- push_to_remote: Push commits to remote origin (args: {{"branch": "branch_name"}}).
- pull_from_remote: Bring in commits from the remote: teammates' or other people's latest work (args: {{"branch": "branch_name"}}).
- query_codebase_rag: Search THIS project's code to answer questions about how the code works (args: {{"query": "search text"}}).

User Command: "{transcript}"

Current Git Status:
Branch: {status_info.get('branch', 'main')}, Uncommitted Changed Files: {len(status_info.get('changed_files', []))}

Rules:
- If the user asks to commit or save their work, include commit_changes even when they gave no message. Never ask them for a message; the user confirms before anything runs.
- Never return an empty tool_calls list. For a general question, use query_codebase_rag.
- Plan only what the user asked for. Never add commit_changes, push_to_remote or pull_from_remote
  unless the user asked for that action, even if there are uncommitted changes.
- Questions about an action ("is it safe to push?", "what would happen if I committed?") and negations
  ("don't commit, just show me the diff") are read-only: use get_git_status / get_git_diff instead.

Return JSON ONLY in this format:
{{
  "reasoning": "Brief explanation of plan",
  "tool_calls": [
    {{"tool": "tool_name", "args": {{}}}}
  ],
  "requires_confirm": true/false,
  "risk_band": "safe" | "caution" | "high-risk"
}}
"""
        # Structured output: the plan must match agent/plan_schema.Plan. If it does not, the LLM
        # gets one retry with the validation error; after that the keyword rules take over.
        response = await self.generate(prompt)
        plan, error = parse_plan(response)
        source = "llm"
        if plan is None:
            logger.warning(f"[Planner] Invalid plan ({error}); asking the LLM to fix it")
            retry_prompt = (
                f"{prompt}\nYour previous answer was rejected: {error}.\n"
                "Answer again with ONLY the JSON object, using only the tools and arguments listed above."
            )
            plan, error = parse_plan(await self.generate(retry_prompt))
            source = "llm_retry"
        if plan is not None:
            return guard_plan(transcript, {**plan.model_dump(), "source": source})

        logger.warning(f"[Planner] Still invalid after a retry ({error}); using the keyword rules")
        return guard_plan(transcript, {**self._rule_plan(transcript), "source": "rules", "schema_error": error})

    @staticmethod
    def _rule_plan(transcript: str) -> dict:
        """Keyword planner used when the LLM is unavailable or returns no usable plan."""
        text_lower = transcript.lower()
        tool_calls = []
        requires_confirm = False
        risk_band = "safe"

        if _is_question_or_negated(text_lower):
            # "what would happen if I committed?", "don't commit, show me the diff": read only
            tool_calls = [{"tool": "get_git_status", "args": {}}, {"tool": "get_git_diff", "args": {}}]
        elif "commit" in text_lower and "push" in text_lower:
            tool_calls = [
                {"tool": "get_git_diff", "args": {}},
                {"tool": "commit_changes", "args": {}},
                {"tool": "push_to_remote", "args": {}}
            ]
            requires_confirm = True
            risk_band = "caution"
        elif "commit" in text_lower or "save" in text_lower:
            tool_calls = [
                {"tool": "get_git_diff", "args": {}},
                {"tool": "commit_changes", "args": {}}
            ]
            requires_confirm = True
        elif "push" in text_lower:
            # Push only what is already committed: never commit work the user didn't ask to commit
            tool_calls = [{"tool": "push_to_remote", "args": {}}]
            requires_confirm = True
            risk_band = "caution"
        elif "pull" in text_lower:
            tool_calls = [{"tool": "pull_from_remote", "args": {}}]
            requires_confirm = True
        elif "status" in text_lower or "changed" in text_lower:
            tool_calls = [{"tool": "get_git_status", "args": {}}, {"tool": "get_git_diff", "args": {}}]
        elif "review" in text_lower:
            tool_calls = [{"tool": "get_git_diff", "args": {}}]
        else:
            tool_calls = [{"tool": "query_codebase_rag", "args": {"query": transcript}}]

        return {
            "reasoning": f"Planned tools for '{transcript}'",
            "tool_calls": tool_calls,
            "requires_confirm": requires_confirm,
            "risk_band": risk_band
        }

    async def generate_reasoning(self, transcript: str, rag_context: str = "", git_info: str = "") -> str:
        """
        Synthesizes plain-language narration reasoning for the user based on
        RAG codebase context, git status/diffs, and user prompt.
        """
        prompt = f"""You are the AI assistant for Angizo, a voice-driven accessibility tool.
Answer the user's question in at most 2 short spoken sentences (under 45 words) based on the provided codebase context.

User Question: "{transcript}"

Retrieved Codebase Context:
{rag_context[:2500] if rag_context else "No relevant codebase files found."}

Git Repository Status:
{git_info[:1000] if git_info else "No git changes active."}

Answer requirement:
- Answer the user's specific question directly (e.g. mention the exact tech stack or framework used in the code snippets).
- Do NOT output intent names like 'code_query' or 'git_status'.
- Do NOT use markdown code blocks or code fences.
- Return plain text spoken response only: no markdown, backticks or asterisks.
"""
        response = await self.generate(prompt)
        response_clean = _clean_spoken(response.replace("code_query", "")) if response else ""
        if response_clean and len(response_clean) > 5:
            return response_clean
        
        # No answer (LLM unavailable or rate-limited). Say so: a made-up generic answer
        # ("this project uses FastAPI...") would sound like a real one.
        return "I couldn't get an answer just now. Please try again in a moment."

# ── Fast path: unambiguous commands are planned without an LLM call ────────
# Each pattern must match the WHOLE command (after removing politeness words), so anything
# with extra detail ("commit with message ...", "push to staging") still goes to the LLM.

_FILLER_WORDS = re.compile(
    r"\b(please|hey|hi|angizo|angizo|can you|could you|would you|kindly|now|for me|just)\b"
)
_FAST_PATTERNS = [
    (r"(commit|save) (my |all |the )?(changes|work|files|code)( and push( (it|them|to origin))?)?",
     None),  # tools decided below: push is added only if the command says so
    (r"commit( everything)?( and push( (it|them|to origin))?)?", None),
    (r"(commit|save) and push( my| the| all)?( changes| work| code| files)?", None),
    (r"(what is |what's |whats |show |show me |check )?(my |the )?(git )?status",
     ["get_git_status", "get_git_diff"]),
    (r"(what|which) files (did i|have i) (change|changed|modify|modified)",
     ["get_git_status", "get_git_diff"]),
    (r"(review|show|show me|read|explain) (my |the )?(git )?(diff|changes)",
     ["get_git_diff"]),
    (r"what (did i change|changed|has changed)", ["get_git_diff"]),
    (r"push( my| the)?( branch| changes| commits| code)?( to origin| to remote)?", ["push_to_remote"]),
    (r"pull( the)?( latest)?( changes| code)?( from origin| from remote)?", ["pull_from_remote"]),
]


def fast_plan(transcript: str):
    """A plan for a clear, common command, or None when the LLM should decide."""
    text = transcript.lower().strip()
    text = _FILLER_WORDS.sub(" ", text)
    text = re.sub(r"[^a-z' ]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return None
    if not _is_question_or_negated(text):
        for pattern, tools in _FAST_PATTERNS:
            if re.fullmatch(pattern, text):
                if tools is None:  # a commit, with push only when asked
                    tools = ["get_git_diff", "commit_changes"] + (["push_to_remote"] if "push" in text else [])
                return _fast(text, tools)
    # A question about the code that mentions no git action: straight to code search.
    # ("is it safe to push?" or "what would happen if I committed?" still go to the LLM.)
    negated = any(n in text for n in _NEGATIONS)
    if not negated and text.startswith(_CODE_QUESTION_STARTS) and not any(w in text for w in _GIT_WORDS):
        plan = _fast(text, ["query_codebase_rag"])
        plan["tool_calls"][0]["args"] = {"query": transcript}
        return plan
    return None


_CODE_QUESTION_STARTS = ("what", "how", "why", "which", "where", "explain", "describe", "tell me", "does", "is there")
_GIT_WORDS = ("commit", "push", "pull", "merge", "branch", "stash", "staged", "diff", "status", "git",
              "change", "rebase", "remote", "origin", "repo")


def _fast(text: str, tools: list) -> dict:
    return {
        "reasoning": f"Fast path: '{text}'",
        "tool_calls": [{"tool": t, "args": {}} for t in tools],
        "requires_confirm": any(t in _ACTION_WORDS for t in tools),
        "risk_band": "caution" if "push_to_remote" in tools else "safe",
        "fast_path": True,
        "source": "fast_path",
    }


# ── Plan guard: the LLM proposes, this code decides ─────────────────────────
# A tool that changes the repository stays in a plan only if the user's own words asked for it.

_ACTION_WORDS = {
    "commit_changes": ("commit", "save"),
    "push_to_remote": ("push", "publish", "upload"),
    "pull_from_remote": ("pull", "sync", "fetch", "update from", "get the latest", "latest changes",
                         "latest work", "teammates' work", "teammate's work", "bring in", "other people's work"),
}
_NEGATIONS = ("don't", "dont", "do not", "never", "without", "no need to", "instead of", "not yet")
_QUESTION_STARTS = ("what would", "what happens", "what if", "is it safe", "should i", "can i safely",
                    "why", "how do i", "how does", "explain")


def _is_question_or_negated(text: str) -> bool:
    text = text.lower().strip()
    return any(n in text for n in _NEGATIONS) or text.startswith(_QUESTION_STARTS)


def guard_plan(transcript: str, plan: dict) -> dict:
    """
    Remove repository-changing tools the user did not ask for: an action whose words never
    appear in the command, or any action when the command is a question about it or a negation
    ("is it safe to push?", "don't commit"). Read-only tools always pass. If nothing is left,
    the plan becomes a read-only status + diff.
    """
    text = transcript.lower()
    hypothetical = _is_question_or_negated(text)
    kept, dropped = [], []
    for call in plan.get("tool_calls", []):
        tool = call.get("tool")
        words = _ACTION_WORDS.get(tool)
        if words is not None and (hypothetical or not any(w in text for w in words)):
            dropped.append(tool)
            continue
        kept.append(call)
    if not dropped:
        return plan
    logger.warning(f"[PlanGuard] Dropped unrequested actions {dropped} for: '{transcript}'")
    if not kept:
        kept = [{"tool": "get_git_status", "args": {}}, {"tool": "get_git_diff", "args": {}}]
    return {**plan, "tool_calls": kept, "dropped_actions": dropped}


gemini_llm = GeminiLLM()
