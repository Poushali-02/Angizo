"""
neurocode-backend/agent/plan_schema.py

Structured output for the planner: the LLM's JSON plan must match this schema, or it is
not used. parse_plan() turns raw LLM text into a validated Plan, or into an error message
that is sent back to the LLM for one retry (see GeminiLLM.plan_actions).

What the schema rules out:
- tools that do not exist (`tool` is a Literal of the six real tools)
- arguments a tool does not take, or of the wrong type
- branch names that git would read as something else: "+main" means FORCE push in a git
  refspec, "main:prod" pushes to a different branch, "-f" looks like an option
- empty plans and absurdly long ones
"""

import json
import re
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

ToolName = Literal[
    "get_git_status",
    "get_git_diff",
    "commit_changes",
    "push_to_remote",
    "pull_from_remote",
    "query_codebase_rag",
]

# The only arguments each tool accepts
ALLOWED_ARGS: dict[str, set[str]] = {
    "get_git_status": set(),
    "get_git_diff": set(),
    "commit_changes": {"message"},
    "push_to_remote": {"branch"},
    "pull_from_remote": {"branch"},
    "query_codebase_rag": {"query"},
}

# A plain branch name: letters, digits, . _ / -, not starting with "-" or ".", no "..", no ":" or "+"
_BRANCH = re.compile(r"^(?![-.])(?!.*\.\.)[A-Za-z0-9._/-]{1,100}$")


class ToolCall(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool: ToolName
    args: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def check_args(self):
        unknown = set(self.args) - ALLOWED_ARGS[self.tool]
        if unknown:
            raise ValueError(f"{self.tool} does not take {sorted(unknown)}")
        for key, value in self.args.items():
            if value is not None and not isinstance(value, str):
                raise ValueError(f"{self.tool}.{key} must be a string")
        # Empty optional arguments mean "not given"
        self.args = {k: v.strip() for k, v in self.args.items() if isinstance(v, str) and v.strip()}

        branch = self.args.get("branch")
        if branch is not None and not _BRANCH.match(branch):
            raise ValueError(f"unsafe branch name {branch!r}")
        message = self.args.get("message")
        if message is not None and ("\n" in message or len(message) > 120):
            raise ValueError("commit message must be one line of at most 120 characters")
        query = self.args.get("query")
        if query is not None and len(query) > 300:
            raise ValueError("query must be at most 300 characters")
        return self


class Plan(BaseModel):
    model_config = ConfigDict(extra="ignore")

    reasoning: str = ""
    tool_calls: list[ToolCall] = Field(min_length=1, max_length=4)
    requires_confirm: bool = False
    risk_band: Literal["safe", "caution", "high-risk"] = "safe"

    @field_validator("risk_band", mode="before")
    @classmethod
    def normalise_risk(cls, value):
        return str(value).strip().lower() if value is not None else "safe"


def parse_plan(raw: str) -> tuple[Optional[Plan], str]:
    """(plan, "") when `raw` is a valid plan, else (None, a short reason to send back to the LLM)."""
    text = (raw or "").strip()
    if not text:
        return None, "the answer was empty"
    # Models sometimes wrap JSON in a code fence or add a sentence around it: take the object
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return None, "the answer did not contain a JSON object"
    try:
        data = json.loads(text[start:end + 1])
    except json.JSONDecodeError as e:
        return None, f"invalid JSON ({e.msg})"
    try:
        return Plan.model_validate(data), ""
    except ValidationError as e:
        # Say what was sent as well as what was wrong, so the retry can fix that exact value
        problems = "; ".join(
            f"{'.'.join(str(p) for p in err['loc']) or 'plan'}: {err['msg']}"
            + (f" (got {str(err['input'])[:60]!r})" if err.get("type") != "missing" and "input" in err else "")
            for err in e.errors()[:3]
        )
        return None, problems
