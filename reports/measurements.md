# Angizo measurements

Measured 2026-11-28 02:48 on Windows 11, Python 3.13.3, in the testing sandbox (every git action in a fresh clone whose origin is a local bare repo). LLM: Groq `openai/gpt-oss-120b` with `openai/gpt-oss-20b` as the rate-limit fallback, free tier. Reproduce with `python backend/evals/measure.py --runs 3`; raw numbers are in `measurements.json`.

## Summary

| Measure | Result |
|---|---|
| Planner accuracy (32 commands × 3 runs) | 97% mean (runs: 97%, 97%, 97%) |
| Unsafe actions planned (commit, push or pull nobody asked for) | **0** of 68 plans |
| Agent scenarios that ended correctly | 10 of 10 |
| Code search: right file first / in top 3 | 7 of 8 / 8 of 8 |
| LLM calls / tokens / rate-limited / fallback model used | 62 / 38,714 / 0 / 0 |

## 1. Planner: does it pick the right tools?

A plan is correct when it includes the tools the command asked for and none it forbids. Clear commands take the fast path (no LLM, deterministic, measured once); the rest go to the LLM and are measured on every run, because LLM output varies between runs.

| Plan source | Plans | Correct | Median time |
|---|---|---|---|
| fast_path | 14 | 100% | 0.00 s |
| llm | 54 | 94% | 0.85 s |

Schema validation: 54 LLM plans valid on the first try, 0 fixed by the one retry, 0 fell back to the keyword rules.

Mistakes:

- "sync with origin" (run 1): planned ['get_git_status'] via llm
- "sync with origin" (run 2): planned ['get_git_status'] via llm
- "sync with origin" (run 3): planned ['get_git_status'] via llm

## 2. Agent: time per node, real graph, real git

Each scenario runs the production graph with a timer around every node. "First question" is when a spoken confirmation would start; for a rejected push the path shows the recovery loop (verify → recover → confirm). Times exclude speech synthesis.

| Scenario | Correct | Median total | Median to first question | LLM calls | Path |
|---|---|---|---|---|---|
| status | 2/2 | 3.7 s | — | 1 | context → understand → reason → confirm → execute → verify → narrate |
| review | 2/2 | 2.8 s | — | 1 | context → understand → reason → confirm → execute → verify → narrate |
| code question | 2/2 | 2.1 s | — | 1 | context → understand → reason → confirm → execute → verify → narrate |
| commit (yes) | 2/2 | 3.8 s | 2.1 s | 1 | context → understand → reason → confirm → confirm → execute → verify → narrate |
| rejected push, recovered (yes, yes) | 2/2 | 5.8 s | 1.7 s | 0 | context → understand → reason → confirm → confirm → execute → verify → recover → confirm → confirm → execute → verify → narrate |

Time spent in each node, across all scenario runs:

| Node | Runs | Median | p95 | Share of total |
|---|---|---|---|---|
| context | 10 | 1.37 s | 1.75 s | 38% |
| understand | 10 | 0.00 s | 0.00 s | 0% |
| reason | 10 | 0.85 s | 1.20 s | 20% |
| confirm | 10 | 0.00 s | 0.00 s | 0% |
| execute | 10 | 1.29 s | 4.16 s | 42% |
| verify | 10 | 0.00 s | 0.00 s | 0% |
| recover | 2 | 0.00 s | 0.00 s | 0% |
| narrate | 10 | 0.00 s | 0.00 s | 0% |

What the agent said (first run of each scenario):

- **status**: "On main, 1 changed file: auth.py. The login function now takes a third argument retries default three; it loops that many times calling check and returns True on success, otherwise returns False after the loop."
- **review**: "On main, 1 changed file: auth.py. The login function now takes a third argument retries default three; it loops that many times calling check and returns True on success, otherwise returns False after the loop."
- **code question**: "The charge function validates that the amount is positive, then returns a dictionary containing the last four digits of the card and the charged amount."
- **commit (yes)**: "Committed 1 file with message: feat(auth): add retry logic to login function."
- **rejected push, recovered (yes, yes)**: "Pulled the new commits from origin, merged them, and pushed successfully."

## 3. Code search (keyword RAG)

| Question | Expected | Retrieved (top 3) | Hit@1 | Hit@3 |
|---|---|---|---|---|
| what does the charge function do | payment.py | app.ts, payment.py | ✗ | ✓ |
| how is the card amount validated | payment.py | payment.py | ✓ | ✓ |
| how does login check the password | auth.py | auth.py | ✓ | ✓ |
| where is the admin user checked | auth.py | auth.py | ✓ | ✓ |
| how is the total of prices computed | app.ts | app.ts | ✓ | ✓ |
| what does reduce sum in total | app.ts | app.ts | ✓ | ✓ |
| why does order id crash | crash.js | crash.js | ✓ | ✓ |
| what is this playground project for | README.md | README.md | ✓ | ✓ |

Keyword overlap, not embeddings: questions phrased with different words than the code are the cases to compare against an embedding search later.

## 4. LLM usage

| Model | Calls | OK | Rate-limited (429) | Median latency | Mean tokens per call |
|---|---|---|---|---|---|
| `openai/gpt-oss-120b` | 62 | 62 | 0 | 0.85 s | 624 |

## 5. Speech (Sarvam bulbul:v3)

| Text | Characters | Seconds | OK |
|---|---|---|---|
| short (acknowledgement) | 21 | 2.25 | ✓ |
| medium (first sentence) | 33 | 2.57 | ✓ |
| long (two sentences) | 135 | 3.64 | ✓ |
| repeat (from cache) | 21 | 0.00 | ✓ |

## Caveats

- One machine, a small sandbox project, free-tier APIs: absolute times are indicative, not production figures.
- Git runs on a OneDrive-synced Windows folder, which makes the context and execute nodes slower than usual.
- The free Groq tier allows about 8,000 tokens a minute per model; the run pauses between LLM calls, and rate-limited calls switch to the fallback model (counted above).
- The planner eval set was written by hand for this project; it tests behaviour, not language coverage.
