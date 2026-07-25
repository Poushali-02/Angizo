"""
neurocode-backend/tools/diff_intelligence.py

Gemini AI Integration for Diff Intelligence & Intent Classification:
- Smart intent classification with fixed taxonomy fallback
- Diff risk classification ('safe' | 'caution' | 'high-risk')
- Commit message drafting
- Pre-commit accessibility prose code review
- Conflict diagnosis explanation
"""

import logging
import json
import httpx
import config

logger = logging.getLogger("neurocode.diff_intelligence")

class DiffIntelligence:
    def __init__(self, api_key: str = None):
        # Prefer Groq API key; fallback to Gemini key for compatibility
        self.api_key = api_key or config.GROQ_API_KEY or config.GEMINI_API_KEY
        # Groq uses OpenAI-compatible endpoint
        self.endpoint = "https://api.groq.com/openai/v1/chat/completions"
        # Model name (default from config)
        self.model = config.GROQ_MODEL if hasattr(config, "GROQ_MODEL") else "llama-3.3-70b-versatile"

    async def _call_groq(self, prompt: str) -> str:
        """Internal helper to query Groq API (OpenAI‑compatible)."""
        if not self.api_key:
            return ""

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.0,
        }
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.post(self.endpoint, json=payload, headers=headers)
                if res.status_code == 200:
                    data = res.json()
                    # Groq returns a list of choices with message content
                    choices = data.get("choices", [])
                    if choices:
                        return choices[0].get("message", {}).get("content", "").strip()
                else:
                    logger.warning(f"[Groq] API error {res.status_code}: {res.text}")
        except Exception as e:
            logger.error(f"[Groq] Exception during API call: {e}")
        return ""

    async def classify_intent(self, transcript: str) -> str:
        """
        Classifies free-form transcript into fixed intent taxonomy using Gemini.
        Supported intents: git_status, git_commit, git_push, git_pull, git_branch_create,
        git_branch_switch, git_explain_conflict, git_review, git_undo, github_open_pr.
        """
        prompt = f"""You are the intent classifier for NeuroCode voice accessibility agent.
Classify the following user command transcript into EXACTLY one of these intent strings:
- git_status
- git_commit
- git_push
- git_pull
- git_branch_create
- git_branch_switch
- git_explain_conflict
- git_review
- git_undo
- github_open_pr
- code_query (for general questions, tech stack queries, codebase explanations, or questions asking how/what/why)

User command transcript: "{transcript}"

Return ONLY the single intent string (e.g. code_query). Do not include any other text, quotes, or markdown.
"""
        result = await self._call_groq(prompt)
        intent = result.strip().lower().replace("`", "").replace("'", "").replace('"', "")
        valid_intents = [
            "git_status", "git_commit", "git_push", "git_pull", "git_branch_create",
            "git_branch_switch", "git_explain_conflict", "git_review", "git_undo", "github_open_pr",
            "code_query"
        ]
        if intent in valid_intents:
            return intent
        
        # Rule-based fallback if Gemini API is missing key or returned unexpected string
        text_lower = transcript.lower()
        if "?" in text_lower or "what" in text_lower or "how" in text_lower or "explain" in text_lower or "stack" in text_lower or "tech" in text_lower:
            return "code_query"
        elif "status" in text_lower or "what changed" in text_lower or "files" in text_lower:
            return "git_status"
        elif "commit" in text_lower or "save" in text_lower:
            return "git_commit"
        elif "push" in text_lower:
            return "git_push"
        elif "pull" in text_lower:
            return "git_pull"
        elif "review" in text_lower or "check my changes" in text_lower:
            return "git_review"
        elif "conflict" in text_lower or "why can't i push" in text_lower or "why cant i push" in text_lower:
            return "git_explain_conflict"
        elif "undo" in text_lower or "revert" in text_lower:
            return "git_undo"
        
        return "code_query"

    async def classify_diff(self, diff_text: str) -> dict:
        """
        Classifies diff into risk_band ('safe' | 'caution' | 'high-risk'),
        summary, blast_radius, and affected_areas.
        """
        if not diff_text.strip():
            return {
                "summary": "No uncommitted changes found.",
                "risk_band": "safe",
                "affected_areas": [],
                "blast_radius": 0
            }

        prompt = f"""Analyze this git diff for an accessibility voice agent:

```diff
{diff_text[:3000]}
```

Respond with JSON only:
{{
  "summary": "1-2 sentence plain language overview",
  "risk_band": "safe" | "caution" | "high-risk",
  "affected_areas": ["area1", "area2"],
  "blast_radius": integer_file_count
}}
"""
        raw_json = await self._call_groq(prompt)
        try:
            # Groq may still return JSON in the content string
            clean_json = raw_json.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            res = json.loads(clean_json)
            return {
                "summary": res.get("summary", "Changes processed."),
                "risk_band": res.get("risk_band", "safe"),
                "affected_areas": res.get("affected_areas", []),
                "blast_radius": res.get("blast_radius", 1)
            }
        except Exception:
            # Rule fallback
            file_count = diff_text.count("diff --git") or 1
            risk = "high-risk" if file_count > 5 or "auth" in diff_text or "password" in diff_text else ("caution" if file_count > 2 else "safe")
            return {
                "summary": f"Detected changes across {file_count} file(s).",
                "risk_band": risk,
                "affected_areas": ["codebase"],
                "blast_radius": file_count
            }

    async def draft_commit_message(self, diff_text: str) -> str:
        """Drafts a concise conventional commit message from diff."""
        if not diff_text.strip():
            return "Update workspace files"

        prompt = f"""Draft a single-line conventional commit message for this git diff:
{diff_text[:2000]}

Return ONLY the commit message string without quotes or extra text."""
        msg = await self._call_groq(prompt)
        if msg:
            return msg.strip().replace('"', '')
        return "Update workspace changes"

    async def review_before_commit(self, diff_text: str) -> str:
        """Generates concise prose code review for voice narration."""
        if not diff_text.strip():
            return "There are no uncommitted changes in your working tree."

        prompt = f"""You are the code review engine for NeuroCode voice accessibility assistant.
Analyze this exact git diff and explain the precise changes made:

```diff
{diff_text[:3500]}
```

Instructions for voice response:
- Explicitly describe the specific code modifications in the diff (for example: mention exact status codes changed like 500 to 400, modified variables, added try-catch blocks, or updated endpoints).
- Do NOT give generic statements like "changes related to exam configuration". State the exact code edits made.
- Keep the response direct, clear, and spoken-friendly in 2-3 sentences.
"""
        review = await self._call_groq(prompt)
        if review:
            return review.strip()
        return "Your repository has modified files with uncommitted changes."

    async def explain_conflict(self, diagnosis_info: dict) -> str:
        """Plain-language explanation of git push/merge conflict."""
        prompt = f"""Explain why a git push failed in simple terms based on this conflict diagnosis:
{json.dumps(diagnosis_info)}

Provide a clear 2-sentence explanation and action item for the developer."""
        explanation = await self._call_groq(prompt)
        if explanation:
            return explanation.strip()
        return "Your local branch is behind the remote origin. You need to pull the latest changes before pushing."

    async def generate_observer_summary(self, event_data: dict) -> str:
        """
        Generates a dynamic spoken accessibility narration explaining:
          - What the generated code/file does
          - Why it is necessary for the project
        The LLM dynamically determines the length and depth of explanation based on code complexity.
        Uses Groq LLM with fallbacks.
        """
        modified_files = event_data.get("modified_files", [])
        created_files = event_data.get("created_files", [])
        lines_added = event_data.get("lines_added", 0)
        code_snippet = event_data.get("code_snippet", "")
        file_name = event_data.get("file", "") or (created_files or modified_files or ["code"])[0]

        if code_snippet:
            prompt = f"""You are the accessibility voice narrator for NeuroCode speaking to a blind software developer.
GitHub Copilot has just generated code in file '{file_name}'.

CODE GENERATED:
```
{code_snippet[:1500]}
```

Analyze the code above and explain it aloud. Dynamically decide how many sentences you need based on the code's complexity:
- For simple utility edits: Give a quick, concise explanation.
- For complex files/modules: Provide a thorough explanation detailing what the code does, why it is necessary, and key functionality.

REQUIREMENTS:
- Keep the response concise and under 60 words (max 350 characters total).
- Do not use markdown syntax, code blocks, bullet points, symbols, or line numbers.
- Speak in natural, spoken prose optimized for screen readers and TTS narration.
- Focus on what the file does and why it is necessary for the application architecture.
"""
        else:
            prompt = f"""You are the accessibility voice narrator for NeuroCode.
Copilot generated {lines_added} lines in '{file_name}'.
Explain what this code does and why it is necessary for the application in clear, natural spoken prose (max 50 words).
"""

        result = await self._call_groq(prompt)
        if result and len(result.strip()) > 10:
            return result.strip().strip('"').strip("'")

        primary_file = file_name.split("/")[-1]
        return f"Copilot updated {primary_file} with {lines_added} lines of code to implement core application logic."

diff_intelligence = DiffIntelligence()
