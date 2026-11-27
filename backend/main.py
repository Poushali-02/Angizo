"""
neurocode-backend/main.py

FastAPI app entrypoint.
Matches DESIGN.md module layout: main.py at the backend root.
"""

# Load .env FIRST — before any other local imports read os.getenv()
import os
from dotenv import load_dotenv
if os.getenv("ANGIZO_SKIP_DOTENV") != "1":  # tests set this so they never load real keys
    load_dotenv()  # reads backend/.env into os.environ

import logging
import uvicorn

from fastapi import FastAPI
from api.ws import router as ws_router
from api.rest import router as rest_router
import config

# --- Logging ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("neurocode")

# --- App ---
app = FastAPI(
    title="NeuroCode Accessibility Agent",
    description="AI Accessibility Agent backend — modular monolith (FastAPI)",
    version="0.1.0",
)

app.include_router(ws_router)
app.include_router(rest_router)


@app.on_event("startup")
async def on_startup():
    logger.info(
        f"NeuroCode backend starting on {config.HOST}:{config.PORT}"
    )


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=config.HOST,
        port=config.PORT,
        reload=True,
    )
