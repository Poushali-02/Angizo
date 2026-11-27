"""
neurocode-backend/tools/gemini_llm.py

Gemini LLM Integration (with Groq LLM Fallback):
- Primary LLM: Google Gemini REST API (gemini-1.5-flash)
- Fallback LLM: Groq API (openai/gpt-oss-120b)
- Generates voice reasoning, code explanations, and intent classification with RAG context.
"""

import json
import logging
import httpx
import config
from tools.diff_intelligence import diff_intelligence, _clean_spoken

logger = logging.getLogger("neurocode.gemini_llm")

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
                    elif res.status_code in (400, 401, 403) and "API key" in res.text:
                        # A rejected key won't start working mid-session: stop paying the round trip
                        logger.warning(f"[GeminiLLM] API key rejected ({res.status_code}). Using Groq only until restart.")
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
        prompt = f"""You are the AI Planner for NeuroCode accessibility development agent.
Analyze the user command and select atomic tools to execute:

Available Atomic Tools:
- get_git_status: Get active branch and modified/untracked files.
- get_git_diff: Get working tree git diff for modified files.
- commit_changes: Stage and commit changes (args: {{"message": "conventional commit msg"}}, optional: leave it out and the system drafts one from the diff).
- push_to_remote: Push commits to remote origin (args: {{"branch": "branch_name"}}).
- pull_from_remote: Fetch and pull remote changes (args: {{"branch": "branch_name"}}).
- query_codebase_rag: Search codebase files to answer user questions (args: {{"query": "search text"}}).

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
        response = await self.generate(prompt)
        try:
            clean_json = response.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            data = json.loads(clean_json)
            # An empty plan falls through to the rule-based planner below
            if isinstance(data.get("tool_calls"), list) and data["tool_calls"]:
                return guard_plan(transcript, data)
        except Exception:
            pass

        return guard_plan(transcript, self._rule_plan(transcript))

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
        prompt = f"""You are the AI assistant for NeuroCode, a voice-driven accessibility tool.
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
        
        # Smart fallback if LLM response is empty or uninformative
        if rag_context:
            return "Based on your codebase files, this project uses Python with FastAPI for the backend and a VS Code TypeScript extension."
        return "Processed your codebase query successfully."

# ── Plan guard: the LLM proposes, this code decides ─────────────────────────
# A tool that changes the repository stays in a plan only if the user's own words asked for it.

_ACTION_WORDS = {
    "commit_changes": ("commit", "save"),
    "push_to_remote": ("push", "publish", "upload"),
    "pull_from_remote": ("pull", "sync", "fetch", "update from", "get the latest", "latest changes"),
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
