# Hard Architectural Constraints

- The webview NEVER opens a WebSocket directly. Audio/UI events go
  webview -> postMessage -> extension host -> WebSocket -> backend.
  See DESIGN.md's topology note before touching networking code.
- Backend is a modular monolith (FastAPI). Do not propose splitting
  into separate services.
- Match module names/paths exactly as specified in DESIGN.md.
- Mutating Git actions (commit, push, branch, undo) always require
  user confirmation before executing. Read-only actions do not.