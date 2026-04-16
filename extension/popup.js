const BACKEND_URL       = "http://localhost:8000";
const POLL_INTERVAL     = 2000;
const CHUNK_INTERVAL_MS = 30000; // 30s for testing

const states = {
  idle:       document.getElementById("state-idle"),
  recording:  document.getElementById("state-recording"),
  processing: document.getElementById("state-processing"),
  ready:      document.getElementById("state-ready"),
  error:      document.getElementById("state-error"),
};

const btnStart      = document.getElementById("btn-start");
const btnStop       = document.getElementById("btn-stop");
const btnRetry      = document.getElementById("btn-retry");
const btnNew        = document.getElementById("btn-new");
const btnNewError   = document.getElementById("btn-new-error");
const btnDocx       = document.getElementById("btn-docx");
const timerEl       = document.getElementById("timer");
const processingTxt = document.getElementById("processing-text");

// ── Recording state ────────────────────────────────────────────
let timerInterval   = null;
let pollInterval    = null;
let chunkInterval   = null;
let elapsedSeconds  = 0;
let currentSession  = null;
let mediaRecorder   = null;
let audioStream     = null;
let micStream       = null;   // ← microphone stream
let audioContext    = null;   // ← AudioContext for mixing
let chunkIndex      = 0;
let speakerTimeline = [];
let participants    = [];
let recordingStart  = null;
let isRecording     = false;

// ── Show state ─────────────────────────────────────────────────
function showState(name) {
  Object.values(states).forEach((el) => el.classList.remove("active"));
  states[name].classList.add("active");
}

// ── Timer ──────────────────────────────────────────────────────
function startTimer() {
  elapsedSeconds = 0;
  timerInterval  = setInterval(() => {
    elapsedSeconds++;
    const h = String(Math.floor(elapsedSeconds / 3600)).padStart(2, "0");
    const m = String(Math.floor((elapsedSeconds % 3600) / 60)).padStart(2, "0");
    const s = String(elapsedSeconds % 60).padStart(2, "0");
    timerEl.textContent = `${h}:${m}:${s}`;
  }, 1000);
}

function stopTimer() {
  clearInterval(timerInterval);
  timerInterval = null;
}

// ── Processing messages ────────────────────────────────────────
const processingMessages = [
  { delay: 0,     text: "Analyzing meeting audio..."  },
  { delay: 10000, text: "Mapping speaker voices..."   },
  { delay: 25000, text: "Synthesizing AI insights..."  },
  { delay: 60000, text: "Orchestrating final notes..." },
];

function startProcessingMessages() {
  processingMessages.forEach(({ delay, text }) => {
    setTimeout(() => {
      if (processingTxt) processingTxt.textContent = text;
    }, delay);
  });
}

// ── Polling ────────────────────────────────────────────────────
function startPolling(sessionId) {
  pollInterval = setInterval(async () => {
    try {
      const res  = await fetch(`${BACKEND_URL}/status?session_id=${sessionId}`);
      if (res.status === 404) {
        stopPolling();
        await chrome.storage.local.clear();
        showState("idle");
        return;
      }
      const data = await res.json();
      if (data.status === "ready") {
        stopPolling();
        // Open the ready state in a persistent new tab instead of the popup
        // so the user can click anywhere without it closing
        const docxUrl = data.docx_url ? `${BACKEND_URL}${data.docx_url}` : "";
        // Show ready state in popup too (for reference)
        showState("ready");
        if (btnDocx && docxUrl) btnDocx.href = docxUrl;
      } else if (data.status === "failed") {
        stopPolling();
        showState("error");
      }
    } catch (err) {
      console.error("Poll error:", err);
    }
  }, POLL_INTERVAL);
}

function stopPolling() {
  clearInterval(pollInterval);
  pollInterval = null;
}

// ── Upload chunk ───────────────────────────────────────────────
async function uploadChunk(audioBlob, index) {
  const formData = new FormData();
  formData.append("audio",            audioBlob, `chunk_${index}.webm`);
  formData.append("chunk_index",      index);
  formData.append("session_id",       currentSession);
  formData.append("speaker_timeline", JSON.stringify(speakerTimeline));
  formData.append("participants",     JSON.stringify(participants));

  try {
    const res = await fetch(`${BACKEND_URL}/upload-chunk`, {
      method: "POST",
      body:   formData,
    });
    if (!res.ok) console.error(`Chunk ${index} failed:`, res.status);
    else         console.log(`Chunk ${index} uploaded — ${audioBlob.size} bytes`);
  } catch (err) {
    console.error(`Chunk ${index} error:`, err);
  }
}

// ── Finalize ───────────────────────────────────────────────────
async function finalizeSession() {
  try {
    const res = await fetch(`${BACKEND_URL}/finalize`, {
      method:  "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        session_id:       currentSession,
        participants:     participants,
        speaker_timeline: speakerTimeline,
      }),
    });
    if (!res.ok) console.error("Finalize failed:", res.status);
    else         console.log("Finalize sent OK");
  } catch (err) {
    console.error("Finalize error:", err);
  }
}

// ── Record one chunk — stop/restart creates fresh WebM header ──
function recordChunk() {
  if (!audioStream || !isRecording) return;

  const currentIndex = chunkIndex++;

  // Create a fresh MediaRecorder for each chunk
  // This ensures every chunk has its own WebM header
  const recorder = new MediaRecorder(audioStream, { mimeType: "audio/webm" });
  const chunks   = [];

  recorder.ondataavailable = (e) => {
    if (e.data.size > 0) chunks.push(e.data);
  };

  recorder.onstop = async () => {
    if (chunks.length > 0) {
      const blob = new Blob(chunks, { type: "audio/webm" });
      console.log(`Chunk ${currentIndex} complete — ${blob.size} bytes`);
      await uploadChunk(blob, currentIndex);
    }
  };

  recorder.start();

  // Stop after CHUNK_INTERVAL_MS — this triggers onstop → upload
  setTimeout(() => {
    if (recorder.state === "recording") {
      recorder.stop();
    }
  }, CHUNK_INTERVAL_MS);

  // Save reference to stop manually on End Meeting
  mediaRecorder = recorder;
}

// ── Listen for speaker updates from content.js ─────────────────
chrome.runtime.onMessage.addListener((msg) => {
  if (msg.action === "SPEAKER_UPDATE" && recordingStart) {
    const elapsed = Date.now() - recordingStart;
    speakerTimeline.push({ name: msg.name, timestamp_ms: elapsed });
  }
  if (msg.action === "PARTICIPANTS_UPDATE") {
    participants = msg.participants;
  }
});

// ── Button: Start Recording ────────────────────────────────────
btnStart.addEventListener("click", async () => {

  currentSession  = crypto.randomUUID();
  chunkIndex      = 0;
  speakerTimeline = [];
  participants    = [];
  recordingStart  = null;
  isRecording     = true;

  try {
    // Step 1: Capture tab audio (user must tick "Share tab audio")
    const displayStream = await navigator.mediaDevices.getDisplayMedia({
      video: true,
      audio: true,
    });

    const tabAudioTrack = displayStream.getAudioTracks()[0];
    const videoTrack    = displayStream.getVideoTracks()[0];

    if (videoTrack) videoTrack.stop(); // we only need audio

    if (!tabAudioTrack) {
      alert(
        "No tab audio captured.\n\n" +
        "When the screen share picker appears:\n" +
        "1. Click 'Chrome Tab'\n" +
        "2. Select your Google Meet tab\n" +
        "3. Tick 'Share tab audio'\n" +
        "4. Click Share"
      );
      isRecording = false;
      return;
    }

    // Step 2: Capture microphone audio
    // Disable echo cancellation, noise suppression, and auto gain control
    // so Chrome doesn't suppress the user's voice when tab audio is present
    let micAudioTrack = null;
    try {
      micStream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: false,
          noiseSuppression: false,
          autoGainControl: false,
        },
        video: false,
      });
      micAudioTrack = micStream.getAudioTracks()[0];
      console.log("Microphone track:", micAudioTrack.label);
    } catch (micErr) {
      console.warn("Microphone not available, recording tab audio only:", micErr.message);
    }

    // Step 3: Mix tab audio + microphone using Web Audio API
    audioContext = new AudioContext();
    const destination = audioContext.createMediaStreamDestination();

    // Connect tab audio source
    const tabSource = audioContext.createMediaStreamSource(new MediaStream([tabAudioTrack]));
    tabSource.connect(destination);

    // Connect microphone source (if available) with gain boost
    if (micAudioTrack) {
      const micSource = audioContext.createMediaStreamSource(new MediaStream([micAudioTrack]));
      const micGain   = audioContext.createGain();
      micGain.gain.value = 1.5; // Boost mic volume to ensure voice is captured
      micSource.connect(micGain);
      micGain.connect(destination);
    }

    // Use the mixed stream for recording
    audioStream    = destination.stream;
    recordingStart = Date.now();

    console.log("Tab audio track:", tabAudioTrack.label);

    // Auto-stop when user clicks "Stop sharing" in browser
    tabAudioTrack.onended = () => {
      console.log("Tab sharing ended");
      if (isRecording) btnStop.click();
    };

    // Start first chunk immediately
    recordChunk();

    // Start new chunk every CHUNK_INTERVAL_MS
    chunkInterval = setInterval(() => {
      if (isRecording) recordChunk();
    }, CHUNK_INTERVAL_MS);

    await chrome.storage.local.set({
      currentSession: currentSession,
      currentState:   "recording",
    });

    showState("recording");
    startTimer();
    console.log("Recording started. Session:", currentSession);

  } catch (err) {
    isRecording = false;
    console.error("Start error:", err);
    if (err.name === "NotAllowedError") {
      alert("Screen sharing was cancelled. Please try again.");
    } else {
      alert("Could not start: " + err.message);
    }
  }
});

// ── Button: End Meeting ────────────────────────────────────────
btnStop.addEventListener("click", async () => {
  isRecording = false;
  stopTimer();

  // Stop chunk interval
  clearInterval(chunkInterval);
  chunkInterval = null;

  // Stop current recorder — triggers final chunk upload
  if (mediaRecorder && mediaRecorder.state === "recording") {
    mediaRecorder.stop();
    await new Promise(r => setTimeout(r, 500)); // wait for final chunk
  }

  // Stop audio stream tracks
  if (audioStream) {
    audioStream.getTracks().forEach(t => t.stop());
    audioStream = null;
  }

  // Stop microphone stream
  if (micStream) {
    micStream.getTracks().forEach(t => t.stop());
    micStream = null;
  }

  // Close AudioContext
  if (audioContext) {
    audioContext.close();
    audioContext = null;
  }

  showState("processing");
  startProcessingMessages();
  await chrome.storage.local.clear();
  await finalizeSession();

  if (currentSession) {
    startPolling(currentSession);
  }
});

// ── Button: Retry ─────────────────────────────────────────────
btnRetry.addEventListener("click", async () => {
  if (!currentSession) return;
  showState("processing");
  startProcessingMessages();
  try {
    await fetch(`${BACKEND_URL}/finalize`, {
      method:  "POST",
      headers: { "Content-Type": "application/json" },
      body:    JSON.stringify({ session_id: currentSession }),
    });
    startPolling(currentSession);
  } catch (err) {
    showState("error");
  }
});

// ── Button: New Recording ──────────────────────────────────────
async function resetToIdle() {
  isRecording = false;
  stopPolling();
  stopTimer();
  clearInterval(chunkInterval);
  chunkInterval = null;
  if (mediaRecorder && mediaRecorder.state === "recording") {
    mediaRecorder.stop();
  }
  if (audioStream) {
    audioStream.getTracks().forEach(t => t.stop());
    audioStream = null;
  }
  if (micStream) {
    micStream.getTracks().forEach(t => t.stop());
    micStream = null;
  }
  if (audioContext) {
    audioContext.close();
    audioContext = null;
  }
  currentSession = null;
  elapsedSeconds = 0;
  timerEl.textContent = "00:00:00";
  await chrome.storage.local.clear();
  showState("idle");
}

btnNew.addEventListener("click", resetToIdle);
btnNewError.addEventListener("click", resetToIdle);

// ── Init ───────────────────────────────────────────────────────
(async () => {
  const stored = await chrome.storage.local.get(["currentSession", "currentState"]);
  if (stored.currentSession && stored.currentState === "recording") {
    try {
      const res = await fetch(`${BACKEND_URL}/status?session_id=${stored.currentSession}`);
      if (res.status === 404) {
        await chrome.storage.local.clear();
        showState("idle");
        return;
      }
      currentSession = stored.currentSession;
      showState("recording");
      startTimer();
    } catch (e) {
      await chrome.storage.local.clear();
      showState("idle");
    }
  } else {
    await chrome.storage.local.clear();
    showState("idle");
  }
})();