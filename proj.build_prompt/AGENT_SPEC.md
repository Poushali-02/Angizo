# NeuroCode — Agent Behavior Specification

This file defines exact expected behavior for each supported command, for use when generating the LangGraph node implementations and tool wrappers.

## The Loop

```
Listen → Understand Intent → Gather Context → Reason → Confirm (conditional)
→ Execute → Verify → Narrate
```

Every command passes through every node. Read-only commands skip the Confirm wait but still pass through the node (it's a no-op pass-through, not a skipped step) — this keeps the graph shape consistent for all intents.

## Intent classification

The `Understand Intent` node must map free-form transcripts to one of these intents. Use Gemini for classification with a small fixed intent set — do not attempt open-ended intent extraction.

| Intent | Example utterances | Confirmation required? |
|---|---|---|
| `git_status` | "What's my git status?", "What changed?" | No |
| `git_commit` | "Commit my changes." | Yes |
| `git_push` | "Push changes." | Yes |
| `git_pull` | "Pull latest changes." | Yes |
| `git_branch_create` | "Create a branch called payment-ui." | Yes |
| `git_branch_switch` | "Switch to the develop branch." | Yes |
| `git_explain_conflict` | "Why can't I push?", "Explain this merge conflict." | No |
| `git_review` | "Review my changes before committing." | No |
| `git_undo` | "Undo my last commit." | Yes, with consequence stated |
| `github_open_pr` | "Open a pull request." | Yes |
| `github_show_comments` | "Show review comments." | No |
| `diff_explain` | (triggered automatically on detecting an uncommitted AI-agent-authored change, not by direct user command) | No |
| `interrupt` | detected via VAD START_SPEECH during playback, not transcribed as a command | N/A — handled client-side |

## Tool interfaces (for code generation)

### `git_tool.py`
```python
def status() -> GitStatus:
    """Returns changed/added/deleted files, current branch, ahead/behind counts."""

def commit(message: str) -> CommitResult:
    """Runs git add . && git commit -m <message>."""

def push(branch: str) -> PushResult:
    """Runs git push origin <branch>. Raises on conflict/rejection."""

def pull(branch: str) -> PullResult: ...

def create_branch(name: str) -> None: ...
def switch_branch(name: str) -> None: ...
def diagnose_push_failure() -> ConflictDiagnosis:
    """Runs git fetch, compares local vs remote refs, identifies ahead/behind/diverged state and conflicting files."""

def undo_last_commit(soft: bool = True) -> UndoResult:
    """Explains what will happen (files affected, whether changes are preserved) before caller decides to proceed."""
```

### `github_tool.py`
```python
def create_pull_request(title: str, body: str, base: str, head: str) -> PRResult: ...
def list_review_comments(pr_number: int) -> list[ReviewComment]: ...
def get_repo_metadata() -> RepoMetadata: ...
```

### `diff_intelligence.py`
```python
def classify_diff(diff_text: str, repo_context: str) -> DiffClassification:
    """
    Returns:
      - summary: str (one or two sentences, plain language)
      - risk_band: 'safe' | 'caution' | 'high-risk'
      - affected_areas: list[str]  (e.g. ['authentication', 'database'])
      - blast_radius: int  (number of files touched)
    """

def draft_commit_message(diff_text: str) -> str: ...
def review_before_commit(diff_text: str) -> str:
    """Prose review — praise, concerns, suggested additions (e.g. missing tests)."""

def explain_conflict(diagnosis: ConflictDiagnosis) -> str:
    """Plain-language explanation of why a push/merge failed."""
```

### `accessibility_engine.py`
```python
def select_earcon(risk_band: str) -> EarconId:
    """Maps risk_band to one of exactly 3 sounds: 'safe', 'caution', 'high_risk'.
    Distinguish by timbre, not pitch, for single-listen recognizability."""

def narrate(text: str, risk_band: str, channel: Literal['primary', 'filler']) -> AsyncIterator[bytes]:
    """
    channel='primary' -> ElevenLabs, tone mapped to risk_band
    channel='filler'  -> Sarvam TTS, short and fast, used only during processing gaps
    Both voices must be tuned to sound like one continuous identity.
    """

def route_to_braille(fragment: str) -> None:
    """Sends ONLY the flagged ambiguous fragment (e.g. '});', ']]') to the simulated
    Braille panel — never a full file or full diff."""
```

## Full traces (use these to validate generated node logic)

### Trace: "Commit my changes"
```
Listen: audio -> Sarvam STT -> "commit my changes"
Understand: intent = git_commit
Context: git_tool.status() -> 3 files changed
Reason: diff_intelligence.draft_commit_message(diff) -> "Update authentication validation"
Confirm: narrate("I found changes in three files. Suggested commit: Update
         authentication validation. Would you like to continue?", primary)
         -> wait for transcript
User: "yes"
Execute: git_tool.commit("Update authentication validation")
Verify: commit hash returned, no error
Narrate: "Committed successfully." + safe earcon
```

### Trace: "Why can't I push?"
```
Listen -> "why can't I push"
Understand: intent = git_explain_conflict
Context: git_tool.diagnose_push_failure() -> runs fetch, compares refs
         -> { remote_ahead: 3, conflicting_files: ['auth.py'] }
Reason: diff_intelligence.explain_conflict(diagnosis)
        -> "Another developer pushed three commits. You'll need to pull
            and resolve a conflict in auth.py."
Confirm: not required (read-only/explanatory)
Execute: none (informational only)
Narrate: the explanation above + caution earcon
```

### Trace: "Review my changes before committing"
```
Listen -> "review my changes before committing"
Understand: intent = git_review
Context: git diff (working tree vs HEAD)
Reason: diff_intelligence.review_before_commit(diff)
        -> "You added password validation, removed unused imports, and
            updated two API endpoints. Consider adding a test for invalid
            passwords."
Confirm: not required
Execute: none
Narrate: the review above + risk-mapped earcon
```

### Trace: interruption mid-narration
```
State: playback.ts actively streaming primary narration audio
Event: Sarvam STT VAD fires START_SPEECH
Client: immediately fade-stop local playback (~200-300ms), close/reopen
        TTS socket for next utterance -- NO backend round trip for the stop itself
Then: new transcript proceeds through the normal Listen -> ... loop as
      the next turn
```

## Earcon design constraint
Exactly 3 sounds. No more. Mapped strictly to risk band (`safe` / `caution` / `high-risk`), not to change type (insert/delete/rename) — change type and nuance are carried by voice narration, not earcons. Use distinct timbres (e.g. soft chime / flat tone / sharp double-beep) rather than relying on pitch differences, since timbre is recognizable on a single listen without training.

## Voice tone mapping (for ElevenLabs parameter tuning)
| Risk band | Tone target |
|---|---|
| safe | Calm, even pace |
| caution | Slightly more clipped pace, neutral-alert tone |
| high-risk | Urgent, clipped, faster pace |

Sarvam filler voice should be selected/tuned to sit close to the ElevenLabs primary voice in pitch and character so the handoff between the two is not noticeable.
