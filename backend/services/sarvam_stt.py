import os
import io
import httpx
import tempfile
import subprocess
from dotenv import load_dotenv

load_dotenv()

SARVAM_API_KEY = os.getenv("SARVAM_API_KEY")
STT_URL        = "https://api.sarvam.ai/speech-to-text-translate"


# ── Transcribe one audio chunk ─────────────────────────────────
async def transcribe_chunk(audio_bytes: bytes, chunk_index: int) -> dict:
    if not SARVAM_API_KEY:
        raise ValueError("SARVAM_API_KEY not found in .env")

    if len(audio_bytes) < 1000:
        print(f"STT chunk {chunk_index}: too small ({len(audio_bytes)} bytes), skipping")
        return _failed_result()

    print(f"STT chunk {chunk_index}: received {len(audio_bytes)} bytes")

    # Convert to WAV first — WAV is self-contained per chunk
    # WebM chunks 1+ have no container header so Sarvam rejects them
    wav_bytes = _convert_to_wav(audio_bytes, chunk_index)

    if not wav_bytes:
        print(f"STT chunk {chunk_index}: conversion failed — sending raw webm")
        wav_bytes = audio_bytes
        filename  = f"chunk_{chunk_index}.webm"
        mimetype  = "audio/webm"
    else:
        print(f"STT chunk {chunk_index}: converted to WAV — {len(wav_bytes)} bytes")
        filename  = f"chunk_{chunk_index}.wav"
        mimetype  = "audio/wav"

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                STT_URL,
                headers={
                    "api-subscription-key": SARVAM_API_KEY,
                },
                files={
                    "file": (filename, wav_bytes, mimetype),
                },
                data={
                    "model":                "saaras:v2.5",
                    "with_timestamps":      "true",
                    "target_language_code": "en-IN",
                },
            )

        if response.status_code != 200:
            print(f"STT error chunk {chunk_index}: {response.status_code} {response.text}")
            return _failed_result()

        result     = response.json()
        transcript = result.get("transcript", "").strip()
        words      = result.get("words", [])

        if not transcript:
            print(f"STT chunk {chunk_index}: empty transcript")
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
        import traceback
        print(f"STT chunk {chunk_index}: unexpected error — {e}")
        traceback.print_exc()
        return _failed_result()

# ── Convert audio bytes to WAV using ffmpeg ────────────────────
def _convert_to_wav(audio_bytes: bytes, chunk_index: int) -> bytes:
    """
    Uses ffmpeg to convert any audio format to WAV.
    WAV is self-contained — every chunk is a valid standalone file.
    This fixes the WebM continuation chunk problem where chunks 1+
    have no container header and Sarvam rejects them.
    """
    try:
        # Write input to temp file
        with tempfile.NamedTemporaryFile(
            suffix=".webm", delete=False
        ) as tmp_in:
            tmp_in.write(audio_bytes)
            tmp_in_path = tmp_in.name

        tmp_out_path = tmp_in_path.replace(".webm", ".wav")

        # Run ffmpeg conversion
        result = subprocess.run(
            [
                "ffmpeg",
                "-y",                    # overwrite output
                "-i", tmp_in_path,       # input file
                "-ar", "16000",          # 16kHz sample rate (Sarvam requirement)
                "-ac", "1",              # mono
                "-f", "wav",             # output format
                tmp_out_path,
            ],
            capture_output=True,
            timeout=60,
        )

        if result.returncode != 0:
            print(f"ffmpeg error chunk {chunk_index}:", result.stderr.decode()[-200:])
            return None

        # Read converted WAV
        with open(tmp_out_path, "rb") as f:
            wav_bytes = f.read()

        return wav_bytes if len(wav_bytes) > 0 else None

    except subprocess.TimeoutExpired:
        print(f"ffmpeg timeout chunk {chunk_index}")
        return None
    except FileNotFoundError:
        print("ffmpeg not found — install ffmpeg and add to PATH")
        return None
    except Exception as e:
        print(f"Conversion error chunk {chunk_index}: {e}")
        return None
    finally:
        # Clean up temp files
        try:
            os.unlink(tmp_in_path)
        except Exception:
            pass
        try:
            os.unlink(tmp_out_path)
        except Exception:
            pass


# ── Failed result ──────────────────────────────────────────────
def _failed_result() -> dict:
    return {
        "transcript": "",
        "words":      [],
        "status":     "failed",
    }