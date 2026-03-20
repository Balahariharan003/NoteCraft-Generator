const BACKEND_URL = "http://localhost:8000";
const CHUNK_INTERVAL_MS = 180000; // 3 minutes

let mediaRecorder = null;
let sessionId = null;
let chunkIndex = 0;
let speakerTimeline = [];
let participants = [];
let recordingStartTime = null;

// ── Listen for messages from popup.js ─────────────────────────
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.action === "START_RECORDING") {
    startRecording(message.tabId).then(() => {
      sendResponse({ success: true, sessionId });
    });
    return true; // keep channel open for async response
  }

  if (message.action === "STOP_RECORDING") {
    stopRecording().then(() => {
      sendResponse({ success: true });
    });
    return true;
  }

  if (message.action === "SPEAKER_UPDATE") {
    // Received from content.js — store speaker event with timestamp
    const elapsed = Date.now() - recordingStartTime;
    speakerTimeline.push({
      name: message.name,
      timestamp_ms: elapsed,
    });
  }

  if (message.action === "PARTICIPANTS_UPDATE") {
    // Received from content.js — update participant list
    participants = message.participants;
  }
});

// ── Start recording ────────────────────────────────────────────
async function startRecording(tabId) {
  // Generate a unique session ID
  sessionId = crypto.randomUUID();
  chunkIndex = 0;
  speakerTimeline = [];
  participants = [];
  recordingStartTime = Date.now();

  // Capture the tab's audio stream
  const stream = await new Promise((resolve, reject) => {
    chrome.tabCapture.capture({ audio: true, video: false }, (capturedStream) => {
      if (chrome.runtime.lastError) {
        reject(chrome.runtime.lastError);
      } else {
        resolve(capturedStream);
      }
    });
  });

  // Start MediaRecorder — fires ondataavailable every 3 minutes
  mediaRecorder = new MediaRecorder(stream, { mimeType: "audio/webm" });

  mediaRecorder.ondataavailable = async (event) => {
    if (event.data && event.data.size > 0) {
      await uploadChunk(event.data);
    }
  };

  mediaRecorder.onerror = (error) => {
    console.error("MediaRecorder error:", error);
  };

  // timeslice = 180000ms → auto fires ondataavailable every 3 min
  mediaRecorder.start(CHUNK_INTERVAL_MS);

  console.log("Recording started. Session ID:", sessionId);
}

// ── Stop recording ─────────────────────────────────────────────
async function stopRecording() {
  if (!mediaRecorder) return;

  // Stop the recorder — this fires one final ondataavailable
  await new Promise((resolve) => {
    mediaRecorder.onstop = resolve;
    mediaRecorder.stop();
  });

  // Stop all audio tracks
  mediaRecorder.stream.getTracks().forEach((track) => track.stop());
  mediaRecorder = null;

  // Send finalize request to backend
  await finalizeSession();

  console.log("Recording stopped. Finalize sent.");
}

// ── Upload a single audio chunk to backend ─────────────────────
async function uploadChunk(audioBlob) {
  const currentIndex = chunkIndex++;

  const formData = new FormData();
  formData.append("audio", audioBlob, `chunk_${currentIndex}.webm`);
  formData.append("chunk_index", currentIndex);
  formData.append("session_id", sessionId);
  formData.append("speaker_timeline", JSON.stringify(speakerTimeline));
  formData.append("participants", JSON.stringify(participants));

  try {
    const response = await fetch(`${BACKEND_URL}/upload-chunk`, {
      method: "POST",
      body: formData,
    });

    if (!response.ok) {
      console.error(`Chunk ${currentIndex} upload failed:`, response.status);
    } else {
      console.log(`Chunk ${currentIndex} uploaded successfully`);
    }
  } catch (error) {
    // Store failed chunk in chrome.storage for retry
    console.error(`Chunk ${currentIndex} upload error:`, error);
    await storeFailedChunk(currentIndex, audioBlob);
  }
}

// ── Send finalize signal to backend ───────────────────────────
async function finalizeSession() {
  try {
    const response = await fetch(`${BACKEND_URL}/finalize`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        session_id: sessionId,
        participants: participants,
        speaker_timeline: speakerTimeline,
      }),
    });

    if (!response.ok) {
      console.error("Finalize failed:", response.status);
    }
  } catch (error) {
    console.error("Finalize error:", error);
  }
}

// ── Store failed chunk locally for retry ──────────────────────
async function storeFailedChunk(index, blob) {
  const reader = new FileReader();
  reader.readAsDataURL(blob);
  reader.onloadend = async () => {
    const key = `failed_chunk_${sessionId}_${index}`;
    await chrome.storage.local.set({ [key]: reader.result });
    console.log(`Chunk ${index} saved locally for retry`);
  };
}