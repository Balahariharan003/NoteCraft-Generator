// offscreen.js — runs in the extension's own context (NOT in Meet's page)
// This guarantees clean microphone access independent of Google Meet

let micStream = null;
let mediaRecorder = null;
let isRecording = false;

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.target !== "offscreen") return;

  if (msg.action === "START_MIC") {
    startMicCapture();
    sendResponse({ ok: true });
  } else if (msg.action === "STOP_MIC") {
    stopMicCapture();
    sendResponse({ ok: true });
  } else if (msg.action === "GET_MIC_CHUNK") {
    getMicChunk().then(blob => {
      if (blob) {
        blob.arrayBuffer().then(buffer => {
          sendResponse({ ok: true, data: new Uint8Array(buffer) });
        });
      } else {
        sendResponse({ ok: false });
      }
    });
    return true; // async response
  }
});

async function startMicCapture() {
  try {
    micStream = await navigator.mediaDevices.getUserMedia({
      audio: {
        echoCancellation: false,
        noiseSuppression: false,
        autoGainControl: true
      },
      video: false
    });

    const track = micStream.getAudioTracks()[0];
    console.log("🎤 Offscreen mic captured:", track.label, "enabled:", track.enabled, "readyState:", track.readyState);

    // Record continuously — we'll grab chunks on demand
    mediaRecorder = new MediaRecorder(micStream, { mimeType: "audio/webm" });
    mediaRecorder.start(30000); // continuous recording
    isRecording = true;

    console.log("🎤 Offscreen mic recording started");
  } catch (err) {
    console.error("🎤 Offscreen mic FAILED:", err);
  }
}

function getMicChunk() {
  return new Promise((resolve) => {
    if (!mediaRecorder || mediaRecorder.state !== "recording") {
      console.warn("🎤 No active recorder for mic chunk");
      resolve(null);
      return;
    }

    const chunks = [];
    const handleData = (e) => {
      if (e.data.size > 0) chunks.push(e.data);
    };

    // Listen for next data
    mediaRecorder.addEventListener("dataavailable", handleData);

    // Request data — this triggers dataavailable
    mediaRecorder.requestData();

    // Give it a moment to deliver the data (increased to 500ms)
    setTimeout(() => {
      mediaRecorder.removeEventListener("dataavailable", handleData);
      if (chunks.length > 0) {
        resolve(new Blob(chunks, { type: "audio/webm" }));
      } else {
        resolve(null);
      }
    }, 500);
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
