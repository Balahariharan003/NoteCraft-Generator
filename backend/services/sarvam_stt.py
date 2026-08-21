import os
import sys
import time
import tempfile
import subprocess
import asyncio
from dotenv import load_dotenv

load_dotenv()

# Register NVIDIA DLL paths for faster-whisper/ctranslate2 on Windows
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
                    os.environ["PATH"] = root + os.pathsep + os.environ.get("PATH", "")

from faster_whisper import WhisperModel

STT_DEVICE = os.getenv("STT_DEVICE", "cuda")
STT_COMPUTE_TYPE = os.getenv("STT_COMPUTE_TYPE", "float16")
STT_TIMEOUT_SECONDS = float(os.getenv("STT_TIMEOUT_SECONDS", "60.0"))
STT_BEAM_SIZE = int(os.getenv("STT_BEAM_SIZE", "2"))

print(f"[STARTUP] Loading local Whisper Medium model on GPU ({STT_DEVICE}, compute_type={STT_COMPUTE_TYPE})...")
try:
    whisper_model = WhisperModel("medium", device=STT_DEVICE, compute_type=STT_COMPUTE_TYPE)
    print(f"[STARTUP] Whisper Medium model successfully loaded on CUDA GPU ({STT_COMPUTE_TYPE})!")
except Exception as e:
    print(f"[STARTUP WARNING] Failed to load Whisper on CUDA ({e}), falling back to CPU...")
    whisper_model = WhisperModel("medium", device="cpu", compute_type="int8")

# ── STT GPU In-Flight Lock to prevent concurrent model inference collision ──
_whisper_gpu_lock = asyncio.Lock()


# ── GPU Memory Helper ────────────────────────────────────────────
def get_gpu_memory_str() -> str:
    try:
        import torch
        if torch.cuda.is_available():
            allocated_mb = torch.cuda.memory_allocated() / (1024 * 1024)
            reserved_mb = torch.cuda.memory_reserved() / (1024 * 1024)
            return f"Allocated: {allocated_mb:.1f} MB | Reserved: {reserved_mb:.1f} MB"
    except Exception:
        pass
    return "GPU Memory: N/A"


# ── Synchronous worker function executed in background thread ───
def _transcribe_sync(wav_path: str, chunk_index: int, language_hint: str = None) -> dict:
    t_start = time.time()
    initial_prompt = (
        "Meeting proceedings, Minutes of Meeting, Erode, Agriculture, Water Resources, "
        "District Collector, Farmers Association, grievance redressal, கூட்டுறவு, வேளாண்மை, "
        "நீர்வளம், பாசனம், கூட்ட நடவடிக்கைகள், மனுக்கள், துறை அலுவலர்கள்."
    )

    lang_to_use = language_hint if language_hint in ["ta", "en"] else None

    segments_gen, info = whisper_model.transcribe(
        wav_path,
        beam_size=STT_BEAM_SIZE,
        best_of=2,
        word_timestamps=True,
        language=lang_to_use,
        task="transcribe",
        vad_filter=True,
        vad_parameters=dict(min_silence_duration_ms=500, speech_pad_ms=200),
        initial_prompt=initial_prompt,
        condition_on_previous_text=False,
        compression_ratio_threshold=2.4,
        no_speech_threshold=0.6,
    )

    detected_lang = getattr(info, "language", "unknown")
    lang_prob = getattr(info, "language_probability", 0.0)

    # Language validation: if session was pinned as Tamil, preserve it unless high-confidence change
    if language_hint == "ta" and detected_lang != "ta" and lang_prob < 0.8:
        detected_lang = "ta"

    full_transcript = []
    all_words = []

    for segment in segments_gen:
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

    duration = time.time() - t_start
    combined_text = " ".join(full_transcript).strip()

    return {
        "transcript": combined_text,
        "words":      all_words,
        "status":     "success" if combined_text else "empty",
        "language":   detected_lang,
        "characters": len(combined_text),
        "duration":   duration,
    }


# ── Async entry point with GPU Lock and Timeout Protection ─────
async def transcribe_chunk(
    audio_bytes: bytes,
    chunk_index: int,
    start_time_sec: int = 0,
    end_time_sec: int = 30,
    language_hint: str = None
) -> dict:
    start_str = f"{start_time_sec // 60:02d}:{start_time_sec % 60:02d}"
    end_str = f"{end_time_sec // 60:02d}:{end_time_sec % 60:02d}"

    if len(audio_bytes) < 1000:
        print(f"[STT] Chunk {chunk_index} ({start_str}-{end_str}): audio payload too small ({len(audio_bytes)}B), marked empty")
        return _failed_result(chunk_index, start_str, end_str, "Audio payload too small", status="empty")

    wav_bytes = _convert_to_wav(audio_bytes, chunk_index)
    if not wav_bytes:
        print(f"[STT ERROR] Chunk {chunk_index} ({start_str}-{end_str}): WAV conversion failed")
        return _failed_result(chunk_index, start_str, end_str, "WAV conversion failed", status="failed")

    tmp_wav = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(wav_bytes)
            tmp_wav = f.name

        # Enforce controlled sequential GPU inference via lock
        async with _whisper_gpu_lock:
            print(f"[STT] Chunk {chunk_index} ({start_str}-{end_str}) starting transcription on GPU...")
            result = await asyncio.wait_for(
                asyncio.to_thread(_transcribe_sync, tmp_wav, chunk_index, language_hint),
                timeout=STT_TIMEOUT_SECONDS,
            )

        result["chunk_id"] = chunk_index
        result["start_time"] = start_str
        result["end_time"] = end_str
        
        print(f"[STT] Chunk {chunk_index} ({start_str}-{end_str}) finished in {result.get('duration', 0):.2f}s | Language: {result.get('language')} | {result.get('characters', 0)} chars")
        return result

    except asyncio.TimeoutError:
        print(f"[STT ERROR] Chunk {chunk_index} ({start_str}-{end_str}) exceeded timeout of {STT_TIMEOUT_SECONDS}s")
        return _failed_result(chunk_index, start_str, end_str, f"Exceeded timeout of {STT_TIMEOUT_SECONDS}s", status="failed")
    except Exception as e:
        print(f"[STT ERROR] Chunk {chunk_index} ({start_str}-{end_str}) Whisper error: {e}")
        return _failed_result(chunk_index, start_str, end_str, str(e), status="failed")
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
            capture_output=True, timeout=30,
        )

        if result.returncode != 0:
            print(f"[FFMPEG ERROR] Chunk {chunk_index}:", result.stderr.decode()[-300:])
            return None

        with open(tmp_out, "rb") as f:
            return f.read()

    except Exception as e:
        print(f"[FFMPEG ERROR] WAV conversion error chunk {chunk_index}: {e}")
        return None
    finally:
        for p in [tmp_in, tmp_out]:
            try:
                if p and os.path.exists(p):
                    os.unlink(p)
            except Exception:
                pass


def _failed_result(chunk_id: int, start_time: str, end_time: str, error_msg: str = "", status: str = "failed") -> dict:
    return {
        "chunk_id":   chunk_id,
        "start_time": start_time,
        "end_time":   end_time,
        "transcript": "",
        "words":      [],
        "status":     status,
        "error":      error_msg,
        "language":   "unknown",
        "characters": 0,
        "duration":   0.0,
    }