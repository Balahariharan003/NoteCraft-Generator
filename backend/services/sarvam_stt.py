import os
import httpx
from dotenv import load_dotenv

load_dotenv()

SARVAM_API_KEY = os.getenv("SARVAM_API_KEY")
STT_URL        = "https://api.sarvam.ai/speech-to-text-translate"


# ── Transcribe one audio chunk ─────────────────────────────────
async def transcribe_chunk(audio_bytes: bytes, chunk_index: int) -> dict:
    """
    Sends audio to Sarvam Saaras v2.5.
    Returns:
        {
          "transcript": "full english text...",
          "words": [{ "word": "hello", "start": 0.2, "end": 0.6 }, ...],
          "status": "ok" | "failed"
        }
    """
    if not SARVAM_API_KEY:
        raise ValueError("SARVAM_API_KEY not found in .env")

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                STT_URL,
                headers={
                    "api-subscription-key": SARVAM_API_KEY,
                },
                files={
                    "file": (f"chunk_{chunk_index}.webm", audio_bytes, "audio/webm"),
                },
                data={
                    "model":            "saaras:v2.5",
                    "with_timestamps":  "true",
                    "target_language_code": "en-IN",
                },
            )

        if response.status_code != 200:
            print(f"STT error chunk {chunk_index}: {response.status_code} {response.text}")
            return _failed_result()

        result = response.json()

        # Extract transcript text
        transcript = result.get("transcript", "").strip()

        # Extract word-level timestamps if available
        words = result.get("words", [])

        if not transcript:
            print(f"STT chunk {chunk_index}: empty transcript returned")
            return _failed_result()

        print(f"STT chunk {chunk_index}: {len(transcript)} chars transcribed")

        return {
            "transcript": transcript,
            "words":      words,
            "status":     "ok",
        }

    except httpx.TimeoutException:
        print(f"STT chunk {chunk_index}: request timed out")
        return _failed_result()

    except Exception as e:
        print(f"STT chunk {chunk_index}: unexpected error — {e}")
        return _failed_result()


# ── Helper: return a failed result ─────────────────────────────
def _failed_result() -> dict:
    return {
        "transcript": "",
        "words":      [],
        "status":     "failed",
    }