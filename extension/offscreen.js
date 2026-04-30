// offscreen.js — runs in the extension's own context (NOT in Meet's page)
// This guarantees clean microphone access independent of Google Meet

let micStream = null;
let mediaRecorder = null;
let isRecording = false;
let pendingChunks = [];

// Guard against multiple message handlers
let messageHandlerAdded = false;

function addMessageHandler() {
  if (messageHandlerAdded) return;
  messageHandlerAdded = true;
  
  chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
    try {
      // Handle any message targeting offscreen
      if (!msg.target || msg.target !== "offscreen") {
        return false;
      }

      if (msg.action === "PING") {
        sendResponse({ ok: true });
        return false;
      } else if (msg.action === "START_MIC") {
        startMicCapture().then(sendResponse).catch(err => {
          console.error("Start mic error:", err);
          sendResponse({ ok: false, error: err.message || String(err) });
        });
        return true;
      } else if (msg.action === "STOP_MIC") {
        try {
          stopMicCapture();
          sendResponse({ ok: true });
        } catch (err) {
          sendResponse({ ok: false, error: err.message });
        }
        return false;
      } else if (msg.action === "GET_MIC_CHUNK") {
        getMicChunk().then(blob => {
          if (blob) {
            blob.arrayBuffer().then(buffer => {
              sendResponse({ ok: true, data: new Uint8Array(buffer) });
            }).catch(err => {
              console.error("Get chunk error:", err);
              sendResponse({ ok: false, error: err.message });
            });
          } else {
            sendResponse({ ok: false });
          }
        }).catch(err => {
          console.error("Get mic chunk error:", err);
          sendResponse({ ok: false, error: err.message });
        });
        return true;
      }
      
      return false;
    } catch (err) {
      console.error("Message handler error:", err);
      try {
        sendResponse({ ok: false, error: err.message });
      } catch (e) {
        console.error("Failed to send error response:", e);
      }
      return false;
    }
  });
}

// Add message handler
addMessageHandler();

async function startMicCapture() {
  try {
    if (isRecording) {
      console.log("🎤 Mic already recording");
      return { ok: true };
    }
    
    // Request microphone access with compatible constraints
    // Note: echoCancellation, noiseSuppression, autoGainControl are preferences, not requirements
    try {
      micStream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: { ideal: false },
          noiseSuppression: { ideal: false },
          autoGainControl: { ideal: false }
        },
        video: false
      });
    } catch (err) {
      // If the constraints failed, try simpler version
      if (err.name === "OverconstrainedError") {
        console.warn("🎤 Audio constraints overconstrained, trying simpler version");
        micStream = await navigator.mediaDevices.getUserMedia({
          audio: true,
          video: false
        });
      } else {
        throw err;
      }
    }

    const track = micStream.getAudioTracks()[0];
    if (!track) {
      throw new Error("No audio tracks available");
    }
    
    console.log("🎤 Offscreen mic captured:", track.label);

    isRecording = true;
    startNewRecorder();
    
    console.log("🎤 Offscreen mic recording started");
    return { ok: true };
  } catch (err) {
    console.error("🎤 Offscreen mic FAILED:", err);
    isRecording = false;
    // Clean up on failure
    if (micStream) {
      micStream.getTracks().forEach(t => t.stop());
      micStream = null;
    }
    return { ok: false, error: err.message || String(err) };
  }
}

function startNewRecorder() {
  if (!micStream) return;
  
  mediaRecorder = new MediaRecorder(micStream, { mimeType: "audio/webm" });
  pendingChunks = [];
  
  mediaRecorder.ondataavailable = (e) => {
    if (e.data.size > 0) pendingChunks.push(e.data);
  };
  
  mediaRecorder.start();
}

function getMicChunk() {
  return new Promise((resolve) => {
    if (!mediaRecorder || mediaRecorder.state !== "recording") {
      console.warn("🎤 No active recorder for mic chunk");
      resolve(null);
      return;
    }

    // To ensure each chunk has a valid WebM header, we stop the current 
    // recorder and start a new one immediately.
    mediaRecorder.onstop = () => {
      if (pendingChunks.length > 0) {
        resolve(new Blob(pendingChunks, { type: "audio/webm" }));
      } else {
        resolve(null);
      }
      if (isRecording) {
        startNewRecorder();
      }
    };

    mediaRecorder.stop();
  });
}

function stopMicCapture() {
  isRecording = false;
  if (mediaRecorder && mediaRecorder.state === "recording") {
    mediaRecorder.stop();
  }
  if (micStream) {
    micStream.getTracks().forEach(t => t.stop());
    micStream = null;
  }
  console.log("🎤 Offscreen mic stopped");
}

// ── Auto-request permission if opened as a tab ────────────────
if (window.location.hash === "#allow") {
  navigator.mediaDevices.getUserMedia({ audio: true })
    .then(() => {
      document.body.innerHTML = "<h1>Permission Granted!</h1><p>You can close this tab and start recording now.</p>";
    })
    .catch((err) => {
      document.body.innerHTML = `<h1>Permission Denied</h1><p>${err.message}</p>`;
    });
}
