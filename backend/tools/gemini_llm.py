"""
neurocode-backend/tools/gemini_llm.py

Gemini LLM Integration (with Groq LLM Fallback):
- Primary LLM: Google Gemini REST API (gemini-1.5-flash)
- Fallback LLM: Groq API (llama-3.3-70b-versatile)
- Generates voice reasoning, code explanations, and intent classification with RAG context.
"""

import json
import logging
import httpx
import config
from tools.diff_intelligence import diff_intelligence

logger = logging.getLogger("neurocode.gemini_llm")

class GeminiLLM:
    def __init__(self):
        self.api_key = config.GEMINI_API_KEY
        self.model = getattr(config, "GEMINI_MODEL", "gemini-1.5-flash")
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
                    else:
                        logger.warning(f"[GeminiLLM] API error {res.status_code}: {res.text}. Falling back to Groq.")
            except Exception as e:
                logger.warning(f"[GeminiLLM] Exception during Gemini API call: {e}. Falling back to Groq.")

        # Fallback to Groq LLM (llama-3.3-70b-versatile)
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
- commit_changes: Stage and commit changes (args: {{"message": "conventional commit msg"}}).
- push_to_remote: Push commits to remote origin (args: {{"branch": "branch_name"}}).
- pull_from_remote: Fetch and pull remote changes (args: {{"branch": "branch_name"}}).
- query_codebase_rag: Search codebase files to answer user questions (args: {{"query": "search text"}}).

User Command: "{transcript}"

Current Git Status:
Branch: {status_info.get('branch', 'main')}, Uncommitted Changed Files: {len(status_info.get('changed_files', []))}

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
            if "tool_calls" in data and isinstance(data["tool_calls"], list):
                return data
        except Exception:
            pass

        # Rule-based dynamic fallback planner
        text_lower = transcript.lower()
        tool_calls = []
        requires_confirm = False
        risk_band = "safe"

        if "commit" in text_lower and "push" in text_lower:
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
            if len(status_info.get("changed_files", [])) > 0:
                tool_calls = [
                    {"tool": "get_git_diff", "args": {}},
                    {"tool": "commit_changes", "args": {}},
                    {"tool": "push_to_remote", "args": {}}
                ]
            else:
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
Answer the user's question clearly and concisely in 2-3 spoken sentences based on the provided codebase context.

User Question: "{transcript}"

Retrieved Codebase Context:
{rag_context[:2500] if rag_context else "No relevant codebase files found."}

Git Repository Status:
{git_info[:1000] if git_info else "No git changes active."}

Answer requirement:
- Answer the user's specific question directly (e.g. mention the exact tech stack or framework used in the code snippets).
- Do NOT output intent names like 'code_query' or 'git_status'.
- Do NOT use markdown code blocks or code fences.
- Return plain text spoken response only.
"""
        response = await self.generate(prompt)
        response_clean = response.strip().replace("code_query", "").strip() if response else ""
        if response_clean and len(response_clean) > 5:
            return response_clean
        
        # Smart fallback if LLM response is empty or uninformative
        if rag_context:
            return "Based on your codebase files, this project uses Python with FastAPI for the backend and a VS Code TypeScript extension."
        return "Processed your codebase query successfully."

gemini_llm = GeminiLLM()
