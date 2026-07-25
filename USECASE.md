# NeuroCode — Use Cases & Accessibility Impact Guide

## Executive Summary

**NeuroCode** is an AI-powered accessibility agent built specifically for **blind and low-vision software developers**. 

Standard AI coding tools (such as Cursor, GitHub Copilot, Claude Code, and visual IDE extensions) rely almost entirely on **visual feedback loops**: graphical diff views, red/green code comparisons, spinning loading icons, popup dialogs, and visual branch selectors. For a developer relying on a screen reader (like NVDA, JAWS, or VoiceOver), these visual interfaces introduce extreme friction, cognitive fatigue, and navigation barriers.

NeuroCode transforms software engineering into an **audio-first, voice-guided experience**. It sits alongside developers to convert complex visual Git diffs, codebase structures, and repository state changes into clear spoken prose, risk-banded auditory cues, and safe interactive voice workflows.

---

## Feature-by-Feature Accessibility Impact

Below is a detailed breakdown of every core feature built into NeuroCode and how it solves specific challenges faced by visually impaired software engineers.

---

### 1. EchoDiff: Voice-First Code & Diff Intelligence

#### The Accessibility Problem
When a developer makes code changes or pulls updates from a team repository, screen readers recite raw unified Git diffs line-by-line:
```diff
@@ -14,6 +14,12 @@
+ import { AuthProvider } from './auth';
- const oldAuth = require('./legacy_auth');
```
A screen reader reads every symbol aloud: *"at at minus fourteen comma six plus fourteen comma twelve at at plus import open curly bracket AuthProvider close curly bracket..."*. Reviewing a 10-file pull request or working tree diff using a screen reader can take **15 to 30 minutes of exhausting auditory processing**.

#### How NeuroCode Solves It
EchoDiff uses LLM diff intelligence (`diff_intelligence.py`) powered by Groq/Gemini to analyze repository diffs and synthesize them into **2-sentence spoken executive summaries**:
* **Risk Banding:** Classifies diff risk as `safe` (read-only/doc edits), `caution` (minor logic tweaks), or `high-risk` (auth, database, core algorithms).
* **Blast Radius Calculation:** Spoke-lists affected files, components, and module dependencies.
* **Spoken Prose Output:** Spoken aloud directly: *"You modified 3 files in the authentication service. Added JWT token validation in auth.ts and removed legacy session checks. Overall risk is caution due to security boundary updates."*

#### Impact on Blind Developers
* **90% Reduction in Review Time:** Reduces multi-minute diff recitation into a 10-second spoken summary.
* **Instant Risk Awareness:** Blind developers immediately understand if a change is safe to commit or requires careful review without manual line auditing.

---

### 2. Native Host OS Voice Input & Continuous Audio Streaming

#### The Accessibility Problem
VS Code extensions render custom UIs in sandboxed Webview iframes (Chromium). Modern browser security policies block microphone permissions (`Permissions policy violation`) inside sandboxed iframes. Sighted users click graphical buttons or type in text boxes, but blind developers using screen readers struggle with nested iframe focus traps, missing ARIA tags, or focus jumping.

#### How NeuroCode Solves It
NeuroCode bypasses browser iframe permission blocks entirely by capturing audio at the **host operating system level**:
* **Direct OS Capture:** Uses Python `sounddevice` and `numpy` inside the backend process to capture raw 16kHz Int16 PCM audio directly from the physical microphone.
* **Sarvam AI STT Integration:** Streams raw PCM audio directly to Sarvam AI STT (`saarika:v2.5`), converting Indian English and technical developer speech into text.
* **Voice-Activated Toggle:** Users trigger microphone recording via a global hotkey or simple voice toggle without needing to navigate UI elements.

#### Impact on Blind Developers
* **100% Frictionless Voice Control:** Hands-free interaction without fighting VS Code webview iframe permissions.
* **High Technical STT Accuracy:** Accurately recognizes coding vocabulary, Git commands, and developer jargon.

---

### 3. Zero-Silence Audio Handoff (Instant Filler Narration)

#### The Accessibility Problem
Sighted developers glance at spinning loading indicators, progress bars, or bouncing dots while waiting for AI responses. For a blind developer, an AI response delay of 3 to 6 seconds manifests as **complete, terrifying silence ("dead air")**. The user cannot tell if the system crashed, lost network connection, or is actively working.

#### How NeuroCode Solves It
NeuroCode introduces **Zero-Silence Handoff** powered by Sarvam AI TTS (`bulbul:v2`):
1. The instant a voice or text command hits the backend WebSocket (`ws.py`), the system generates and streams an immediate filler audio payload (*"Analyzing workspace changes..."* or *"Inspecting repository diffs..."*) in under **200 milliseconds**.
2. While filler audio plays in the webview audio engine, the LangGraph agent graph, RAG engine, and LLM process the query in parallel.
3. The final answer payload replaces the filler seamlessly without audio stutter or awkward pauses.

#### Impact on Blind Developers
* **Zero Spatial or State Uncertainty:** Provides constant, reassuring acoustic feedback so blind developers always know the system state.
* **Eliminates Dead Air Anxiety:** Converts waiting periods into active, informative auditory context.

---

### 4. 7-Node State Machine with Human-in-the-Loop Safety Confirmation

#### The Accessibility Problem
Autonomous AI agents that execute Git commands directly can easily cause catastrophic data loss if a voice command is misheard (e.g. mistaking *"check branch"* for *"checkout branch"* with uncommitted changes, or force-pushing over team work). Screen reader users cannot quickly visual-check terminal commands before hitting Enter.

#### How NeuroCode Solves It
NeuroCode enforces a strict **7-Node LangGraph State Machine** (`Understand` → `Context` → `Reason` → `Confirm` → `Execute` → `Verify` → `Narrate`):
* **Mutating Action Intercept:** Actions like `git_commit`, `git_push`, `git_branch_switch`, and `git_undo` are intercepted at the `Confirm` node.
* **Spoken Confirmation Prompts:** The agent pauses execution and speaks a high-contrast warning: *"Switching to main branch will overwrite 2 uncommitted files. Are you sure you want to proceed?"*
* **Explicit User Choice:** Execution proceeds only when the user confirms via voice or keyboard button (`[Yes]` / `[No]`).

#### Impact on Blind Developers
* **Bulletproof Repository Safety:** Blind developers can issue voice commands without fear of accidental code deletion or repository corruption.
* **Clear Impact Statements:** Explains the consequence of an action *before* it is executed.

---

### 5. Multi-Tier Risk-Modulated Voice Narration

#### The Accessibility Problem
Standard screen readers recite all text in a flat, robotic, monotonic voice, making it hard to distinguish between routine information (e.g. file saved) and critical warnings (e.g. merge conflict or failing build).

#### How NeuroCode Solves It
NeuroCode features a **Multi-Tier Voice Narration Engine** combining ElevenLabs API and Sarvam AI TTS:
* **Risk-Modulated Parameters:** ElevenLabs voice parameters (stability, similarity boost, style) adjust dynamically based on the risk band:
  * **Safe (`safe`):** Calm, natural, relaxed cadence.
  * **Caution (`caution`):** Measured, precise tone.
  * **High Risk (`high-risk`):** Firm, alert, clear cadence.
* **Guaranteed TTS Fallback:** If ElevenLabs is unconfigured or encounters API quota limits, the system instantly falls back to Sarvam AI TTS (`bulbul:v2`, speaker `anushka` / `ratan`), ensuring **100% voice uptime**.

#### Impact on Blind Developers
* **Auditory Intuition:** Developers feel the risk level of an action through vocal tone and pitch before processing the verbal content.
* **Fail-Safe Audio:** Guarantees that response audio is always delivered.

---

### 6. Local Codebase Semantic RAG Engine

#### The Accessibility Problem
Locating where a specific function, class, or variable is defined across a large codebase requires opening multiple files, using search panels, and line-navigating with a screen reader. This creates immense spatial orientation effort for blind programmers.

#### How NeuroCode Solves It
NeuroCode includes a zero-dependency **Local Codebase RAG Engine** (`rag_engine.py`):
* Indexes workspace source files (`.py`, `.ts`, `.js`, `.json`, `.md`).
* Tokenizes code into semantic blocks while skipping `.git` and `node_modules`.
* Performs sub-50ms TF-IDF semantic relevance ranking against user voice queries.
* Injects exact codebase context into Gemini/Groq LLM to generate precise, voice-narrated answers: *"The authentication middleware is defined in src/middleware/auth.ts on line 42."*

#### Impact on Blind Developers
* **Instant Code Exploration:** Allows blind developers to ask natural questions (*"Where is user authentication handled?"*) and get immediate spoken answers with exact file paths.
* **Eliminates Manual Searching:** Removes the need to manually tab through dozens of open files.

---

### 7. Automated Conventional Commit Message Drafting

#### The Accessibility Problem
Writing good conventional commit messages requires reviewing uncommitted diffs to summarize changes accurately. For blind developers, gathering this context manually is tedious.

#### How NeuroCode Solves It
* Automatically inspects uncommitted diffs via `git_tool.py`.
* Uses `diff_intelligence.py` to generate structured conventional commit messages (e.g., `feat(auth): implement JWT token validation`).
* Reads the draft aloud to the developer and prompts for confirmation before committing.

#### Impact on Blind Developers
* **Effortless Best Practices:** Helps blind developers maintain professional Git commit standards without manual diff inspection.

---

### 8. Accessible Dark-Mode UI & Audio Earcons

#### The Accessibility Problem
Many AI tool webviews are cluttered with low-contrast UI elements, missing keyboard focus indicators, or unannounced dynamic DOM updates.

#### How NeuroCode Solves It
* **High Contrast (WCAG 2.1 AAA):** Dark theme designed for low-vision developers.
* **Screen Reader Live Regions:** Dynamic responses use ARIA live regions (`aria-live="polite"`) for immediate screen reader announcements.
* **Audio Earcons:** Distinct sound chimes indicate system state changes (recording start, transcribing, success, error).

#### Impact on Blind & Low-Vision Developers
* **Universal Usability:** Accommodates fully blind users via audio narration and low-vision users via high-contrast visual cues.

---

## Sighted vs. Blind Developer Workflow Matrix

| Workflow Task | Sighted Developer Workflow (Cursor/Copilot) | Blind Developer Workflow (Standard Tools) | Blind Developer Workflow (**NeuroCode**) |
|---|---|---|---|
| **Reviewing Uncommitted Diffs** | Glances at red/green visual diff panel (5 seconds). | Listens to screen reader read diff code line-by-line (15-30 mins). | Listens to **EchoDiff 2-sentence spoken summary & risk rating** (10 seconds). |
| **Executing Git Operations** | Clicks Git panel icons or types terminal commands. | Navigates terminal output using screen reader cursor key commands. | Speaks natural voice command (**"Commit my changes"**). |
| **System Loading Feedback** | Watches animated spinner / loading bar. | Experiences silent "dead air", uncertain if app hung. | Listens to **Zero-Silence Handoff instant filler audio** (<200ms). |
| **Preventing Bad Pushes/Commits** | Visually verifies changed files before pushing. | Hopes no unintended files were staged; hard to visually verify. | Intercepted by **7-Node Safety Loop with spoken prompt**. |
| **Finding Codebase Context** | Opens files side-by-side; scans code visually. | Opens multiple tabs, reads line numbers with screen reader. | Asks voice question; receives **spoken location & RAG explanation**. |

---

## Conclusion

NeuroCode bridges the accessibility gap in modern AI-assisted software development. By transforming visual IDE interactions into an audio-first, voice-guided, risk-aware conversational experience, NeuroCode enables blind and low-vision developers to code, review, and manage software with the same speed, autonomy, and confidence as sighted peers.
