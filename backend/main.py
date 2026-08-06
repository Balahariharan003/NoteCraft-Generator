import os
from dotenv import load_dotenv

# Load environment variables first
load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from routers import chunks, finalize, status

app = FastAPI(title="NoteCraft AI Backend (GPU Accelerated)", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chunks.router,   tags=["Chunks"])
app.include_router(finalize.router, tags=["Finalize"])
app.include_router(status.router,   tags=["Status"])

OUTPUTS_DIR = os.path.join(os.path.dirname(__file__), "outputs")
os.makedirs(OUTPUTS_DIR, exist_ok=True)
app.mount("/outputs", StaticFiles(directory=OUTPUTS_DIR), name="outputs")

@app.get("/")
async def root():
    return {
        "status": "NoteCraft AI Backend is running",
        "device": "NVIDIA GPU (CUDA:0)",
        "stt_engine": "Whisper Medium (Local CUDA)",
        "llm_model": os.getenv("LLM_MODEL", "llama3.1:8b"),
    }