import os
import tempfile
import subprocess
from dotenv import load_dotenv

load_dotenv()

# Register NVIDIA DLL paths for faster-whisper/ctranslate2 on Windows
# MUST RUN BEFORE IMPORTING FASTER_WHISPER
if os.name == "nt":
    import site
    search_dirs = list(site.getsitepackages())
    if hasattr(site, "getusersitepackages"):
        user_site = site.getusersitepackages()
        if isinstance(user_site, str):
            search_dirs.append(user_site)
        elif isinstance(user_site, list):
            search_dirs.extend(user_site)

    for site_pkg in search_dirs:
        nvidia_dir = os.path.join(site_pkg, "nvidia")
        if os.path.exists(nvidia_dir):
            for root, dirs, files in os.walk(nvidia_dir):
                if any(f.endswith(".dll") for f in files):
                    try:
                        os.add_dll_directory(root)
                    except Exception:
                        pass
                    # CRITICAL: Also add to PATH so CTranslate2 C++ engine can find it
                    os.environ["PATH"] = root + os.pathsep + os.environ.get("PATH", "")

from faster_whisper import WhisperModel
load_dotenv()

STT_DEVICE = os.getenv("STT_DEVICE", "cuda")
STT_COMPUTE_TYPE = os.getenv("STT_COMPUTE_TYPE", "float16")
print(f"Loading local Whisper Medium model on GPU ({STT_DEVICE}, compute_type={STT_COMPUTE_TYPE})...")
try:
    whisper_model = WhisperModel("medium", device=STT_DEVICE, compute_type=STT_COMPUTE_TYPE)
    print(f"Whisper Medium model successfully loaded on CUDA GPU ({STT_COMPUTE_TYPE})!")
except Exception as e:
    print(f"Warning: Failed to load Whisper on CUDA ({e}), falling back to CPU...")
    whisper_model = WhisperModel("medium", device="cpu", compute_type="int8")


# ── Transcribe one audio chunk using local Whisper Medium ──────
async def transcribe_chunk(audio_bytes: bytes, chunk_index: int) -> dict:
    if len(audio_bytes) < 1000:
        print(f"STT chunk {chunk_index}: too small ({len(audio_bytes)} bytes), skipping")
        return _failed_result()

    print(f"STT chunk {chunk_index}: received {len(audio_bytes)} bytes")

    # Convert to WAV (16kHz mono)
    wav_bytes = _convert_to_wav(audio_bytes, chunk_index)
    if not wav_bytes:
        print(f"STT chunk {chunk_index}: WAV conversion failed")
        return _failed_result()

    # Save WAV bytes to a temp file for faster-whisper processing
    tmp_wav = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(wav_bytes)
            tmp_wav = f.name

        # Perform local transcription with word-level timestamps
        segments, info = whisper_model.transcribe(
            tmp_wav,
            beam_size=3,
            word_timestamps=True,
            language="en"
        )

        full_transcript = []
        all_words = []

        for segment in segments:
            text = segment.text.strip()
            if text:
                full_transcript.append(text)

            if segment.words:
                for w in segment.words:
                    all_words.append({
                        "word":  w.word.strip(),
                        "start": round(w.start, 2),
                        "end":   round(w.end, 2),
                    })

        combined_text = " ".join(full_transcript).strip()

        if not combined_text:
            print(f"STT chunk {chunk_index}: empty transcript")
            return _failed_result()

        print(f"STT chunk {chunk_index}: {len(combined_text)} chars transcribed using local Whisper Medium")

        return {
            "transcript": combined_text,
            "words":      all_words,
            "status":     "ok",
        }

    except Exception as e:
        print(f"STT chunk {chunk_index} Whisper Error: {e}")
        return _failed_result()
    finally:
        if tmp_wav and os.path.exists(tmp_wav):
            try:
                os.unlink(tmp_wav)
            except Exception:
                pass


# ── Convert audio bytes to WAV using ffmpeg ────────────────────
def _convert_to_wav(audio_bytes: bytes, chunk_index: int) -> bytes:
    tmp_in = tmp_out = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as f:
            f.write(audio_bytes)
            tmp_in = f.name

        tmp_out = tmp_in.replace(".webm", ".wav")

        result = subprocess.run(
            ["ffmpeg", "-y", "-i", tmp_in, "-ar", "16000", "-ac", "1", "-f", "wav", tmp_out],
            capture_output=True, timeout=60,
        )

        if result.returncode != 0:
            print(f"ffmpeg error chunk {chunk_index}:", result.stderr.decode()[-300:])
            return None

        with open(tmp_out, "rb") as f:
            return f.read()

    except Exception as e:
        print(f"WAV conversion error chunk {chunk_index}: {e}")
        return None
    finally:
        for p in [tmp_in, tmp_out]:
            try:
                if p and os.path.exists(p):
                    os.unlink(p)
            except Exception:
                pass


def _failed_result() -> dict:
    return {"transcript": "", "words": [], "status": "failed"}