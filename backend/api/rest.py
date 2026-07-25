"""
neurocode-backend/api/rest.py

REST endpoints: health check, config, auth token exchange.
Step 1: Only /health is implemented.

Matches DESIGN.md API contract:
  GET /health
  GET /config          (placeholder)
  POST /auth/token     (placeholder)
"""

from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok"}


# Placeholder — Step 2+
# @router.get("/config")
# async def config():
#     """Non-secret client config (feature flags, mode)."""
#     pass

# @router.post("/auth/token")
# async def auth_token():
#     """Exchange for session-scoped token (PAT stored server-side)."""
#     pass
