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

    async def generate_copilot_spoken_summary(self, event_data: dict) -> str:
        """
        Prompt Spec 1 (STREAM.md):
        Generates EXACTLY ONE short, spoken sentence (max 15 words) for completed generations.
        """
        modified_files = ", ".join(event_data.get("modified_files", [])) or event_data.get("file", "code file")
        created_files = ", ".join(event_data.get("created_files", [])) or "none"
        lines_added = event_data.get("lines_added", 0)
        lines_removed = event_data.get("lines_removed", 0)
        error_count = event_data.get("error_count", 0)
        warning_count = event_data.get("warning_count", 0)

        prompt = f"""SYSTEM PROMPT:
You are the accessibility voice narrator for NeuroCode.
A blind software developer is using GitHub Copilot. Copilot has just completed an automated code generation session.

Summarize what Copilot generated into EXACTLY ONE short, spoken sentence (max 15 words) suitable for a screen reader or TTS voice engine. Do not use code markdown syntax, special characters, or raw diff markers.

INPUT DATA:
Files Modified: {modified_files}
Files Created: {created_files}
Lines Added: {lines_added}
Lines Removed: {lines_removed}
LSP Diagnostics: {error_count} errors, {warning_count} warnings

OUTPUT FORMAT:
Return ONLY the plain text spoken sentence.
"""
        result = await self._call_groq(prompt)
        if result and len(result.strip()) > 5:
            return result.strip().strip('"').strip("'")

        primary_file = (event_data.get("file") or "file").split("/")[-1].split("\\")[-1]
        err_msg = "with zero errors" if error_count == 0 else f"with {error_count} errors"
        return f"Copilot generated code in {primary_file} across {lines_added} lines {err_msg}."

    async def generate_milestone_spoken_alert(self, action_type: str, target_name: str) -> str:
        """
        Prompt Spec 2 (STREAM.md):
        Generates an instant, concise spoken alert (max 6 words) for file creation or dependency updates.
        """
        prompt = f"""SYSTEM PROMPT:
Generate an instant, 6-word spoken alert for a blind developer when an automated AI agent creates a new file or updates project dependencies.

INPUT:
Action: {action_type}
Target: {target_name}

EXAMPLE OUTPUTS:
- "Copilot created new file payment.py."
- "Copilot added dependency jsonwebtoken to package.json."

OUTPUT FORMAT:
Return ONLY the plain text spoken sentence.
"""
        result = await self._call_groq(prompt)
        if result and len(result.strip()) > 5:
            return result.strip().strip('"').strip("'")

        target_short = target_name.split("/")[-1].split("\\")[-1]
        if action_type == "file_created":
            return f"Copilot created new file {target_short}."
        elif action_type == "dependency_updated":
            return f"Copilot updated project dependencies in {target_short}."
        return f"Copilot modified {target_short}."

    async def generate_observer_summary(self, event_data: dict) -> str:
        """
        Generates dynamic spoken accessibility narration matching STREAM.md specifications.
        Routes copilot_complete to Prompt Spec 1 and milestone events to Prompt Spec 2.
        """
        event_type = event_data.get("event_type", "copilot_complete")
        target_file = event_data.get("file", "") or "workspace file"

        if event_type == "file_created":
            return await self.generate_milestone_spoken_alert("file_created", target_file)
        elif event_type == "dependency_updated":
            return await self.generate_milestone_spoken_alert("dependency_updated", target_file)
        else:
            return await self.generate_copilot_spoken_summary(event_data)

diff_intelligence = DiffIntelligence()
