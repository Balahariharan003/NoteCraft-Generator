from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
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
    Deletes the session data after the file is served.
    """
    file_path = os.path.join(OUTPUTS_DIR, filename)

    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File not found")

    # Extract session_id from filename (e.g. "abc123.pdf" -> "abc123")
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

    # Delete session after both files are served
    # We delete on DOCX download (last file) to ensure PDF was downloaded first
    # For simplicity in college project — delete on any download
    response = FileResponse(
        path         = file_path,
        filename     = filename,
        media_type   = media_type,
    )

    # Cleanup after response is sent
    _schedule_cleanup(session_id, file_path)

    return response


# ── Schedule cleanup after download ───────────────────────────
def _schedule_cleanup(session_id: str, file_path: str):
    """
    Deletes the file and session data.
    Called after serving the download.
    """
    try:
        if os.path.exists(file_path):
            os.remove(file_path)
            print(f"Deleted file: {file_path}")

        # Only delete session when all outputs are gone
        outputs_dir = OUTPUTS_DIR
        remaining = [
            f for f in os.listdir(outputs_dir)
            if f.startswith(session_id)
        ]

        if not remaining:
            delete_session(session_id)
            print(f"Session {session_id} deleted — all files downloaded")

    except Exception as e:
        print(f"Cleanup error: {e}")