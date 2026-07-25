# NeuroCode — Build Roadmap

## Build order (do not reorder — voice input is the highest-risk unknown)

1. [x] **Voice input spike (Day 1).** `AudioWorklet` PCM capture in webview → stream to backend → Sarvam STT → transcript appears.
2. [x] Agent core loop (LangGraph skeleton — 7 nodes)
3. [x] Git Tool (GitPython) wired into the loop for `git_status`, `git_commit`, `git_push`
4. [x] Diff Intelligence (Gemini) wired in for smart intent classification, `git_review`, and commit message drafting
5. [x] Voice output: ElevenLabs primary narration streaming back to client
6. [ ] Earcon player (3-sound set) synced to risk band
7. [x] Zero-Silence Handoff: Sarvam filler narration layer on top of processing gaps
8. [ ] Barge-in: client-side VAD-triggered playback stop
9. [ ] GitHub Tool (PyGithub): PR creation, `git_explain_conflict`, `git_undo`
10. [ ] Simulated Braille panel (on-screen mock, fragment-only routing)
11. [ ] MongoDB Atlas: session/command history logging
12. [ ] RAG engine: repo embeddings + Atlas Vector Search (only if steps 1–11 are solid with time remaining)
13. [ ] Deployment: Docker + DigitalOcean App Platform, Local Mode fallback switch tested


## Phase 1 — MVP (build for the hackathon)
Everything in `PRODUCT.md`'s MVP Feature List. This is the demo.

## Phase 2 — only if time remains after Phase 1 is fully working, or a sponsor track explicitly requires it
- GitHub OAuth / GitHub App (replacing PAT) — confirm GitHub track rules first
- Structural Braille compiler (full AST-aware tactile layout, beyond flagged fragments)
- PR review comment threading as a richer, dedicated navigation experience
- Multi-agent conflict detection ("two AI suggestions disagree" earcon)

## Phase 3 — post-hackathon roadmap (mention in pitch closing only, do not build)
- NeuroCode Learn: accessible programming education built around the same audio-grammar vocabulary as Assist, so students learn the sounds/voice patterns they'll use professionally from day one
- Tactile structure export (swell paper / 3D-printable diagrams of data structures)
- Meeting/screen-share accessibility narration
- Native OS-level screen reader / Braille driver integration (beyond simulation)

## Explicitly rejected ideas (with reasoning, so they don't get re-proposed mid-build)
- **Standalone DevOps automation agent** — different problem (operations, not accessibility), no research-backed gap, would dilute the pitch
- **Structural Braille Routing as a headline demo feature** — real and useful, but most judges have never seen a Braille display; keep it to one sentence + a labeled simulation, not a hardware demo
- **Tactile Export as MVP** — memorable but hardware-dependent (printer/swell paper), hard to justify frequency of real-world use, cut to roadmap
- **6-8 earcon vocabulary** — not recognizable on a single cold listen by a live audience; cut to 3, risk-band only
- **Chasing all 8 sponsor tracks** — Actian, SuperPlane, and Solana don't map naturally onto this architecture; forcing them in risks looking gimmicky. Only build for tracks where the integration is genuinely load-bearing (Gemini, ElevenLabs, GitHub, MongoDB, DigitalOcean)
- **Positioning as competing with Cursor/Copilot** — always frame as complementary: "they generate code, we make understanding and managing that code accessible"

## Known technical risks to de-risk early, not discover late
- Web Speech API `SpeechRecognition` is broken inside Electron (VS Code webviews) — already designed around via Sarvam, but do not fall back to browser STT under time pressure
- `MediaRecorder`'s default `webm/opus` output is incompatible with Sarvam's WAV/PCM-only streaming endpoint — must use `AudioWorkletNode` for raw PCM capture, not `MediaRecorder`
- Sarvam TTS has no server-side cancel — barge-in must be fully client-side
- GitPython shells out to a system `git` binary — confirm it's on PATH and credentials are configured identically on both the local dev machine and whatever machine runs the demo
