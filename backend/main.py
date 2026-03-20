from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import os

from routers import chunks, finalize, status

# ── App ────────────────────────────────────────────────────────
app = FastAPI(
    title="MoM Generator API",
    version="1.0.0",
)

# ── CORS ───────────────────────────────────────────────────────
# Allows the Chrome extension to POST to this backend.
# In production restrict origins to your actual domain.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ────────────────────────────────────────────────────
app.include_router(chunks.router,   tags=["Chunks"])
app.include_router(finalize.router, tags=["Finalize"])
app.include_router(status.router,   tags=["Status"])

# ── Serve outputs folder for file downloads ────────────────────
OUTPUTS_DIR = os.path.join(os.path.dirname(__file__), "outputs")
os.makedirs(OUTPUTS_DIR, exist_ok=True)

app.mount(
    "/outputs",
    StaticFiles(directory=OUTPUTS_DIR),
    name="outputs",
)

# ── Health check ───────────────────────────────────────────────
@app.get("/")
async def root():
    return {"status": "MoM Generator API is running"}


# ── Run ────────────────────────────────────────────────────────
# Start with: uvicorn main:app --reload --port 8000