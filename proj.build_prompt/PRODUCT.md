# NeuroCode — Product Specification

## One-line description
An AI Accessibility Agent, delivered as a VS Code extension, that lets blind and low-vision developers understand, review, and manage AI-generated code changes and Git workflows by voice — without reading raw diffs line by line.

## Problem statement
Blind developers already code fluently using screen readers, Braille displays, and keyboard-first workflows. What breaks that workflow is the newest layer of software development: AI coding agents generate multi-file diffs faster than any screen reader can narrate, and Git operations assume a visual mental model of branches and conflicts. Every "please wait" moment that a sighted developer glances past is, for a blind developer, a silent, uncertain gap.

**Positioning statement:** We bridge the accessibility gap created by AI-assisted software development. We do not replace Copilot, Cursor, or Claude Code — we make the changes those tools produce, and the Git workflow around them, accessible and reviewable by voice.

## Target user
Blind or low-vision professional software developers who:
- Use a screen reader (NVDA, JAWS, VoiceOver) as their primary interface
- May use a refreshable Braille display for exact syntax verification
- Already use or want to use AI coding agents (Copilot, Cursor, Claude Code) in VS Code
- Work with Git/GitHub as part of their normal workflow

## Core positioning: Why this is an Agent, not just an extension
Every user request follows this loop, without exception:

```
Listen → Understand Intent → Gather Context → Reason → Confirm (when needed)
→ Execute → Verify → Narrate
```

A command is never executed blindly. "Push changes" is not `git push` bound to a button — it's the agent checking branch state, uncommitted changes, remote reachability, and conflict risk, then confirming with the user before acting. The extension is the interface; the agent is the intelligence.

## The Four Pillars

### 1. EchoDiff — AI Change Intelligence
Not a summarizer. Gemini understands, classifies, prioritizes, and estimates risk over AI-generated diffs. Output is delivered through three layers together:
- **Earcon** (fixed set of 3, risk-band only: safe / caution / high-risk, distinguished by timbre not pitch)
- **Voice summary** (ElevenLabs, tone mapped to risk) — carries the actual meaning and nuance
- **Braille** (simulated for demo) — only the exact ambiguous punctuation/syntax fragment, on demand

### 2. Accessibility Agent — Reason Before Acting
The loop itself. Applies to every command, not just Git ones. Never executes without having gathered context and, where the action is consequential (commit, push, undo), confirming with the user first.

### 3. Adaptive Accessibility — Continuous, Never Silent
- **Zero-Silence Handoff:** every processing gap (AI "thinking," Git running) is filled with live incremental narration, never dead air
- **Barge-in:** the user can interrupt narration at any point; playback stops immediately, client-side, on VAD speech-start detection — no round trip to the backend required
- **Voice identity consistency:** filler narration (Sarvam) and primary narration (ElevenLabs) are tuned to sound like one continuous voice, not two separate systems

### 4. GitHub Collaboration — Voice Git, End to End
One conversational surface for the full Git/GitHub lifecycle: status, commit, push, pull, branch, PR creation, review comments, conflict explanation, rollback — all agent-mediated, all confirmed before executing.

## MVP Feature List (build this)

| Feature | Description |
|---|---|
| Voice command capture | Raw PCM audio streamed to Sarvam STT via backend |
| EchoDiff | Gemini-classified diff summary + risk band, spoken + earcon |
| Voice Git — status | "What's my Git status?" |
| Voice Git — commit | Reasons about changed files, drafts message via Gemini, confirms, commits |
| Voice Git — push | Checks branch/remote/conflict state, confirms, pushes, narrates result |
| Voice Git — branch | Create/switch branch by voice |
| Voice Git — conflict explain | "Why can't I push?" — diagnoses via `git status` + `git fetch` comparison |
| Voice Git — review | "Review my changes before committing" — Gemini prose review |
| Voice Git — undo | "Undo my last commit" — explains consequence, confirms, executes |
| PR creation | "Open a pull request" — creates PR with AI-written accessible description via PyGithub |
| Zero-Silence Handoff | Continuous filler narration during any processing gap |
| Barge-in / interrupt | User can stop narration mid-sentence by speaking |
| Earcon set | 3 sounds only: safe / caution / high-risk |
| Simulated Braille panel | On-screen mock of what a physical display would show for flagged fragments |

## Explicitly out of scope for MVP (roadmap only)

- **NeuroCode Learn** (accessible programming education) — future product line, mention as closing vision only
- **Tactile structure export** (swell paper / 3D print) — hardware-dependent, low demo-time-to-value ratio
- **Structural Braille compiler** (full AST-aware tactile layout) — MVP only routes flagged fragments, not full structural compilation
- **PR review threading as a standalone feature** — folded into Voice Git as one more command, not a separate pillar
- **GitHub OAuth / GitHub App** — Phase 2, only if GitHub track rules require it or time permits after MVP is solid
- **Multi-agent conflict detection** — stretch idea, not MVP

## Example user flows

**Commit and push:**
1. User: "Review my changes before committing."
2. Agent: diff → Gemini → "You added password validation, removed unused imports, updated two endpoints. Consider adding a test for invalid passwords." (medium-risk earcon)
3. User: "Commit my changes."
4. Agent: "Three files changed. Suggested commit: 'Update authentication validation.' Continue?"
5. User: "Yes." → commits.
6. User: "Push changes."
7. Agent: "You're on feature/auth. Remote is reachable. Pushing." → pushes → "Push completed successfully."

**Conflict diagnosis:**
1. User: "Why can't I push?"
2. Agent: runs `git status` + `git fetch`, compares branches → "The remote branch has new commits. You'll need to pull and resolve a conflict in auth.py."

**Interruption:**
1. Agent is mid-narration of a long risk summary.
2. User starts speaking.
3. Agent stops playback immediately (client-side, on VAD signal), takes the new input.

## Demo script (~90 seconds, no slides)
1. Set up the problem verbally: "As a sighted developer, you glance at a diff for three seconds. Now imagine you're blind." (30–45s)
2. Play a raw screen reader reading a diff line-by-line, uninterrupted, for 20–30s. Let the room feel it.
3. One-sentence pivot: "We didn't build another AI coding assistant. We built an AI Accessibility Agent."
4. Trigger a real Copilot/agent refactor. Say nothing. NeuroCode speaks first — risk-classified summary + earcon.
5. Voice Git live: commit → push → narrate outcome.
6. Zero-Silence Handoff: "Watch what happens while AI is thinking" — continuous filler narration.
7. Braille, one sentence: "Speech is excellent for logic. Braille is excellent for punctuation." Show the fragment land on the simulated panel.
8. Close: "Our goal isn't to help blind developers write code. It's to let them understand, review, and collaborate with AI as efficiently as every other developer."

## Sponsor track alignment
| Track | Role |
|---|---|
| Gemini API | Diff understanding, risk classification, commit drafting, conflict explanation |
| ElevenLabs | Primary risk-toned narration, voice identity |
| GitHub | Real commit/push/branch/PR/review execution |
| MongoDB Atlas | Session/risk history + vector search for RAG |
| DigitalOcean | Backend hosting |

Sarvam (STT + filler TTS) is a technical reliability choice, not a sponsor-track target — no prize is being chased with it.

## Anticipated Q&A
- **"Why not Cursor?"** → "Cursor helps developers generate code. NeuroCode helps blind developers understand and manage AI-generated changes. They complement each other."
- **"Why is this agentic, not just an extension?"** → Recite the loop: understand → context → reason → confirm → execute → verify → narrate.
- **"How autonomous is it really?"** → It always confirms before executing anything consequential — the strength is accessible orchestration, not autonomy that removes the developer from the loop.
- **"Why not use an OS-level agent (Claude computer use, etc.)?"** → Those act on the visual screen; that doesn't help a user who can't see it. NeuroCode is a narrow, accessibility-specialized reasoning layer over one workflow, translated into the audio/tactile vocabulary this specific population already trusts.
