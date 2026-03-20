import os
import httpx
from dotenv import load_dotenv

load_dotenv()

SARVAM_API_KEY = os.getenv("SARVAM_API_KEY")
STT_URL        = "https://api.sarvam.ai/speech-to-text-translate"


async def transcribe_chunk(audio_bytes: bytes, chunk_index: int) -> dict:
    if not SARVAM_API_KEY:
        raise ValueError("SARVAM_API_KEY not found in .env")

    print(f"STT chunk {chunk_index}: received {len(audio_bytes)} bytes")

    if len(audio_bytes) < 1000:
        print(f"STT chunk {chunk_index}: too small — skipping")
        return _failed()

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                STT_URL,
                headers={"api-subscription-key": SARVAM_API_KEY},
                files={"file": (f"chunk_{chunk_index}.webm", audio_bytes, "audio/webm")},
                data={
                    "model":                "saaras:v2.5",
                    "with_timestamps":      "true",
                    "target_language_code": "en-IN",
                },
            )

        if response.status_code != 200:
            print(f"STT error chunk {chunk_index}: {response.status_code} {response.text}")
            return _failed()

        result     = response.json()
        transcript = result.get("transcript", "").strip()
        words      = result.get("words", [])

        if not transcript:
            print(f"STT chunk {chunk_index}: empty transcript")
            return _failed()

        print(f"STT chunk {chunk_index}: {len(transcript)} chars transcribed")
        return {"transcript": transcript, "words": words, "status": "ok"}

    except httpx.TimeoutException:
        print(f"STT chunk {chunk_index}: timed out")
        return _failed()
    except Exception as e:
        print(f"STT chunk {chunk_index}: error — {e}")
        return _failed()


def _failed():
    return {"transcript": "", "words": [], "status": "failed"}