from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask
import os
from models import StatusResponse
from session.store import get_session, delete_session

router = APIRouter()

OUTPUTS_DIR = os.path.join(os.path.dirname(__file__), "..", "outputs")


# ── GET /status ────────────────────────────────────────────────
@router.get("/status", response_model=StatusResponse)
async def get_status(session_id: str):
    """
    Called by popup.js every 2 seconds after End Meeting.
    Returns current pipeline status and download URLs when ready.
    """
    session = get_session(session_id)

    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    return StatusResponse(
        session_id = session_id,
        status     = session.get("status", "processing"),
        pdf_url    = session.get("pdf_url"),
        docx_url   = session.get("docx_url"),
    )


# ── GET /outputs/{filename} ────────────────────────────────────
@router.get("/outputs/{filename}")
async def download_file(filename: str):
    """
    Serves the generated PDF or DOCX file for download.
    Deletes the file AFTER it is fully sent to the user.
    """
    file_path = os.path.abspath(
        os.path.join(OUTPUTS_DIR, filename)
    )

    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File not found")

    # Extract session_id from filename (e.g. "test-001.pdf" -> "test-001")
    session_id = filename.rsplit(".", 1)[0]

    # Determine media type
    if filename.endswith(".pdf"):
        media_type = "application/pdf"
    elif filename.endswith(".docx"):
        media_type = (
            "application/vnd.openxmlformats-officedocument"
            ".wordprocessingml.document"
        )
    else:
        raise HTTPException(status_code=400, detail="Invalid file type")

    # ── KEY FIX: use BackgroundTask ────────────────────────────
    # BackgroundTask runs AFTER the file is fully sent to the user
    # Previously cleanup ran BEFORE serving — causing the 500 error
    return FileResponse(
        path        = file_path,
        filename    = filename,
        media_type  = media_type,
        background  = BackgroundTask(
            _cleanup_after_download, session_id, file_path
        ),
    )


# ── Cleanup runs AFTER file is fully downloaded ────────────────
def _cleanup_after_download(session_id: str, file_path: str):
    """
    Deletes the served file.
    If no more output files exist for this session — delete session.
    """
    try:
        if os.path.exists(file_path):
            os.remove(file_path)
            print(f"Deleted file: {file_path}")

        # Check if any other output files remain for this session
        remaining = [
            f for f in os.listdir(OUTPUTS_DIR)
            if f.startswith(session_id)
        ]

        if not remaining:
            delete_session(session_id)
            print(f"Session {session_id} deleted — all files downloaded")

    except Exception as e:
        print(f"Cleanup error: {e}")